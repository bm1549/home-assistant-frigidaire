"""API key sign-in, through the official Electrolux API (beta).

This is the method for accounts that sign in to the Frigidaire app with Google or Apple, which
have no password to give. The user copies an API key, an access token and a refresh token from
the Electrolux developer portal.

Refresh tokens work once. The library rotates the pair as the access token nears expiry and
hands the new pair to a callback, which writes it straight into the entry's data: losing it
would leave the entry with a spent refresh token. For the same reason validation stores the
backend's tokens, not the values the user typed, which validation may already have spent.

Shared code never imports this module except through ``auth.METHODS``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

import frigidaire

from .errors import CannotConnect, InvalidAuth

METHOD = "api_key"
BETA = True
# The free plan allows about 5,000 calls a day; the live stream keeps data current in between.
RESYNC_INTERVAL = timedelta(minutes=5)

DEVELOPER_PORTAL = "https://developer.electrolux.one/dashboard"
DESCRIPTION_PLACEHOLDERS = {"portal_url": DEVELOPER_PORTAL}
# QuotaExceededError is the library's shared rate-limit error; this method has no other.
RATE_LIMIT_ERRORS: tuple[type[frigidaire.FrigidaireException], ...] = ()

CREDENTIAL_KEYS = ("api_key", "access_token", "refresh_token")
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
SCHEMA = vol.Schema({vol.Required(key): _SECRET for key in CREDENTIAL_KEYS})
REAUTH_SCHEMA = SCHEMA

USER_AGENT = "home-assistant-frigidaire"

TokenCallback = Callable[[str, str], None]


def build_backend(
    api_key: str, access_token: str, refresh_token: str, on_tokens: TokenCallback | None
) -> frigidaire.ApiKeyBackend:
    """The one place this method's backend is constructed. Tests patch it to return a fake."""
    return frigidaire.ApiKeyBackend(api_key, access_token, refresh_token, on_tokens=on_tokens, user_agent=USER_AGENT)


async def async_validate(
    hass: HomeAssistant, user_input: dict[str, Any], entry: ConfigEntry | None = None
) -> tuple[str, list[frigidaire.Appliance]]:
    """Connect, then read the account email and appliances; return them.

    ``user_input`` is updated in place with the backend's tokens, which the config flow stores:
    if validation refreshed them, the typed refresh token is already spent.
    """
    for key in CREDENTIAL_KEYS:
        user_input[key] = str(user_input[key]).strip()
    try:
        backend = build_backend(user_input["api_key"], user_input["access_token"], user_input["refresh_token"], None)
    except frigidaire.AuthenticationError as err:  # for example, an access token that is not a JWT
        raise InvalidAuth from err
    except frigidaire.FrigidaireException as err:
        raise CannotConnect from err
    client = frigidaire.Frigidaire(backend)
    try:
        await client.connect()
        email = await client.account_email()
        appliances = await client.get_appliances()
    except frigidaire.AuthenticationError as err:
        raise InvalidAuth from err
    except frigidaire.FrigidaireException as err:
        raise CannotConnect from err
    finally:
        user_input["access_token"], user_input["refresh_token"] = backend.tokens
        await client.close()
    return email, appliances


def create_backend(hass: HomeAssistant, entry: ConfigEntry) -> frigidaire.Backend:
    """The backend for a configured entry; every rotated token pair is saved to the entry at once."""

    @callback
    def save_tokens(access_token: str, refresh_token: str) -> None:
        # The library calls this on the event loop. Updating data does not reload the entry: the
        # options flow reloads it itself, and there is no update listener.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "access_token": access_token, "refresh_token": refresh_token}
        )

    backend = build_backend(entry.data["api_key"], entry.data["access_token"], entry.data["refresh_token"], save_tokens)
    return _ConfirmedReauth(backend, entry.entry_id)


async def async_remove(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nothing is stored outside the entry. Tokens are not revoked: the portal manages them."""
    _unconfirmed_auth_failures.discard(entry.entry_id)


# Entries whose last call failed with an AuthenticationError that carried no HTTP status. Kept per
# entry id, outside any one backend, so the count survives a setup retry, which builds a new one.
_unconfirmed_auth_failures: set[str] = set()


class _ConfirmedReauth:
    """Passes everything to the backend, but asks for new credentials only once a failure repeats.

    The SDK reports a failed token refresh the same way whether the server refused the refresh
    token or the network dropped mid-request, so a single Wi-Fi blip would otherwise prompt the
    user to sign in again. An ``AuthenticationError`` with an HTTP status (401 or 403) is the
    server rejecting the credentials and passes through at once. One without a status is passed
    on as a plain ``FrigidaireException`` the first time, so the caller backs off and retries as
    for any failure; if the next call for this entry fails the same way, the error passes through
    and reauth starts. Any successful call clears the suspicion. Real reauth is delayed by one
    retry, never suppressed.
    """

    def __init__(self, backend: frigidaire.Backend, entry_id: str) -> None:
        self._backend = backend
        self._entry_id = entry_id

    def __repr__(self) -> str:
        return repr(self._backend)

    def __getattr__(self, name: str) -> Any:
        # supports_live_updates, tokens and anything else the wrapped backend offers.
        return getattr(self._backend, name)

    async def _guard(self, awaitable: Any) -> Any:
        try:
            result = await awaitable
        except frigidaire.AuthenticationError as err:
            if err.status_code is not None or self._entry_id in _unconfirmed_auth_failures:
                _unconfirmed_auth_failures.discard(self._entry_id)
                raise
            _unconfirmed_auth_failures.add(self._entry_id)
            raise frigidaire.FrigidaireException(
                "Could not refresh the Electrolux API tokens; retrying before asking to sign in again"
            ) from err
        _unconfirmed_auth_failures.discard(self._entry_id)
        return result

    async def connect(self) -> None:
        await self._guard(self._backend.connect())

    async def account_email(self) -> str:
        return await self._guard(self._backend.account_email())

    async def fetch_records(self) -> list[dict]:
        return await self._guard(self._backend.fetch_records())

    async def fetch_record(self, appliance_id: str) -> dict:
        return await self._guard(self._backend.fetch_record(appliance_id))

    async def send(self, appliance_id: str, key: str, value: Any) -> None:
        await self._guard(self._backend.send(appliance_id, key, value))

    async def listen(
        self,
        on_record: Callable[[dict], None],
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        def connected() -> None:
            _unconfirmed_auth_failures.discard(self._entry_id)
            on_connect()

        await self._guard(self._backend.listen(on_record, connected, on_disconnect))

    async def close(self) -> None:
        await self._backend.close()

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

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

import frigidaire

from ..const import DOMAIN
from .errors import CannotConnect, CredentialsInUse, InvalidAuth

METHOD = "api_key"
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

_LOGGER = logging.getLogger(__name__)

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
    if validation refreshed them, the typed refresh token is already spent. Tokens another
    configured entry holds are refused before any call (``entry`` is the one being
    re-authenticated, which may reuse its own).
    """
    for key in CREDENTIAL_KEYS:
        user_input[key] = str(user_input[key]).strip()
    # Validating tokens a configured entry holds would spend its refresh token, and the rotated
    # pair would then be thrown away when the duplicate account is refused.
    for other in hass.config_entries.async_entries(DOMAIN):
        if (
            (entry is None or other.entry_id != entry.entry_id)
            and other.data.get("auth_method") == METHOD
            and other.data.get("refresh_token") == user_input["refresh_token"]
        ):
            raise CredentialsInUse
    try:
        backend = build_backend(user_input["api_key"], user_input["access_token"], user_input["refresh_token"], None)
    except frigidaire.AuthenticationError as err:  # for example, an access token that is not a JWT
        raise InvalidAuth from err
    except frigidaire.FrigidaireException as err:
        raise CannotConnect from err
    client = frigidaire.AsyncFrigidaire(backend)
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
    """The backend for a configured entry; every rotated token pair is saved to the entry at once.

    An ``AuthenticationError`` from it always means the tokens are rejected: the library reports a
    token refresh that got no answer as a plain ``FrigidaireException``, which backs off and retries.
    """
    held = entry.data["refresh_token"]  # the refresh token this backend holds now

    @callback
    def save_tokens(access_token: str, refresh_token: str) -> None:
        nonlocal held
        # The library calls this on the event loop. Updating data does not reload the entry: the
        # options flow reloads it itself, and there is no update listener.
        if entry.data.get("refresh_token") != held:
            # The entry moved on without this backend, for example through reauth while one of
            # its requests was in flight: its tokens are the ones to keep.
            _LOGGER.debug("Not saving tokens rotated by a backend the entry no longer uses")
            return
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "access_token": access_token, "refresh_token": refresh_token}
        )
        held = refresh_token

    return build_backend(entry.data["api_key"], entry.data["access_token"], entry.data["refresh_token"], save_tokens)


def reauth_description_placeholders(entry: ConfigEntry) -> dict[str, str]:
    """What the reauth form's description shows: the account, as its email."""
    return {"username": entry.unique_id or entry.title}


async def async_remove(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nothing is stored outside the entry. Tokens are not revoked: the portal manages them."""

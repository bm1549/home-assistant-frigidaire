"""Email-and-password sign-in, through the Frigidaire app's login.

Everything specific to this method lives here, including where each entry keeps its session.
Each entry has its own session file so multiple accounts do not clobber each other's sessions,
which forced re-authentication and tripped Frigidaire's active-session cap (cas_3403). The
setup flow runs before an entry id exists and saves to the legacy shared file; setup migrates
from it once.

Shared code never imports this module except through ``auth.METHODS``.
"""

from __future__ import annotations

import contextlib
import os
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

import frigidaire

from .errors import CannotConnect, InvalidAuth

METHOD = "password"
RESYNC_INTERVAL = timedelta(seconds=30)
SCHEMA = vol.Schema({"username": str, "password": str})
REAUTH_SCHEMA = vol.Schema({vol.Required("password"): str})
DESCRIPTION_PLACEHOLDERS: dict[str, str] = {}
# Frigidaire's active-session cap: a rate limit to wait out, never a reason to log in again.
RATE_LIMIT_ERRORS: tuple[type[frigidaire.FrigidaireException], ...] = (frigidaire.SessionCapError,)

LEGACY_SESSION_FILE = "frigidaire.json"
TIMEOUT = 60  # seconds


def build_backend(username: str, password: str, session_store: frigidaire.SessionStore) -> frigidaire.Backend:
    """The one place this method's backend is constructed. Tests patch it to return a fake."""
    return frigidaire.PasswordBackend(username, password, session_store=session_store, timeout=TIMEOUT)


def _session_path(hass: HomeAssistant, entry_id: str | None) -> str:
    return hass.config.path(f"frigidaire-{entry_id}.json" if entry_id else LEGACY_SESSION_FILE)


class _EntrySessionStore:
    """The entry's own session file, falling back to the legacy shared file for a one-time migration.

    The library loads and saves from its worker thread, so no file access runs in the event loop.
    """

    def __init__(self, path: str, legacy_path: str) -> None:
        self._store = frigidaire.JsonFileSessionStore(path)
        self._legacy_path = legacy_path

    def load(self) -> tuple[str | None, str | None]:
        session_key, regional_base_url = self._store.load()
        if session_key is None:
            session_key, regional_base_url = frigidaire.JsonFileSessionStore(self._legacy_path).load()
        return session_key, regional_base_url

    def save(self, session_key: str, regional_base_url: str | None) -> None:
        self._store.save(session_key, regional_base_url)


class _FreshLoginStore:
    """Saves the session but never offers a stored one, so validation always checks the password.

    Saving lets setup reuse the session instead of minting a second one: Frigidaire caps active
    sessions per account.
    """

    def __init__(self, path: str) -> None:
        self._store = frigidaire.JsonFileSessionStore(path)

    def load(self) -> tuple[str | None, str | None]:
        return None, None

    def save(self, session_key: str, regional_base_url: str | None) -> None:
        self._store.save(session_key, regional_base_url)


async def async_validate(
    hass: HomeAssistant, user_input: dict[str, Any], entry: ConfigEntry | None = None
) -> tuple[str, list[frigidaire.Appliance]]:
    """Verify the credentials with a full login; return the account email and its appliances.

    ``entry`` is the entry being re-authenticated, whose session file then receives the new session.
    """
    store = _FreshLoginStore(_session_path(hass, entry.entry_id if entry else None))
    client = frigidaire.Frigidaire(build_backend(user_input["username"], user_input["password"], store))
    try:
        await client.connect()
        appliances = await client.get_appliances()
        email = await client.account_email()
    except frigidaire.LoginError as err:
        # Any rejected login, not just bad credentials: an account without a password or one
        # mid-registration is also something to fix on the Frigidaire side, not a connectivity issue.
        raise InvalidAuth from err
    except frigidaire.FrigidaireException as err:
        raise CannotConnect from err
    finally:
        await client.close()
    return email, appliances


def create_backend(hass: HomeAssistant, entry: ConfigEntry) -> frigidaire.Backend:
    """The backend for a configured entry, reusing its saved session while the server accepts it."""
    store = _EntrySessionStore(_session_path(hass, entry.entry_id), _session_path(hass, None))
    return build_backend(entry.data["username"], entry.data["password"], store)


def reauth_description_placeholders(entry: ConfigEntry) -> dict[str, str]:
    """What the reauth form's description shows: the username as it was typed."""
    return {"username": entry.data.get("username") or entry.unique_id or entry.title}


async def async_remove(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the entry's session file. The legacy shared file may still serve other entries."""
    path = _session_path(hass, entry.entry_id)

    def remove() -> None:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)

    await hass.async_add_executor_job(remove)

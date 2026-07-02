"""The frigidaire integration."""

from __future__ import annotations

import threading
import traceback

from homeassistant import data_entry_flow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

import frigidaire

from .auth_store import load_auth, per_entry_auth_path, resolve_initial_auth_path, save_auth
from .const import DOMAIN, PLATFORMS

# Guards writes to an entry's auth file: the client may re-authenticate from
# multiple entity worker threads, so its persist callback can fire concurrently.
_AUTH_WRITE_LOCK = threading.Lock()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up frigidaire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    def setup(username: str, password: str) -> None:
        # Each entry persists to its own file so multiple accounts don't clobber
        # each other's session keys (which would force re-auth and trip cas_3403).
        auth_path: str = per_entry_auth_path(hass.config.path(), entry.entry_id)

        def persist_session_key(session_key: str, regional_base_url: str | None) -> None:
            # Called whenever the client mints a new session key, including on
            # runtime re-authentication. Persisting it means a still-valid token
            # survives restarts instead of being abandoned — abandoned sessions
            # linger server-side and trip Frigidaire's active-session cap (cas_3403).
            with _AUTH_WRITE_LOCK:
                save_auth(auth_path, session_key, regional_base_url)

        try:
            # Fall back to the legacy shared file on first run so an existing
            # cached key is migrated instead of forcing a re-auth.
            session_key, regional_base_url = load_auth(resolve_initial_auth_path(hass.config.path(), entry.entry_id))
            client = frigidaire.Frigidaire(
                username=username,
                password=password,
                timeout=60,
                session_key=session_key,
                regional_base_url=regional_base_url,
                on_session_key_update=persist_session_key,
            )
            persist_session_key(client.session_key, client.regional_base_url)

            hass.data[DOMAIN][entry.entry_id] = client
        except ConnectionError as err:
            raise ConfigEntryNotReady("Cannot connect to Frigidaire") from err
        except frigidaire.FrigidaireException as err:
            # Handle frigidaire 429 gracefully
            if "cas_3403" in traceback.format_exc():
                raise data_entry_flow.AbortFlow(
                    "You have exceeded Frigidaire's maximum number of active sessions. "
                    "Please log out of another device or wait until an existing session expires."
                ) from err
            raise data_entry_flow.AbortFlow("Frigidaire backend exception") from err

    await hass.async_add_executor_job(setup, entry.data["username"], entry.data["password"])

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

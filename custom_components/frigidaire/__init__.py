"""The frigidaire integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady

import frigidaire

from .auth import METHODS
from .const import PLATFORMS
from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator, describe_error

_LOGGER = logging.getLogger(__name__)

# Entries from before minor version 2 carry no auth_method; they all signed in with a password.
LEGACY_AUTH_METHOD = "password"


async def async_setup_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> bool:
    """Set up frigidaire from a config entry."""
    method = entry.data.get("auth_method")
    if (module := METHODS.get(method)) is None:
        raise ConfigEntryError(f"Unknown sign-in method {method!r}; delete this entry and add it again")

    client: frigidaire.Frigidaire | None = None
    try:
        client = frigidaire.Frigidaire(module.create_backend(hass, entry))
        await client.connect()
    except frigidaire.AuthenticationError as err:
        if client is not None:
            await client.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except frigidaire.FrigidaireException as err:
        if client is not None:
            await client.close()
        raise ConfigEntryNotReady(describe_error(err, module.RATE_LIMIT_ERRORS)) from err

    coordinator = FrigidaireCoordinator(hass, entry, client, module)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        await client.close()
        # The helper raises without a message; surface ours so the UI says why.
        raise ConfigEntryNotReady(str(err.__cause__ or err)) from err.__cause__
    except Exception:
        await client.close()
        raise
    entry.runtime_data = coordinator
    entry.async_on_unload(client.close)
    if client.supports_live_updates:
        coordinator.async_start_live_updates()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> bool:
    """Bring an entry's data up to the current version.

    Minor version 2 records the sign-in method. Entities, options, the unique id and session
    files are untouched.
    """
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "auth_method": LEGACY_AUTH_METHOD}, minor_version=2
        )
        _LOGGER.debug("Migrated entry %s to minor version 2", entry.entry_id)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> None:
    """Clean up what the entry's sign-in method left behind, such as a session file."""
    if (module := METHODS.get(entry.data.get("auth_method", LEGACY_AUTH_METHOD))) is not None:
        await module.async_remove(hass, entry)

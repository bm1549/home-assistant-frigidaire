"""The frigidaire integration."""

from __future__ import annotations

from functools import partial

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

import frigidaire

from .const import PLATFORMS
from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator, describe_error
from .session import initial_session, session_store


async def async_setup_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> bool:
    """Set up frigidaire from a config entry."""
    session_key, regional_base_url = initial_session(hass.config.path(), entry.entry_id)
    connect = partial(
        frigidaire.Frigidaire,
        entry.data["username"],
        entry.data["password"],
        session_key=session_key,
        regional_base_url=regional_base_url,
        session_store=session_store(hass.config.path(), entry.entry_id),
        timeout=60,
    )
    try:
        client = await hass.async_add_executor_job(connect)
    except frigidaire.AuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except frigidaire.FrigidaireException as err:
        raise ConfigEntryNotReady(describe_error(err)) from err

    coordinator = FrigidaireCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        # The helper raises without a message; surface ours so the UI says why.
        raise ConfigEntryNotReady(str(err.__cause__ or err)) from err.__cause__
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> None:
    """Reload the entry when options change so entity selection takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

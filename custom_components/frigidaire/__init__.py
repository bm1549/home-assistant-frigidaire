"""The frigidaire integration."""

from __future__ import annotations

import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

import frigidaire

from .config_flow import AUTH_FILE, load_auth, save_auth
from .const import DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up frigidaire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    def setup(username: str, password: str) -> None:
        auth_path: str = os.path.join(hass.config.path(), AUTH_FILE)

        try:
            session_key, regional_base_url = load_auth(auth_path)
            client = frigidaire.Frigidaire(
                username=username,
                password=password,
                timeout=60,
                session_key=session_key,
                regional_base_url=regional_base_url,
            )
            save_auth(auth_path, client.session_key, client.regional_base_url)

            appliances = client.get_appliances()
            hass.data[DOMAIN][entry.entry_id] = {"client": client, "appliances": appliances}
        except ConnectionError as err:
            raise ConfigEntryNotReady("Cannot connect to Frigidaire") from err
        except frigidaire.FrigidaireException as err:
            if "cas_3403" in str(err):
                raise ConfigEntryNotReady(
                    "Rate limited by Frigidaire. Will retry automatically."
                ) from err
            raise ConfigEntryNotReady(f"Frigidaire error during setup: {err}") from err

    await hass.async_add_executor_job(setup, entry.data["username"], entry.data["password"])

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the switch platform when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

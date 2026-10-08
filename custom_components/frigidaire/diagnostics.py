"""Diagnostics downloads: the raw cloud records, redacted, plus how they were parsed.

Every model-specific fix so far started from a payload a user pasted into an issue.
This makes that a file attachment with the personal fields already removed.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from frigidaire import Appliance

from .const import DOMAIN
from .coordinator import FrigidaireConfigEntry

TO_REDACT = {
    "username",
    "password",
    "applianceId",
    "deviceId",
    "TimeZoneStandardName",
    "TimeZoneDaylightRule",
}

# Accessors worth seeing next to the raw record when triaging a report.
PARSED_FIELDS = (
    "destination",
    "connection_state",
    "state",
    "mode",
    "mode_state",
    "fan_speed",
    "fan_speed_state",
    "temperature_unit",
    "ambient_temperature",
    "target_temperature",
    "humidity",
    "target_humidity",
    "filter_state",
    "filter_needs_attention",
    "alerts",
    "bucket_full",
    "compressor_running",
    "sleep_mode",
    "vertical_swing",
    "ui_locked",
    "display_light",
    "clean_air_mode",
    "start_time",
    "stop_time",
    "is_connected",
)


def _describe(appliance: Appliance) -> dict[str, Any]:
    parsed = {name: getattr(appliance, name) for name in PARSED_FIELDS}
    parsed["nickname"] = appliance.nickname
    parsed["model"] = appliance.appliance_type
    return {"parsed": parsed, "raw": async_redact_data(appliance.raw, TO_REDACT)}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FrigidaireConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "last_update_success": coordinator.last_update_success,
        "appliances": [_describe(appliance) for appliance in (coordinator.data or {}).values()],
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    appliance_ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
    appliances = [a for appliance_id, a in (entry.runtime_data.data or {}).items() if appliance_id in appliance_ids]
    if not appliances:
        return {"error": "appliance not in the last account fetch"}
    return _describe(appliances[0])

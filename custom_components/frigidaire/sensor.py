"""Sensor entities for frigidaire integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .const import CONF_CURRENT_FAN_SPEED_SENSOR, CONF_FILTER_RUNTIME_SENSOR, DOMAIN
from .diagnostics import filter_runtime_hours
from .helpers import suggest_area

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire sensor entities from a config entry."""
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    state_store: dict = hass.data[DOMAIN][entry.entry_id].setdefault("climate_state", {})
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities: list[SensorEntity] = [
        FrigidaireCurrentFanSpeedSensor(appliance, state_store, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
        and options.get(appliance.appliance_id, {}).get(CONF_CURRENT_FAN_SPEED_SENSOR, False)
    ]
    entities += [
        FrigidaireFilterRuntimeSensor(appliance, state_store, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get(CONF_FILTER_RUNTIME_SENSOR, False)
    ]

    async_add_entities(entities, update_before_add=True)


class FrigidaireCurrentFanSpeedSensor(SensorEntity):
    """Reports the actual running fan speed published by the climate entity."""

    _attr_icon = "mdi:fan"

    def __init__(
        self, appliance: frigidaire.Appliance, state_store: dict, suggested_area: str | None = None
    ) -> None:
        self._appliance = appliance
        self._state_store = state_store
        self._attr_unique_id = f"{appliance.appliance_id}_current_fan_speed"
        self._attr_name = "Current Fan Speed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    def update(self) -> None:
        data = self._state_store.get(self._appliance.appliance_id)
        if not data:
            self._attr_available = False
            self._attr_native_value = None
            return
        self._attr_available = bool(data.get("available"))
        self._attr_native_value = data.get("current_fan_speed")


class FrigidaireFilterRuntimeSensor(SensorEntity):
    """Report cumulative air-filter runtime from the owning appliance entity."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:air-filter"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, appliance: frigidaire.Appliance, state_store: dict, suggested_area: str | None = None
    ) -> None:
        self._appliance = appliance
        self._state_store = state_store
        self._attr_unique_id = f"{appliance.appliance_id}_filter_runtime"
        self._attr_name = "Filter Runtime"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    def update(self) -> None:
        data = self._state_store.get(self._appliance.appliance_id)
        raw_runtime = None if not data else data.get("filter_runtime")
        runtime_hours = filter_runtime_hours(raw_runtime)
        self._attr_available = bool(data and data.get("available") and runtime_hours is not None)
        self._attr_native_value = runtime_hours if self._attr_available else None

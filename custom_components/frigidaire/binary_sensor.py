"""Binary sensor entities for frigidaire integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .const import (
    CONF_ACTIVE_ALERTS_SENSOR,
    CONF_CHECK_FILTER_SENSOR,
    CONF_COMPRESSOR_SENSOR,
    DOMAIN,
)
from .diagnostics import filter_needs_attention
from .helpers import suggest_area


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire binary sensor entities from a config entry."""
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    state_store: dict = hass.data[DOMAIN][entry.entry_id].setdefault("climate_state", {})
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities: list[BinarySensorEntity] = [
        FrigidaireCheckFilterSensor(appliance, state_store, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get(CONF_CHECK_FILTER_SENSOR, False)
    ]
    entities += [
        FrigidaireActiveAlertsSensor(appliance, state_store, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get(CONF_ACTIVE_ALERTS_SENSOR, False)
    ]

    entities += [
        FrigidaireCompressorSensor(appliance, state_store, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
        and options.get(appliance.appliance_id, {}).get(CONF_COMPRESSOR_SENSOR, False)
    ]

    async_add_entities(entities, update_before_add=True)


class FrigidaireCheckFilterSensor(BinarySensorEntity):
    """Binary sensor that is ON when the filter needs attention."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, appliance: frigidaire.Appliance, state_store: dict, suggested_area: str | None = None
    ) -> None:
        self._appliance = appliance
        self._state_store = state_store
        self._filter_state: str | None = None
        self._attr_unique_id = f"{appliance.appliance_id}_check_filter"
        self._attr_name = "Check Filter"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self._filter_state is None:
            return None
        return {"filter_state": self._filter_state}

    def update(self) -> None:
        data = self._state_store.get(self._appliance.appliance_id)
        self._filter_state = None if not data else data.get("filter_state")
        self._attr_available = bool(data and data.get("available") and self._filter_state is not None)
        self._attr_is_on = filter_needs_attention(self._filter_state) if self._attr_available else None


class FrigidaireActiveAlertsSensor(BinarySensorEntity):
    """Binary sensor that is ON while the appliance reports active alerts."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, appliance: frigidaire.Appliance, state_store: dict, suggested_area: str | None = None
    ) -> None:
        self._appliance = appliance
        self._state_store = state_store
        self._active_alerts: list[str] | None = None
        self._attr_unique_id = f"{appliance.appliance_id}_active_alerts"
        self._attr_name = "Active Alerts"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self._active_alerts is None:
            return None
        return {"active_alerts": self._active_alerts}

    def update(self) -> None:
        data = self._state_store.get(self._appliance.appliance_id)
        self._active_alerts = None if not data else data.get("active_alerts")
        self._attr_available = bool(data and data.get("available") and self._active_alerts is not None)
        self._attr_is_on = bool(self._active_alerts) if self._attr_available else None


class FrigidaireCompressorSensor(BinarySensorEntity):
    """Binary sensor that is ON while the compressor is estimated to be cooling.

    Reads the estimate published by the climate entity so it stays consistent
    with hvac_action and makes no API calls of its own.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self, appliance: frigidaire.Appliance, state_store: dict, suggested_area: str | None = None
    ) -> None:
        self._appliance = appliance
        self._state_store = state_store
        self._attr_unique_id = f"{appliance.appliance_id}_compressor"
        self._attr_name = "Compressor"
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
            self._attr_is_on = None
            return
        self._attr_available = bool(data.get("available"))
        self._attr_is_on = data.get("compressor_running")

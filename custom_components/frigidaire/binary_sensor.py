"""Binary sensor entities for frigidaire integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

import frigidaire

from .const import DOMAIN
from .coordinator import FrigidaireApplianceCoordinator
from .helpers import suggest_area


def _normalize(value):
    if isinstance(value, str):
        return value.upper()
    return value


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire binary sensor entities from a config entry."""
    coordinators: dict[str, FrigidaireApplianceCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities = [
        FrigidaireCheckFilterSensor(coordinators[appliance.appliance_id], suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get("check_filter", False)
    ]

    async_add_entities(entities)


class FrigidaireCheckFilterSensor(CoordinatorEntity[FrigidaireApplianceCoordinator], BinarySensorEntity):
    """Binary sensor that is ON when the filter needs attention."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: FrigidaireApplianceCoordinator, suggested_area: str | None = None) -> None:
        super().__init__(coordinator)
        self._appliance = coordinator.appliance
        self._attr_unique_id = f"{self._appliance.appliance_id}_check_filter"
        self._attr_name = "Check Filter"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._appliance.appliance_id)},
            name=self._appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def _details(self) -> dict:
        return self.coordinator.data or {}

    @property
    def is_on(self) -> bool | None:
        filter_state = _normalize(self._details.get(frigidaire.Detail.FILTER_STATE))
        if filter_state is None:
            return None
        return filter_state != frigidaire.FilterState.GOOD

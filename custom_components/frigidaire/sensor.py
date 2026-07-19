"""Sensor entities for frigidaire integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

import frigidaire

from .const import CONF_CURRENT_FAN_SPEED_SENSOR, CONF_FILTER_RUNTIME_SENSOR, DOMAIN
from .coordinator import FrigidaireApplianceCoordinator
from .diagnostics import AIR_FILTER_LIFETIME_KEY, filter_runtime_hours
from .helpers import suggest_area


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire sensor entities from a config entry."""
    coordinators: dict[str, FrigidaireApplianceCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities: list[SensorEntity] = [
        FrigidaireReportedFanSpeedSensor(
            coordinators[appliance.appliance_id], suggest_area(hass, appliance.nickname)
        )
        for appliance in appliances
        if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
        and options.get(appliance.appliance_id, {}).get(CONF_CURRENT_FAN_SPEED_SENSOR, False)
    ]
    entities += [
        FrigidaireFilterRuntimeSensor(coordinators[appliance.appliance_id], suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get(CONF_FILTER_RUNTIME_SENSOR, False)
    ]

    async_add_entities(entities)


class FrigidaireReportedFanSpeedSensor(CoordinatorEntity[FrigidaireApplianceCoordinator], SensorEntity):
    """Report the appliance's fan-speed state without implying physical motion."""

    _attr_icon = "mdi:fan"

    def __init__(self, coordinator: FrigidaireApplianceCoordinator, suggested_area: str | None = None) -> None:
        super().__init__(coordinator)
        self._appliance = coordinator.appliance
        # Preserve the established unique ID so existing entity history remains intact.
        self._attr_unique_id = f"{self._appliance.appliance_id}_current_fan_speed"
        self._attr_name = "Reported Fan Speed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._appliance.appliance_id)},
            name=self._appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.reported_fan_speed is not None

    @property
    def native_value(self) -> str | None:
        return self.coordinator.reported_fan_speed


class FrigidaireFilterRuntimeSensor(CoordinatorEntity[FrigidaireApplianceCoordinator], SensorEntity):
    """Report cumulative air-filter runtime from the owning appliance entity."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:air-filter"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: FrigidaireApplianceCoordinator, suggested_area: str | None = None) -> None:
        super().__init__(coordinator)
        self._appliance = coordinator.appliance
        self._attr_unique_id = f"{self._appliance.appliance_id}_filter_runtime"
        self._attr_name = "Filter Runtime"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._appliance.appliance_id)},
            name=self._appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def _runtime_hours(self) -> float | None:
        return filter_runtime_hours((self.coordinator.data or {}).get(AIR_FILTER_LIFETIME_KEY))

    @property
    def available(self) -> bool:
        return super().available and self._runtime_hours is not None

    @property
    def native_value(self) -> float | None:
        return self._runtime_hours

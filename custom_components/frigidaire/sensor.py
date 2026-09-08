"""Sensor entities for values the appliances report."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import Appliance, Destination, Unit

from .const import CONF_FILTER_RUNTIME_SENSOR
from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity

FRIGIDAIRE_TO_HA_UNIT = {
    Unit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
    Unit.CELSIUS: UnitOfTemperature.CELSIUS,
}


@dataclass(frozen=True, kw_only=True)
class SensorDescription:
    """A sensor derived from one reported value.

    Sensors without an ``option`` are created only when the appliance reports a usable value,
    so appliances without the hardware stay clean. Opt-in sensors are created when their
    option is on and go unavailable while the value is missing.
    """

    key: str
    name: str
    value_fn: Callable[[Appliance], float | None]
    device_class: SensorDeviceClass
    native_unit: str | None = None
    native_unit_fn: Callable[[Appliance], str | None] | None = None
    state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    icon: str | None = None
    attributes_fn: Callable[[Appliance], Mapping[str, Any] | None] | None = None
    destination: Destination | None = None  # only this appliance type
    option: str | None = None  # a per-device option key in const.py


# Deliberately absent: pm10. On a Telica portable AC it alternates between a fixed
# placeholder (199) and a value identical to pm25, so it would publish a bogus reading
# half the time.
SENSOR_DESCRIPTIONS = (
    SensorDescription(
        key="temperature",
        name="Temperature",
        value_fn=lambda appliance: appliance.ambient_temperature,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_fn=lambda appliance: FRIGIDAIRE_TO_HA_UNIT.get(appliance.temperature_unit),
        # The climate entity already carries an air conditioner's room temperature.
        destination=Destination.DEHUMIDIFIER,
    ),
    SensorDescription(
        key="humidity",
        name="Humidity",
        value_fn=lambda appliance: appliance.humidity,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
    ),
    SensorDescription(
        key="pm25",
        name="PM2.5",
        value_fn=lambda appliance: appliance.pm25,
        device_class=SensorDeviceClass.PM25,
        native_unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    SensorDescription(
        key="wifi_signal",
        name="Wi-Fi Signal",
        value_fn=lambda appliance: appliance.wifi_rssi,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Useful when diagnosing a flaky appliance, noise the rest of the time.
        enabled_default=False,
        attributes_fn=lambda appliance: (
            None if appliance.wifi_link_quality is None else {"link_quality": appliance.wifi_link_quality}
        ),
    ),
    SensorDescription(
        key="filter_runtime",
        name="Filter Runtime",
        value_fn=lambda appliance: appliance.filter_runtime_seconds,
        device_class=SensorDeviceClass.DURATION,
        native_unit=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:air-filter",
        option=CONF_FILTER_RUNTIME_SENSOR,
    ),
)


def _wanted(description: SensorDescription, appliance: Appliance, options: Mapping[str, Any]) -> bool:
    if description.destination is not None and appliance.destination is not description.destination:
        return False
    if description.option is not None:
        return bool(options.get(description.option, False))
    return description.value_fn(appliance) is not None


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire sensor entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        FrigidaireSensor(coordinator, appliance, description)
        for appliance in coordinator.data.values()
        for description in SENSOR_DESCRIPTIONS
        if _wanted(description, appliance, entry.options.get(appliance.appliance_id, {}))
    )


class FrigidaireSensor(FrigidaireEntity, SensorEntity):
    """A sensor backed by one reported value."""

    def __init__(self, coordinator: FrigidaireCoordinator, appliance: Appliance, description: SensorDescription):
        super().__init__(
            coordinator, appliance, unique_id=f"{appliance.appliance_id}_{description.key}", name=description.name
        )
        self._description = description
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_entity_category = description.entity_category
        self._attr_entity_registry_enabled_default = description.enabled_default
        self._attr_icon = description.icon

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self._description.native_unit_fn is not None:
            return self._description.native_unit_fn(self.appliance)
        return self._description.native_unit

    @property
    def native_value(self) -> float | None:
        return self._description.value_fn(self.appliance)

    @property
    def available(self) -> bool:
        # An appliance can stop reporting a value (or report a placeholder) while staying
        # online, so go unavailable rather than holding a stale reading.
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self._description.attributes_fn is None:
            return None
        return self._description.attributes_fn(self.appliance)

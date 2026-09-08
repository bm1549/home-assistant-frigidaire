"""Binary sensor entities for frigidaire integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import Appliance, Destination, Detail

from .const import CONF_BUCKET_STATUS_SENSOR, CONF_CHECK_FILTER_SENSOR, CONF_COMPRESSOR_ESTIMATE
from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity


@dataclass(frozen=True, kw_only=True)
class BinarySensorDescription:
    """A binary sensor derived from the appliance snapshot (and, for the estimate, the coordinator).

    Sensors without an ``option`` are created only when the appliance reports the value.
    Opt-in sensors are created when their option is on and go unavailable while the value
    is unknown, so models that never report it show that rather than a misleading "off".
    """

    key: str
    name: str
    is_on: Callable[[FrigidaireCoordinator, Appliance], bool | None]
    device_class: BinarySensorDeviceClass | None = None
    translation_key: str | None = None
    icon_fn: Callable[[bool | None], str | None] | None = None
    attributes_fn: Callable[[Appliance], Mapping[str, Any] | None] | None = None
    destination: Destination | None = None
    option: str | None = None


def _filter_state(appliance: Appliance) -> Mapping[str, Any] | None:
    raw = appliance.get(Detail.FILTER_STATE)
    return None if raw is None else {"filter_state": str(raw).upper()}


BINARY_SENSOR_DESCRIPTIONS = (
    # Distinguishes a genuinely offline appliance from stale values: a disconnected
    # appliance keeps serving its last-known state, so every other entity looks healthy.
    BinarySensorDescription(
        key="connectivity",
        name="Connectivity",
        is_on=lambda _coordinator, appliance: appliance.is_connected,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        attributes_fn=lambda appliance: (
            None if appliance.connection_state is None else {"connection_state": appliance.connection_state.value}
        ),
    ),
    BinarySensorDescription(
        key="check_filter",
        name="Check Filter",
        is_on=lambda _coordinator, appliance: appliance.filter_needs_attention,
        device_class=BinarySensorDeviceClass.PROBLEM,
        attributes_fn=_filter_state,
        option=CONF_CHECK_FILTER_SENSOR,
    ),
    # No device_class so the bucket_status translation renders Full/Empty.
    BinarySensorDescription(
        key="bucket_status",
        name="Bucket Status",
        is_on=lambda _coordinator, appliance: appliance.bucket_full,
        translation_key="bucket_status",
        icon_fn=lambda is_on: "mdi:water-alert" if is_on else "mdi:cup-water",
        destination=Destination.DEHUMIDIFIER,
        option=CONF_BUCKET_STATUS_SENSOR,
    ),
    BinarySensorDescription(
        key="compressor",
        name="Compressor Estimate",
        is_on=lambda coordinator, appliance: coordinator.compressor_estimate(appliance.appliance_id),
        device_class=BinarySensorDeviceClass.RUNNING,
        destination=Destination.AIR_CONDITIONER,
        option=CONF_COMPRESSOR_ESTIMATE,
    ),
)


def _wanted(
    description: BinarySensorDescription,
    coordinator: FrigidaireCoordinator,
    appliance: Appliance,
    options: Mapping[str, Any],
) -> bool:
    if description.destination is not None and appliance.destination is not description.destination:
        return False
    if description.option is not None:
        return bool(options.get(description.option, False))
    return description.is_on(coordinator, appliance) is not None


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire binary sensor entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        FrigidaireBinarySensor(coordinator, appliance, description)
        for appliance in coordinator.data.values()
        for description in BINARY_SENSOR_DESCRIPTIONS
        if _wanted(description, coordinator, appliance, entry.options.get(appliance.appliance_id, {}))
    )


class FrigidaireBinarySensor(FrigidaireEntity, BinarySensorEntity):
    """A binary sensor backed by one derived value."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: FrigidaireCoordinator, appliance: Appliance, description: BinarySensorDescription
    ) -> None:
        super().__init__(
            coordinator, appliance, unique_id=f"{appliance.appliance_id}_{description.key}", name=description.name
        )
        self._description = description
        self._attr_device_class = description.device_class
        self._attr_translation_key = description.translation_key

    @property
    def is_on(self) -> bool | None:
        return self._description.is_on(self.coordinator, self.appliance)

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def icon(self) -> str | None:
        if self._description.icon_fn is None:
            return None
        return self._description.icon_fn(self.is_on)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self._description.attributes_fn is None:
            return None
        return self._description.attributes_fn(self.appliance)

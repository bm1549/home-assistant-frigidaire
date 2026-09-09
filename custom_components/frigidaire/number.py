"""Number entities for the air conditioner ON/OFF timers."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import Appliance, ApplianceState, Destination

from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity, Optimistic, async_add_appliance_entities

STEP_SECONDS = 1800  # the appliance snaps timers to 30 minutes
MAX_SECONDS = 86400  # 24 hours


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Timers for every air conditioner, and for any other appliance that reports them."""

    def build(appliance: Appliance) -> list[FrigidaireTimerNumber]:
        has_timers = appliance.start_time is not None or appliance.stop_time is not None
        if appliance.destination is not Destination.AIR_CONDITIONER and not has_timers:
            return []
        return [FrigidaireTimerNumber(entry.runtime_data, appliance, timer_type) for timer_type in ("on", "off")]

    async_add_appliance_entities(entry.runtime_data, async_add_entities, build)


class FrigidaireTimerNumber(FrigidaireEntity, NumberEntity):
    """AC ON or OFF timer, in seconds with 30-minute steps."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_max_value = MAX_SECONDS
    _attr_native_min_value = 0
    _attr_native_step = STEP_SECONDS
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator: FrigidaireCoordinator, appliance: Appliance, timer_type: str) -> None:
        super().__init__(
            coordinator,
            appliance,
            unique_id=f"{appliance.appliance_id}_timer_{timer_type}",
            name="On Timer" if timer_type == "on" else "Off Timer",
        )
        self._is_on_timer = timer_type == "on"
        self._optimistic = Optimistic()

    @property
    def native_value(self) -> float:
        if (value := self._optimistic.get("value")) is not None:
            return value
        appliance = self.appliance
        if self._is_on_timer:
            # A start timer only means something while the unit is off or counting down.
            active = appliance.state in (ApplianceState.OFF, ApplianceState.DELAYED_START)
            seconds = appliance.start_time
        else:
            active = appliance.state is ApplianceState.RUNNING
            seconds = appliance.stop_time
        if not active or seconds is None:
            return 0
        return round(seconds / STEP_SECONDS) * STEP_SECONDS

    def set_native_value(self, value: float) -> None:
        seconds = int(round(value / STEP_SECONDS) * STEP_SECONDS)
        seconds = max(0, min(MAX_SECONDS, seconds))
        if self._is_on_timer:
            self.client.set_start_time(self.appliance, seconds)
        else:
            self.client.set_stop_time(self.appliance, seconds)
        self._optimistic.set("value", float(seconds))
        self.refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic.expire()
        super()._handle_coordinator_update()

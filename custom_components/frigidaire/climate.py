"""ClimateEntity for frigidaire integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import ApplianceState, Destination, Detail, FanSpeed, Mode, Unit

from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity, Optimistic

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        FrigidaireClimate(coordinator, appliance)
        for appliance in coordinator.data.values()
        if appliance.destination is Destination.AIR_CONDITIONER
    )


FRIGIDAIRE_TO_HA_UNIT = {
    Unit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
    Unit.CELSIUS: UnitOfTemperature.CELSIUS,
}
HA_TO_FRIGIDAIRE_UNIT = {v: k for k, v in FRIGIDAIRE_TO_HA_UNIT.items()}

FRIGIDAIRE_TO_HA_MODE = {
    Mode.OFF: HVACMode.OFF,
    Mode.COOL: HVACMode.COOL,
    Mode.FAN: HVACMode.FAN_ONLY,
    Mode.ECO: HVACMode.AUTO,
    Mode.AUTO: HVACMode.AUTO,
    Mode.DRY: HVACMode.DRY,
}

# An air conditioner's "auto" is its energy-saving ECO mode (the library also guards this).
HA_TO_FRIGIDAIRE_HVAC_MODE = {
    HVACMode.AUTO: Mode.ECO,
    HVACMode.FAN_ONLY: Mode.FAN,
    HVACMode.COOL: Mode.COOL,
    HVACMode.OFF: Mode.OFF,
    HVACMode.DRY: Mode.DRY,
}

# mode_state is the mode the appliance reports it is actually running. Only the concrete
# running modes map to an action; ECO/AUTO/SMART are settings and fall through to the
# mode-derived fallback in hvac_action.
MODE_STATE_TO_HA_ACTION = {
    Mode.COOL: HVACAction.COOLING,
    Mode.FAN: HVACAction.FAN,
    Mode.DRY: HVACAction.DRYING,
}

FRIGIDAIRE_TO_HA_FAN_SPEED = {
    FanSpeed.AUTO: FAN_AUTO,
    FanSpeed.LOW: FAN_LOW,
    FanSpeed.MEDIUM: FAN_MEDIUM,
    FanSpeed.HIGH: FAN_HIGH,
}
HA_TO_FRIGIDAIRE_FAN_MODE = {v: k for k, v in FRIGIDAIRE_TO_HA_FAN_SPEED.items()}

BASE_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.FAN_MODE
    | ClimateEntityFeature.PRESET_MODE
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.TURN_ON
)


class FrigidaireClimate(FrigidaireEntity, ClimateEntity):
    """A Frigidaire air conditioner."""

    _attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.AUTO, HVACMode.FAN_ONLY, HVACMode.DRY]
    _attr_preset_modes = [PRESET_NONE, PRESET_SLEEP]
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: FrigidaireCoordinator, appliance) -> None:
        super().__init__(coordinator, appliance, unique_id=appliance.appliance_id, name=appliance.nickname)
        self._optimistic = Optimistic()
        self._update_swing_support()

    def _update_swing_support(self) -> None:
        """Advertise swing only on models with a motorised louver; the others omit the key."""
        if self.appliance.vertical_swing is not None:
            self._attr_supported_features = BASE_FEATURES | ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL]
        else:
            self._attr_supported_features = BASE_FEATURES
            self._attr_swing_modes = None

    @property
    def available(self) -> bool:
        # Some portable models omit applianceState, so a reported mode is enough.
        appliance = self.appliance
        return super().available and (appliance.state is not None or appliance.mode is not None)

    @property
    def temperature_unit(self) -> str:
        return FRIGIDAIRE_TO_HA_UNIT.get(self.appliance.temperature_unit, UnitOfTemperature.FAHRENHEIT)

    @property
    def min_temp(self) -> float:
        return 60 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 16

    @property
    def max_temp(self) -> float:
        return 90 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 32

    @property
    def current_temperature(self) -> float | None:
        return self.appliance.ambient_temperature

    @property
    def target_temperature(self) -> float | None:
        if (temperature := self._optimistic.get("temperature")) is not None:
            return temperature
        return self.appliance.target_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        if (hvac_mode := self._optimistic.get("hvac_mode")) is not None:
            return hvac_mode
        appliance = self.appliance
        if appliance.state is ApplianceState.OFF:
            return HVACMode.OFF
        hvac_mode = FRIGIDAIRE_TO_HA_MODE.get(appliance.mode)
        if hvac_mode is None and appliance.get(Detail.MODE) is not None:
            _LOGGER.warning("Unsupported HVAC mode '%s' reported by device.", appliance.get(Detail.MODE))
        return hvac_mode

    @property
    def hvac_action(self) -> HVACAction | None:
        hvac_mode = self.hvac_mode
        if hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        appliance = self.appliance
        if appliance.state is not ApplianceState.RUNNING:
            return HVACAction.IDLE
        # The reported running mode wins: in ECO the requested mode says nothing about
        # whether the unit is cooling or just running the fan right now. hvac_mode stays on
        # the requested mode, which is the user's selection and must not flap.
        if (action := MODE_STATE_TO_HA_ACTION.get(appliance.mode_state)) is not None:
            return action
        if hvac_mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        # The opt-in temperature-based estimate only refines models without mode_state.
        if self.coordinator.compressor_estimate(self.appliance_id) is False:
            return HVACAction.IDLE
        if hvac_mode == HVACMode.DRY:
            return HVACAction.DRYING
        return HVACAction.COOLING

    @property
    def fan_mode(self) -> str | None:
        if (fan_mode := self._optimistic.get("fan_mode")) is not None:
            return fan_mode
        return FRIGIDAIRE_TO_HA_FAN_SPEED.get(self.appliance.fan_speed)

    @property
    def swing_mode(self) -> str | None:
        if not self._attr_supported_features & ClimateEntityFeature.SWING_MODE:
            return None
        if (swing_mode := self._optimistic.get("swing_mode")) is not None:
            return swing_mode
        return SWING_VERTICAL if self.appliance.vertical_swing else SWING_OFF

    @property
    def preset_mode(self) -> str | None:
        if (preset_mode := self._optimistic.get("preset_mode")) is not None:
            return preset_mode
        return PRESET_SLEEP if self.appliance.sleep_mode else PRESET_NONE

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        appliance = self.appliance
        attributes: dict[str, Any] = {"check_filter": appliance.filter_needs_attention or False}
        # The reported speed can resolve an AUTO setting to a concrete level, but may hold
        # its last value while the appliance is off. Unknown speeds pass through lowercased.
        if (raw_speed := appliance.get(Detail.FAN_SPEED_STATE)) is not None:
            reported = FRIGIDAIRE_TO_HA_FAN_SPEED.get(appliance.fan_speed_state, str(raw_speed).lower())
            attributes["reported_fan_speed"] = reported
            attributes["current_fan_speed"] = reported  # legacy alias for existing templates
        if appliance.alerts is not None:
            attributes["active_alerts"] = appliance.alerts
        return attributes

    def set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self.client.set_temperature(self.appliance, int(temperature), HA_TO_FRIGIDAIRE_UNIT[self.temperature_unit])
        self._optimistic.set("temperature", float(int(temperature)))
        self.refresh()

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if (mode := HA_TO_FRIGIDAIRE_HVAC_MODE.get(hvac_mode)) is None:
            return
        self.client.set_mode(self.appliance, mode)
        self._optimistic.set("hvac_mode", hvac_mode)
        self.refresh()

    def set_fan_mode(self, fan_mode: str) -> None:
        if (fan_speed := HA_TO_FRIGIDAIRE_FAN_MODE.get(fan_mode)) is None:
            return
        self.client.set_fan_speed(self.appliance, fan_speed)
        self._optimistic.set("fan_mode", fan_mode)
        self.refresh()

    def set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            return
        self.client.set_sleep_mode(self.appliance, preset_mode == PRESET_SLEEP)
        self._optimistic.set("preset_mode", preset_mode)
        self.refresh()

    def set_swing_mode(self, swing_mode: str) -> None:
        if not self._attr_swing_modes or swing_mode not in self._attr_swing_modes:
            return
        self.client.set_vertical_swing(self.appliance, swing_mode == SWING_VERTICAL)
        self._optimistic.set("swing_mode", swing_mode)
        self.refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic.expire()
        self._update_swing_support()
        super()._handle_coordinator_update()

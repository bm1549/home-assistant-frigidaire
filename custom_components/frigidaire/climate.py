"""ClimateEntity for frigidaire integration."""

from __future__ import annotations

import logging
import time
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .compressor import estimate_compressor_running
from .const import (
    CONF_COMPRESSOR_OFF_DELAY,
    CONF_COOL_HYSTERESIS,
    DEFAULT_COMPRESSOR_OFF_DELAY,
    DEFAULT_COOL_HYSTERESIS,
    DOMAIN,
)
from .diagnostics import (
    AIR_FILTER_LIFETIME_KEY,
    filter_needs_attention,
    normalize_alerts,
    normalize_filter_state,
)
from .helpers import suggest_area

_LOGGER = logging.getLogger(__name__)


def _normalize_enum_value(value):
    """Normalize API values to uppercase for enum comparison."""
    if isinstance(value, str):
        return value.upper()
    return value


def _coerce_float(value, default) -> float:
    """Coerce an option value to float, falling back to default on bad input."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    state_store: dict = hass.data[DOMAIN][entry.entry_id].setdefault("climate_state", {})

    async_add_entities(
        [
            FrigidaireClimate(
                client,
                appliance,
                suggest_area(hass, appliance.nickname),
                entry.options.get(appliance.appliance_id, {}),
                state_store,
            )
            for appliance in appliances
            if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
        ],
        update_before_add=True,
    )


FRIGIDAIRE_TO_HA_UNIT = {
    frigidaire.Unit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
    frigidaire.Unit.CELSIUS: UnitOfTemperature.CELSIUS,
}

FRIGIDAIRE_TO_HA_MODE = {
    frigidaire.Mode.OFF: HVACMode.OFF,
    frigidaire.Mode.COOL: HVACMode.COOL,
    frigidaire.Mode.FAN: HVACMode.FAN_ONLY,
    frigidaire.Mode.ECO: HVACMode.AUTO,
    frigidaire.Mode.AUTO: HVACMode.AUTO,
    frigidaire.Mode.DRY: HVACMode.DRY,
}

FRIGIDAIRE_TO_HA_FAN_SPEED = {
    frigidaire.FanSpeed.AUTO: FAN_AUTO,
    frigidaire.FanSpeed.LOW: FAN_LOW,
    frigidaire.FanSpeed.MEDIUM: FAN_MEDIUM,
    frigidaire.FanSpeed.HIGH: FAN_HIGH,
}

HA_TO_FRIGIDAIRE_UNIT = {
    UnitOfTemperature.FAHRENHEIT: frigidaire.Unit.FAHRENHEIT,
    UnitOfTemperature.CELSIUS: frigidaire.Unit.CELSIUS,
}

HA_TO_FRIGIDAIRE_FAN_MODE = {
    FAN_AUTO: frigidaire.FanSpeed.AUTO,
    FAN_LOW: frigidaire.FanSpeed.LOW,
    FAN_MEDIUM: frigidaire.FanSpeed.MEDIUM,
    FAN_HIGH: frigidaire.FanSpeed.HIGH,
}

HA_TO_FRIGIDAIRE_HVAC_MODE = {
    HVACMode.AUTO: frigidaire.Mode.AUTO,
    HVACMode.FAN_ONLY: frigidaire.Mode.FAN,
    HVACMode.COOL: frigidaire.Mode.COOL,
    HVACMode.OFF: frigidaire.Mode.OFF,
    HVACMode.DRY: frigidaire.Mode.DRY,
}

FRIGIDAIRE_TO_HA_SWING = {
    frigidaire.VerticalSwing.ON: SWING_VERTICAL,
    frigidaire.VerticalSwing.OFF: SWING_OFF,
}

HA_TO_FRIGIDAIRE_SWING = {
    SWING_VERTICAL: frigidaire.VerticalSwing.ON,
    SWING_OFF: frigidaire.VerticalSwing.OFF,
}

HA_TO_FRIGIDAIRE_PRESET = {
    PRESET_SLEEP: frigidaire.SleepMode.ON,
    PRESET_NONE: frigidaire.SleepMode.OFF,
}

OPTIMISTIC_WINDOW = 5  # seconds

# Raw reported fan-speed state. It can resolve AUTO to a concrete level, but it
# persists while the appliance is off and is not physical running telemetry.
# Keep the raw key for library versions predating FAN_SPEED_STATE.
FAN_SPEED_STATE_KEY = "fanSpeedState"


class FrigidaireClimate(ClimateEntity):
    """Representation of a Frigidaire appliance."""

    def __init__(
        self,
        client,
        appliance,
        suggested_area: str | None = None,
        options: Mapping[str, Any] | None = None,
        state_store: dict | None = None,
    ):
        """Build FrigidaireClimate.

        client: the client used to contact the frigidaire API
        appliance: the basic information about the frigidaire appliance, used to contact
            the API
        options: per-appliance options from the config entry (compressor-state
            estimation tuning, etc.)
        state_store: per-entry dict the entity publishes compressor / fan state
            into for the optional diagnostic sensor entities to read.
        """

        self._client: frigidaire.Frigidaire = client
        self._appliance: frigidaire.Appliance = appliance
        self._details: dict = {}
        self._state_store = state_store

        # Compressor-state estimation tuning (configurable via the options flow).
        options = options or {}
        self._cool_hysteresis = _coerce_float(options.get(CONF_COOL_HYSTERESIS), DEFAULT_COOL_HYSTERESIS)
        self._compressor_off_delay = _coerce_float(
            options.get(CONF_COMPRESSOR_OFF_DELAY), DEFAULT_COMPRESSOR_OFF_DELAY
        )

        # Optimistic state — holds values for OPTIMISTIC_WINDOW seconds after a command
        self._optimistic_until: float = 0
        self._optimistic_temperature: float | None = None
        self._optimistic_hvac_mode: str | None = None
        self._optimistic_fan_mode: str | None = None
        self._optimistic_preset_mode: str | None = None
        self._optimistic_swing_mode: str | None = None

        # Monotonic timestamp of when the room first dropped below the setpoint
        # band, and the last estimated compressor state. Used to delay flipping
        # hvac_action to idle and to hold state inside the hysteresis deadband.
        self._compressor_satisfied_since: float | None = None
        self._compressor_estimate: bool = True

        # Entity Class Attributes
        self._attr_unique_id = self._appliance.appliance_id
        self._attr_name = self._appliance.nickname
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._appliance.appliance_id)},
            name=self._appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._attr_preset_modes = [PRESET_NONE, PRESET_SLEEP]
        self._attr_swing_modes = [SWING_OFF, SWING_VERTICAL]
        self._attr_target_temperature_step = 1

        self._attr_fan_modes = [
            FAN_AUTO,
            FAN_LOW,
            FAN_MEDIUM,
            FAN_HIGH,
        ]

        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.AUTO,
            HVACMode.FAN_ONLY,
            HVACMode.DRY,
        ]

    def _set_optimistic_window(self) -> None:
        self._optimistic_until = time.monotonic() + OPTIMISTIC_WINDOW

    def _is_optimistic(self) -> bool:
        return time.monotonic() < self._optimistic_until

    def _clear_optimistic(self) -> None:
        self._optimistic_temperature = None
        self._optimistic_hvac_mode = None
        self._optimistic_fan_mode = None
        self._optimistic_preset_mode = None
        self._optimistic_swing_mode = None

    def _is_compressor_running(self) -> bool:
        """Estimate whether the compressor is actively cooling/drying.

        The Frigidaire API does not expose compressor state directly, so infer
        it. A window / room AC only runs the compressor while the room is above
        the target setpoint. Two configurable knobs shape the estimate:

        - cool_hysteresis: a deadband (in the device's temperature unit) around
          the setpoint. The compressor is reported cooling above
          target + hysteresis and idle below target - hysteresis; inside the
          band the previous estimate is held, which prevents flapping when the
          room hovers around the setpoint.
        - compressor_off_delay: how long the room must stay below the band before
          we flip to idle, modelling compressor run-on. Cooling is reported again
          immediately once the room rises back above the band.

        fanSpeedState is deliberately excluded: live devices retain that value
        while powered off, so it is not evidence that the fan or compressor is
        physically running.

        This estimate exists mainly to feed energy-usage calculations, so it errs
        toward reporting activity when the device gives us nothing to go on.
        """
        current = self.current_temperature
        target = self.target_temperature
        self._compressor_estimate, self._compressor_satisfied_since = estimate_compressor_running(
            current,
            target,
            hysteresis=self._cool_hysteresis,
            off_delay=self._compressor_off_delay,
            previous=self._compressor_estimate,
            satisfied_since=self._compressor_satisfied_since,
            now=time.monotonic(),
        )
        return self._compressor_estimate

    @property
    def reported_fan_speed(self) -> str | None:
        """Return the appliance's reported fan-speed state.

        This can resolve an AUTO setting to a concrete level, but it may retain
        the last value while the appliance is off and is not running telemetry.
        """
        raw = self._details.get(FAN_SPEED_STATE_KEY)
        if raw is None:
            return None
        return FRIGIDAIRE_TO_HA_FAN_SPEED.get(_normalize_enum_value(raw), str(raw).lower())

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        unit = _normalize_enum_value(self._details.get(frigidaire.Detail.TEMPERATURE_REPRESENTATION))

        return FRIGIDAIRE_TO_HA_UNIT[unit]

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self._is_optimistic() and self._optimistic_temperature is not None:
            return self._optimistic_temperature
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return self._details.get(frigidaire.Detail.TARGET_TEMPERATURE_F)
        else:
            return self._details.get(frigidaire.Detail.TARGET_TEMPERATURE_C)

    @property
    def hvac_mode(self):
        """Return current operation i.e. heat, cool, idle."""
        if self._is_optimistic() and self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
        frigidaire_mode = _normalize_enum_value(self._details.get(frigidaire.Detail.MODE))

        if frigidaire_mode not in FRIGIDAIRE_TO_HA_MODE:
            _LOGGER.warning("Unsupported HVAC mode '%s' reported by device.", frigidaire_mode)
            return None

        return FRIGIDAIRE_TO_HA_MODE[frigidaire_mode]

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        mode = self.hvac_mode
        if mode is None:
            return None
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        appliance_state = _normalize_enum_value(self._details.get(frigidaire.Detail.APPLIANCE_STATE))
        if appliance_state is not None and appliance_state != frigidaire.ApplianceState.RUNNING:
            # OFF or DELAYED_START — the unit is powered but not conditioning.
            return HVACAction.IDLE
        # The fan runs whenever the unit is on, but the compressor cycles
        # independently. Only report cooling/drying while the compressor is
        # estimated to be running; otherwise the unit is idling (fan-only).
        if mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        if not self._is_compressor_running():
            return HVACAction.IDLE
        if mode == HVACMode.DRY:
            return HVACAction.DRYING
        return HVACAction.COOLING

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return self._details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_F)
        else:
            return self._details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_C)

    @property
    def fan_mode(self):
        """Return the fan setting."""
        if self._is_optimistic() and self._optimistic_fan_mode is not None:
            return self._optimistic_fan_mode
        fan_speed = _normalize_enum_value(self._details.get(frigidaire.Detail.FAN_SPEED))

        if not fan_speed:
            return None

        return FRIGIDAIRE_TO_HA_FAN_SPEED.get(fan_speed)

    @property
    def swing_mode(self) -> str | None:
        """Return the swing setting."""
        if self._is_optimistic() and self._optimistic_swing_mode is not None:
            return self._optimistic_swing_mode
        swing = _normalize_enum_value(self._details.get(frigidaire.Detail.VERTICAL_SWING))
        if swing == frigidaire.VerticalSwing.ON:
            return SWING_VERTICAL
        return SWING_OFF

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return 60

        return 16

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return 90

        return 32

    @property
    def preset_mode(self) -> str | None:
        if self._is_optimistic() and self._optimistic_preset_mode is not None:
            return self._optimistic_preset_mode
        sleep = _normalize_enum_value(self._details.get(frigidaire.Detail.SLEEP_MODE))
        if sleep == frigidaire.SleepMode.ON:
            return PRESET_SLEEP
        return PRESET_NONE

    def set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in HA_TO_FRIGIDAIRE_PRESET:
            return
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_sleep_mode(HA_TO_FRIGIDAIRE_PRESET[preset_mode])
        )
        self._optimistic_preset_mode = preset_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def set_swing_mode(self, swing_mode: str) -> None:
        if swing_mode not in HA_TO_FRIGIDAIRE_SWING:
            return
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_vertical_swing(HA_TO_FRIGIDAIRE_SWING[swing_mode])
        )
        self._optimistic_swing_mode = swing_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attributes: dict[str, Any] = {
            "check_filter": filter_needs_attention(self._details.get(frigidaire.Detail.FILTER_STATE)) or False,
        }
        reported_fan_speed = self.reported_fan_speed
        if reported_fan_speed is not None:
            attributes["reported_fan_speed"] = reported_fan_speed
            # Keep the original attribute for existing dashboards and templates.
            attributes["current_fan_speed"] = reported_fan_speed
        return attributes

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = int(temperature)
        temperature_unit = HA_TO_FRIGIDAIRE_UNIT[self.temperature_unit]

        _LOGGER.debug("Setting temperature to %s %s", temperature, self.temperature_unit)
        self._client.execute_action(self._appliance, frigidaire.Action.set_temperature(temperature, temperature_unit))
        self._optimistic_temperature = float(temperature)
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        if fan_mode not in HA_TO_FRIGIDAIRE_FAN_MODE:
            return
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_fan_speed(HA_TO_FRIGIDAIRE_FAN_MODE[fan_mode])
        )
        self._optimistic_fan_mode = fan_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def set_hvac_mode(self, hvac_mode):
        """Set new target operation mode."""
        _LOGGER.debug("Setting HVAC mode to %s", hvac_mode)

        if hvac_mode == HVACMode.OFF:
            self._client.execute_action(self._appliance, frigidaire.Action.set_mode(frigidaire.Mode.OFF))
        else:
            if hvac_mode not in HA_TO_FRIGIDAIRE_HVAC_MODE:
                return
            if _normalize_enum_value(self._details.get(frigidaire.Detail.MODE)) == frigidaire.Mode.OFF:
                self._client.execute_action(self._appliance, frigidaire.Action.set_power(frigidaire.Power.ON))
                # temperature reverts to default when the device is turned on
                current_temp = self.target_temperature
                if current_temp is not None:
                    self._client.execute_action(
                        self._appliance,
                        frigidaire.Action.set_temperature(
                            int(current_temp), HA_TO_FRIGIDAIRE_UNIT[self.temperature_unit]
                        ),
                    )
            self._client.execute_action(
                self._appliance, frigidaire.Action.set_mode(HA_TO_FRIGIDAIRE_HVAC_MODE[hvac_mode])
            )

        self._optimistic_hvac_mode = hvac_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def update(self):
        """Retrieve latest state and updates the details."""
        try:
            details = self._client.get_appliance_details(self._appliance)
            self._details = details
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False
        else:
            # If we successfully retrieved details, the appliance is available.
            # Prefer applianceState when present; fall back to checking for a
            # reported mode, since some portable AC models (e.g. FHPW-series)
            # omit applianceState from their API response.
            appliance_state = self._details.get(frigidaire.Detail.APPLIANCE_STATE)
            mode = self._details.get(frigidaire.Detail.MODE)
            self._attr_available = appliance_state is not None or mode is not None

            if not self._is_optimistic():
                self._clear_optimistic()
        finally:
            self._publish_shared_state()

    def _publish_shared_state(self) -> None:
        """Publish state for the optional diagnostic entities.

        Optional entities read this store so they remain synchronized with the
        climate entity without making their own API calls.
        """
        if self._state_store is None:
            return
        if not self._attr_available:
            self._state_store[self._appliance.appliance_id] = {
                "available": False,
                "active_alerts": None,
                "compressor_running": None,
                "reported_fan_speed": None,
                "filter_runtime": None,
                "filter_state": None,
            }
            return
        action = self.hvac_action
        self._state_store[self._appliance.appliance_id] = {
            "available": True,
            "active_alerts": normalize_alerts(self._details.get(frigidaire.Detail.ALERTS)),
            "compressor_running": None if action is None else action in (HVACAction.COOLING, HVACAction.DRYING),
            "reported_fan_speed": self.reported_fan_speed,
            "filter_runtime": self._details.get(AIR_FILTER_LIFETIME_KEY),
            "filter_state": normalize_filter_state(self._details.get(frigidaire.Detail.FILTER_STATE)),
        }

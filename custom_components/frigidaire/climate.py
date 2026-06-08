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
    FAN_OFF,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_OFF,
    SWING_VERTICAL,
    HVACMode,
    HVACAction,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

OPTIMISTIC_WINDOW = 5  # seconds to hold optimistic state after setting


def _normalize_enum_value(value):
    """Normalize API values to uppercase for enum comparison."""
    if isinstance(value, str):
        return value.upper()
    return value


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]

    def get_entities(username: str, password: str) -> list[frigidaire.Appliance]:
        return client.get_appliances()

    appliances = await hass.async_add_executor_job(get_entities, entry.data["username"], entry.data["password"])

    async_add_entities(
        [
            FrigidaireClimate(client, appliance)
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

FRIGIDAIRE_TO_HA_PRESET = {
    frigidaire.SleepMode.OFF: PRESET_NONE,
    frigidaire.SleepMode.ON: PRESET_SLEEP
}

FRIGIDAIRE_TO_HA_SWING = {
    frigidaire.VerticalSwing.OFF: SWING_OFF,
    frigidaire.VerticalSwing.ON: SWING_VERTICAL
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

HA_TO_FRIGIDAIRE_PRESET = {
    PRESET_NONE: frigidaire.SleepMode.OFF,
    PRESET_SLEEP: frigidaire.SleepMode.ON
}

HA_TO_FRIGIDAIRE_SWING = {
    SWING_OFF: frigidaire.VerticalSwing.OFF,
    SWING_VERTICAL: frigidaire.VerticalSwing.ON
}

HA_TO_FRIGIDAIRE_HVAC_MODE = {
    HVACMode.AUTO: frigidaire.Mode.AUTO,
    HVACMode.FAN_ONLY: frigidaire.Mode.FAN,
    HVACMode.COOL: frigidaire.Mode.COOL,
    HVACMode.OFF: frigidaire.Mode.OFF,
    HVACMode.DRY: frigidaire.Mode.DRY,
}


class FrigidaireClimate(ClimateEntity):
    """Representation of a Frigidaire appliance."""

    def __init__(self, client, appliance):
        """Build FrigidaireClimate.

        client: the client used to contact the frigidaire API
        appliance: the basic information about the frigidaire appliance, used to contact
            the API
        """

        self._client: frigidaire.Frigidaire = client
        self._appliance: frigidaire.Appliance = appliance
        self._details: dict | None = None

        # Optimistic state overrides
        self._optimistic_hvac_mode: Optional[HVACMode] = None
        self._optimistic_fan_mode: Optional[str] = None
        self._optimistic_preset_mode: Optional[str] = None
        self._optimistic_swing_mode: Optional[str] = None
        self._optimistic_temperature: Optional[float] = None
        self._optimistic_until: Optional[float] = None

        # Entity Class Attributes
        self._attr_unique_id = self._appliance.appliance_id
        self._attr_name = self._appliance.nickname
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.PRESET_MODE
        )
        self._attr_target_temperature_step = 1

        # Although we can access the Frigidaire API to get updates, they are
        # not reflected immediately after making a request. To improve the UX
        # around this, we set assume_state to True
        self._attr_assumed_state = True

        self._attr_preset_modes = [
            PRESET_NONE,
            PRESET_SLEEP
        ]

        self._attr_swing_modes = [
            SWING_OFF,
            SWING_VERTICAL
        ]

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

    @property
    def assumed_state(self):
        """Return True if unable to access real state of the entity."""
        return self._attr_assumed_state

    @property
    def unique_id(self):
        """Return unique ID based on Frigidaire ID."""
        return self._attr_unique_id
    
    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._appliance.appliance_id)},
            "name": self._appliance.nickname,
            "manufacturer": "Frigidaire",
            "model": "AC",
            "via_device": (DOMAIN, self._appliance.appliance_id),
        }

    @property
    def name(self):
        """Return the name of the entity."""
        return self._attr_name

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._attr_supported_features

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._attr_hvac_modes
    
    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation."""
        if not self._details:
            return None

        # During optimistic window, derive action directly from optimistic mode
        if self._is_optimistic() and self._optimistic_hvac_mode is not None:
            if self._optimistic_hvac_mode == HVACMode.OFF:
                return HVACAction.OFF
            elif self._optimistic_hvac_mode == HVACMode.COOL:
                return HVACAction.COOLING
            elif self._optimistic_hvac_mode == HVACMode.AUTO:
                return HVACAction.COOLING
            elif self._optimistic_hvac_mode == HVACMode.FAN_ONLY:
                return HVACAction.FAN
            elif self._optimistic_hvac_mode == HVACMode.DRY:
                return HVACAction.DRYING
            return HVACAction.IDLE

        # No optimistic state — use real API data
        appliance_state = _normalize_enum_value(
            self._details.get(frigidaire.Detail.APPLIANCE_STATE)
        )

        if appliance_state in ["OFF", "DELAYED_START"]:
            return HVACAction.OFF

        mode = self.hvac_mode
        if mode == HVACMode.COOL:
            return HVACAction.COOLING
        elif mode == HVACMode.AUTO:
            return HVACAction.COOLING
        elif mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        elif mode == HVACMode.DRY:
            return HVACAction.DRYING

        return HVACAction.IDLE

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._attr_target_temperature_step

    @property
    def fan_modes(self):
        """List of available fan modes."""
        return self._attr_fan_modes

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        if not self._details:
            return UnitOfTemperature.FAHRENHEIT  # Default to Fahrenheit if we don't have details yet
        
        unit = _normalize_enum_value(self._details.get(frigidaire.Detail.TEMPERATURE_REPRESENTATION))

        return FRIGIDAIRE_TO_HA_UNIT[unit]
    
    @property
    def swing_mode(self):
        """Return the swing setting."""
        if self._is_optimistic() and self._optimistic_swing_mode is not None:
            return self._optimistic_swing_mode
        if not self._details:
            return SWING_OFF
        swing = _normalize_enum_value(self._details.get(frigidaire.Detail.VERTICAL_SWING))
        return FRIGIDAIRE_TO_HA_SWING[swing]

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self._is_optimistic() and self._optimistic_temperature is not None:
            return self._optimistic_temperature
        if not self._details:
            return 0
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return self._details.get(frigidaire.Detail.TARGET_TEMPERATURE_F)
        return self._details.get(frigidaire.Detail.TARGET_TEMPERATURE_C)
        
    @property
    def preset_mode(self):
        """Return current preset mode."""
        if self._is_optimistic() and self._optimistic_preset_mode is not None:
            return self._optimistic_preset_mode
        if not self._details:
            return PRESET_NONE
        sleep = _normalize_enum_value(self._details.get(frigidaire.Detail.SLEEP_MODE))
        return FRIGIDAIRE_TO_HA_PRESET[sleep]

    @property
    def hvac_mode(self):
        """Return current operation i.e. heat, cool, idle."""
        if self._is_optimistic() and self._optimistic_hvac_mode is not None:
            return self._optimistic_hvac_mode
        if not self._details:
            return HVACMode.OFF
        appliance_state = _normalize_enum_value(
            self._details.get(frigidaire.Detail.APPLIANCE_STATE)
        )
        if appliance_state in ["OFF", "DELAYED_START"]:
            return HVACMode.OFF
        frigidaire_mode = _normalize_enum_value(self._details.get(frigidaire.Detail.MODE))
        return FRIGIDAIRE_TO_HA_MODE[frigidaire_mode]

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if not self._details:
            return 0
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return self._details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_F)
        return self._details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_C)

    @property
    def fan_mode(self):
        """Return the fan setting."""
        if self._is_optimistic() and self._optimistic_fan_mode is not None:
            return self._optimistic_fan_mode
        if not self._details:
            return FAN_OFF
        fan_speed = _normalize_enum_value(self._details.get(frigidaire.Detail.FAN_SPEED))
        if not fan_speed:
            return FAN_OFF
        return FRIGIDAIRE_TO_HA_FAN_SPEED[fan_speed]

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return 60 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 16

    @property
    def max_temp(self):
        return 90 if self.temperature_unit == UnitOfTemperature.FAHRENHEIT else 32

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the extra state attributes, check_filter, start_time and stop_time."""
        if not self._details:
            return None
        return {
            "check_filter": bool(_normalize_enum_value(self._details.get(frigidaire.Detail.FILTER_STATE)) == "CHANGE"),
            "start_time": self._details.get(frigidaire.Detail.START_TIME),
            "stop_time": self._details.get(frigidaire.Detail.STOP_TIME),
        }
    
    def _is_optimistic(self) -> bool:
        """Return True if we are within the optimistic window."""
        if self._optimistic_until is None:
            return False
        from datetime import datetime
        return datetime.now().timestamp() < self._optimistic_until
    

    def _set_optimistic_window(self) -> None:
        """Start the optimistic window."""
        from datetime import datetime, timedelta
        self._optimistic_until = (datetime.now() + timedelta(seconds=OPTIMISTIC_WINDOW)).timestamp()

    def _clear_optimistic(self) -> None:
        """Clear all optimistic overrides."""
        self._optimistic_hvac_mode = None
        self._optimistic_fan_mode = None
        self._optimistic_preset_mode = None
        self._optimistic_swing_mode = None
        self._optimistic_temperature = None
        self._optimistic_until = None

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
            self._appliance,
            frigidaire.Action.set_fan_speed(HA_TO_FRIGIDAIRE_FAN_MODE[fan_mode]),
        )
        self._optimistic_fan_mode = fan_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def set_preset_mode(self, preset_mode) -> None:
        """Set new preset mode."""
        if preset_mode not in HA_TO_FRIGIDAIRE_PRESET:
            return
        self._client.execute_action(
            self._appliance,
            frigidaire.Action.set_sleep_mode(HA_TO_FRIGIDAIRE_PRESET[preset_mode]),
        )
        self._optimistic_preset_mode = preset_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def set_swing_mode(self, swing_mode) -> None:
        """Set new swing mode."""
        if swing_mode not in HA_TO_FRIGIDAIRE_SWING:
            return
        self._client.execute_action(
            self._appliance,
            frigidaire.Action.set_vertical_swing(HA_TO_FRIGIDAIRE_SWING[swing_mode]),
        )
        self._optimistic_swing_mode = swing_mode
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
                self._client.execute_action(self._appliance,
                    [
                        frigidaire.Action.set_power(frigidaire.Power.ON),
                        frigidaire.Action.set_temperature(int(self.target_temperature)),
                    ],
                )
            self._client.execute_action(self._appliance, frigidaire.Action.set_mode(HA_TO_FRIGIDAIRE_HVAC_MODE[hvac_mode]))

        self._optimistic_hvac_mode = hvac_mode
        self._set_optimistic_window()
        self.schedule_update_ha_state(force_refresh=False)

    def update(self):
        """Retrieve latest state and updates the details."""
        try:
            details = self._client.get_appliance_details(self._appliance)
            _LOGGER.debug(
                "Retrieved details for appliance %s: %s",
                self._appliance.appliance_id, details,
            )
            self._details = details
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False
        else:
            appliance_state = self._details.get(frigidaire.Detail.APPLIANCE_STATE)
            self._attr_available = appliance_state is not None

            # Clear optimistic state once polling window expires
            if not self._is_optimistic():
                self._clear_optimistic()

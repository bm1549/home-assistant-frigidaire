"""ClimateEntity for frigidaire integration."""
from __future__ import annotations

import logging

import frigidaire

from homeassistant.components.humidifier import HumidifierEntity
from homeassistant.components.humidifier.const import (
    ATTR_AVAILABLE_MODES,
    DEVICE_CLASS_DEHUMIDIFIER,
    MODE_BOOST,
    MODE_NORMAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


class FrigidaireClimate(HumidifierEntity):
    """Representation of a Frigidaire appliance."""

    def __init__(self, client, appliance):
        """Build FrigidaireClimate.

        client: the client used to contact the frigidaire API
        appliance: the basic information about the frigidaire appliance, used to contact the API
        """

        self._client = client
        self._appliance = appliance
        self._details = None

        # Entity Class Attributes
        self._attr_unique_id = appliance.appliance_id
        self._attr_name = appliance.nickname
        self._attr_supported_features = SUPPORT_MODES
        self._attr_target_temperature_step = 1

        # Although we can access the Frigidaire API to get updates, they are
        # not reflected immediately after making a request. To improve the UX
        # around this, we set assume_state to True
        self._attr_assumed_state = True

        self._attr_fan_modes = [
            FAN_AUTO,
            FAN_LOW,
            FAN_MEDIUM,
            FAN_HIGH,
        ]

        self._attr_hvac_modes = [
            HVAC_MODE_OFF,
            HVAC_MODE_COOL,
            HVAC_MODE_AUTO,
            HVAC_MODE_FAN_ONLY,
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
    def name(self):
        """Return the name of the entity."""
        return self._attr_name

    @property
    def device_class(self):
        return DEVICE_CLASS_DEHUMIDIFIER

    @property
    def is_on(self):
        return

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._attr_supported_features

    @property
    def available_modes(self):
        """List of available operation modes."""
        return self._attr_hvac_modes

    @property
    def target_humidity(self):
        """Return the humidity we try to reach."""
        return (
            self._details.for_code(frigidaire.HaclCode.TARGET_TEMPERATURE)
            .containers.for_id(frigidaire.ContainerId.TEMPERATURE)
            .number_value
        )

    @property
    def mode(self):
        """Return current operation ie. dry, continuous."""
        convert = {
            frigidaire.Mode.OFF.value: HVAC_MODE_OFF,
            frigidaire.Mode.COOL.value: HVAC_MODE_COOL,
            frigidaire.Mode.FAN.value: HVAC_MODE_FAN_ONLY,
            frigidaire.Mode.ECO.value: HVAC_MODE_AUTO,
        }

        frigidaire_mode = self._details.for_code(
            frigidaire.HaclCode.AC_MODE
        ).number_value

        return convert[frigidaire_mode]

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return (
            self._details.for_code(frigidaire.HaclCode.AMBIENT_TEMPERATURE)
            .containers.for_id(frigidaire.ContainerId.TEMPERATURE)
            .number_value
        )

    @property
    def fan_mode(self):
        """Return the fan setting."""
        convert = {
            frigidaire.FanSpeed.OFF.value: FAN_OFF,  # when the AC is off
            frigidaire.FanSpeed.LOW.value: FAN_LOW,
            frigidaire.FanSpeed.HIGH.value: FAN_HIGH,
        }
        fan_speed = self._details.for_code(frigidaire.HaclCode.AC_FAN_SPEED_SETTING)

        if not fan_speed:
            return FAN_OFF

        return convert[fan_speed.number_value]

    @property
    def min_humidity(self):
        """Return the minimum humidity."""
        return 35

    @property
    def max_humidity(self):
        """Return the maximum humidity."""
        return 85

    def set_humidity(self, **kwargs):
        """Set new target humidity."""
        humidity = kwargs.get(ATTR_HUMIDITY)
        if humidity is None:
            return
        humidity = int(humidity)
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_mode(frigidaire.Mode.DRY)
        )
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_humidity(humidity)
        )

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        convert = {
            FAN_LOW: frigidaire.FanSpeed.LOW,
            FAN_HIGH: frigidaire.FanSpeed.HIGH,
        }

        # Guard against unexpected fan modes
        if fan_mode not in convert:
            return

        action = frigidaire.Action.set_fan_speed(convert[fan_mode])
        self._client.execute_action(self._appliance, action)

    def set_mode(self, mode):
        """Set new target operation mode."""
        if mode == HVAC_MODE_OFF:
            self._client.execute_action(
                self._appliance, frigidaire.Action.set_power(frigidaire.Power.OFF)
            )
            return

        convert = {
            HVAC_MODE_AUTO: frigidaire.Mode.ECO,
            HVAC_MODE_FAN_ONLY: frigidaire.Mode.FAN,
            HVAC_MODE_COOL: frigidaire.Mode.COOL,
        }

        # Guard against unexpected hvac modes
        if hvac_mode not in convert:
            return

        # Turn on if not currently on.
        if self._details.for_code(frigidaire.HaclCode.AC_MODE) == 0:
            self._client.execute_action(
                self._appliance, frigidaire.Action.set_power(frigidaire.Power.ON)
            )

        self._client.execute_action(
            self._appliance, frigidaire.Action.set_mode(convert[hvac_mode])
        )

    def update(self):
        """Retrieve latest state and updates the details."""
        try:
            details = self._client.get_appliance_details(self._appliance)
            self._details = details
            self._attr_available = True
        except (frigidaire.FrigidaireException):
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False

"""ClimateEntity for frigidaire integration."""
from __future__ import annotations

import logging
from typing import List, Any

import frigidaire

from homeassistant.components.humidifier import HumidifierEntity
from homeassistant.components.humidifier.const import (
    DEVICE_CLASS_DEHUMIDIFIER,
    MODE_BOOST,
    MODE_NORMAL,
    SUPPORT_MODES,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]

    def get_entities(username: str, password: str) -> List[frigidaire.Appliance]:
        return client.get_appliances()

    appliances = await hass.async_add_executor_job(
        get_entities, entry.data["username"], entry.data["password"]
    )

    async_add_entities(
        [
            FrigidaireDehumidifier(client, appliance)
            for appliance in appliances
            if appliance.appliance_class == frigidaire.ApplianceClass.DEHUMIDIFIER
        ],
        update_before_add=True,
    )


FRIGIDAIRE_TO_HA_MODE = {
    frigidaire.Mode.DRY.value: MODE_NORMAL,
    frigidaire.Mode.CONTINUOUS.value: MODE_BOOST,
}

HA_TO_FRIGIDAIRE_MODE = {
    MODE_NORMAL: frigidaire.Mode.DRY,
    MODE_BOOST: frigidaire.Mode.CONTINUOUS,
}


class FrigidaireDehumidifier(HumidifierEntity):
    """Representation of a Frigidaire dehumidifier."""

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

        # Although we can access the Frigidaire API to get updates, they are
        # not reflected immediately after making a request. To improve the UX
        # around this, we set assume_state to True
        self._attr_assumed_state = True

        # self._attr_fan_modes = [
        #     FAN_LOW,
        #     FAN_HIGH,
        # ]

        self._attr_modes = [
            MODE_NORMAL,
            MODE_BOOST,
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
        return (
            self._details.for_code(frigidaire.HaclCode.APPLIANCE_STATE).number_value
            != 0
        )

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._attr_supported_features

    @property
    def available_modes(self):
        """List of available operation modes."""
        return self._attr_modes

    @property
    def target_humidity(self):
        """Return the humidity we try to reach."""
        return self._details.for_code(frigidaire.HaclCode.TARGET_HUMIDITY).number_value

    @property
    def mode(self):
        """Return current operation ie. dry, continuous."""
        frigidaire_mode = self._details.for_code(
            frigidaire.HaclCode.AC_MODE
        ).number_value

        return FRIGIDAIRE_TO_HA_MODE[frigidaire_mode]

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return self._details.for_code(frigidaire.HaclCode.AMBIENT_HUMIDITY).number_value

    # @property
    # def fan_mode(self):
    #     """Return the fan setting."""
    #     convert = {
    #         frigidaire.FanSpeed.OFF.value: FAN_OFF,  # when the AC is off
    #         frigidaire.FanSpeed.LOW.value: FAN_LOW,
    #         frigidaire.FanSpeed.HIGH.value: FAN_HIGH,
    #     }
    #     fan_speed = self._details.for_code(frigidaire.HaclCode.AC_FAN_SPEED_SETTING)
    #
    #     if not fan_speed:
    #         return FAN_OFF
    #
    #     return convert[fan_speed.number_value]

    @property
    def min_humidity(self):
        """Return the minimum humidity."""
        return 35

    @property
    def max_humidity(self):
        """Return the maximum humidity."""
        return 85

    def turn_on(self, **kwargs: Any) -> None:
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_power(frigidaire.Power.ON)
        )

    def turn_off(self, **kwargs: Any) -> None:
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_power(frigidaire.Power.OFF)
        )

    def set_humidity(self, humidity: int):
        """Set new target humidity."""
        if humidity is None:
            return
        # Only supports 5% steps
        humidity = 5 * round(humidity / 5)
        # We have to be in dry mode to set a target humidity
        self.set_mode(MODE_NORMAL)
        self._client.execute_action(
            self._appliance, frigidaire.Action.set_humidity(humidity)
        )

    # def set_fan_mode(self, fan_mode):
    #     """Set new target fan mode."""
    #     convert = {
    #         FAN_LOW: frigidaire.FanSpeed.LOW,
    #         FAN_HIGH: frigidaire.FanSpeed.HIGH,
    #     }
    #
    #     # Guard against unexpected fan modes
    #     if fan_mode not in convert:
    #         return
    #
    #     action = frigidaire.Action.set_fan_speed(convert[fan_mode])
    #     self._client.execute_action(self._appliance, action)

    def set_mode(self, mode):
        """Set new target operation mode."""

        # Guard against unexpected modes
        if mode not in HA_TO_FRIGIDAIRE_MODE:
            return

        # Turn on if not currently on.
        if self._details.for_code(frigidaire.HaclCode.APPLIANCE_STATE) == 0:
            self.turn_on()

        self._client.execute_action(
            self._appliance, frigidaire.Action.set_mode(HA_TO_FRIGIDAIRE_MODE[mode])
        )

    def update(self):
        """Retrieve latest state and updates the details."""
        try:
            details = self._client.get_appliance_details(self._appliance)
            self._details = details
            self._attr_available = True
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False

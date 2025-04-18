"""ClimateEntity for frigidaire integration."""
from __future__ import annotations

import logging
from typing import List, Any, Mapping, Optional, Dict

import frigidaire
import voluptuous as vol

from homeassistant.components.humidifier import HumidifierEntity, HumidifierDeviceClass
from homeassistant.components.humidifier.const import (
    MODE_BOOST,
    MODE_SLEEP,
    MODE_AUTO,
    MODE_NORMAL,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


FAN_LOW = "low"
FAN_MEDIUM = "medium"
FAN_HIGH = "high"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire from a config entry."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_fan_mode",
        {vol.Required("fan_mode"): cv.string},
        "set_fan_mode",
    )

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
            if appliance.destination == frigidaire.Destination.DEHUMIDIFIER
        ],
        update_before_add=True,
    )


FRIGIDAIRE_TO_HA_MODE = {
    frigidaire.Mode.DRY: MODE_NORMAL,
    frigidaire.Mode.CONTINUOUS: MODE_BOOST,
    frigidaire.Mode.QUIET: MODE_SLEEP,
    frigidaire.Mode.AUTO: MODE_AUTO,
}

HA_TO_FRIGIDAIRE_MODE = {v: k for k, v in FRIGIDAIRE_TO_HA_MODE.items()}

FRIGIDAIRE_TO_HA_FAN_MODE = {
    frigidaire.FanSpeed.LOW: FAN_LOW,
    frigidaire.FanSpeed.MEDIUM: FAN_MEDIUM,
    frigidaire.FanSpeed.HIGH: FAN_HIGH,
}

HA_TO_FRIGIDAIRE_FAN_MODE = {v: k for k, v in FRIGIDAIRE_TO_HA_FAN_MODE.items()}


class FrigidaireDehumidifier(HumidifierEntity):
    """Representation of a Frigidaire dehumidifier."""

    def __init__(self, client, appliance):
        """Build FrigidaireClimate.

        client: the client used to contact the frigidaire API
        appliance: the basic information about the frigidaire appliance, used to contact
            the API
        """

        self._client: frigidaire.Frigidaire = client
        self._appliance: frigidaire.Appliance = appliance
        self._details: Optional[Dict] = None

        # Entity Class Attributes
        self._attr_unique_id = self._appliance.appliance_id
        self._attr_name = self._appliance.nickname
        self._attr_supported_features = HumidifierEntityFeature.MODES

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
            MODE_AUTO,
            MODE_SLEEP,
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
        return HumidifierDeviceClass.DEHUMIDIFIER

    @property
    def is_on(self):
        return self._details.get(frigidaire.Detail.APPLIANCE_STATE) == frigidaire.ApplianceState.RUNNING

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
        return self._details.get(frigidaire.Detail.TARGET_HUMIDITY)

    @property
    def mode(self):
        """Return current operation i.e. dry, continuous."""
        frigidaire_mode = self._details.get(frigidaire.Detail.MODE)

        if frigidaire_mode == frigidaire.Mode.OFF:
            return MODE_NORMAL

        return FRIGIDAIRE_TO_HA_MODE[frigidaire_mode]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Add extra state attributes specific to Frigidaire dehumidifiers"""
        fan_speed = self._details.get(frigidaire.Detail.FAN_SPEED)

        attrib = {
            "current_humidity": self._details.get(frigidaire.Detail.SENSOR_HUMIDITY),
            "check_filter": bool(
                self._details.get(frigidaire.Detail.FILTER_STATE) != frigidaire.FilterState.GOOD
            ),
            "fan_mode": FRIGIDAIRE_TO_HA_FAN_MODE[fan_speed],
        }

        # The following attributes only exist on some models of dehumidifier
        bin_full = False
        alerts = self._details.get(frigidaire.Detail.ALERTS)
        if alerts is not None:
            # 1) Old approach
            if frigidaire.Alert.BUCKET_FULL in alerts:
                bin_full = True

            # 2) New approach
            if any(alert.get("code") == "BUCKET_FULL" for alert in alerts):
                bin_full = True

        # Fallback to waterBucketLevel if alert is not set
        if not bin_full:
            water_bucket_level = self._details.get(frigidaire.Detail.WATER_BUCKET_LEVEL)
            if water_bucket_level == 1:
                bin_full = True

        attrib["bin_full"] = bin_full

        return attrib

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

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        # Guard against unexpected fan modes
        if fan_mode not in HA_TO_FRIGIDAIRE_FAN_MODE:
            return

        action = frigidaire.Action.set_fan_speed(HA_TO_FRIGIDAIRE_FAN_MODE[fan_mode])
        self._client.execute_action(self._appliance, action)

    def set_mode(self, mode):
        """Set new target operation mode."""

        # Guard against unexpected modes
        if mode not in HA_TO_FRIGIDAIRE_MODE:
            return

        # Turn on if not currently on.
        if self._details.get(frigidaire.Detail.APPLIANCE_STATE) == frigidaire.ApplianceState.OFF:
            self.turn_on()

        self._client.execute_action(
            self._appliance, frigidaire.Action.set_mode(HA_TO_FRIGIDAIRE_MODE[mode])
        )

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
            self._attr_available = (
                self._details.get("connectivityState") == "connected"
            )

"""HumidifierEntity for frigidaire dehumidifiers."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components.humidifier import HumidifierAction, HumidifierDeviceClass, HumidifierEntity
from homeassistant.components.humidifier.const import (
    MODE_AUTO,
    MODE_BOOST,
    MODE_NORMAL,
    MODE_SLEEP,
    HumidifierEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import ApplianceState, Destination, Detail, FanSpeed, Mode

from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity, async_add_appliance_entities

_LOGGER = logging.getLogger(__name__)

FAN_LOW = "low"
FAN_MEDIUM = "medium"
FAN_HIGH = "high"


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up frigidaire from a config entry."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("set_fan_mode", {vol.Required("fan_mode"): cv.string}, "set_fan_mode")

    async_add_appliance_entities(
        entry.runtime_data,
        async_add_entities,
        lambda appliance: (
            [FrigidaireDehumidifier(entry.runtime_data, appliance)]
            if appliance.destination is Destination.DEHUMIDIFIER
            else []
        ),
    )


FRIGIDAIRE_TO_HA_MODE = {
    Mode.DRY: MODE_NORMAL,
    Mode.CONTINUOUS: MODE_BOOST,
    Mode.QUIET: MODE_SLEEP,
    Mode.AUTO: MODE_AUTO,
    Mode.SMART: MODE_AUTO,
}

HA_TO_FRIGIDAIRE_MODE = {
    MODE_NORMAL: Mode.DRY,
    MODE_BOOST: Mode.CONTINUOUS,
    MODE_SLEEP: Mode.QUIET,
    MODE_AUTO: Mode.AUTO,
}

FRIGIDAIRE_TO_HA_FAN_MODE = {
    FanSpeed.LOW: FAN_LOW,
    FanSpeed.MEDIUM: FAN_MEDIUM,
    FanSpeed.HIGH: FAN_HIGH,
}
HA_TO_FRIGIDAIRE_FAN_MODE = {v: k for k, v in FRIGIDAIRE_TO_HA_FAN_MODE.items()}


class FrigidaireDehumidifier(FrigidaireEntity, HumidifierEntity):
    """A Frigidaire dehumidifier."""

    _attr_available_modes = [MODE_NORMAL, MODE_BOOST, MODE_AUTO, MODE_SLEEP]
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_max_humidity = 85
    _attr_min_humidity = 35
    _attr_supported_features = HumidifierEntityFeature.MODES

    def __init__(self, coordinator: FrigidaireCoordinator, appliance) -> None:
        super().__init__(coordinator, appliance, unique_id=appliance.appliance_id, name=appliance.nickname)

    @property
    def available(self) -> bool:
        # Some models omit applianceState, so a reported mode is enough.
        appliance = self.appliance
        return super().available and (appliance.state is not None or appliance.mode is not None)

    @property
    def is_on(self) -> bool:
        return self.appliance.state is ApplianceState.RUNNING

    @property
    def action(self) -> HumidifierAction | None:
        """What the unit is doing, on models that report the compressor; None elsewhere."""
        compressor = self.appliance.compressor_running
        if compressor is None:
            return None
        if not self.is_on:
            return HumidifierAction.OFF
        return HumidifierAction.DRYING if compressor else HumidifierAction.IDLE

    @property
    def target_humidity(self) -> float | None:
        return self.appliance.target_humidity

    @property
    def current_humidity(self) -> float | None:
        return self.appliance.humidity

    @property
    def mode(self) -> str | None:
        appliance = self.appliance
        if appliance.mode is Mode.OFF:
            return MODE_NORMAL
        mode = FRIGIDAIRE_TO_HA_MODE.get(appliance.mode)
        if mode is None and appliance.get(Detail.MODE) is not None:
            _LOGGER.warning("Unsupported dehumidifier mode '%s' reported by device.", appliance.get(Detail.MODE))
        return mode

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        appliance = self.appliance
        attributes: dict[str, Any] = {
            "check_filter": appliance.filter_needs_attention or False,
            "fan_mode": FRIGIDAIRE_TO_HA_FAN_MODE.get(appliance.fan_speed),
            # Unreported stays False to preserve the attribute's historical always-bool shape.
            "bin_full": appliance.bucket_full or False,
        }
        if appliance.alerts is not None:
            attributes["active_alerts"] = appliance.alerts
        return attributes

    def turn_on(self, **kwargs: Any) -> None:
        self.client.set_power(self.appliance, True)
        self.refresh()

    def turn_off(self, **kwargs: Any) -> None:
        self.client.set_power(self.appliance, False)
        self.refresh()

    def set_humidity(self, humidity: int) -> None:
        self.client.set_humidity(self.appliance, humidity)
        self.refresh()

    def set_fan_mode(self, fan_mode: str) -> None:
        if (fan_speed := HA_TO_FRIGIDAIRE_FAN_MODE.get(fan_mode)) is None:
            return
        self.client.set_fan_speed(self.appliance, fan_speed)
        self.refresh()

    def set_mode(self, mode: str) -> None:
        if (frigidaire_mode := HA_TO_FRIGIDAIRE_MODE.get(mode)) is None:
            return
        self.client.set_mode(self.appliance, frigidaire_mode)
        self.refresh()

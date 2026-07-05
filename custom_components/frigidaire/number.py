"""Number entities for Frigidaire AC timers (ON/OFF)."""

from __future__ import annotations

import logging
import time

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .const import DOMAIN
from .helpers import suggest_area

_LOGGER = logging.getLogger(__name__)


def _normalize(value):
    if isinstance(value, str):
        return value.upper()
    return value


STEP_SECONDS = 1800  # 30 minutes
MAX_SECONDS = 86400  # 24 hours
OPTIMISTIC_WINDOW = 5  # seconds to hold optimistic state after a command


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Frigidaire timer number entities."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]

    entities = [
        FrigidaireTimerNumber(client, appliance, timer_type, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
        for timer_type in ("on", "off")
    ]

    async_add_entities(entities, update_before_add=True)


class FrigidaireTimerNumber(NumberEntity):
    """AC ON or OFF timer, expressed in seconds with 30-minute steps."""

    def __init__(
        self,
        client: frigidaire.Frigidaire,
        appliance: frigidaire.Appliance,
        timer_type: str,
        suggested_area: str | None = None,
    ) -> None:
        self._client = client
        self._appliance = appliance
        self._timer_type = timer_type  # "on" or "off"
        self._details: dict = {}
        self._optimistic_until: float = 0
        self._optimistic_value: float | None = None

        suffix = "On Timer" if timer_type == "on" else "Off Timer"
        self._attr_unique_id = f"{appliance.appliance_id}_timer_{timer_type}"
        self._attr_name = suffix
        self._attr_native_min_value = 0
        self._attr_native_max_value = MAX_SECONDS
        self._attr_native_step = STEP_SECONDS
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = NumberDeviceClass.DURATION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def native_value(self) -> float:
        if time.monotonic() < self._optimistic_until:
            return self._optimistic_value or 0
        appliance_state = _normalize(self._details.get(frigidaire.Detail.APPLIANCE_STATE))
        if self._timer_type == "on":
            active = appliance_state in (frigidaire.ApplianceState.OFF, frigidaire.ApplianceState.DELAYED_START)
            detail_key = frigidaire.Detail.START_TIME
        else:
            active = appliance_state == frigidaire.ApplianceState.RUNNING
            detail_key = frigidaire.Detail.STOP_TIME
        if not active:
            return 0
        raw = self._details.get(detail_key) or 0
        return max(0, round(raw / STEP_SECONDS) * STEP_SECONDS)

    def set_native_value(self, value: float) -> None:
        seconds = int(round(value / STEP_SECONDS) * STEP_SECONDS)
        seconds = max(0, min(MAX_SECONDS, seconds))
        action = (
            frigidaire.Action.set_start_time(seconds)
            if self._timer_type == "on"
            else frigidaire.Action.set_stop_time(seconds)
        )
        self._client.execute_action(self._appliance, action)
        self._optimistic_value = float(seconds)
        self._optimistic_until = time.monotonic() + OPTIMISTIC_WINDOW

    def update(self) -> None:
        try:
            self._details = self._client.get_appliance_details(self._appliance)
            self._attr_available = True
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False
        else:
            if time.monotonic() >= self._optimistic_until:
                self._optimistic_value = None

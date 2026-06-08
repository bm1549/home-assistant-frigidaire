"""Number entities for Frigidaire timers (ON/OFF)."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Optional, Dict, List

import frigidaire

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


STEP_SECONDS = 1800  # 30 minutes
MAX_SECONDS = 86400  # 24 hours
OPTIMISTIC_WINDOW = 5  # seconds to hold optimistic state after setting


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frigidaire timer number entities."""
    client = hass.data[DOMAIN][entry.entry_id]

    appliances = await hass.async_add_executor_job(
        client.get_appliances
    )

    entities: List[NumberEntity] = []

    for appliance in appliances:
        if appliance.destination != frigidaire.Destination.AIR_CONDITIONER:
            continue

        entities.append(FrigidaireTimerNumber(client, appliance, "off"))
        entities.append(FrigidaireTimerNumber(client, appliance, "on"))

    async_add_entities(entities, update_before_add=False)


class FrigidaireTimerNumber(NumberEntity):
    """Representation of AC timer (ON/OFF) in minutes."""

    def __init__(self, client, appliance, timer_type: str):
        self._client: frigidaire.Frigidaire = client
        self._appliance: frigidaire.Appliance = appliance
        self._details: Optional[Dict] = None

        self._timer_type = timer_type  # "on" or "off"

        self._optimistic_until: Optional[datetime] = None

        suffix = "On Timer" if timer_type == "on" else "Off Timer"

        # Entity attributes
        self._attr_unique_id = f"{appliance.appliance_id}_timer_{timer_type}"
        self._attr_name = f"{appliance.nickname} {suffix}"
        self._attr_native_value = 0
        self._attr_native_min_value = 0
        self._attr_native_max_value = MAX_SECONDS
        self._attr_native_step = STEP_SECONDS
        self._attr_native_unit_of_measurement = "s"
        self._attr_device_class = "duration"
        self._attr_available = True
        self._attr_assumed_state = True

    @property
    def assumed_state(self):
        """Return True if unable to access real state of the entity."""
        return self._attr_assumed_state

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
    def extra_state_attributes(self) -> dict:
        detail_key, attr_key = (
            (frigidaire.Detail.STOP_TIME, "ac_off_timer")
            if self._timer_type == "off"
            else (frigidaire.Detail.START_TIME, "ac_on_timer")
        )
        seconds = (self._details or {}).get(detail_key) or 0
        return {attr_key: seconds}

    async def async_set_native_value(self, value: float) -> None:
        """Set timer in minutes (rounded to nearest 30)."""
        try:
            seconds = int(round(value / STEP_SECONDS) * STEP_SECONDS)
            seconds = max(0, min(MAX_SECONDS, seconds))

            _LOGGER.debug("Setting %s timer for %s: requested=%s normalized=%s",
                self._timer_type,
                self._appliance.appliance_id,
                value,
                seconds,
            )

            if self._attr_native_value == seconds:
                _LOGGER.debug("Timer unchanged, skipping API call")
                return

            action = (
                frigidaire.Action.set_stop_time(seconds)
                if self._timer_type == "off"
                else frigidaire.Action.set_start_time(seconds)
            )

            await self.hass.async_add_executor_job(
                self._client.execute_action, self._appliance, action
            )

            self._attr_native_value = seconds
            self._optimistic_until = datetime.now() + timedelta(seconds=OPTIMISTIC_WINDOW)
            self.async_write_ha_state()

        except frigidaire.FrigidaireException:
            _LOGGER.error("Failed to set %s timer for %s",
                self._timer_type,
                self._appliance.appliance_id,
            )

    def update(self):
        """Retrieve latest state and update timer value."""
        try:
            details = self._client.get_appliance_details(self._appliance)
            _LOGGER.debug("Retrieved details for appliance %s: %s", self._appliance.appliance_id, details)
            self._details = details or {}
            appliance_state = self._details.get(frigidaire.Detail.APPLIANCE_STATE)
            if self._timer_type == "off":
                active = appliance_state == frigidaire.ApplianceState.RUNNING
                detail_key = frigidaire.Detail.STOP_TIME
            else:
                active = appliance_state in (
                    frigidaire.ApplianceState.OFF,
                    frigidaire.ApplianceState.DELAYED_START,
                )
                detail_key = frigidaire.Detail.START_TIME

            self._attr_available = appliance_state is not None

            if self._optimistic_until and datetime.now() < self._optimistic_until:
                _LOGGER.debug(
                    "Holding optimistic value for %s timer, %s seconds remaining",
                    self._timer_type,
                    (self._optimistic_until - datetime.now()).seconds,
                )
                return

            self._optimistic_until = None
            self._attr_native_value = self._details.get(detail_key) if active else 0

        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to update %s timer for %s",
                    self._timer_type,
                    self._appliance.appliance_id,
                )
            self._attr_available = False

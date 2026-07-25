"""DataUpdateCoordinator for the frigidaire integration."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

import frigidaire

from .compressor import CompressorEstimator
from .const import (
    CONF_COMPRESSOR_OFF_DELAY,
    CONF_COOL_HYSTERESIS,
    DEFAULT_COMPRESSOR_OFF_DELAY,
    DEFAULT_COOL_HYSTERESIS,
)

_LOGGER = logging.getLogger(__name__)

# A single shared poll per appliance replaces the old per-entity polling: a
# device that exposes several entities (climate/switch/number/binary_sensor/…)
# now hits the API once per cycle instead of once per entity. On failure we back
# off exponentially up to MAX_INTERVAL so that when Frigidaire's auth servers are
# flaky (upstream Gigya/token outages) we stop hammering them — repeated re-auth
# is what trips Frigidaire's active-session cap (cas_3403).
BASE_INTERVAL = timedelta(seconds=30)
MAX_INTERVAL = timedelta(minutes=10)
FAN_SPEED_STATE_KEY = "fanSpeedState"


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.upper()
    return value


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class FrigidaireApplianceCoordinator(DataUpdateCoordinator[dict]):
    """Polls a single Frigidaire appliance and shares its details with every entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: frigidaire.Frigidaire,
        appliance: frigidaire.Appliance,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"frigidaire {appliance.nickname}",
            update_interval=BASE_INTERVAL,
        )
        self.client = client
        self.appliance = appliance
        self._failure_count = 0
        options = options or {}
        self._compressor_estimator = (
            CompressorEstimator(
                hysteresis=_coerce_float(options.get(CONF_COOL_HYSTERESIS), DEFAULT_COOL_HYSTERESIS),
                off_delay=_coerce_float(options.get(CONF_COMPRESSOR_OFF_DELAY), DEFAULT_COMPRESSOR_OFF_DELAY),
            )
            if appliance.destination == frigidaire.Destination.AIR_CONDITIONER
            else None
        )
        self._compressor_running: bool | None = None

    @property
    def compressor_running(self) -> bool | None:
        """Return the shared temperature-based compressor estimate."""
        return self._compressor_running

    @property
    def reported_fan_speed(self) -> str | None:
        """Return the reported fan-speed state without implying motion."""
        raw = (self.data or {}).get(FAN_SPEED_STATE_KEY)
        if raw is None:
            return None
        return {
            frigidaire.FanSpeed.AUTO: "auto",
            frigidaire.FanSpeed.LOW: "low",
            frigidaire.FanSpeed.MEDIUM: "medium",
            frigidaire.FanSpeed.HIGH: "high",
        }.get(_normalize(raw), str(raw).lower())

    def _update_compressor_estimate(self, details: dict) -> None:
        """Update the shared estimate from one coordinator response."""
        if self._compressor_estimator is None:
            return

        mode = _normalize(details.get(frigidaire.Detail.MODE))
        appliance_state = _normalize(details.get(frigidaire.Detail.APPLIANCE_STATE))
        if mode == frigidaire.Mode.OFF or (
            appliance_state is not None and appliance_state != frigidaire.ApplianceState.RUNNING
        ):
            self._compressor_running = self._compressor_estimator.force_off()
            return
        if mode == frigidaire.Mode.FAN:
            self._compressor_running = self._compressor_estimator.force_off()
            return
        if mode not in (frigidaire.Mode.COOL, frigidaire.Mode.ECO, frigidaire.Mode.AUTO, frigidaire.Mode.DRY):
            self._compressor_running = None
            return

        unit = _normalize(details.get(frigidaire.Detail.TEMPERATURE_REPRESENTATION))
        if unit == frigidaire.Unit.FAHRENHEIT:
            current = details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_F)
            target = details.get(frigidaire.Detail.TARGET_TEMPERATURE_F)
        elif unit == frigidaire.Unit.CELSIUS:
            current = details.get(frigidaire.Detail.AMBIENT_TEMPERATURE_C)
            target = details.get(frigidaire.Detail.TARGET_TEMPERATURE_C)
        else:
            self._compressor_running = self._compressor_estimator.running
            return

        self._compressor_running = self._compressor_estimator.update(current, target, now=time.monotonic())

    async def _async_update_data(self) -> dict:
        """Fetch the latest appliance details, backing off on repeated failures."""
        try:
            details = await self.hass.async_add_executor_job(self.client.get_appliance_details, self.appliance)
        except (frigidaire.FrigidaireException, ConnectionError) as err:
            self._failure_count += 1
            # 30s, 60s, 120s, 240s … capped at MAX_INTERVAL.
            backoff = BASE_INTERVAL * (2 ** (self._failure_count - 1))
            self.update_interval = min(backoff, MAX_INTERVAL)
            raise UpdateFailed(f"Error communicating with Frigidaire: {err}") from err

        # Recovered — resume the normal polling cadence.
        if self._failure_count:
            self._failure_count = 0
            self.update_interval = BASE_INTERVAL
        self._update_compressor_estimate(details)
        return details

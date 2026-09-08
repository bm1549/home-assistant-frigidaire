"""One account-level poll feeds every entity."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from frigidaire import (
    Appliance,
    ApplianceState,
    AuthenticationError,
    Destination,
    Frigidaire,
    FrigidaireException,
    Mode,
    SessionCapError,
)

from .compressor import CompressorEstimator
from .const import (
    CONF_COMPRESSOR_ESTIMATE,
    CONF_COMPRESSOR_OFF_DELAY,
    CONF_COOL_HYSTERESIS,
    DEFAULT_COMPRESSOR_OFF_DELAY,
    DEFAULT_COOL_HYSTERESIS,
)

_LOGGER = logging.getLogger(__name__)

# The whole account is fetched once per cycle. On failure the next poll backs off
# exponentially up to MAX_BACKOFF so that when Frigidaire's auth servers are flaky we
# stop hammering them: repeated re-authentication is what trips the session cap.
BASE_INTERVAL = timedelta(seconds=30)
MAX_BACKOFF = timedelta(minutes=10)

type FrigidaireConfigEntry = ConfigEntry[FrigidaireCoordinator]


def describe_error(err: FrigidaireException) -> str:
    """A log line that says what the API returned. The library redacts response bodies from
    exception messages, so without the structured fields a session cap looks like any failure."""
    parts = []
    if err.status_code is not None:
        parts.append(f"status={err.status_code}")
    if err.error_code:
        parts.append(f"error={err.error_code}")
    context = f" ({', '.join(parts)})" if parts else ""
    if isinstance(err, SessionCapError):
        return f"Rate limited by Frigidaire{context}; will retry automatically"
    return f"Error communicating with Frigidaire{context}: {err}"


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)


class FrigidaireCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Polls the account and holds the latest snapshot of every appliance, keyed by id."""

    def __init__(self, hass: HomeAssistant, entry: FrigidaireConfigEntry, client: Frigidaire) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="frigidaire", update_interval=BASE_INTERVAL)
        self.client = client
        self._failures = 0
        # Opt-in per air conditioner: the API exposes no compressor telemetry, so this
        # estimates it from the temperatures. Kept here so the climate entity and the
        # diagnostic sensor share one estimate.
        self._estimators: dict[str, CompressorEstimator] = {}
        self._compressor_running: dict[str, bool | None] = {}
        for appliance_id, options in entry.options.items():
            if options.get(CONF_COMPRESSOR_ESTIMATE, False):
                self._estimators[appliance_id] = CompressorEstimator(
                    hysteresis=_coerce_float(options.get(CONF_COOL_HYSTERESIS), DEFAULT_COOL_HYSTERESIS),
                    off_delay=_coerce_float(options.get(CONF_COMPRESSOR_OFF_DELAY), DEFAULT_COMPRESSOR_OFF_DELAY),
                )

    async def _async_update_data(self) -> dict[str, Appliance]:
        try:
            appliances = await self.hass.async_add_executor_job(self.client.get_appliances)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FrigidaireException as err:
            self._failures += 1
            backoff = min(BASE_INTERVAL * 2 ** min(self._failures, 20), MAX_BACKOFF)
            raise UpdateFailed(describe_error(err), retry_after=backoff.total_seconds()) from err
        self._failures = 0

        data = {appliance.appliance_id: appliance for appliance in appliances}
        for appliance_id in set(self.data or {}) - set(data):
            previous = self.data[appliance_id]
            _LOGGER.warning("%s (%s) is no longer on the account", previous.nickname, appliance_id)
        for appliance in appliances:
            self._update_compressor_estimate(appliance)
        return data

    def compressor_estimate(self, appliance_id: str) -> bool | None:
        """The opt-in estimate, or None when it is disabled or undecidable for this appliance."""
        return self._compressor_running.get(appliance_id)

    def _update_compressor_estimate(self, appliance: Appliance) -> None:
        estimator = self._estimators.get(appliance.appliance_id)
        if estimator is None or appliance.destination is not Destination.AIR_CONDITIONER:
            return
        mode = appliance.mode
        state = appliance.state
        if mode is Mode.OFF or mode is Mode.FAN or (state is not None and state is not ApplianceState.RUNNING):
            running: bool | None = estimator.force_off()
        elif mode not in (Mode.COOL, Mode.ECO, Mode.AUTO, Mode.DRY) or appliance.temperature_unit is None:
            running = None
        else:
            running = estimator.update(
                appliance.ambient_temperature, appliance.target_temperature, now=time.monotonic()
            )
        self._compressor_running[appliance.appliance_id] = running

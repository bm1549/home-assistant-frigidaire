"""One account-level fetch feeds every entity; a command refreshes just its appliance.

The fetch runs every ``RESYNC_INTERVAL`` of the entry's sign-in method: 30 seconds for email
and password.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from types import ModuleType

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from frigidaire import (
    Appliance,
    ApplianceState,
    AsyncFrigidaire,
    AuthenticationError,
    Destination,
    FrigidaireException,
    Mode,
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

# The whole account is fetched once per cycle, every RESYNC_INTERVAL of the entry's sign-in
# method. On failure the next fetch backs off exponentially from that interval up to
# MAX_BACKOFF so that when Frigidaire's auth servers are flaky we stop hammering them:
# repeated re-authentication is what trips the password method's session cap.
MAX_BACKOFF = timedelta(minutes=10)

type FrigidaireConfigEntry = ConfigEntry[FrigidaireCoordinator]


def describe_error(err: FrigidaireException, rate_limit_errors: tuple[type[FrigidaireException], ...] = ()) -> str:
    """A log line that says what the API returned. The library redacts response bodies from
    exception messages, so without the structured fields a session cap looks like any failure.

    ``rate_limit_errors`` is the sign-in method's ``RATE_LIMIT_ERRORS``: its own errors that mean
    "wait and retry"."""
    parts = []
    if err.status_code is not None:
        parts.append(f"status={err.status_code}")
    if err.error_code:
        parts.append(f"error={err.error_code}")
    context = f" ({', '.join(parts)})" if parts else ""
    if isinstance(err, rate_limit_errors):
        return f"Rate limited by Frigidaire{context}; will retry automatically"
    return f"Error communicating with Frigidaire{context}: {err}"


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)


class FrigidaireCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Fetches the account and holds the latest snapshot of every appliance, keyed by id."""

    def __init__(
        self, hass: HomeAssistant, entry: FrigidaireConfigEntry, client: AsyncFrigidaire, method: ModuleType
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="frigidaire", update_interval=method.RESYNC_INTERVAL)
        self.client = client
        self._interval: timedelta = method.RESYNC_INTERVAL
        self._rate_limit_errors: tuple[type[FrigidaireException], ...] = method.RATE_LIMIT_ERRORS
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

    def describe_error(self, err: FrigidaireException) -> str:
        return describe_error(err, self._rate_limit_errors)

    async def _async_update_data(self) -> dict[str, Appliance]:
        try:
            appliances = await self.client.get_appliances()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FrigidaireException as err:
            self._failures += 1
            raise UpdateFailed(self.describe_error(err), retry_after=self._backoff().total_seconds()) from err
        self._failures = 0

        data = {appliance.appliance_id: self._ingest(appliance) for appliance in appliances}
        for appliance_id in set(self.data or {}) - set(data):
            previous = self.data[appliance_id]
            _LOGGER.warning("%s (%s) is no longer on the account", previous.nickname, appliance_id)
        return data

    def _backoff(self) -> timedelta:
        return min(self._interval * 2 ** min(self._failures, 20), max(MAX_BACKOFF, self._interval))

    async def async_refresh_appliance(self, appliance: Appliance) -> None:
        """Fetch one appliance's state, after a command, and publish it to every entity.

        A failure is logged and left to the next scheduled fetch, which handles it as usual;
        rejected credentials start reauth straight away.
        """
        try:
            fresh = await self.client.refresh(appliance)
        except AuthenticationError:
            self._start_reauth()
            return
        except FrigidaireException as err:
            _LOGGER.warning("Refreshing %s after a command failed: %s", appliance.nickname, self.describe_error(err))
            return
        self._publish(fresh)

    @callback
    def _publish(self, appliance: Appliance) -> None:
        self.async_set_updated_data({**(self.data or {}), appliance.appliance_id: self._ingest(appliance)})

    @callback
    def _start_reauth(self) -> None:
        assert self.config_entry is not None
        self.config_entry.async_start_reauth(self.hass)

    def _ingest(self, appliance: Appliance) -> Appliance:
        """Every fresh snapshot passes through here before entities see it."""
        self._update_compressor_estimate(appliance)
        return appliance

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

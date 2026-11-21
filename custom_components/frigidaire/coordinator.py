"""One account-level fetch feeds every entity; a command refreshes just its appliance.

Password entries poll every 30 seconds. API key entries resync every 5 minutes and get live
updates from the event stream in between; each interval is the sign-in method's own
``RESYNC_INTERVAL``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from types import ModuleType

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from frigidaire import (
    Appliance,
    ApplianceState,
    AuthenticationError,
    Destination,
    Frigidaire,
    FrigidaireException,
    Mode,
    QuotaExceededError,
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

# The live update stream, for backends that have one, runs as an entry background task. The
# library reconnects it after most failures itself; if it gives up, it is restarted after
# STREAM_RETRY, doubling up to MAX_BACKOFF.
STREAM_TASK_NAME = "frigidaire live updates"
STREAM_RETRY = timedelta(seconds=60)

type FrigidaireConfigEntry = ConfigEntry[FrigidaireCoordinator]


def describe_error(err: FrigidaireException, rate_limit_errors: tuple[type[FrigidaireException], ...] = ()) -> str:
    """A log line that says what the API returned. The library redacts response bodies from
    exception messages, so without the structured fields a session cap looks like any failure.

    ``rate_limit_errors`` is the sign-in method's ``RATE_LIMIT_ERRORS``: its own errors that, like
    the shared ``QuotaExceededError``, mean "wait and retry"."""
    parts = []
    if err.status_code is not None:
        parts.append(f"status={err.status_code}")
    if err.error_code:
        parts.append(f"error={err.error_code}")
    context = f" ({', '.join(parts)})" if parts else ""
    if isinstance(err, (QuotaExceededError, *rate_limit_errors)):
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
        self, hass: HomeAssistant, entry: FrigidaireConfigEntry, client: Frigidaire, method: ModuleType
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="frigidaire", update_interval=method.RESYNC_INTERVAL)
        self.client = client
        self._interval: timedelta = method.RESYNC_INTERVAL
        self._rate_limit_errors: tuple[type[FrigidaireException], ...] = method.RATE_LIMIT_ERRORS
        self._failures = 0
        self._quota_hold = False  # a quota error is being waited out
        # The live update stream, when the backend has one.
        self.stream_connected = False
        self._stream_has_connected = False
        self._stream_failures = 0
        self._cancel_stream_retry: CALLBACK_TYPE | None = None
        # Set while a reconnect resync has run within the last resync interval.
        self._cancel_reconnect_resync_hold: CALLBACK_TYPE | None = None
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
        # A quota backoff stretches the interval (see below) until the next fetch is tried.
        self.update_interval = self._interval
        self._quota_hold = False
        try:
            appliances = await self.client.get_appliances()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except QuotaExceededError as err:
            self._failures += 1
            # The server's hint, but never sooner than a normal fetch; without one, the usual backoff.
            if err.retry_after is None:
                wait = self._backoff().total_seconds()
            else:
                wait = max(err.retry_after, self._interval.total_seconds())
            # Pushes and command refreshes reschedule the next fetch at update_interval, which
            # would cut the wait short; hold it at the server's hint until a fetch is tried again.
            self.update_interval = timedelta(seconds=wait)
            self._quota_hold = True
            raise UpdateFailed(self.describe_error(err), retry_after=wait) from err
        except FrigidaireException as err:
            self._failures += 1
            raise UpdateFailed(self.describe_error(err), retry_after=self._backoff().total_seconds()) from err
        self._failures = 0

        data = {appliance.appliance_id: self._ingest(appliance) for appliance in appliances}
        for appliance_id in set(self.data or {}) - set(data):
            previous = self.data[appliance_id]
            # Not "no longer on the account": a backend may skip an appliance it could not read
            # this time, and it comes back on a later fetch.
            _LOGGER.warning(
                "%s (%s) was not in the latest fetch; its entities are unavailable until it is back",
                previous.nickname,
                appliance_id,
            )
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

    # --- live updates ---

    @callback
    def async_start_live_updates(self) -> None:
        """Run the backend's live update stream for the life of the entry. Call once, after setup."""
        assert self.config_entry is not None
        self.config_entry.async_on_unload(self._async_cancel_stream_retry)
        self.config_entry.async_on_unload(self._async_end_reconnect_resync_hold)
        self._async_start_stream()

    @callback
    def _async_start_stream(self, _now: datetime | None = None) -> None:
        assert self.config_entry is not None
        self._cancel_stream_retry = None
        self.config_entry.async_create_background_task(self.hass, self._async_run_stream(), name=STREAM_TASK_NAME)

    @callback
    def _async_cancel_stream_retry(self) -> None:
        if self._cancel_stream_retry is not None:
            self._cancel_stream_retry()
            self._cancel_stream_retry = None

    async def _async_run_stream(self) -> None:
        try:
            await self.client.listen(self._publish, self._handle_stream_connect, self._handle_stream_disconnect)
        except AuthenticationError:
            _LOGGER.warning("Live updates stopped: the credentials were rejected")
            self._start_reauth()
            return
        except FrigidaireException as err:
            reason = self.describe_error(err)
        else:
            reason = "the stream ended"
        self._stream_failures += 1
        delay = min(STREAM_RETRY * 2 ** min(self._stream_failures - 1, 20), MAX_BACKOFF)
        _LOGGER.warning("Live updates stopped (%s); retrying in %s", reason, delay)
        self._cancel_stream_retry = async_call_later(self.hass, delay, self._async_start_stream)

    @callback
    def _handle_stream_connect(self) -> None:
        self.stream_connected = True
        self._stream_failures = 0
        if self._stream_has_connected and not self._quota_hold and self._cancel_reconnect_resync_hold is None:
            # Whatever changed while the stream was down was never pushed; one full fetch catches up.
            # While a quota error is waited out, the fetch that ends the wait does that instead. At
            # most one per resync interval, so a flapping stream cannot spend the daily quota; the
            # scheduled resync catches up after any reconnect skipped here.
            assert self.config_entry is not None
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), name="frigidaire resync after reconnect"
            )
            self._cancel_reconnect_resync_hold = async_call_later(
                self.hass, self._interval, self._async_end_reconnect_resync_hold
            )
        self._stream_has_connected = True

    @callback
    def _async_end_reconnect_resync_hold(self, _now: datetime | None = None) -> None:
        if self._cancel_reconnect_resync_hold is not None:
            self._cancel_reconnect_resync_hold()
            self._cancel_reconnect_resync_hold = None

    @callback
    def _handle_stream_disconnect(self) -> None:
        self.stream_connected = False

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

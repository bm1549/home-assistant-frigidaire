"""Tests for temperature-based compressor estimation."""

from compressor import estimate_compressor_running


def estimate(
    current,
    target,
    *,
    hysteresis=0,
    off_delay=180,
    previous=True,
    satisfied_since=None,
    now=100,
):
    return estimate_compressor_running(
        current,
        target,
        hysteresis=hysteresis,
        off_delay=off_delay,
        previous=previous,
        satisfied_since=satisfied_since,
        now=now,
    )


def test_above_target_reports_running_and_clears_timer():
    assert estimate(72, 70, previous=False, satisfied_since=50) == (True, None)


def test_satisfied_temperature_starts_off_delay():
    assert estimate(70, 70, now=100) == (True, 100)


def test_below_hysteresis_band_starts_off_delay():
    assert estimate(68, 70, hysteresis=1, now=100) == (True, 100)


def test_satisfied_temperature_stops_after_delay():
    assert estimate(70, 70, satisfied_since=100, now=279) == (True, 100)
    assert estimate(70, 70, satisfied_since=100, now=280) == (False, 100)


def test_deadband_holds_previous_estimate_and_clears_timer():
    assert estimate(70, 70, hysteresis=1, previous=False, satisfied_since=50) == (False, None)


def test_missing_temperature_holds_previous_estimate():
    assert estimate(None, 70, previous=False, satisfied_since=50) == (False, None)
    assert estimate(72, None, previous=False, satisfied_since=50) == (False, None)


def test_rising_temperature_restarts_compressor_immediately():
    assert estimate(72, 70, previous=False, satisfied_since=50) == (True, None)

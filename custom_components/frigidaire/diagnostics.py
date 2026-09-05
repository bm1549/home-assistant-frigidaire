"""Parsing helpers for Frigidaire appliance diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

AIR_FILTER_LIFETIME_KEY = "airFilterLifeTime"
GOOD_FILTER_STATE = "GOOD"


def normalize_alerts(value: Any) -> list[str] | None:
    """Return alert codes from either supported API response format."""
    if value is None:
        return None

    raw_alerts = value if isinstance(value, list | tuple | set | frozenset) else [value]
    alerts: list[str] = []
    for alert in raw_alerts:
        code = alert.get("code") if isinstance(alert, Mapping) else alert
        if code is not None:
            alerts.append(str(code).upper())
    return alerts


def normalize_filter_state(value: Any) -> str | None:
    """Return a normalized filter-state string."""
    if value is None:
        return None
    return str(value).upper()


def filter_needs_attention(value: Any) -> bool | None:
    """Return whether a reported filter state requires attention."""
    state = normalize_filter_state(value)
    return None if state is None else state != GOOD_FILTER_STATE


def bucket_is_full(
    alerts: list[str] | None,
    water_bucket_level: Any,
    water_tank_full: Any,
) -> bool | None:
    """Return whether the water bucket is full, or None when unreported.

    Different dehumidifier models report the bucket through different signals,
    so all three are checked: a BUCKET_FULL alert code, waterBucketLevel == 1,
    and waterTankFull. ``alerts`` must already be normalized (see
    ``normalize_alerts``). Returns None when the appliance reports none of the
    signals, letting callers distinguish "empty" from "not supported by this
    model".
    """
    if alerts is None and water_bucket_level is None and water_tank_full is None:
        return None
    if alerts is not None and "BUCKET_FULL" in alerts:
        return True
    if water_bucket_level == 1:
        return True
    tank = water_tank_full.upper() if isinstance(water_tank_full, str) else water_tank_full
    return tank in ("YES", True)


def filter_runtime_seconds(value: Any) -> float | None:
    """Return valid cumulative filter-runtime seconds."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds

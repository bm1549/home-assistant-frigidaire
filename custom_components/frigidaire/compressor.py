"""Temperature-based compressor state estimation."""

from __future__ import annotations


def estimate_compressor_running(
    current: float | None,
    target: float | None,
    *,
    hysteresis: float,
    off_delay: float,
    previous: bool,
    satisfied_since: float | None,
    now: float,
) -> tuple[bool, float | None]:
    """Return the next compressor estimate and satisfied-band timestamp."""
    if current is None or target is None:
        return previous, None

    if current > target + hysteresis:
        return True, None

    if current <= target - hysteresis:
        satisfied_since = now if satisfied_since is None else satisfied_since
        if now - satisfied_since >= off_delay:
            return False, satisfied_since
        return previous, satisfied_since

    return previous, None

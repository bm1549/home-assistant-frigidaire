"""Tests for Frigidaire diagnostic parsing."""

import math

import pytest
from diagnostics import (
    bucket_is_full,
    filter_needs_attention,
    filter_runtime_seconds,
    normalize_alerts,
    normalize_filter_state,
)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, None),
        ("good", False),
        ("CLEAN", True),
        ("CHANGE", True),
        ("BUY", True),
    ],
)
def test_filter_needs_attention(state, expected):
    assert filter_needs_attention(state) is expected


def test_normalize_filter_state():
    assert normalize_filter_state("clean") == "CLEAN"


@pytest.mark.parametrize(
    ("alerts", "expected"),
    [
        (None, None),
        ([], []),
        ("communication_fault", ["COMMUNICATION_FAULT"]),
        (["BUS_HIGH_VOLTAGE", {"code": "communication_fault"}], ["BUS_HIGH_VOLTAGE", "COMMUNICATION_FAULT"]),
        ([{"message": "missing code"}], []),
    ],
)
def test_normalize_alerts(alerts, expected):
    assert normalize_alerts(alerts) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (482400, 482400),
        ("3600", 3600),
        (0, 0),
        (None, None),
        ("invalid", None),
        (-1, None),
        (math.inf, None),
    ],
)
def test_filter_runtime_seconds(seconds, expected):
    assert filter_runtime_seconds(seconds) == expected


@pytest.mark.parametrize(
    ("alerts", "water_bucket_level", "water_tank_full", "expected"),
    [
        (None, None, None, None),
        ([], None, None, False),
        (["BUCKET_FULL"], None, None, True),
        (["FILTER"], 0, None, False),
        (None, 1, None, True),
        (None, 0, "NO", False),
        (None, None, "yes", True),
        (None, None, True, True),
        (None, None, False, False),
    ],
)
def test_bucket_is_full(alerts, water_bucket_level, water_tank_full, expected):
    assert bucket_is_full(alerts, water_bucket_level, water_tank_full) is expected

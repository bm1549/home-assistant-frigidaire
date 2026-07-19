"""Tests for Frigidaire diagnostic parsing."""

import math

import pytest
from diagnostics import (
    filter_needs_attention,
    filter_runtime_hours,
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
        (482400, 134),
        ("3600", 1),
        (0, 0),
        (None, None),
        ("invalid", None),
        (-1, None),
        (math.inf, None),
    ],
)
def test_filter_runtime_hours(seconds, expected):
    assert filter_runtime_hours(seconds) == expected

"""Tests for Frigidaire diagnostic parsing."""

import math

import pytest
from diagnostics import (
    filter_needs_attention,
    filter_runtime_seconds,
    humidity_percent,
    link_quality,
    network_rssi,
    normalize_alerts,
    normalize_filter_state,
    particulate_matter,
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
    ("value", "expected"),
    [
        (86, 86),
        ("48.5", 48.5),
        (0, 0),
        (100, 100),
        (None, None),
        ("invalid", None),
        (-1, None),
        (101, None),
        (math.inf, None),
        (math.nan, None),
    ],
)
def test_humidity_percent(value, expected):
    assert humidity_percent(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4, 4),
        ("12", 12),
        (0, 0),
        (None, None),
        ("invalid", None),
        (-1, None),
        (math.inf, None),
        (math.nan, None),
    ],
)
def test_particulate_matter(value, expected):
    assert particulate_matter(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"linkQualityIndicator": "EXCELLENT", "rssi": -41}, -41),
        ({"rssi": "-67"}, -67),
        # Positive dBm is not a real reading, so treat it as a placeholder.
        ({"rssi": 41}, None),
        ({"rssi": 0}, None),
        ({"linkQualityIndicator": "EXCELLENT"}, None),
        ({}, None),
        (None, None),
        # Appliances that report no Wi-Fi telemetry can send a scalar or a list here.
        ("EXCELLENT", None),
        ([], None),
    ],
)
def test_network_rssi(value, expected):
    assert network_rssi(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"linkQualityIndicator": "EXCELLENT", "rssi": -41}, "EXCELLENT"),
        ({"linkQualityIndicator": "poor"}, "POOR"),
        ({"rssi": -41}, None),
        ({}, None),
        (None, None),
        ("EXCELLENT", None),
    ],
)
def test_link_quality(value, expected):
    assert link_quality(value) == expected

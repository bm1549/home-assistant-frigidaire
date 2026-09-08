"""Tests for the deprecation scanner in `scripts/`.

The scanner is what stands between a Home Assistant deprecation and a user filing an issue about
it, so it needs to keep working against Home Assistant versions that do not exist yet. These tests
therefore build their own deprecated constants and enums in the shapes core uses, rather than
pointing at whatever core happens to deprecate today (which would make the suite go quiet the day
that deprecation is removed).
"""

from __future__ import annotations

import logging
import sys
import types
from enum import StrEnum
from pathlib import Path

import pytest
from homeassistant.helpers.deprecation import (
    DeprecatedConstant,
    DeprecatedConstantEnum,
    EnumWithDeprecatedMembers,
)

from scripts.check_deprecations import (
    Finding,
    earliest_removal,
    has_findings,
    render_markdown,
    scan_source,
)
from scripts.deprecation_pytest_plugin import DeprecationRecorder, breaks_in, is_deprecation


class Density(StrEnum):
    """Stand-in for the enum a deprecated constant points at."""

    MICROGRAMS_PER_CUBIC_METER = "µg/m³"


class Feature(
    StrEnum,
    metaclass=EnumWithDeprecatedMembers,
    deprecated={"OLD_MEMBER": ("Feature.NEW_MEMBER", "2099.1")},
):
    """Stand-in for a core enum with a deprecated member."""

    OLD_MEMBER = "old"
    NEW_MEMBER = "new"


@pytest.fixture
def fake_ha_module() -> types.ModuleType:
    """Register a module that looks like a Home Assistant one mid-deprecation.

    `scan_source` resolves imports through `sys.modules`, so registering under the
    `homeassistant.` prefix is enough to make the scanner treat this as core.
    """
    name = "homeassistant.fake_const_for_tests"
    module = types.ModuleType(name)
    module.LIVE_CONSTANT = "live"
    module.DEAD_CONSTANT = "dead"
    module._DEPRECATED_DEAD_CONSTANT = DeprecatedConstant("NEW_CONSTANT", "NEW_CONSTANT", "2099.6")
    module.ENUM_CONSTANT = "enum"
    module._DEPRECATED_ENUM_CONSTANT = DeprecatedConstantEnum(Density.MICROGRAMS_PER_CUBIC_METER, "2099.8")
    module.Feature = Feature
    sys.modules[name] = module
    yield module
    del sys.modules[name]


def write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "module_under_scan.py"
    path.write_text(source)
    return path


def test_flags_deprecated_constant_import(tmp_path: Path, fake_ha_module: types.ModuleType) -> None:
    """A deprecated constant is reported with its replacement, removal version and line."""
    path = write(
        tmp_path,
        "from homeassistant.fake_const_for_tests import (\n    LIVE_CONSTANT,\n    DEAD_CONSTANT,\n)\n",
    )

    findings = scan_source(path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "constant"
    assert finding.name == "homeassistant.fake_const_for_tests.DEAD_CONSTANT"
    assert finding.replacement == "NEW_CONSTANT"
    assert finding.breaks_in == "2099.6"
    # The name's own line, not the line the `from` sits on.
    assert finding.locations == [f"{path}:3"]


def test_names_the_enum_member_a_constant_was_replaced_by(tmp_path: Path, fake_ha_module: types.ModuleType) -> None:
    """`DeprecatedConstantEnum` carries an enum member rather than a replacement string."""
    path = write(tmp_path, "from homeassistant.fake_const_for_tests import ENUM_CONSTANT\n")

    (finding,) = scan_source(path)

    assert finding.replacement == "Density.MICROGRAMS_PER_CUBIC_METER"
    assert finding.breaks_in == "2099.8"


def test_flags_deprecated_enum_member(tmp_path: Path, fake_ha_module: types.ModuleType) -> None:
    """Deprecated enum members are only visible on attribute access, not on the import."""
    path = write(
        tmp_path,
        "from homeassistant.fake_const_for_tests import Feature\n\nSUPPORTED = Feature.OLD_MEMBER\n",
    )

    (finding,) = scan_source(path)

    assert finding.kind == "enum member"
    assert finding.name == "Feature.OLD_MEMBER"
    assert finding.replacement == "Feature.NEW_MEMBER"
    assert finding.breaks_in == "2099.1"


def test_ignores_healthy_code(tmp_path: Path, fake_ha_module: types.ModuleType) -> None:
    """Live constants, live enum members and non-core imports are all left alone."""
    path = write(
        tmp_path,
        "import json\n"
        "from homeassistant.fake_const_for_tests import LIVE_CONSTANT, Feature\n"
        "\n"
        "SUPPORTED = Feature.NEW_MEMBER\n"
        "PARSED = json.loads\n",
    )

    assert scan_source(path) == []


def test_survives_a_module_that_no_longer_exists(tmp_path: Path) -> None:
    """A removed module is a breakage for the test run to report, not a scanner crash."""
    path = write(tmp_path, "from homeassistant.module_that_was_removed import ANYTHING\n")

    assert scan_source(path) == []


@pytest.mark.parametrize(
    ("message", "expected_version"),
    [
        (
            "The deprecated constant CONCENTRATION_MICROGRAMS_PER_CUBIC_METER was used from frigidaire. "
            "It will be removed in HA Core 2027.8. Use UnitOfDensity.MICROGRAMS_PER_CUBIC_METER instead, "
            "please report it to the author of the 'frigidaire' custom integration",
            "2027.8",
        ),
        (
            "Detected that custom integration 'frigidaire' calls async_forward_entry_setup. "
            "This will stop working in Home Assistant 2025.6, please report it to the author",
            "2025.6",
        ),
    ],
)
def test_recognises_both_core_deprecation_message_shapes(message: str, expected_version: str) -> None:
    """Core reports deprecations two ways; both name a version and both are ours to catch."""
    assert is_deprecation(message, "frigidaire")
    assert breaks_in(message) == expected_version


def test_ignores_deprecations_belonging_to_other_integrations() -> None:
    """Another integration's deprecation is not ours to open an issue about."""
    message = (
        "The deprecated constant SOMETHING was used from other_integration. "
        "It will be removed in HA Core 2027.8. Use SomethingElse instead"
    )

    assert not is_deprecation(message, "frigidaire")


def test_ignores_ordinary_warnings() -> None:
    """The test run logs plenty of warnings that have nothing to do with deprecations."""
    assert not is_deprecation("Error fetching frigidaire data: timed out", "frigidaire")


def test_recorder_keeps_one_entry_per_message() -> None:
    """Core repeats the same warning across a run; the report should not."""
    recorder = DeprecationRecorder("frigidaire")
    record = "The deprecated constant FOO was used from frigidaire. It will be removed in HA Core 2099.1."

    for _ in range(3):
        recorder.emit(_log_record(record))
    recorder.emit(_log_record("The deprecated constant BAR was used from frigidaire."))

    assert len(recorder.findings) == 2
    assert recorder.findings[record]["breaks_in"] == "2099.1"


def _log_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("homeassistant.const", logging.WARNING, __file__, 0, message, None, None)


def test_title_deadline_is_the_soonest_removal() -> None:
    """The issue title leads with the deadline, so it has to be the nearest one, compared as numbers."""
    findings = [
        Finding("constant", "a", "detail", breaks_in="2027.10"),
        Finding("constant", "b", "detail", breaks_in="2027.9"),
        Finding("runtime", "c", "detail", breaks_in="2028.1"),
    ]

    # 2027.9 beats 2027.10 numerically, though it loses as a string.
    assert earliest_removal(findings) == "2027.9"


def test_no_deadline_when_nothing_names_a_version() -> None:
    """An unannounced deprecation, or a suite that already fails, leaves the title version-less."""
    assert earliest_removal([]) is None
    assert earliest_removal([Finding("runtime", "a", "detail")]) is None


def test_report_says_so_when_nothing_is_deprecated() -> None:
    """A clean run still produces a body, so the workflow can close a stale issue with it."""
    result = _result()

    assert not has_findings(result)
    assert "No deprecated Home Assistant APIs are in use" in render_markdown(result)


def test_report_lists_findings_soonest_removal_first() -> None:
    """The issue body should lead with whatever breaks first."""
    result = _result(
        static_findings=[
            vars(Finding("constant", "later.CONST", "detail", "NEW", "2099.9", ["a.py:1"])),
            vars(Finding("constant", "sooner.CONST", "detail", "NEW", "2026.1", ["b.py:2"])),
        ]
    )

    body = render_markdown(result)

    assert has_findings(result)
    assert body.index("sooner.CONST") < body.index("later.CONST")


def test_report_flags_a_suite_that_no_longer_passes() -> None:
    """A deprecation that has already become a removal shows up as a failing suite."""
    result = _result(tests_ran=True, pytest_exit_code=1, pytest_output="ImportError: cannot import name FOO")

    assert has_findings(result)
    assert "does not pass against this Home Assistant" in render_markdown(result)


def _result(**overrides) -> dict:
    result = {
        "ha_version": "2099.1.0",
        "scanned_at": "2099-01-01",
        "static_findings": [],
        "runtime_findings": [],
        "tests_ran": True,
        "pytest_exit_code": 0,
        "pytest_output": "",
    }
    return result | overrides

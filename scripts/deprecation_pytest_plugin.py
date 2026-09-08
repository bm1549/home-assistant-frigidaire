"""Pytest plugin that records the Home Assistant deprecation warnings a test run produces.

Home Assistant reports deprecations through the logging module, never as Python
``DeprecationWarning``s: ``helpers/deprecation.py`` logs "The deprecated <thing> <name> was used
from <integration>..." and ``helpers/frame.py`` logs "Detected that custom integration '<domain>'
<did something>...". Both only fire when the calling frame sits inside ``custom_components/``,
which is exactly what the test suite exercises.

So the cheapest way to see what a user's log would show is to run the suite and listen. This plugin
attaches a handler to the root logger for the whole session, keeps the records that look like a
deprecation notice about this integration, and writes them to the JSON file named by
``--deprecation-report``. It never fails a test; ``scripts/check_deprecations.py`` decides what to
do with the findings.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

# The two message shapes Home Assistant uses to report a deprecation. Matching on the message rather
# than the logger name keeps this working when core moves the reporting helpers around; both are
# anchored on wording that has been stable for years.
DEPRECATION_PATTERNS = (
    re.compile(r"The deprecated .* was (used|called|accessed)", re.IGNORECASE),
    re.compile(r"Detected (that )?(custom integration|code that)", re.IGNORECASE),
)

# Pulled out of the messages above so findings can be grouped by what breaks and when. Home
# Assistant versions are calendar-shaped (2027.8, sometimes 2027.8.1), which is specific enough to
# match without dragging in the sentence's trailing full stop.
BREAKS_IN_PATTERN = re.compile(r"(?:removed in HA Core|stop working in Home Assistant) (?P<version>\d+\.\d+(?:\.\d+)*)")


def breaks_in(message: str) -> str | None:
    """Return the HA version a deprecation breaks in, if the message names one."""
    if match := BREAKS_IN_PATTERN.search(message):
        return match.group("version")
    return None


def is_deprecation(message: str, integration: str) -> bool:
    """Return whether this log message is a deprecation notice aimed at `integration`.

    Core's own deprecations (and those of any other loaded custom integration) are not ours to fix.
    Every message about us names the integration, either as "from frigidaire" or as
    "integration 'frigidaire'".
    """
    if integration not in message:
        return False
    return any(pattern.search(message) for pattern in DEPRECATION_PATTERNS)


class DeprecationRecorder(logging.Handler):
    """Collects deprecation log records, deduplicated by message."""

    def __init__(self, integration: str) -> None:
        super().__init__(level=logging.WARNING)
        self.integration = integration
        self.findings: dict[str, dict[str, str | None]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed record must not break the test run
            return
        if not is_deprecation(message, self.integration):
            return
        self.findings.setdefault(
            message,
            {"message": message, "logger": record.name, "breaks_in": breaks_in(message)},
        )


RECORDER_KEY: pytest.StashKey[DeprecationRecorder] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the options that control where findings go."""
    group = parser.getgroup("ha-deprecations")
    group.addoption(
        "--deprecation-report",
        default=None,
        help="Write Home Assistant deprecation warnings seen during the run to this JSON file.",
    )
    group.addoption(
        "--deprecation-integration",
        default="frigidaire",
        help="Only record deprecation warnings whose message names this integration.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Start listening before collection, so import-time deprecations are caught too."""
    if not config.getoption("--deprecation-report"):
        return
    recorder = DeprecationRecorder(config.getoption("--deprecation-integration"))
    # Deprecations are logged on core's own loggers (homeassistant.const,
    # homeassistant.helpers.frame, ...), so listen at the root and let propagation do the work.
    logging.getLogger().addHandler(recorder)
    config.stash[RECORDER_KEY] = recorder


def pytest_unconfigure(config: pytest.Config) -> None:
    """Detach the handler and write the report."""
    recorder = config.stash.get(RECORDER_KEY, None)
    if recorder is None:
        return
    logging.getLogger().removeHandler(recorder)
    report = Path(config.getoption("--deprecation-report"))
    report.parent.mkdir(parents=True, exist_ok=True)
    findings = sorted(recorder.findings.values(), key=lambda finding: finding["message"] or "")
    report.write_text(json.dumps(findings, indent=2) + "\n")

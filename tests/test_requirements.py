"""Guard against the test environment drifting from what users install."""

import json
import re
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "frigidaire" / "manifest.json"
REQUIREMENTS_TEST = ROOT / "requirements_test.txt"


def _pinned(spec_lines: list[str]) -> str:
    matches = [m.group(1) for line in spec_lines if (m := re.fullmatch(r"frigidaire==(\S+)", line.strip()))]
    assert len(matches) == 1, f"expected exactly one frigidaire pin, found {matches}"
    return matches[0]


def test_manifest_and_test_requirements_pin_the_same_frigidaire() -> None:
    manifest_pin = _pinned(json.loads(MANIFEST.read_text())["requirements"])
    test_pin = _pinned(REQUIREMENTS_TEST.read_text().splitlines())
    assert manifest_pin == test_pin


def test_installed_frigidaire_matches_manifest_pin() -> None:
    """The harness must exercise the library version users actually get."""
    manifest_pin = _pinned(json.loads(MANIFEST.read_text())["requirements"])
    assert metadata.version("frigidaire") == manifest_pin

"""Check that the integration still loads on the oldest Home Assistant that ``hacs.json`` promises.

HACS only offers a release to installs at or above ``hacs.json``'s ``homeassistant`` version, so that
field is a promise: everything older is turned away, everything newer gets the update. The test
workflow only runs against the pinned (newest) Home Assistant, so nothing held us to the promise --
0.1.50 started importing ``UnitOfDensity``, which core only gained in 2026.9, while ``hacs.json``
still said 2025.8, and users in between got an integration that failed to set up (#176).

This script is the cheap half of keeping that promise: run against exactly the minimum Home
Assistant (see the ``minimum-home-assistant`` job in ``.github/workflows/test.yml``), it imports
every module of the integration. A name core does not have yet fails right there, at import time,
which is how it fails for users too.

Usage:
    python scripts/check_minimum_version.py

Exits 0 when every module imports, 1 otherwise.
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "frigidaire"
HACS_JSON = REPO_ROOT / "hacs.json"


def minimum_version() -> str:
    return json.loads(HACS_JSON.read_text())["homeassistant"]


def integration_modules() -> list[str]:
    package = "custom_components.frigidaire"
    modules = [path.stem for path in sorted(INTEGRATION_DIR.glob("*.py")) if path.stem != "__init__"]
    return [package] + [f"{package}.{module}" for module in modules]


def main() -> int:
    from homeassistant.const import __version__ as installed

    # A job that quietly installed some other version would pass without proving anything.
    wanted = minimum_version()
    if installed != wanted:
        print(f"hacs.json promises Home Assistant {wanted}, but {installed} is installed")
        return 1

    sys.path.insert(0, str(REPO_ROOT))
    failures = 0
    for module in integration_modules():
        try:
            importlib.import_module(module)
        except Exception:
            failures += 1
            print(f"FAIL {module}\n{traceback.format_exc()}")
        else:
            print(f"ok   {module}")

    if failures:
        print(
            f"\n{failures} module(s) do not import on Home Assistant {wanted}, the minimum in hacs.json. "
            "Either keep the code working there, or raise hacs.json's minimum to the release that has what it needs."
        )
        return 1
    print(f"\nEvery module imports on Home Assistant {wanted}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

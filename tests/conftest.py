"""Shared test configuration.

Two kinds of tests live here:

- Pure-helper tests (`test_auth_store.py`, `test_diagnostics.py`) import `auth_store` and
  `diagnostics` directly; the sys.path insert below makes that work without importing the
  integration package (which needs Home Assistant).
- Integration tests use the `hass` fixture from pytest-homeassistant-custom-component with
  `frigidaire.Frigidaire` replaced by `StubFrigidaire`, so nothing touches the network.
"""

from __future__ import annotations

import copy
import os
import sys
from collections.abc import Awaitable, Callable, Generator
from unittest.mock import patch

import frigidaire
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "frigidaire"))

DOMAIN = "frigidaire"


class StubFrigidaire:
    """Stands in for frigidaire.Frigidaire.

    Serves canned appliance records and records every command the integration sends, so
    tests can assert on both state and the exact PUT sequence without any HTTP.
    """

    def __init__(self, records: list[dict]) -> None:
        # Real strings, not MagicMocks: the integration persists these to its auth file.
        self.session_key = "stub-session-key"
        self.regional_base_url = "https://api.us.ocp.electrolux.one"
        self.records: dict[str, dict] = {r["applianceId"]: copy.deepcopy(r) for r in records}
        self.commands: list[tuple[str, object]] = []
        self.details_error: Exception | None = None
        self.appliances_error: Exception | None = None

    def get_appliances(self) -> list[frigidaire.Appliance]:
        if self.appliances_error is not None:
            raise self.appliances_error
        return [frigidaire.Appliance(record) for record in self.records.values()]

    def get_appliance_details(self, appliance: frigidaire.Appliance) -> dict:
        if self.details_error is not None:
            raise self.details_error
        return self.records[appliance.appliance_id]["properties"]["reported"]

    def get_appliance_raw(self, appliance: frigidaire.Appliance) -> dict:
        if self.details_error is not None:
            raise self.details_error
        return self.records[appliance.appliance_id]

    def execute_action(self, appliance: frigidaire.Appliance, action: list[frigidaire.Component]) -> None:
        self.commands.extend((component.name, component.value) for component in action)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Let Home Assistant load custom_components/frigidaire from this checkout.

    Creating `hass` imports `custom_components` while pytest-homeassistant-custom-component's own
    `testing_config` dir is first on sys.path, so the cached module is that package (a regular one,
    which shadows this checkout's namespace package no matter the sys.path order). Dropping the
    cached entry makes the loader's next import resolve through `pythonpath = ["."]` instead.
    """
    cached = sys.modules.pop("custom_components", None)
    yield
    if cached is not None:
        sys.modules["custom_components"] = cached


@pytest.fixture
def frigidaire_stub():
    """Patch frigidaire.Frigidaire for the whole test; returns an installer for the stub.

    The patch stays active across config-entry reloads, which construct a new client.
    """
    with patch("frigidaire.Frigidaire") as client_cls:

        def install(records: list[dict]) -> StubFrigidaire:
            stub = StubFrigidaire(records)
            client_cls.return_value = stub
            return stub

        yield install


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, frigidaire_stub, tmp_path
) -> Callable[..., Awaitable[tuple[MockConfigEntry, StubFrigidaire]]]:
    """Return a coroutine that sets up a frigidaire config entry against the given records."""
    # Auth files are written under hass.config.path(); keep them out of the shared test config dir.
    hass.config.config_dir = str(tmp_path)
    # Temperatures are asserted in the unit the appliance reports.
    hass.config.units = US_CUSTOMARY_SYSTEM

    async def _setup(records: list[dict], options: dict | None = None) -> tuple[MockConfigEntry, StubFrigidaire]:
        stub = frigidaire_stub(records)
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "user@example.com", "password": "secret"},
            options=options or {},
            unique_id="user@example.com",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry, stub

    return _setup

"""Shared test configuration.

Integration tests use the `hass` fixture from pytest-homeassistant-custom-component with
`frigidaire.Frigidaire` replaced by the library's own `FakeFrigidaire`, so nothing touches
the network and the real command builders and parsing still run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from unittest.mock import patch

import pytest
from frigidaire.testing import FakeFrigidaire
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "frigidaire"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Let Home Assistant load custom_components/frigidaire from this checkout.

    Creating `hass` imports `custom_components` while pytest-homeassistant-custom-component's own
    `testing_config` dir is first on sys.path, so the cached module is that package (a regular one,
    which shadows this checkout's namespace package no matter the sys.path order). Dropping the
    cached entry makes the loader's next import resolve through `pythonpath = ["."]` instead.
    """
    import sys

    cached = sys.modules.pop("custom_components", None)
    yield
    if cached is not None:
        sys.modules["custom_components"] = cached


@pytest.fixture
def frigidaire_stub():
    """Patch frigidaire.Frigidaire for the whole test; returns an installer for the fake.

    The patch stays active across config-entry reloads and config flows, which construct new
    clients: every construction hands back the same fake, wired to whatever session store the
    integration passed so the session-file behaviour is exercised too.
    """
    with patch("frigidaire.Frigidaire") as client_cls:

        def install(records: list[dict]) -> FakeFrigidaire:
            stub = FakeFrigidaire(records)

            def construct(username: str, password: str, **kwargs) -> FakeFrigidaire:
                if stub.error is not None:
                    raise stub.error
                stub.username = username
                stub.password = password
                stub._session_store = kwargs.get("session_store")
                stub._persist_session()
                return stub

            client_cls.side_effect = construct
            return stub

        yield install


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, frigidaire_stub, tmp_path
) -> Callable[..., Awaitable[tuple[MockConfigEntry, FakeFrigidaire]]]:
    """Return a coroutine that sets up a frigidaire config entry against the given records."""
    # Session files are written under hass.config.path(); keep them out of the shared test config dir.
    hass.config.config_dir = str(tmp_path)
    # Temperatures are asserted in the unit the appliance reports.
    hass.config.units = US_CUSTOMARY_SYSTEM

    async def _setup(records: list[dict], options: dict | None = None) -> tuple[MockConfigEntry, FakeFrigidaire]:
        stub = frigidaire_stub(records)
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "user@example.com", "password": "secret"},
            options=options or {},
            unique_id="user@example.com",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        return entry, stub

    return _setup

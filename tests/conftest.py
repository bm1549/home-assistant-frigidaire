"""Shared test configuration.

Integration tests use the `hass` fixture from pytest-homeassistant-custom-component with the
password method's backend replaced by the library's own `FakeBackend`, so nothing touches the
network and the real facade, command sequences and parsing still run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator
from unittest.mock import patch

import pytest
from frigidaire.testing import FakeBackend
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


# The password method's single patch point for building a backend.
BUILD_BACKEND = "custom_components.frigidaire.auth.password.build_backend"
ENTRY_DATA = {"auth_method": "password", "username": "user@example.com", "password": "secret"}


@pytest.fixture
def frigidaire_stub():
    """Patch the password method's backend factory for the whole test; returns an installer for the fake.

    The patch stays active across config-entry reloads and config flows, which build new backends:
    every build hands back the same fake, recording the credentials it was given and saving a session
    to whatever session store the integration passed, as a real login does, so the session-file
    behaviour is exercised too.
    """
    with patch(BUILD_BACKEND) as build:

        def install(records: list[dict]) -> FakeBackend:
            stub = FakeBackend(records)

            def construct(username: str, password: str, session_store) -> FakeBackend:
                stub.username = username
                stub.password = password
                stub.session_store = session_store
                if stub.error is None:
                    session_store.save("fake-session-key", "https://fake.invalid")
                return stub

            build.side_effect = construct
            return stub

        yield install


def make_entry(hass: HomeAssistant, *, options: dict | None = None) -> MockConfigEntry:
    """A current-version password entry for user@example.com, added to hass but not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        data=dict(ENTRY_DATA),
        options=options or {},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, frigidaire_stub, tmp_path
) -> Callable[..., Awaitable[tuple[MockConfigEntry, FakeBackend]]]:
    """Return a coroutine that sets up a frigidaire config entry against the given records."""
    # Session files are written under hass.config.path(); keep them out of the shared test config dir.
    hass.config.config_dir = str(tmp_path)
    # Temperatures are asserted in the unit the appliance reports.
    hass.config.units = US_CUSTOMARY_SYSTEM

    async def _setup(records: list[dict], options: dict | None = None) -> tuple[MockConfigEntry, FakeBackend]:
        stub = frigidaire_stub(records)
        entry = make_entry(hass, options=options)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        return entry, stub

    return _setup

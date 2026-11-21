"""Shared test configuration.

Integration tests use the `hass` fixture from pytest-homeassistant-custom-component with the
sign-in method's backend replaced by the library's own `FakeBackend`, so nothing touches the
network and the real facade, command sequences and parsing still run.

Tests use the password method unless they parametrize `auth_method`, for example
`@pytest.mark.parametrize("auth_method", ["password", "api_key"])`; the `method` fixture then
says how to drive that method (what to type, its resync interval, a definite auth error).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import patch

import frigidaire
import pytest
from frigidaire.testing import FakeBackend
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.frigidaire.coordinator import STREAM_TASK_NAME

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


@dataclass(frozen=True)
class MethodCase:
    """How the tests drive one sign-in method: its patch point, what a user types, and its timing."""

    name: str
    build_backend: str  # the method's single patch point for building a backend
    setup_input: dict  # what the user types in the setup form
    reauth_input: dict  # what the user types in the reauth form
    resync: timedelta  # the method's RESYNC_INTERVAL
    auth_error: Callable[[], Exception]  # an error that means the credentials are rejected, for certain

    @property
    def entry_data(self) -> dict:
        return {"auth_method": self.name, **self.setup_input}


METHOD_CASES: dict[str, MethodCase] = {
    "password": MethodCase(
        name="password",
        build_backend="custom_components.frigidaire.auth.password.build_backend",
        setup_input={"username": "user@example.com", "password": "secret"},
        reauth_input={"password": "new-secret"},
        resync=timedelta(seconds=30),
        auth_error=lambda: frigidaire.AuthenticationError("Failed to authenticate"),
    ),
    "api_key": MethodCase(
        name="api_key",
        build_backend="custom_components.frigidaire.auth.api_key.build_backend",
        setup_input={"api_key": "the-api-key", "access_token": "access-1", "refresh_token": "refresh-1"},
        reauth_input={"api_key": "new-api-key", "access_token": "access-2", "refresh_token": "refresh-2"},
        resync=timedelta(minutes=5),
        # With an HTTP status, the server rejected the credentials: reauth starts at once.
        auth_error=lambda: frigidaire.AuthenticationError("Rejected", status_code=401),
    ),
}
# The method every test uses unless it parametrizes ``auth_method``.
DEFAULT_METHOD = "password"

# Kept for tests written against the password method.
BUILD_BACKEND = METHOD_CASES["password"].build_backend
ENTRY_DATA = METHOD_CASES["password"].entry_data


class FakeApiKeyBackend(FakeBackend):
    """``FakeBackend`` with the ``ApiKeyBackend``'s live updates and token behaviour.

    ``tokens`` is the pair in use; ``rotate`` replaces it and hands it to the ``on_tokens`` callback,
    as a refresh does. ``rotate_on_connect`` makes the next ``connect`` rotate to that pair, as when
    the typed access token was near expiry. ``listen_error``, when set, is raised by ``listen``.
    """

    def __init__(self, records: list[dict]) -> None:
        super().__init__(records, supports_live_updates=True)
        self.tokens: tuple[str, str] = ("", "")
        self.on_tokens: Callable[[str, str], None] | None = None
        self.rotate_on_connect: tuple[str, str] | None = None
        self.listen_error: Exception | None = None

    def rotate(self, access_token: str, refresh_token: str) -> None:
        self.tokens = (access_token, refresh_token)
        if self.on_tokens is not None:
            self.on_tokens(access_token, refresh_token)

    async def connect(self) -> None:
        if self.rotate_on_connect is not None:
            pair, self.rotate_on_connect = self.rotate_on_connect, None
            self.rotate(*pair)
        await super().connect()

    async def listen(self, on_record, on_connect, on_disconnect) -> None:
        if self.listen_error is not None:
            raise self.listen_error
        await super().listen(on_record, on_connect, on_disconnect)


@pytest.fixture
def auth_method() -> str:
    """The sign-in method under test. Parametrize this name to run a test once per method."""
    return DEFAULT_METHOD


@pytest.fixture
def method(auth_method: str) -> MethodCase:
    return METHOD_CASES[auth_method]


@pytest.fixture
def method_cases() -> dict[str, MethodCase]:
    """Every method's case, for tests that involve more than one method."""
    return METHOD_CASES


def _unexpected_build(*args, **kwargs):
    raise AssertionError("A test built a backend for a sign-in method other than the one under test")


@pytest.fixture
def frigidaire_stub(method: MethodCase):
    """Patch the method's backend factory for the whole test; returns an installer for the fake.

    The patch stays active across config-entry reloads and config flows, which build new backends:
    every build hands back the same fake, recording the credentials it was given in
    ``stub.credentials``. For the password method it also records ``.username``, ``.password`` and
    ``.session_store`` and saves a session to that store, as a real login does, so the session-file
    behaviour is exercised too. For the API key method the fake is a ``FakeApiKeyBackend`` whose
    ``tokens`` start as the ones it was built with and whose ``on_tokens`` is the callback it got.
    Every other method's factory fails the test if called, so nothing reaches a real backend.
    """
    others = [case.build_backend for case in METHOD_CASES.values() if case.name != method.name]
    with contextlib.ExitStack() as stack:
        for target in others:
            stack.enter_context(patch(target, side_effect=_unexpected_build))
        build = stack.enter_context(patch(method.build_backend))

        def install(records: list[dict]) -> FakeBackend:
            if method.name == "api_key":
                stub: FakeBackend = FakeApiKeyBackend(records)

                def construct_api_key(api_key: str, access_token: str, refresh_token: str, on_tokens) -> FakeBackend:
                    stub.credentials = {
                        "api_key": api_key,
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                    }
                    stub.tokens = (access_token, refresh_token)
                    stub.on_tokens = on_tokens
                    return stub

                build.side_effect = construct_api_key
                return stub

            stub = FakeBackend(records)

            def construct(username: str, password: str, session_store) -> FakeBackend:
                stub.credentials = {"username": username, "password": password}
                stub.username = username
                stub.password = password
                stub.session_store = session_store
                if stub.error is None:
                    session_store.save("fake-session-key", "https://fake.invalid")
                return stub

            build.side_effect = construct
            return stub

        yield install


def make_entry(hass: HomeAssistant, *, options: dict | None = None, data: dict | None = None) -> MockConfigEntry:
    """A current-version entry for user@example.com (password unless ``data`` says otherwise), not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        data=dict(ENTRY_DATA if data is None else data),
        options=options or {},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def add_entry(hass: HomeAssistant) -> Callable[..., MockConfigEntry]:
    """``make_entry`` bound to ``hass``: add a current-version entry without setting it up."""
    return lambda **kwargs: make_entry(hass, **kwargs)


async def _settle(hass: HomeAssistant) -> None:
    """``async_block_till_done(wait_background_tasks=True)``, minus the live update stream.

    The stream is an entry background task that runs until the entry unloads, so waiting for it
    would never return.
    """
    while True:
        await hass.async_block_till_done()
        pending = [
            task
            for task in hass._background_tasks
            if not task.done() and getattr(task, "get_name", lambda: None)() != STREAM_TASK_NAME
        ]
        if not pending:
            return
        await asyncio.wait(pending)


@pytest.fixture
def settle(hass: HomeAssistant) -> Callable[[], Awaitable[None]]:
    """Wait for all pending work, background tasks included, except a running live update stream."""
    return lambda: _settle(hass)


@pytest.fixture
def poll(hass: HomeAssistant, method: MethodCase) -> Callable[..., Awaitable[None]]:
    """Fire time forward, by default just past the method's resync interval, then settle.

    Each fire is relative to real now, not the previous fire.
    """

    async def _poll(seconds: float | None = None) -> None:
        if seconds is None:
            seconds = method.resync.total_seconds() + 1
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await _settle(hass)

    return _poll


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, frigidaire_stub, method: MethodCase, tmp_path
) -> Callable[..., Awaitable[tuple[MockConfigEntry, FakeBackend]]]:
    """Return a coroutine that sets up a config entry for the method under test against the given records."""
    # Session files are written under hass.config.path(); keep them out of the shared test config dir.
    hass.config.config_dir = str(tmp_path)
    # Temperatures are asserted in the unit the appliance reports.
    hass.config.units = US_CUSTOMARY_SYSTEM

    async def _setup(records: list[dict], options: dict | None = None) -> tuple[MockConfigEntry, FakeBackend]:
        stub = frigidaire_stub(records)
        entry = make_entry(hass, options=options, data=method.entry_data)
        await hass.config_entries.async_setup(entry.entry_id)
        await _settle(hass)
        return entry, stub

    return _setup

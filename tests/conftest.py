"""Shared test configuration.

Integration tests use the `hass` fixture from pytest-homeassistant-custom-component with the
sign-in method's backend replaced by the library's own `FakeBackend`, so nothing touches the
network and the real async client, command plans and parsing still run.

Tests use the first sign-in method in the menu (password) unless they parametrize `auth_method`,
for example `@pytest.mark.parametrize("auth_method", list(METHODS))`; the `method` fixture then
says how to drive that method (what to type, its resync interval, a definite auth error). A test
that only makes sense for one method says so the same way, with that one method.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import MagicMock, patch

import frigidaire
import pytest
from frigidaire.testing import FakeBackend
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.frigidaire.auth import METHODS
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


# Installs a method's fake: given the patched ``build_backend`` and the records, it returns the
# fake backend and sets the mock's side effect so every build hands that fake back.
Installer = Callable[[MagicMock, list[dict]], FakeBackend]


@dataclass(frozen=True)
class MethodCase:
    """How the tests drive one sign-in method: its patch point, what a user types, and its timing."""

    name: str
    build_backend: str  # the method's single patch point for building a backend
    install: Installer  # builds the fake that every patched build_backend call returns
    setup_input: dict  # what the user types in the setup form
    reauth_input: dict  # what the user types in the reauth form
    resync: timedelta  # the method's RESYNC_INTERVAL
    auth_error: Callable[[], Exception]  # an error that means the credentials are rejected, for certain

    @property
    def entry_data(self) -> dict:
        return {"auth_method": self.name, **self.setup_input}


def _install_password(build: MagicMock, records: list[dict]) -> FakeBackend:
    """A ``FakeBackend`` that records ``.username``, ``.password`` and ``.session_store`` and saves
    a session to that store, as a real login does, so the session-file behaviour is exercised too."""
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


def _install_api_key(build: MagicMock, records: list[dict]) -> FakeBackend:
    """A ``FakeApiKeyBackend`` whose ``tokens`` start as the pair it was built with and whose
    ``on_tokens`` is the callback it got, so token saving runs as with the real backend."""
    stub = FakeApiKeyBackend(records)

    def construct(api_key: str, access_token: str, refresh_token: str, on_tokens) -> FakeBackend:
        stub.credentials = {"api_key": api_key, "access_token": access_token, "refresh_token": refresh_token}
        stub.tokens = (access_token, refresh_token)
        stub.on_tokens = on_tokens
        return stub

    build.side_effect = construct
    return stub


_CASES: dict[str, MethodCase] = {
    "password": MethodCase(
        name="password",
        build_backend="custom_components.frigidaire.auth.password.build_backend",
        install=_install_password,
        setup_input={"username": "user@example.com", "password": "secret"},
        reauth_input={"password": "new-secret"},
        resync=timedelta(seconds=30),
        auth_error=lambda: frigidaire.AuthenticationError("Failed to authenticate"),
    ),
    "api_key": MethodCase(
        name="api_key",
        build_backend="custom_components.frigidaire.auth.api_key.build_backend",
        install=_install_api_key,
        setup_input={"api_key": "the-api-key", "access_token": "access-1", "refresh_token": "refresh-1"},
        reauth_input={"api_key": "new-api-key", "access_token": "access-2", "refresh_token": "refresh-2"},
        resync=timedelta(minutes=5),
        auth_error=lambda: frigidaire.AuthenticationError("Rejected", status_code=401),
    ),
}
# Only the methods the integration has: deleting a method's module drops its case here too.
METHOD_CASES: dict[str, MethodCase] = {name: case for name, case in _CASES.items() if name in METHODS}
# The method every test uses unless it parametrizes ``auth_method``: the first in the setup menu.
DEFAULT_METHOD = next(iter(METHOD_CASES))

# Names of entry background tasks that run for the life of the entry, which ``settle`` must not
# wait for: the live update stream of methods that have one.
LONG_RUNNING_TASKS: frozenset[str] = frozenset({STREAM_TASK_NAME})


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
    ``stub.credentials`` (see each case's installer for what else it records). Every other
    method's factory fails the test if called, so nothing reaches a real backend.
    """
    others = [case.build_backend for case in METHOD_CASES.values() if case.name != method.name]
    with contextlib.ExitStack() as stack:
        for target in others:
            stack.enter_context(patch(target, side_effect=_unexpected_build))
        build = stack.enter_context(patch(method.build_backend))
        yield lambda records: method.install(build, records)


def make_entry(hass: HomeAssistant, *, options: dict | None = None, data: dict | None = None) -> MockConfigEntry:
    """A current-version entry for user@example.com, not set up; ``DEFAULT_METHOD``'s unless ``data`` says otherwise."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        data=dict(METHOD_CASES[DEFAULT_METHOD].entry_data if data is None else data),
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
    """``async_block_till_done(wait_background_tasks=True)``, minus ``LONG_RUNNING_TASKS``,
    which run until the entry unloads, so waiting for them would never return."""
    while True:
        await hass.async_block_till_done()
        pending = [
            task
            for task in hass._background_tasks
            if not task.done() and getattr(task, "get_name", lambda: None)() not in LONG_RUNNING_TASKS
        ]
        if not pending:
            return
        await asyncio.wait(pending)


@pytest.fixture
def settle(hass: HomeAssistant) -> Callable[[], Awaitable[None]]:
    """Wait for all pending work, background tasks included, except the long-running ones."""
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

"""The email-and-password sign-in module: its session files and validation."""

import json
from datetime import timedelta
from unittest.mock import patch

import frigidaire
import pytest
from frigidaire.testing import LEGACY_AC
from homeassistant.core import HomeAssistant

from custom_components.frigidaire.auth import METHODS, password
from custom_components.frigidaire.auth.errors import CannotConnect, InvalidAuth

CREDENTIALS = {"username": "User@Example.com", "password": "secret"}


@pytest.fixture
def auth_method() -> str:
    """Every test here runs against the password method."""
    return "password"


def write_session(path, key: str, url: str) -> None:
    path.write_text(json.dumps({"session_key": key, "regional_base_url": url}))


def store_for_entry(hass: HomeAssistant, entry) -> frigidaire.SessionStore:
    """The session store create_backend hands the backend, before any login touches it."""
    with patch.object(password, "build_backend") as build:
        password.create_backend(hass, entry)
    username, secret, store = build.call_args.args
    assert (username, secret) == ("user@example.com", "secret")
    return store


def test_password_is_the_first_menu_entry() -> None:
    assert list(METHODS)[0] == "password"
    assert METHODS["password"] is password
    assert password.METHOD == "password"
    assert password.RESYNC_INTERVAL == timedelta(seconds=30)
    assert password.RATE_LIMIT_ERRORS == (frigidaire.SessionCapError,)


async def test_validation_logs_in_fresh_and_saves_the_session_for_setup(
    hass: HomeAssistant, frigidaire_stub, tmp_path
) -> None:
    """A stored session must never stand in for checking the password; the new one is kept for setup."""
    hass.config.config_dir = str(tmp_path)
    write_session(tmp_path / "frigidaire.json", "old-key", "https://old.invalid")
    stub = frigidaire_stub([LEGACY_AC])

    email, appliances = await password.async_validate(hass, dict(CREDENTIALS))

    assert email == stub.email  # the real backend reports the login username
    assert [appliance.appliance_id for appliance in appliances] == ["AC-LEGACY-1"]
    assert (stub.username, stub.password) == ("User@Example.com", "secret")
    assert stub.session_store.load() == (None, None)
    saved = json.loads((tmp_path / "frigidaire.json").read_text())
    assert saved == {"session_key": "fake-session-key", "regional_base_url": "https://fake.invalid"}
    assert stub.closed


async def test_reauth_validation_saves_to_the_entry_session_file(
    hass: HomeAssistant, setup_entry, frigidaire_stub, tmp_path
) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    (tmp_path / f"frigidaire-{entry.entry_id}.json").unlink()
    stub = frigidaire_stub([LEGACY_AC])

    await password.async_validate(hass, dict(CREDENTIALS), entry)

    assert stub.session_store.load() == (None, None)
    assert (tmp_path / f"frigidaire-{entry.entry_id}.json").exists()
    assert not (tmp_path / "frigidaire.json").exists()


@pytest.mark.parametrize(
    "error, expected",
    [
        (frigidaire.AuthenticationError("Failed to authenticate"), InvalidAuth),
        (frigidaire.LoginError("Failed to authenticate, sessionInfo was not in response"), InvalidAuth),
        (frigidaire.SessionCapError("Request failed", status_code=429, error_code="cas_3403"), CannotConnect),
        (frigidaire.FrigidaireException("Request failed", status_code=503), CannotConnect),
    ],
)
async def test_validation_maps_library_errors(hass: HomeAssistant, frigidaire_stub, tmp_path, error, expected) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = error

    with pytest.raises(expected):
        await password.async_validate(hass, dict(CREDENTIALS))
    assert stub.closed


async def test_entry_backend_prefers_its_own_session_file(hass: HomeAssistant, setup_entry, tmp_path) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    write_session(tmp_path / "frigidaire.json", "legacy-key", "https://legacy.invalid")
    write_session(tmp_path / f"frigidaire-{entry.entry_id}.json", "own-key", "https://own.invalid")

    assert store_for_entry(hass, entry).load() == ("own-key", "https://own.invalid")


async def test_entry_backend_falls_back_to_the_legacy_session_once(hass: HomeAssistant, setup_entry, tmp_path) -> None:
    """The setup flow saved its session to the shared file; setup adopts it into the entry's own file."""
    entry, _stub = await setup_entry([LEGACY_AC])
    own = tmp_path / f"frigidaire-{entry.entry_id}.json"
    own.unlink()
    write_session(tmp_path / "frigidaire.json", "legacy-key", "https://legacy.invalid")

    store = store_for_entry(hass, entry)
    assert store.load() == ("legacy-key", "https://legacy.invalid")

    store.save("new-key", "https://new.invalid")
    assert json.loads(own.read_text()) == {"session_key": "new-key", "regional_base_url": "https://new.invalid"}
    assert store.load() == ("new-key", "https://new.invalid")


async def test_remove_tolerates_a_missing_session_file(hass: HomeAssistant, setup_entry, tmp_path) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    (tmp_path / f"frigidaire-{entry.entry_id}.json").unlink()

    await password.async_remove(hass, entry)


async def test_reauth_form_shows_the_username_as_typed(hass: HomeAssistant, frigidaire_stub, add_entry, method) -> None:
    """Not the lowercased unique id, and not the entry title when an old entry has no unique id."""
    frigidaire_stub([LEGACY_AC])
    entry = add_entry(data={**method.entry_data, "username": "User@Example.com"})

    result = await entry.start_reauth_flow(hass)

    assert result["description_placeholders"]["username"] == "User@Example.com"

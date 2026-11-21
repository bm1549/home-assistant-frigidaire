"""The API key sign-in module: validation, token persistence and cautious reauth."""

from datetime import timedelta
from unittest.mock import patch

import frigidaire
import pytest
from frigidaire.testing import LEGACY_AC
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.frigidaire.auth import METHODS, api_key
from custom_components.frigidaire.auth.errors import CannotConnect, InvalidAuth

DOMAIN = "frigidaire"
TYPED = {"api_key": "the-api-key", "access_token": "access-1", "refresh_token": "refresh-1"}


@pytest.fixture
def auth_method() -> str:
    """Every test here runs against the API key method."""
    return "api_key"


def reauth_flows(hass: HomeAssistant) -> list[dict]:
    return [
        f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH
    ]


async def open_form(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "api_key"})


def test_api_key_is_the_second_menu_entry_and_in_beta() -> None:
    assert list(METHODS) == ["password", "api_key"]
    assert METHODS["api_key"] is api_key
    assert api_key.METHOD == "api_key"
    assert api_key.BETA is True
    assert api_key.RESYNC_INTERVAL == timedelta(minutes=5)


async def test_form_links_the_developer_portal(hass: HomeAssistant) -> None:
    result = await open_form(hass)

    assert result["step_id"] == "api_key"
    assert result["description_placeholders"] == {"portal_url": "https://developer.electrolux.one/dashboard"}
    assert [str(key) for key in result["data_schema"].schema] == ["api_key", "access_token", "refresh_token"]


async def test_validation_stores_the_backends_tokens_not_the_typed_ones(
    hass: HomeAssistant, frigidaire_stub, settle
) -> None:
    """Validation refreshed the tokens, which spent the typed refresh token: the entry keeps the new pair."""
    stub = frigidaire_stub([LEGACY_AC])
    stub.rotate_on_connect = ("access-rotated", "refresh-rotated")

    result = await open_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(TYPED))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await settle()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "auth_method": "api_key",
        "api_key": "the-api-key",
        "access_token": "access-rotated",
        "refresh_token": "refresh-rotated",
    }
    # Setup built its backend from the stored pair.
    assert stub.credentials["refresh_token"] == "refresh-rotated"


async def test_validation_updates_the_input_in_place(hass: HomeAssistant, frigidaire_stub) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.rotate_on_connect = ("access-rotated", "refresh-rotated")
    user_input = {"api_key": " the-api-key\n", "access_token": "access-1 ", "refresh_token": " refresh-1"}

    email, appliances = await api_key.async_validate(hass, user_input)

    assert email == "user@example.com"
    assert [appliance.appliance_id for appliance in appliances] == ["AC-LEGACY-1"]
    # Pasted whitespace is dropped before the backend sees the values.
    assert stub.credentials == TYPED
    assert user_input == {
        "api_key": "the-api-key",
        "access_token": "access-rotated",
        "refresh_token": "refresh-rotated",
    }
    assert stub.on_tokens is None
    assert stub.closed


async def test_failed_validation_keeps_the_rotated_tokens_in_the_form(hass: HomeAssistant, frigidaire_stub) -> None:
    """Retrying with the typed refresh token would fail: it was spent before the failure."""
    stub = frigidaire_stub([LEGACY_AC])
    stub.rotate_on_connect = ("access-rotated", "refresh-rotated")
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)

    result = await open_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(TYPED))

    assert result["errors"] == {"base": "cannot_connect"}
    suggested = {str(key): key.description["suggested_value"] for key in result["data_schema"].schema}
    assert suggested == {"api_key": "the-api-key", "access_token": "access-rotated", "refresh_token": "refresh-rotated"}


@pytest.mark.parametrize(
    "error, expected",
    [
        (frigidaire.AuthenticationError("Rejected", status_code=401), InvalidAuth),
        # During validation there is nothing to retry: a failed refresh means the typed values do not work.
        (frigidaire.AuthenticationError("Token refresh failed"), InvalidAuth),
        (frigidaire.QuotaExceededError("Quota", retry_after=60, status_code=429), CannotConnect),
        (frigidaire.FrigidaireException("Request failed", status_code=503), CannotConnect),
    ],
)
async def test_validation_maps_library_errors(hass: HomeAssistant, frigidaire_stub, error, expected) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = error

    with pytest.raises(expected):
        await api_key.async_validate(hass, dict(TYPED))
    assert stub.closed


async def test_tokens_that_cannot_be_loaded_are_invalid_auth(hass: HomeAssistant, frigidaire_stub) -> None:
    frigidaire_stub([LEGACY_AC])
    with patch.object(api_key, "build_backend", side_effect=frigidaire.AuthenticationError("not a JWT")):
        with pytest.raises(InvalidAuth):
            await api_key.async_validate(hass, dict(TYPED))


async def test_the_factory_builds_the_librarys_backend_without_any_request() -> None:
    backend = api_key.build_backend("the-api-key", "access-1", "refresh-1", None)
    try:
        assert isinstance(backend, frigidaire.ApiKeyBackend)
        assert backend.tokens == ("access-1", "refresh-1")
        assert "the-api-key" not in repr(backend) and "refresh-1" not in repr(backend)
    finally:
        await backend.close()


async def test_rotated_tokens_are_written_to_the_entry_at_once(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    connects = stub.connect_count

    stub.rotate("access-2", "refresh-2")
    await settle()

    assert entry.data == {
        "auth_method": "api_key",
        "api_key": "the-api-key",
        "access_token": "access-2",
        "refresh_token": "refresh-2",
    }
    # A data update does not reload the entry.
    assert entry.state is ConfigEntryState.LOADED
    assert stub.connect_count == connects

    stub.rotate("access-3", "refresh-3")
    assert (entry.data["access_token"], entry.data["refresh_token"]) == ("access-3", "refresh-3")


async def test_an_unloadable_token_at_setup_starts_reauth(
    hass: HomeAssistant, frigidaire_stub, add_entry, method
) -> None:
    frigidaire_stub([LEGACY_AC])
    entry = add_entry(data=method.entry_data)

    with patch.object(api_key, "build_backend", side_effect=frigidaire.AuthenticationError("not a JWT")):
        assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1


# --- a failed token refresh is retried once before asking for new credentials ---


async def test_one_failed_token_refresh_does_not_start_reauth(
    hass: HomeAssistant, setup_entry, poll, caplog: pytest.LogCaptureFixture
) -> None:
    """The SDK reports a refresh lost to a network blip the same way as a refused one."""
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Token refresh failed")

    await poll()

    assert reauth_flows(hass) == []
    assert entry.state is ConfigEntryState.LOADED
    assert "retrying before asking to sign in again" in caplog.text


async def test_a_repeated_failed_token_refresh_starts_reauth(hass: HomeAssistant, setup_entry, poll) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Token refresh failed")

    await poll()
    assert reauth_flows(hass) == []
    # The failure backed off; the retry fails the same way.
    await poll(seconds=601)

    flows = reauth_flows(hass)
    assert len(flows) == 1
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_a_success_in_between_clears_the_suspicion(hass: HomeAssistant, setup_entry, poll) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Token refresh failed")
    await poll()
    stub.error = None
    await poll(seconds=601)
    assert stub.fetch_count == 3

    stub.error = frigidaire.AuthenticationError("Token refresh failed")
    await poll()

    assert reauth_flows(hass) == []


async def test_a_rejection_with_an_http_status_starts_reauth_at_once(hass: HomeAssistant, setup_entry, poll) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Rejected", status_code=403)

    await poll()

    assert len(reauth_flows(hass)) == 1


async def test_a_failed_token_refresh_at_setup_retries_then_starts_reauth(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, settle
) -> None:
    """The count survives a setup retry, which builds a new backend, so real reauth is only delayed."""
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Token refresh failed")
    entry = add_entry(data=method.entry_data)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert reauth_flows(hass) == []

    await hass.config_entries.async_reload(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1


async def test_a_failed_token_refresh_at_setup_then_success_loads(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, settle
) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Token refresh failed")
    entry = add_entry(data=method.entry_data)
    assert not await hass.config_entries.async_setup(entry.entry_id)

    stub.error = None
    await hass.config_entries.async_reload(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.LOADED
    assert reauth_flows(hass) == []

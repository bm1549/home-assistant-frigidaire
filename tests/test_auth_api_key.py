"""The API key sign-in module: validation, token persistence and when reauth starts."""

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


def test_api_key_is_the_last_menu_entry() -> None:
    assert list(METHODS)[-1] == "api_key"
    assert METHODS["api_key"] is api_key
    assert api_key.METHOD == "api_key"
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


async def test_rotation_by_a_backend_the_entry_no_longer_uses_is_not_saved(
    hass: HomeAssistant, setup_entry, settle, method
) -> None:
    """A request still in flight on the old backend after reauth must not undo the new tokens."""
    entry, stub = await setup_entry([LEGACY_AC])
    old_callback = stub.on_tokens
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], method.reauth_input)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    await settle()
    assert entry.data["refresh_token"] == "refresh-2"

    old_callback("access-OLD-rotated", "refresh-OLD-rotated")

    assert (entry.data["access_token"], entry.data["refresh_token"]) == ("access-2", "refresh-2")
    # The backend the entry uses now still saves its rotations.
    stub.rotate("access-3", "refresh-3")
    assert (entry.data["access_token"], entry.data["refresh_token"]) == ("access-3", "refresh-3")


async def test_adding_the_tokens_an_entry_holds_is_refused_before_any_call(
    hass: HomeAssistant, setup_entry, settle
) -> None:
    """Validating them would spend the entry's refresh token, and the rotated pair would be lost."""
    entry, stub = await setup_entry([LEGACY_AC])
    connects = stub.connect_count
    stub.rotate_on_connect = ("access-NEW", "refresh-NEW")

    result = await open_form(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {key: f" {entry.data[key]} " for key in api_key.CREDENTIAL_KEYS}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "credentials_in_use"}
    assert stub.connect_count == connects
    assert entry.data["refresh_token"] == "refresh-1"


async def test_reauth_refuses_the_tokens_another_entry_holds(
    hass: HomeAssistant, setup_entry, add_entry, method, settle
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    other = add_entry(data={**method.entry_data, "refresh_token": "refresh-other"})
    result = await entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**method.reauth_input, "refresh_token": "refresh-other"}
    )

    assert result["errors"] == {"base": "credentials_in_use"}
    assert other.data["refresh_token"] == "refresh-other"


async def test_reauth_may_reuse_the_entrys_own_tokens(hass: HomeAssistant, setup_entry, method, settle) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    result = await entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {key: entry.data[key] for key in api_key.CREDENTIAL_KEYS}
    )

    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"


async def test_reauth_form_names_the_account_email(hass: HomeAssistant, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    result = await entry.start_reauth_flow(hass)

    assert result["description_placeholders"]["username"] == "user@example.com"


# --- an AuthenticationError means reauth; a refresh that got no answer backs off ---


@pytest.mark.parametrize("status", [None, 400, 401, 403])
async def test_any_authentication_error_starts_reauth(hass: HomeAssistant, setup_entry, poll, status) -> None:
    """The library reports a refresh token the server refused, with or without a status, this way."""
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Rejected", status_code=status)

    await poll()

    flows = reauth_flows(hass)
    assert len(flows) == 1
    assert flows[0]["context"]["entry_id"] == entry.entry_id


# How the library reports a token refresh that got no answer: not a verdict on the tokens.
NO_ANSWER = "Could not refresh the Electrolux access token: ClientConnectorError, no HTTP status"


async def test_a_refresh_without_an_answer_backs_off_and_recovers_without_reauth(
    hass: HomeAssistant, setup_entry, poll
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException(NO_ANSWER)

    await poll()
    await poll(seconds=601)
    await poll(seconds=1201)
    assert reauth_flows(hass) == []
    assert not entry.runtime_data.last_update_success

    stub.error = None
    await poll(seconds=1801)

    assert entry.runtime_data.last_update_success
    assert entry.state is ConfigEntryState.LOADED
    assert reauth_flows(hass) == []


async def test_a_power_cut_with_an_expired_token_recovers_without_reauth(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, poll
) -> None:
    """Home Assistant starts before the network is back while the access token needs a refresh.

    Setup keeps retrying instead of asking for new tokens, and loads once the network returns.
    """
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException(NO_ANSWER)
    entry = add_entry(data=method.entry_data)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    await poll(seconds=6)  # Home Assistant's first setup retry, still offline
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert reauth_flows(hass) == []

    stub.error = None
    await poll(seconds=3600)

    assert entry.state is ConfigEntryState.LOADED
    assert reauth_flows(hass) == []


async def test_an_authentication_error_at_setup_starts_reauth(
    hass: HomeAssistant, frigidaire_stub, add_entry, method
) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Rejected")
    entry = add_entry(data=method.entry_data)

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1

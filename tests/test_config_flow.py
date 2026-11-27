"""User setup flow and the reauth flow started when credentials stop working.

The setup and reauth tests are written once and run for each sign-in method.
"""

import json
from pathlib import Path

import frigidaire
import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.frigidaire.auth import METHODS

DOMAIN = "frigidaire"
CREDENTIALS = {"username": "user@example.com", "password": "secret"}

every_method = pytest.mark.parametrize("auth_method", list(METHODS))


async def start_user_flow(hass: HomeAssistant, method: str = "password"):
    """Open the setup menu and pick a sign-in method, landing on its form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": method})


async def submit_setup(hass: HomeAssistant, method):
    """Pick the method from the menu and submit its form with the method's setup input."""
    result = await start_user_flow(hass, method.name)
    return await hass.config_entries.flow.async_configure(result["flow_id"], dict(method.setup_input))


async def start_reauth(hass: HomeAssistant, stub, poll, method) -> dict:
    """Make the next fetch fail with rejected credentials and return the reauth flow it starts."""
    stub.error = method.auth_error()
    await poll()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    return flows[0]


async def test_user_flow_starts_with_a_menu_of_sign_in_methods(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    # One option per sign-in method, in menu order (each method's own tests check its place).
    assert result["menu_options"] == list(METHODS)


@every_method
async def test_user_flow_creates_entry_with_per_device_options(
    hass: HomeAssistant, frigidaire_stub, method, settle, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC, DEHUMIDIFIER])

    result = await start_user_flow(hass, method.name)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == method.name

    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(method.setup_input))
    assert result["step_id"] == "device"
    assert result["description_placeholders"] == {"device_name": "Bedroom AC"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["description_placeholders"] == {"device_name": "Basement Dehumidifier"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"bucket_status": True})
    await settle()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == method.entry_data
    assert result["options"]["DH-1"]["bucket_status"] is True
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "user@example.com"
    assert stub.credentials == method.setup_input


@every_method
async def test_user_flow_unique_id_is_the_lowercased_account_email(
    hass: HomeAssistant, frigidaire_stub, method, settle, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.email = "User@Example.com"

    result = await submit_setup(hass, method)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await settle()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.config_entries.async_entries(DOMAIN)[0].unique_id == "user@example.com"


@every_method
async def test_user_flow_rejected_credentials_show_invalid_auth(
    hass: HomeAssistant, frigidaire_stub, method, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")

    result = await submit_setup(hass, method)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == method.name
    assert result["errors"] == {"base": "invalid_auth"}


# LoginError and its codes are the password method's login.
@pytest.mark.parametrize("auth_method", ["password"])
async def test_user_flow_rejected_login_without_a_credential_code_shows_invalid_auth(
    hass: HomeAssistant, frigidaire_stub, tmp_path
) -> None:
    """A Google-SSO-only account or an account mid-registration is a login problem to fix in the
    Frigidaire app, so the flow says so instead of 'cannot connect' (HA issues #72, #77)."""
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.LoginError("Failed to authenticate, sessionInfo was not in response")

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.parametrize("auth_method", ["password"])
async def test_transient_login_failure_during_a_poll_does_not_start_reauth(
    hass: HomeAssistant, setup_entry, poll
) -> None:
    """Only a credential rejection should prompt for a password; anything else keeps retrying."""
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.LoginError("Failed to authenticate, sessionInfo was not in response (errorCode=206001)")

    await poll()

    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    assert entry.state is ConfigEntryState.LOADED


@every_method
async def test_user_flow_api_failure_shows_cannot_connect(
    hass: HomeAssistant, frigidaire_stub, method, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)

    result = await submit_setup(hass, method)

    assert result["errors"] == {"base": "cannot_connect"}


@every_method
async def test_user_flow_without_appliances_shows_no_appliances(
    hass: HomeAssistant, frigidaire_stub, method, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([])

    result = await submit_setup(hass, method)

    assert result["errors"] == {"base": "no_appliances"}


@every_method
async def test_user_flow_aborts_for_an_already_configured_account(hass: HomeAssistant, setup_entry, method) -> None:
    await setup_entry([LEGACY_AC])

    # The same account, signed in again with other credentials.
    result = await start_user_flow(hass, method.name)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**method.setup_input, **method.reauth_input}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@every_method
async def test_rejected_credentials_during_a_poll_start_reauth(hass: HomeAssistant, setup_entry, poll, method) -> None:
    entry, stub = await setup_entry([LEGACY_AC])

    flow = await start_reauth(hass, stub, poll, method)

    assert flow["context"]["source"] == config_entries.SOURCE_REAUTH
    assert flow["context"]["entry_id"] == entry.entry_id
    assert flow["step_id"] == "reauth_confirm"


@every_method
async def test_reauth_asks_for_the_entry_methods_credentials(hass: HomeAssistant, setup_entry, poll, method) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    flow = await start_reauth(hass, stub, poll, method)

    result = await hass.config_entries.flow.async_configure(flow["flow_id"])

    assert result["step_id"] == "reauth_confirm"
    assert [str(key) for key in result["data_schema"].schema] == list(method.reauth_input)
    assert result["description_placeholders"]["username"] == "user@example.com"


@every_method
async def test_reauth_with_working_credentials_updates_and_reloads_the_entry(
    hass: HomeAssistant, setup_entry, poll, settle, method, caplog: pytest.LogCaptureFixture
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    flow = await start_reauth(hass, stub, poll, method)

    stub.error = None
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], dict(method.reauth_input))
    await settle()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {**method.entry_data, **method.reauth_input}
    assert entry.state is ConfigEntryState.LOADED
    # The reloaded entry signed in with the new credentials.
    assert stub.credentials == {**method.setup_input, **method.reauth_input}
    # Home Assistant 2026.12 stops reloading entries that also carry an update listener.
    assert "update listener" not in caplog.text


@every_method
async def test_reauth_with_wrong_credentials_shows_invalid_auth(hass: HomeAssistant, setup_entry, poll, method) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    flow = await start_reauth(hass, stub, poll, method)

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], dict(method.reauth_input))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == method.entry_data


# The flow's own check, for every method. With the real password backend this cannot happen (reauth
# asks only for the password and keeps the username, which is the account email); the fake reports
# its email independently. Narrow this to the methods whose new credentials can reach another account
# once one exists.
@every_method
async def test_reauth_with_another_accounts_credentials_aborts(
    hass: HomeAssistant, setup_entry, poll, settle, method
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    flow = await start_reauth(hass, stub, poll, method)

    stub.error = None
    stub.email = "someone-else@example.com"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], dict(method.reauth_input))
    await settle()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data == method.entry_data


EN_JSON = Path(__file__).resolve().parents[1] / "custom_components" / "frigidaire" / "translations" / "en.json"


@every_method
def test_each_method_has_its_menu_label_form_and_reauth_fields(auth_method) -> None:
    """The menu option, the method's form and its reauth fields are all labelled in en.json."""
    module = METHODS[auth_method]
    config = json.loads(EN_JSON.read_text())["config"]
    assert config["step"]["user"]["menu_options"][auth_method]
    assert set(config["step"][auth_method]["data"]) == {str(key) for key in module.SCHEMA.schema}
    assert {str(key) for key in module.REAUTH_SCHEMA.schema} <= set(config["step"]["reauth_confirm"]["data"])
    for reason in ("already_configured", "reauth_successful", "wrong_account"):
        assert config["abort"][reason]
    for error in ("cannot_connect", "invalid_auth", "no_appliances", "unknown"):
        assert config["error"][error]

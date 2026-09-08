"""User setup flow and the reauth flow started when credentials stop working."""

from datetime import timedelta

import frigidaire
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "frigidaire"
CREDENTIALS = {"username": "user@example.com", "password": "secret"}


async def start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_user_flow_creates_entry_with_per_device_options(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([LEGACY_AC, DEHUMIDIFIER])

    result = await start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["step_id"] == "device"
    assert result["description_placeholders"] == {"device_name": "Bedroom AC"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["description_placeholders"] == {"device_name": "Basement Dehumidifier"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"bucket_status": True})
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == CREDENTIALS
    assert result["options"]["DH-1"]["bucket_status"] is True
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "user@example.com"


async def test_user_flow_rejected_credentials_show_invalid_auth(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_api_failure_shows_cannot_connect(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_without_appliances_shows_no_appliances(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([])

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["errors"] == {"base": "no_appliances"}


async def test_user_flow_aborts_for_an_already_configured_account(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([LEGACY_AC])

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_rejected_credentials_during_a_poll_start_reauth(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == config_entries.SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == entry.entry_id
    assert flows[0]["step_id"] == "reauth_confirm"


async def test_reauth_with_a_working_password_updates_and_reloads_the_entry(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]

    stub.error = None
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"password": "new-secret"})
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"
    assert entry.state is ConfigEntryState.LOADED
    assert stub.password == "new-secret"


async def test_reauth_with_a_wrong_password_shows_invalid_auth(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)
    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"password": "still-wrong"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == "secret"

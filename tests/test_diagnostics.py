"""Diagnostics downloads carry the raw records with personal fields redacted."""

import copy
import json

import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.frigidaire.auth import METHODS

DOMAIN = "frigidaire"


@pytest.mark.parametrize("auth_method", list(METHODS))
async def test_config_entry_diagnostics(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry, method
) -> None:
    entry, stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["data"] == {
        "auth_method": method.name,
        **{key: "**REDACTED**" for key in method.setup_input},
    }
    assert diagnostics["auth_method"] == method.name
    assert diagnostics["live_updates"] is stub.supports_live_updates
    assert diagnostics["stream_connected"] is stub.supports_live_updates
    records = {a["raw"]["applianceData"]["applianceName"]: a for a in diagnostics["appliances"]}
    assert records["Bedroom AC"]["raw"]["applianceId"] == "**REDACTED**"
    assert records["Bedroom AC"]["raw"]["properties"]["reported"]["mode"] == "COOL"
    assert records["Bedroom AC"]["raw"]["connectionState"] == "Connected"
    assert records["Bedroom AC"]["parsed"]["destination"] == "AC"
    assert records["Bedroom AC"]["parsed"]["mode"] == "COOL"
    assert records["Basement Dehumidifier"]["parsed"]["destination"] == "DH"


async def test_config_entry_diagnostics_hide_appliance_ids_in_the_options(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    """Options are keyed by appliance id, which Electrolux builds from the serial number."""
    entry, _stub = await setup_entry(
        [LEGACY_AC, DEHUMIDIFIER], options={"DH-1": {"bucket_status": True}, "AC-LEGACY-1": {"ui_lock": True}}
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    # In the entry's options order, under placeholders.
    assert diagnostics["entry"]["options"] == {"appliance_0": {"bucket_status": True}, "appliance_1": {"ui_lock": True}}
    dumped = json.dumps(diagnostics)
    for appliance_id in ("DH-1", "AC-LEGACY-1"):
        assert appliance_id not in dumped


async def test_device_diagnostics_returns_only_that_appliance(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "DH-1"), entry.entry_id)
    assert device is not None

    diagnostics = await get_diagnostics_for_device(hass, hass_client, entry, device)

    assert diagnostics["raw"]["applianceData"]["applianceName"] == "Basement Dehumidifier"
    assert diagnostics["raw"]["applianceId"] == "**REDACTED**"
    assert diagnostics["parsed"]["target_humidity"] == 45


# An API key record, which carries the appliance info the official API returns.
API_KEY_AC = copy.deepcopy(LEGACY_AC)
API_KEY_AC["applianceData"]["applianceInfo"] = {
    "serialNumber": "SN-12345",
    "pnc": "950011234",
    "brand": "FRIGIDAIRE",
    "deviceType": "AIR_CONDITIONER",
    "model": "FHWW083WA1",
    "variant": "1",
    "colour": "WHITE",
}


@pytest.mark.parametrize("auth_method", ["api_key"])
async def test_api_key_entry_diagnostics_redact_the_key_tokens_and_serial(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    entry, stub = await setup_entry([API_KEY_AC])

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["data"] == {
        "auth_method": "api_key",
        "api_key": "**REDACTED**",
        "access_token": "**REDACTED**",
        "refresh_token": "**REDACTED**",
    }
    assert diagnostics["auth_method"] == "api_key"
    assert diagnostics["live_updates"] is True
    assert diagnostics["stream_connected"] is True
    info = diagnostics["appliances"][0]["raw"]["applianceData"]["applianceInfo"]
    assert info["serialNumber"] == "**REDACTED**"
    assert info["model"] == "FHWW083WA1"
    dumped = json.dumps(diagnostics)
    for secret in ("the-api-key", "access-1", "refresh-1", "SN-12345", "AC-LEGACY-1"):
        assert secret not in dumped


@pytest.mark.parametrize("auth_method", ["api_key"])
async def test_diagnostics_report_a_dropped_stream(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    entry.runtime_data._handle_stream_disconnect()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["stream_connected"] is False

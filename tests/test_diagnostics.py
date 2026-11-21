"""Diagnostics downloads carry the raw records with personal fields redacted."""

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
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["data"] == {
        "auth_method": method.name,
        **{key: "**REDACTED**" for key in method.setup_input},
    }
    records = {a["raw"]["applianceData"]["applianceName"]: a for a in diagnostics["appliances"]}
    assert records["Bedroom AC"]["raw"]["applianceId"] == "**REDACTED**"
    assert records["Bedroom AC"]["raw"]["properties"]["reported"]["mode"] == "COOL"
    assert records["Bedroom AC"]["raw"]["connectionState"] == "Connected"
    assert records["Bedroom AC"]["parsed"]["destination"] == "AC"
    assert records["Bedroom AC"]["parsed"]["mode"] == "COOL"
    assert records["Basement Dehumidifier"]["parsed"]["destination"] == "DH"


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


async def test_config_entry_diagnostics_keep_appliance_ids_out_of_options(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry
) -> None:
    options = {"AC-LEGACY-1": {"display_light": True}, "DH-1": {"bucket_status": True}}
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER], options=options)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["options"] == {
        "appliance_0": {"display_light": True},
        "appliance_1": {"bucket_status": True},
    }
    dumped = json.dumps(diagnostics)
    assert "AC-LEGACY-1" not in dumped
    assert "DH-1" not in dumped

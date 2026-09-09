"""Diagnostics downloads carry the raw records with personal fields redacted."""

from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

DOMAIN = "frigidaire"


async def test_config_entry_diagnostics(hass: HomeAssistant, hass_client: ClientSessionGenerator, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["data"] == {"username": "**REDACTED**", "password": "**REDACTED**"}
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

"""All appliance coordinators share one account-level request per cycle."""

from datetime import timedelta

import frigidaire
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import DEHUMIDIFIER, LEGACY_AC, TELICA_AC
from pytest_homeassistant_custom_component.common import async_fire_time_changed

THREE = [LEGACY_AC, TELICA_AC, DEHUMIDIFIER]


def climate_id(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-LEGACY-1")


async def test_setup_fetches_the_account_once(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)

    assert stub.raw_fetch_count == 1


async def test_each_poll_cycle_fetches_the_account_once(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert stub.raw_fetch_count == 2


async def test_every_appliance_sees_its_own_record(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry(THREE)

    registry = er.async_get(hass)
    assert hass.states.get(registry.async_get_entity_id("climate", "frigidaire", "AC-LEGACY-1")).state == "cool"
    assert hass.states.get(registry.async_get_entity_id("climate", "frigidaire", "AC-TELICA-1")).state == "fan_only"
    assert hass.states.get(registry.async_get_entity_id("humidifier", "frigidaire", "DH-1")).state == "on"


async def test_command_refresh_fetches_fresh_data(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["mode"] = "FANONLY"

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate_id(hass), "hvac_mode": "fan_only"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert stub.raw_fetch_count == 2


async def test_account_failure_marks_every_appliance_unavailable(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    stub.details_error = frigidaire.FrigidaireException("Request failed", status_code=429, error_code="cas_3403")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    registry = er.async_get(hass)
    for domain, unique_id in (("climate", "AC-LEGACY-1"), ("climate", "AC-TELICA-1"), ("humidifier", "DH-1")):
        assert hass.states.get(registry.async_get_entity_id(domain, "frigidaire", unique_id)).state == "unavailable"
    assert stub.raw_fetch_count == 2
    assert "Error communicating with Frigidaire (status=429, error=cas_3403)" in caplog.text

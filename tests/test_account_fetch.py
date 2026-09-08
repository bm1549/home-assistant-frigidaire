"""One account-level request per poll cycle feeds every entity."""

from datetime import timedelta

import frigidaire
import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, TELICA_AC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "frigidaire"
THREE = [LEGACY_AC, TELICA_AC, DEHUMIDIFIER]


def climate_id(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-LEGACY-1")


def state_of(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    return hass.states.get(er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)).state


async def poll(hass: HomeAssistant, seconds: int = 31) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_fetches_the_account_once(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)

    assert stub.fetch_count == 1


async def test_each_poll_cycle_fetches_the_account_once(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)

    await poll(hass)

    assert stub.fetch_count == 2


async def test_every_appliance_sees_its_own_record(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry(THREE)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "cool"
    assert state_of(hass, "climate", "AC-TELICA-1") == "fan_only"
    assert state_of(hass, "humidifier", "DH-1") == "on"


async def test_command_refresh_fetches_fresh_data(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry(THREE)
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["mode"] = "FANONLY"

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate_id(hass), "hvac_mode": "fan_only"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert stub.fetch_count == 2
    # Asserted on coordinator data, not the entity state: for OPTIMISTIC_WINDOW seconds
    # after a command the climate entity reports the optimistic mode, so an entity-state
    # assertion would pass even if the refreshed record never reached the coordinator.
    assert entry.runtime_data.data["AC-LEGACY-1"].mode is frigidaire.Mode.FAN


async def test_account_failure_marks_every_appliance_unavailable(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    stub.error = frigidaire.SessionCapError("Request failed", status_code=429, error_code="cas_3403")

    await poll(hass)

    for domain, unique_id in (("climate", "AC-LEGACY-1"), ("climate", "AC-TELICA-1"), ("humidifier", "DH-1")):
        assert state_of(hass, domain, unique_id) == "unavailable"
    assert stub.fetch_count == 2
    assert "Rate limited by Frigidaire (status=429, error=cas_3403)" in caplog.text


async def test_failed_poll_backs_off_before_the_next_attempt(hass: HomeAssistant, setup_entry) -> None:
    """Hammering a flaky auth server with re-authentication is what trips the session cap."""
    _entry, stub = await setup_entry(THREE)
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)

    await poll(hass)  # fails: 2 fetches so far
    stub.error = None
    # Each fire is relative to real now: the failed poll rescheduled itself 60s out.
    await poll(hass, seconds=45)
    assert stub.fetch_count == 2

    await poll(hass, seconds=61)
    assert stub.fetch_count == 3
    assert state_of(hass, "climate", "AC-LEGACY-1") == "cool"


async def test_one_empty_record_does_not_affect_the_others(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)
    del stub.records["AC-LEGACY-1"]["properties"]
    stub.records["AC-TELICA-1"]["properties"]["reported"]["mode"] = "cool"
    stub.records["DH-1"]["properties"]["reported"]["targetHumidity"] = 42

    await poll(hass)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "unavailable"
    assert state_of(hass, "climate", "AC-TELICA-1") == "cool"
    humidifier = hass.states.get(er.async_get(hass).async_get_entity_id("humidifier", DOMAIN, "DH-1"))
    assert humidifier.attributes["humidity"] == 42
    assert stub.fetch_count == 2


async def test_appliance_missing_from_the_account_goes_unavailable(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    del stub.records["AC-TELICA-1"]

    await poll(hass)

    assert state_of(hass, "climate", "AC-TELICA-1") == "unavailable"
    assert state_of(hass, "climate", "AC-LEGACY-1") == "cool"
    assert state_of(hass, "humidifier", "DH-1") == "on"
    assert "Office AC (AC-TELICA-1) is no longer on the account" in caplog.text


async def test_appliance_returning_to_the_account_recovers(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(THREE)
    record = stub.records.pop("AC-TELICA-1")
    await poll(hass)
    assert state_of(hass, "climate", "AC-TELICA-1") == "unavailable"

    stub.records["AC-TELICA-1"] = record
    await poll(hass)

    assert state_of(hass, "climate", "AC-TELICA-1") == "fan_only"


async def test_record_without_an_appliance_id_is_skipped(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    stub.records["no-id"] = {"applianceData": {"modelName": "Mystery", "applianceName": "Mystery"}}
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["mode"] = "FANONLY"

    await poll(hass)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "fan_only"
    assert "Unexpected error" not in caplog.text


async def test_renamed_appliance_keeps_its_identity(hass: HomeAssistant, setup_entry) -> None:
    """Snapshots are fresh each poll, so a rename shows up without a reload."""
    entry, stub = await setup_entry(THREE)
    stub.records["AC-LEGACY-1"]["applianceData"]["applianceName"] = "Guest Room AC"

    await poll(hass)

    assert entry.runtime_data.data["AC-LEGACY-1"].nickname == "Guest Room AC"
    assert state_of(hass, "climate", "AC-LEGACY-1") == "cool"

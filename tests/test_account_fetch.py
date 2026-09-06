"""All appliance coordinators share one account-level request per cycle."""

from collections.abc import Callable
from datetime import timedelta

import frigidaire
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import DEHUMIDIFIER, LEGACY_AC, TELICA_AC
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "frigidaire"
THREE = [LEGACY_AC, TELICA_AC, DEHUMIDIFIER]


def climate_id(hass: HomeAssistant) -> str:
    return er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-LEGACY-1")


def state_of(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    return hass.states.get(er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)).state


def count_apply_record(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, int]:
    """Wrap every appliance coordinator's apply_record and return the live call counts."""
    calls: dict[str, int] = {}

    def wrap(appliance_id: str, original: Callable[[dict], dict]) -> Callable[[dict], dict]:
        def counted(record: dict) -> dict:
            calls[appliance_id] += 1
            return original(record)

        return counted

    for appliance_id, coordinator in hass.data[DOMAIN][entry.entry_id]["coordinators"].items():
        calls[appliance_id] = 0
        coordinator.apply_record = wrap(appliance_id, coordinator.apply_record)
    return calls


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
    assert hass.states.get(climate_id(hass)).state == "fan_only"


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


async def test_command_refresh_applies_the_commanded_record_exactly_once(hass: HomeAssistant, setup_entry) -> None:
    """The commanded coordinator is skipped by the push and applies its own record.

    Pushing to it mid-refresh would call async_set_updated_data while its own refresh is
    still in flight, and that cancels the debouncer — dropping any refresh queued behind
    the one in progress (a script setting hvac_mode and then temperature).
    """
    entry, _stub = await setup_entry(THREE)
    calls = count_apply_record(hass, entry)

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate_id(hass), "hvac_mode": "fan_only"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert calls == {"AC-LEGACY-1": 1, "AC-TELICA-1": 1, "DH-1": 1}


async def test_one_malformed_record_does_not_affect_the_others(hass: HomeAssistant, setup_entry) -> None:
    """The malformed record is the *first* one pushed, and the rest still get fresh values.

    Malforming the last appliance would pass even if the push loop aborted on the error.
    """
    _entry, stub = await setup_entry(THREE)
    del stub.records["AC-LEGACY-1"]["properties"]
    stub.records["AC-TELICA-1"]["properties"]["reported"]["mode"] = "cool"
    stub.records["DH-1"]["properties"]["reported"]["targetHumidity"] = 42

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "unavailable"
    assert state_of(hass, "climate", "AC-TELICA-1") == "cool"
    humidifier = hass.states.get(er.async_get(hass).async_get_entity_id("humidifier", DOMAIN, "DH-1"))
    assert humidifier.attributes["humidity"] == 42
    assert stub.raw_fetch_count == 2


async def test_appliance_missing_from_the_account_goes_unavailable(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    del stub.records["AC-TELICA-1"]

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "climate", "AC-TELICA-1") == "unavailable"
    assert state_of(hass, "climate", "AC-LEGACY-1") == "cool"
    assert state_of(hass, "humidifier", "DH-1") == "on"
    assert "not found in list of appliances" in caplog.text


async def test_empty_reported_properties_fail_that_appliance_only(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry(THREE)
    stub.records["AC-LEGACY-1"]["properties"]["reported"] = {}
    # A fresh value on an appliance behind the failing one, so the assertion below proves
    # the push kept going rather than just reading the state left over from setup.
    stub.records["AC-TELICA-1"]["properties"]["reported"]["mode"] = "cool"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "unavailable"
    assert state_of(hass, "climate", "AC-TELICA-1") == "cool"
    assert "no reported properties" in caplog.text


async def test_record_without_an_appliance_id_is_skipped(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    """An unidentifiable record must not blow up the account fetch.

    Indexing it with record["applianceId"] would raise KeyError past the except clause, so
    the backoff would never run and the poll would fail with a traceback every cycle.
    """
    _entry, stub = await setup_entry(THREE)
    stub.records["no-id"] = {"applianceData": {"modelName": "Mystery", "applianceName": "Mystery"}}
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["mode"] = "FANONLY"
    stub.records["AC-TELICA-1"]["properties"]["reported"]["mode"] = "cool"
    stub.records["DH-1"]["properties"]["reported"]["targetHumidity"] = 42

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "climate", "AC-LEGACY-1") == "fan_only"
    assert state_of(hass, "climate", "AC-TELICA-1") == "cool"
    humidifier = hass.states.get(er.async_get(hass).async_get_entity_id("humidifier", DOMAIN, "DH-1"))
    assert humidifier.attributes["humidity"] == 42
    assert "Unexpected error" not in caplog.text

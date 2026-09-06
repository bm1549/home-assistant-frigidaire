"""Config-entry setup and teardown against stubbed appliances."""

from datetime import timedelta

import frigidaire
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import DEHUMIDIFIER, LEGACY_AC, with_reported
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "frigidaire"


def entity_id_for(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


async def test_setup_creates_expected_entities_for_each_appliance(hass: HomeAssistant, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])

    assert entry.state is ConfigEntryState.LOADED
    assert entity_id_for(hass, "climate", "AC-LEGACY-1") is not None
    assert entity_id_for(hass, "number", "AC-LEGACY-1_timer_on") is not None
    assert entity_id_for(hass, "number", "AC-LEGACY-1_timer_off") is not None
    assert entity_id_for(hass, "humidifier", "DH-1") is not None
    # Connectivity is created for every appliance that reports connectionState, and the
    # dehumidifier's reported sensorHumidity gets a humidity sensor; with no options enabled
    # and no temperature on the dehumidifier, nothing else appears.
    assert entity_id_for(hass, "binary_sensor", "AC-LEGACY-1_connectivity") is not None
    assert entity_id_for(hass, "binary_sensor", "DH-1_connectivity") is not None
    assert entity_id_for(hass, "sensor", "DH-1_humidity") is not None
    registry = er.async_get(hass)
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 7


async def test_dehumidifier_reporting_temperature_gets_temperature_sensor(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, ambientTemperatureF=68, temperatureRepresentation="FAHRENHEIT")])

    sensor_id = entity_id_for(hass, "sensor", "DH-1_temperature")
    assert sensor_id is not None
    assert hass.states.get(sensor_id).state == "68"


async def test_unload_entry_cleans_up(hass: HomeAssistant, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_session_cap_during_setup_reports_rate_limit(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.appliances_error = frigidaire.FrigidaireException("Request failed", status_code=429, error_code="cas_3403")
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "user@example.com", "password": "secret"}, unique_id="user@example.com"
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Rate limited by Frigidaire. Will retry automatically."


async def test_other_api_failure_during_setup_reports_status(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.appliances_error = frigidaire.FrigidaireException("Request failed", status_code=503)
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "user@example.com", "password": "secret"}, unique_id="user@example.com"
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Frigidaire error during setup (status=503): Request failed"


async def test_record_without_properties_fails_the_poll(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed record must fail the poll, not succeed with empty data.

    Empty data leaves the climate entity's temperature_unit with nothing to map, and Home
    Assistant reads capability attributes before it checks availability, so the state write
    would raise and freeze the entity at its last value on every poll.
    """
    _entry, stub = await setup_entry([LEGACY_AC])
    del stub.records["AC-LEGACY-1"]["properties"]

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(entity_id_for(hass, "climate", "AC-LEGACY-1")).state == "unavailable"
    assert "no reported properties" in caplog.text

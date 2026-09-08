"""Config-entry setup and teardown against a fake client."""

import os

import frigidaire
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, with_reported
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "frigidaire"


def entity_id_for(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "user@example.com", "password": "secret"}, unique_id="user@example.com"
    )
    entry.add_to_hass(hass)
    return entry


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


async def test_session_is_persisted_per_entry(hass: HomeAssistant, setup_entry, tmp_path) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    assert os.path.exists(tmp_path / f"frigidaire-{entry.entry_id}.json")


async def test_session_cap_during_setup_reports_rate_limit(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.SessionCapError("Request failed", status_code=429, error_code="cas_3403")
    entry = make_entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Rate limited by Frigidaire (status=429, error=cas_3403); will retry automatically"


async def test_other_api_failure_during_setup_reports_status(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)
    entry = make_entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Error communicating with Frigidaire (status=503): Request failed"


async def test_rejected_credentials_during_setup_start_reauth(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.AuthenticationError("Failed to authenticate")
    entry = make_entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_record_without_properties_makes_that_entity_unavailable(hass: HomeAssistant, setup_entry) -> None:
    """An appliance with nothing reported has no state to show; it must not freeze on stale values."""
    entry, stub = await setup_entry([LEGACY_AC])
    del stub.records["AC-LEGACY-1"]["properties"]

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(entity_id_for(hass, "climate", "AC-LEGACY-1")).state == "unavailable"


async def test_dehumidifier_reporting_timers_gets_timer_entities(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, startTime=-1, stopTime=1800)])

    on_timer = entity_id_for(hass, "number", "DH-1_timer_on")
    off_timer = entity_id_for(hass, "number", "DH-1_timer_off")
    assert on_timer is not None and off_timer is not None
    assert hass.states.get(on_timer).state == "0"  # -1 means not set; the unit is running anyway
    assert hass.states.get(off_timer).state == "1800"


async def test_dehumidifier_without_timers_gets_none(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER])

    assert entity_id_for(hass, "number", "DH-1_timer_on") is None

"""Config-entry setup and teardown against a fake client."""

import os
from unittest.mock import patch

import frigidaire
import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, with_reported
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frigidaire.auth import METHODS

DOMAIN = "frigidaire"


def entity_id_for(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


CREDENTIALS = {"username": "user@example.com", "password": "secret"}

every_method = pytest.mark.parametrize("auth_method", list(METHODS))


def make_entry(hass: HomeAssistant, *, minor_version: int = 2, data: dict | None = None, **kwargs) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=kwargs.pop("version", 1),
        minor_version=minor_version,
        data={"auth_method": "password", **CREDENTIALS} if data is None else data,
        unique_id="user@example.com",
        **kwargs,
    )
    entry.add_to_hass(hass)
    return entry


@every_method
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


@every_method
async def test_unload_entry_cleans_up(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.NOT_LOADED


# Session files, the session cap and the legacy migration are the password method's.
@pytest.mark.parametrize("auth_method", ["password"])
async def test_session_is_persisted_per_entry(hass: HomeAssistant, setup_entry, tmp_path) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    assert os.path.exists(tmp_path / f"frigidaire-{entry.entry_id}.json")


@pytest.mark.parametrize("auth_method", ["password"])
async def test_session_cap_during_setup_reports_rate_limit(
    hass: HomeAssistant, frigidaire_stub, tmp_path, settle
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.SessionCapError("Request failed", status_code=429, error_code="cas_3403")
    entry = make_entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Rate limited by Frigidaire (status=429, error=cas_3403); will retry automatically"


@every_method
async def test_other_api_failure_during_setup_reports_status(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, tmp_path, settle
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = frigidaire.FrigidaireException("Request failed", status_code=503)
    entry = add_entry(data=method.entry_data)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Error communicating with Frigidaire (status=503): Request failed"


@every_method
async def test_rejected_credentials_during_setup_start_reauth(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, tmp_path, settle
) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    stub.error = method.auth_error()
    entry = add_entry(data=method.entry_data)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_record_without_properties_makes_that_entity_unavailable(
    hass: HomeAssistant, setup_entry, settle
) -> None:
    """An appliance with nothing reported has no state to show; it must not freeze on stale values."""
    entry, stub = await setup_entry([LEGACY_AC])
    del stub.records["AC-LEGACY-1"]["properties"]

    await entry.runtime_data.async_refresh()
    await settle()

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


@pytest.mark.parametrize("auth_method", ["password"])
async def test_minor_version_1_entry_migrates_to_the_password_method(
    hass: HomeAssistant, frigidaire_stub, tmp_path, settle
) -> None:
    """Entries from before the sign-in menu signed in with a password; upgrading changes nothing else."""
    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([LEGACY_AC, DEHUMIDIFIER])
    options = {"DH-1": {"bucket_status": True}}
    entry = make_entry(hass, minor_version=1, data=dict(CREDENTIALS), options=options)
    # An entity registered by the previous version must keep its entity id.
    registry = er.async_get(hass)
    before = registry.async_get_or_create("climate", DOMAIN, "AC-LEGACY-1", config_entry=entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (1, 2)
    assert entry.data == {"auth_method": "password", **CREDENTIALS}
    assert entry.options == options
    assert entry.unique_id == "user@example.com"
    assert entity_id_for(hass, "climate", "AC-LEGACY-1") == before.entity_id
    assert entity_id_for(hass, "binary_sensor", "DH-1_bucket_status") is not None


async def test_migration_leaves_the_session_file_alone(hass: HomeAssistant, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    entry = make_entry(hass, minor_version=1, data=dict(CREDENTIALS))
    session_file = tmp_path / f"frigidaire-{entry.entry_id}.json"
    contents = '{"session_key": "kept", "regional_base_url": "https://kept.invalid"}'
    session_file.write_text(contents)

    assert await entry.async_migrate(hass)

    assert entry.minor_version == 2
    assert entry.data == {"auth_method": "password", **CREDENTIALS}
    assert session_file.read_text() == contents


async def test_current_entry_is_not_migrated_again(hass: HomeAssistant, setup_entry, method) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    assert entry.minor_version == 2
    assert entry.data == method.entry_data


async def test_entry_from_a_newer_major_version_is_refused(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([LEGACY_AC])
    entry = make_entry(hass, version=2, minor_version=1)

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.data == {"auth_method": "password", **CREDENTIALS}


async def test_unknown_sign_in_method_fails_setup(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)
    stub = frigidaire_stub([LEGACY_AC])
    entry = make_entry(hass, data={"auth_method": "carrier_pigeon"})

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason == "The sign-in method 'carrier_pigeon' is not available; delete this entry and add it again"
    assert stub.connect_count == 0


@every_method
async def test_unload_closes_the_backend(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    assert not stub.closed

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert stub.closed


@pytest.mark.parametrize("auth_method", ["password"])
async def test_removing_the_entry_deletes_its_session_file(hass: HomeAssistant, setup_entry, tmp_path, settle) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])
    session_file = tmp_path / f"frigidaire-{entry.entry_id}.json"
    assert os.path.exists(session_file)

    await hass.config_entries.async_remove(entry.entry_id)
    await settle()

    assert not os.path.exists(session_file)


@every_method
async def test_removing_the_entry_calls_its_methods_cleanup(hass: HomeAssistant, setup_entry, settle, method) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    with patch(f"custom_components.frigidaire.auth.{method.name}.async_remove") as remove:
        await hass.config_entries.async_remove(entry.entry_id)
        await settle()

    remove.assert_awaited_once()
    assert remove.await_args.args[1].entry_id == entry.entry_id
    assert hass.config_entries.async_entries(DOMAIN) == []

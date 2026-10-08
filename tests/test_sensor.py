"""Automatically created sensors for reported details."""

from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, TELICA_AC, with_reported
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory


def sensor_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", "frigidaire", unique_id)


async def test_telica_gets_humidity_and_pm25_sensors(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([TELICA_AC])

    humidity = sensor_id(hass, "AC-TELICA-1_humidity")
    pm25 = sensor_id(hass, "AC-TELICA-1_pm25")
    assert humidity is not None and pm25 is not None
    assert hass.states.get(humidity).state == "86"
    assert hass.states.get(pm25).state == "2"
    assert sensor_id(hass, "AC-TELICA-1_pm10") is None


async def test_wifi_signal_is_registered_but_disabled_by_default(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([TELICA_AC])

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", "frigidaire", "AC-TELICA-1_wifi_signal")
    assert entity_id is not None
    assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_legacy_ac_gets_no_detail_sensors(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([LEGACY_AC])

    for key in ("humidity", "pm25", "wifi_signal"):
        assert sensor_id(hass, f"AC-LEGACY-1_{key}") is None


async def test_dehumidifier_humidity_sensor_matches_attribute(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER])

    humidity = sensor_id(hass, "DH-1_humidity")
    assert humidity is not None
    assert hass.states.get(humidity).state == "55"


async def test_placeholder_values_do_not_create_sensors(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(TELICA_AC, sensorHumidity=101, pm25=-1, networkInterface={"rssi": 0})])

    for key in ("humidity", "pm25", "wifi_signal"):
        assert sensor_id(hass, f"AC-TELICA-1_{key}") is None


async def test_runtime_counters_are_diagnostic_and_disabled_by_default(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, compressorRuntime=1323904, totalRuntime=3613076)])

    registry = er.async_get(hass)
    for key in ("compressor_runtime", "total_runtime"):
        entity_id = sensor_id(hass, f"DH-1_{key}")
        assert entity_id is not None
        entry = registry.async_get(entity_id)
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_no_runtime_sensors_without_the_readings(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER])

    assert sensor_id(hass, "DH-1_compressor_runtime") is None
    assert sensor_id(hass, "DH-1_total_runtime") is None

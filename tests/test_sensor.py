"""Automatically created sensors for reported details."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from payloads import DEHUMIDIFIER, LEGACY_AC, TELICA_AC, with_reported


def sensor_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", "frigidaire", unique_id)


async def test_telica_gets_humidity_and_pm25_sensors(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([TELICA_AC])

    humidity = sensor_id(hass, "AC-TELICA-1_humidity")
    pm25 = sensor_id(hass, "AC-TELICA-1_pm25")
    assert humidity is not None and pm25 is not None
    # value_fn coerces to float, so the reported integers surface as "86.0" / "2.0".
    assert hass.states.get(humidity).state == "86.0"
    assert hass.states.get(pm25).state == "2.0"
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
    assert hass.states.get(humidity).state == "55.0"


async def test_placeholder_values_do_not_create_sensors(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(TELICA_AC, sensorHumidity=101, pm25=-1, networkInterface={"rssi": 0})])

    for key in ("humidity", "pm25", "wifi_signal"):
        assert sensor_id(hass, f"AC-TELICA-1_{key}") is None

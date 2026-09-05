"""Config-entry setup and teardown against stubbed appliances."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from payloads import DEHUMIDIFIER, LEGACY_AC, with_reported

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
    # No options enabled and the dehumidifier reports no temperature: nothing else appears.
    registry = er.async_get(hass)
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 4


async def test_dehumidifier_reporting_temperature_gets_temperature_sensor(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, ambientTemperatureF=68, temperatureRepresentation="FAHRENHEIT")])

    sensor_id = entity_id_for(hass, "sensor", "DH-1_temperature")
    assert sensor_id is not None
    assert hass.states.get(sensor_id).state == "68"


async def test_unload_entry_cleans_up(hass: HomeAssistant, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC])

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})

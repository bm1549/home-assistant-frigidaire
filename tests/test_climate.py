"""Climate entity behaviour for air conditioners."""

from datetime import timedelta

import frigidaire
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import LEGACY_AC, TELICA_AC, with_reported
from pytest_homeassistant_custom_component.common import async_fire_time_changed

OFF_AC = with_reported(LEGACY_AC, applianceState="OFF", mode="OFF")


def climate_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-LEGACY-1")
    assert entity_id is not None
    return entity_id


async def set_hvac_mode(hass: HomeAssistant, entity_id: str, hvac_mode: str) -> None:
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": hvac_mode}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_running_cool_unit_reports_cool_and_cooling(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([LEGACY_AC])

    state = hass.states.get(climate_id(hass))
    assert state.state == "cool"
    assert state.attributes["hvac_action"] == "cooling"
    assert state.attributes["current_temperature"] == 75
    assert state.attributes["temperature"] == 72
    assert state.attributes["fan_mode"] == "auto"
    assert state.attributes["swing_mode"] == "off"
    assert state.attributes["preset_mode"] == "none"


async def test_powered_off_unit_reports_off(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([OFF_AC])

    state = hass.states.get(climate_id(hass))
    assert state.state == "off"
    assert state.attributes["hvac_action"] == "off"


async def test_set_hvac_mode_on_running_unit_always_sends_power_then_mode(hass: HomeAssistant, setup_entry) -> None:
    """The cloud reports desired state, so RUNNING may be stale; power-on must not be skipped."""
    _entry, stub = await setup_entry([LEGACY_AC])

    await set_hvac_mode(hass, climate_id(hass), "fan_only")

    assert stub.commands == [("executeCommand", frigidaire.Power.ON), ("mode", frigidaire.Mode.FAN)]


async def test_set_hvac_mode_from_off_sends_power_mode_then_setpoint(hass: HomeAssistant, setup_entry) -> None:
    """The setpoint goes last: engaging the mode restores the appliance default and wipes an earlier value."""
    _entry, stub = await setup_entry([OFF_AC])

    await set_hvac_mode(hass, climate_id(hass), "cool")

    assert stub.commands == [
        ("executeCommand", frigidaire.Power.ON),
        ("mode", frigidaire.Mode.COOL),
        ("temperatureRepresentation", frigidaire.Unit.FAHRENHEIT),
        ("targetTemperatureF", 72),
    ]


async def test_turn_off_sends_mode_off(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])

    await set_hvac_mode(hass, climate_id(hass), "off")

    assert stub.commands == [("mode", frigidaire.Mode.OFF)]


async def test_failed_poll_marks_climate_unavailable_and_logs(
    hass: HomeAssistant, setup_entry, caplog: pytest.LogCaptureFixture
) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.details_error = frigidaire.FrigidaireException("Request failed", status_code=429, error_code="cas_3403")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(climate_id(hass)).state == "unavailable"
    assert "Error communicating with Frigidaire (status=429, error=cas_3403)" in caplog.text


async def test_hvac_action_prefers_reported_mode_state(hass: HomeAssistant, setup_entry) -> None:
    """In eco the requested mode says nothing about what the unit is doing; modeState does."""
    await setup_entry([with_reported(TELICA_AC, mode="eco", modeState="cool")])

    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-TELICA-1")
    state = hass.states.get(entity_id)
    assert state.state == "auto"
    assert state.attributes["hvac_action"] == "cooling"


async def test_hvac_action_fan_from_mode_state(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(TELICA_AC, mode="eco", modeState="fanOnly")])

    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-TELICA-1")
    assert hass.states.get(entity_id).attributes["hvac_action"] == "fan"


async def test_hvac_action_falls_back_to_mode_when_mode_state_absent(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(LEGACY_AC, mode="FANONLY")])

    assert hass.states.get(climate_id(hass)).attributes["hvac_action"] == "fan"


async def test_mode_state_overrides_a_concrete_requested_mode(hass: HomeAssistant, setup_entry) -> None:
    """modeState wins even when the requested mode is itself an activity, not just in eco."""
    await setup_entry([with_reported(TELICA_AC, mode="cool", modeState="fanOnly")])

    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-TELICA-1")
    assert hass.states.get(entity_id).attributes["hvac_action"] == "fan"


async def test_hvac_action_falls_back_to_drying_for_dry_mode(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(LEGACY_AC, mode="DRY")])

    assert hass.states.get(climate_id(hass)).attributes["hvac_action"] == "drying"

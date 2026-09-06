"""Opt-in temperature-based compressor estimate."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import LEGACY_AC, TELICA_AC, with_reported
from pytest_homeassistant_custom_component.common import async_fire_time_changed

ESTIMATE_ON = {"AC-LEGACY-1": {"compressor": True, "cool_hysteresis": 0.0, "compressor_off_delay": 0}}


def climate_state(hass: HomeAssistant, unique_id: str):
    return hass.states.get(er.async_get(hass).async_get_entity_id("climate", "frigidaire", unique_id))


def estimate_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("binary_sensor", "frigidaire", f"{unique_id}_compressor")


async def test_option_off_changes_nothing(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(LEGACY_AC, ambientTemperatureF=70)])

    assert climate_state(hass, "AC-LEGACY-1").attributes["hvac_action"] == "cooling"
    assert estimate_id(hass, "AC-LEGACY-1") is None


async def test_room_above_target_estimates_running(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([LEGACY_AC], options=ESTIMATE_ON)  # ambient 75 > target 72

    assert hass.states.get(estimate_id(hass, "AC-LEGACY-1")).state == "on"
    assert climate_state(hass, "AC-LEGACY-1").attributes["hvac_action"] == "cooling"


async def test_room_below_target_estimates_idle_after_off_delay(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([LEGACY_AC], options=ESTIMATE_ON)
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["ambientTemperatureF"] = 70

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(estimate_id(hass, "AC-LEGACY-1")).state == "off"
    assert climate_state(hass, "AC-LEGACY-1").attributes["hvac_action"] == "idle"


async def test_fan_only_beats_estimate(hass: HomeAssistant, setup_entry) -> None:
    """FAN_ONLY is checked before the estimate, so fan mode never reports idle."""
    await setup_entry([with_reported(LEGACY_AC, mode="FANONLY", ambientTemperatureF=70)], options=ESTIMATE_ON)

    assert hass.states.get(estimate_id(hass, "AC-LEGACY-1")).state == "off"
    assert climate_state(hass, "AC-LEGACY-1").attributes["hvac_action"] == "fan"


async def test_estimate_beats_dry(hass: HomeAssistant, setup_entry) -> None:
    """The estimate is checked before DRY, so a satisfied dry cycle reports idle, not drying."""
    await setup_entry([with_reported(LEGACY_AC, mode="DRY", ambientTemperatureF=70)], options=ESTIMATE_ON)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(estimate_id(hass, "AC-LEGACY-1")).state == "off"
    assert climate_state(hass, "AC-LEGACY-1").attributes["hvac_action"] == "idle"


async def test_reported_mode_state_beats_estimate(hass: HomeAssistant, setup_entry) -> None:
    options = {"AC-TELICA-1": {"compressor": True, "cool_hysteresis": 0.0, "compressor_off_delay": 0}}
    await setup_entry(
        [with_reported(TELICA_AC, mode="cool", modeState="cool", ambientTemperatureF=55)], options=options
    )

    assert hass.states.get(estimate_id(hass, "AC-TELICA-1")).state == "off"
    assert climate_state(hass, "AC-TELICA-1").attributes["hvac_action"] == "cooling"

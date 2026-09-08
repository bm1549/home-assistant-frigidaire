"""Switch entity behaviour for opt-in dehumidifier/AC switches."""

from frigidaire.testing import DEHUMIDIFIER, with_reported
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

ALL_SWITCHES_ENABLED = {"DH-1": {"display_light": True, "clean_air_mode": True, "ui_lock": True}}


def display_light_id(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("switch", "frigidaire", "DH-1_display_light")


def ionizer_id(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("switch", "frigidaire", "DH-1_clean_air_mode")


def child_lock_id(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("switch", "frigidaire", "DH-1_ui_lock")


async def turn_on(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


async def turn_off(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_display_light_reports_on_for_display_light_1(hass: HomeAssistant, setup_entry) -> None:
    """DISPLAY_LIGHT_1 is what real appliances report; this is the value the fix must accept."""
    await setup_entry([DEHUMIDIFIER], options=ALL_SWITCHES_ENABLED)

    assert hass.states.get(display_light_id(hass)).state == "on"


async def test_display_light_reports_off_for_display_light_0(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, displayLight="DISPLAY_LIGHT_0")], options=ALL_SWITCHES_ENABLED)

    assert hass.states.get(display_light_id(hass)).state == "off"


async def test_display_light_turn_on_sends_display_light_1(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry(
        [with_reported(DEHUMIDIFIER, displayLight="DISPLAY_LIGHT_0")], options=ALL_SWITCHES_ENABLED
    )

    await turn_on(hass, display_light_id(hass))

    assert stub.commands == [("displayLight", "DISPLAY_LIGHT_1")]


async def test_display_light_turn_off_sends_display_light_0(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([DEHUMIDIFIER], options=ALL_SWITCHES_ENABLED)

    await turn_off(hass, display_light_id(hass))

    assert stub.commands == [("displayLight", "DISPLAY_LIGHT_0")]


async def test_ionizer_reports_on_and_off(hass: HomeAssistant, setup_entry) -> None:
    """Regression guard: cleanAirMode is genuinely ON/OFF and must keep working after the shared is_on change."""
    await setup_entry([with_reported(DEHUMIDIFIER, cleanAirMode="ON")], options=ALL_SWITCHES_ENABLED)

    assert hass.states.get(ionizer_id(hass)).state == "on"


async def test_ionizer_reports_off(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER], options=ALL_SWITCHES_ENABLED)

    assert hass.states.get(ionizer_id(hass)).state == "off"


async def test_child_lock_boolean_switch_still_works(hass: HomeAssistant, setup_entry) -> None:
    """Regression guard: uiLockMode is a bool, not a string, and must keep working after the shared is_on change."""
    _entry, stub = await setup_entry([with_reported(DEHUMIDIFIER, uiLockMode=True)], options=ALL_SWITCHES_ENABLED)

    assert hass.states.get(child_lock_id(hass)).state == "on"

    await turn_off(hass, child_lock_id(hass))

    assert stub.commands == [("uiLockMode", False)]

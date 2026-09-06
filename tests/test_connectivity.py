"""Connectivity binary sensor derived from the appliance record's connectionState."""

import copy
from datetime import timedelta

import frigidaire
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from payloads import LEGACY_AC
from pytest_homeassistant_custom_component.common import async_fire_time_changed


def connectivity_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("binary_sensor", "frigidaire", "AC-LEGACY-1_connectivity")
    assert entity_id is not None
    return entity_id


async def test_connected_appliance_reports_on_with_state_attribute(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([LEGACY_AC])

    state = hass.states.get(connectivity_id(hass))
    assert state.state == "on"
    assert state.attributes["connection_state"] == "CONNECTED"


async def test_disconnected_appliance_reports_off(hass: HomeAssistant, setup_entry) -> None:
    record = copy.deepcopy(LEGACY_AC)
    record["connectionState"] = "Disconnected"
    await setup_entry([record])

    assert hass.states.get(connectivity_id(hass)).state == "off"


async def test_record_without_connection_state_creates_no_sensor(hass: HomeAssistant, setup_entry) -> None:
    record = copy.deepcopy(LEGACY_AC)
    del record["connectionState"]
    await setup_entry([record])

    assert er.async_get(hass).async_get_entity_id("binary_sensor", "frigidaire", "AC-LEGACY-1_connectivity") is None


async def test_failed_poll_makes_connectivity_unavailable(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.details_error = frigidaire.FrigidaireException("Request failed", status_code=503)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()

    assert hass.states.get(connectivity_id(hass)).state == "unavailable"

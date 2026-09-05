"""Humidifier entity behaviour for dehumidifiers."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from payloads import DEHUMIDIFIER, with_reported


def humidifier_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("humidifier", "frigidaire", "DH-1")
    assert entity_id is not None
    return entity_id


async def test_running_dehumidifier_state_and_attributes(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER])

    state = hass.states.get(humidifier_id(hass))
    assert state.state == "on"
    assert state.attributes["mode"] == "normal"
    assert state.attributes["humidity"] == 45
    assert state.attributes["current_humidity"] == 55
    assert state.attributes["fan_mode"] == "low"
    assert state.attributes["check_filter"] is False
    assert state.attributes["bin_full"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"alerts": [{"code": "BUCKET_FULL"}]},
        {"alerts": ["BUCKET_FULL"]},
        {"waterBucketLevel": 1},
        {"waterTankFull": "yes"},
    ],
    ids=["alert-dict", "alert-string", "water-bucket-level", "water-tank-full"],
)
async def test_bin_full_is_detected_from_every_reported_signal(hass: HomeAssistant, setup_entry, changes: dict) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, **changes)])

    assert hass.states.get(humidifier_id(hass)).attributes["bin_full"] is True

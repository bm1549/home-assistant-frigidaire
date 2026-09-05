"""Opt-in binary sensors."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from payloads import DEHUMIDIFIER, LEGACY_AC, with_reported

BUCKET_ENABLED = {"DH-1": {"bucket_status": True}}


def bucket_sensor_id(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("binary_sensor", "frigidaire", "DH-1_bucket_status")


async def test_bucket_sensor_is_off_when_bucket_reported_empty(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([DEHUMIDIFIER], options=BUCKET_ENABLED)

    entity_id = bucket_sensor_id(hass)
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "off"


async def test_bucket_sensor_is_on_when_alert_reported(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, alerts=[{"code": "BUCKET_FULL"}])], options=BUCKET_ENABLED)

    assert hass.states.get(bucket_sensor_id(hass)).state == "on"


async def test_bucket_sensor_is_on_when_level_reported_full(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, waterBucketLevel=1)], options=BUCKET_ENABLED)

    assert hass.states.get(bucket_sensor_id(hass)).state == "on"


async def test_bucket_sensor_is_on_when_tank_full_reported(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(DEHUMIDIFIER, waterTankFull="YES")], options=BUCKET_ENABLED)

    assert hass.states.get(bucket_sensor_id(hass)).state == "on"


async def test_bucket_sensor_unavailable_when_model_reports_no_bucket_signal(hass: HomeAssistant, setup_entry) -> None:
    record = with_reported(DEHUMIDIFIER)
    for key in ("alerts", "waterBucketLevel"):
        record["properties"]["reported"].pop(key)

    await setup_entry([record], options=BUCKET_ENABLED)

    assert hass.states.get(bucket_sensor_id(hass)).state == "unavailable"


async def test_bucket_sensor_not_created_without_option_or_for_air_conditioners(
    hass: HomeAssistant, setup_entry
) -> None:
    await setup_entry([DEHUMIDIFIER, LEGACY_AC], options={"AC-LEGACY-1": {"bucket_status": True}})

    assert bucket_sensor_id(hass) is None
    assert er.async_get(hass).async_get_entity_id("binary_sensor", "frigidaire", "AC-LEGACY-1_bucket_status") is None

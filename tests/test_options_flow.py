"""Per-device options flow: enabling an optional entity creates it after reload."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from payloads import DEHUMIDIFIER, LEGACY_AC


async def test_enabling_check_filter_creates_binary_sensor(hass: HomeAssistant, setup_entry) -> None:
    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("binary_sensor", "frigidaire", "DH-1_check_filter") is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device"
    assert result["description_placeholders"] == {"device_name": "Bedroom AC"}

    # First device (the AC): leave everything off.
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"device_name": "Basement Dehumidifier"}

    # Second device (the dehumidifier): enable the filter sensor.
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={"check_filter": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options["DH-1"]["check_filter"] is True
    assert entry.options["AC-LEGACY-1"]["check_filter"] is False
    sensor_id = registry.async_get_entity_id("binary_sensor", "frigidaire", "DH-1_check_filter")
    assert sensor_id is not None
    assert hass.states.get(sensor_id).state == "off"


async def test_air_conditioner_options_include_compressor_fields_and_serialize(
    hass: HomeAssistant, setup_entry
) -> None:
    import voluptuous_serialize
    from homeassistant.helpers import config_validation as cv

    entry, _stub = await setup_entry([LEGACY_AC, DEHUMIDIFIER])

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["description_placeholders"] == {"device_name": "Bedroom AC"}
    fields = {
        f["name"]: f
        for f in voluptuous_serialize.convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    }
    assert fields["compressor"]["type"] == "boolean"
    assert fields["cool_hysteresis"]["type"] == "float"
    assert fields["compressor_off_delay"]["type"] == "integer"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"compressor": True, "cool_hysteresis": 1.5, "compressor_off_delay": 60}
    )
    assert result["description_placeholders"] == {"device_name": "Basement Dehumidifier"}
    dh_fields = {
        f["name"] for f in voluptuous_serialize.convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    }
    assert "compressor" not in dh_fields

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["AC-LEGACY-1"]["cool_hysteresis"] == 1.5
    assert entry.options["AC-LEGACY-1"]["compressor_off_delay"] == 60

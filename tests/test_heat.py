"""Explicit per-appliance heat opt-in."""

import json
from pathlib import Path

import frigidaire
import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, TELICA_AC, with_reported
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from probatio import to_field_list


def heat_climate_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-TELICA-1")
    assert entity_id is not None
    return entity_id


async def test_heat_option_is_per_device_default_off_and_survives_normal_options_api(
    hass: HomeAssistant, setup_entry
) -> None:
    other = {**TELICA_AC, "applianceId": "AC-TELICA-2"}
    entry, _stub = await setup_entry(
        [TELICA_AC, other, DEHUMIDIFIER],
        options={"AC-TELICA-1": {"compressor": True, "cool_hysteresis": 1.5}},
    )
    assert "heat" not in hass.states.get(heat_climate_id(hass)).attributes["hvac_modes"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {f["name"]: f for f in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)}
    assert fields["heat_supported"]["type"] == "boolean"
    assert fields["heat_supported"]["default"] is False
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={"heat_supported": True})
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    fields = {f["name"] for f in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)}
    assert "heat_supported" not in fields
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.options["AC-TELICA-1"]["heat_supported"] is True
    assert entry.options["AC-TELICA-1"]["compressor"] is True
    assert entry.options["AC-TELICA-1"]["cool_hysteresis"] == 1.5
    assert entry.options["AC-TELICA-2"]["heat_supported"] is False
    assert "heat" in hass.states.get(heat_climate_id(hass)).attributes["hvac_modes"]
    other_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", "AC-TELICA-2")
    assert "heat" not in hass.states.get(other_id).attributes["hvac_modes"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {f["name"]: f for f in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)}
    assert fields["heat_supported"]["default"] is True
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={"heat_supported": False})
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert "heat" not in hass.states.get(heat_climate_id(hass)).attributes["hvac_modes"]


async def test_heat_option_is_available_during_initial_setup(hass: HomeAssistant, frigidaire_stub, tmp_path) -> None:
    from homeassistant import config_entries

    hass.config.config_dir = str(tmp_path)
    frigidaire_stub([TELICA_AC])
    result = await hass.config_entries.flow.async_init("frigidaire", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "user@example.com", "password": "secret"}
    )
    fields = {f["name"]: f for f in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)}
    assert fields["heat_supported"]["default"] is False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"heat_supported": True})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["AC-TELICA-1"]["heat_supported"] is True
    assert "heat" in hass.states.get(heat_climate_id(hass)).attributes["hvac_modes"]


@pytest.mark.parametrize("raw_mode", ["heat", "HEAT"])
@pytest.mark.parametrize(
    "power, expected_mode, expected_action",
    [
        ("running", "heat", "fan"),
        ("off", "off", "off"),
        (None, "heat", "idle"),
    ],
)
async def test_heat_parsing_and_availability(
    hass: HomeAssistant, setup_entry, raw_mode, power, expected_mode, expected_action
) -> None:
    record = with_reported(TELICA_AC, mode=raw_mode, modeState="fanOnly", applianceState=power)
    entry, _stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True}})
    assert entry.runtime_data.data["AC-TELICA-1"].mode is frigidaire.Mode.HEAT
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == expected_mode
    assert state.attributes["hvac_action"] == expected_action
    assert state.attributes["min_temp"] == 60


@pytest.mark.parametrize(
    "power, mode, restore_target",
    [
        ("running", "fanOnly", False),
        ("off", "off", True),
        ("running", "off", True),
    ],
)
async def test_set_heat_sends_power_then_heat_and_restores_off_setpoint(
    hass: HomeAssistant, setup_entry, power, mode, restore_target
) -> None:
    record = with_reported(TELICA_AC, applianceState=power, mode=mode, targetTemperatureF=68)
    _entry, stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True}})
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": heat_climate_id(hass), "hvac_mode": "heat"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    expected = [("executeCommand", frigidaire.Power.ON), ("mode", frigidaire.Mode.HEAT)]
    if restore_target:
        expected += [("temperatureRepresentation", frigidaire.Unit.FAHRENHEIT), ("targetTemperatureF", 68)]
    assert stub.commands == expected
    assert hass.states.get(heat_climate_id(hass)).state == "heat"


@pytest.mark.parametrize("record", [TELICA_AC, LEGACY_AC])
async def test_heat_request_without_opt_in_sends_nothing(hass: HomeAssistant, setup_entry, record) -> None:
    from homeassistant.components.climate.const import HVACMode
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.frigidaire.climate import FrigidaireClimate

    entry, stub = await setup_entry([record])
    appliance_id = record["applianceId"]
    entity_id = er.async_get(hass).async_get_entity_id("climate", "frigidaire", appliance_id)
    assert "heat" not in hass.states.get(entity_id).attributes["hvac_modes"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "heat"}, blocking=True
        )
    # Guard the entity method too: callers need not go through HA's service validation.
    entity = FrigidaireClimate(entry.runtime_data, entry.runtime_data.data[appliance_id])
    entity.set_hvac_mode(HVACMode.HEAT)
    assert stub.commands == []


@pytest.mark.parametrize(
    "mode_state, compressor, expected",
    [
        ("heat", None, "heating"),
        ("HEAT", None, "heating"),
        ("fanOnly", None, "fan"),
        ("idle", None, "idle"),
        ("off", None, "idle"),
        (None, None, None),
        ("unrecognized", None, None),
        (None, "on", "heating"),
        ("fanOnly", "on", "heating"),
        ("heat", "off", "idle"),
        ("fanOnly", "off", "fan"),
    ],
)
async def test_heat_action_uses_telemetry_not_the_cooling_estimator(
    hass: HomeAssistant, setup_entry, mode_state, compressor, expected
) -> None:
    from unittest.mock import patch

    from custom_components.frigidaire.climate import FrigidaireClimate

    record = with_reported(
        TELICA_AC,
        mode="heat",
        modeState=mode_state,
        compressorState=compressor,
        ambientTemperatureF=60,
        targetTemperatureF=72,
    )
    entry, _stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True, "compressor": True}})
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "heat"
    assert state.attributes.get("hvac_action") == expected
    assert entry.runtime_data.compressor_estimate("AC-TELICA-1") is None
    entity = FrigidaireClimate(entry.runtime_data, entry.runtime_data.data["AC-TELICA-1"])
    with patch.object(entry.runtime_data, "compressor_estimate", side_effect=AssertionError("Cooling only")):
        assert entity.hvac_action == expected


async def test_heat_selection_does_not_override_reported_cooling_activity(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry(
        [with_reported(TELICA_AC, mode="heat", modeState="cool", compressorState="on")],
        options={"AC-TELICA-1": {"heat_supported": True}},
    )
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "cooling"


async def test_heat_mode_state_is_activity_not_requested_mode(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry(
        [with_reported(TELICA_AC, mode="eco", modeState="heat")],
        options={"AC-TELICA-1": {"heat_supported": True}},
    )
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "auto"
    assert state.attributes["hvac_action"] == "heating"


@pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
@pytest.mark.parametrize("flow", ["config", "options"])
def test_heat_checkbox_has_an_explicit_english_opt_in_label(filename, flow) -> None:
    component = Path(__file__).resolve().parents[1] / "custom_components" / "frigidaire"
    device = json.loads((component / filename).read_text())[flow]["step"]["device"]
    assert device["data"]["heat_supported"] == "Enable heat mode (confirmed heat-capable device only)"
    assert "does not detect" in device["data_description"]["heat_supported"]


async def test_unrecognized_heat_without_opt_in_does_not_infer_cooling(hass: HomeAssistant, setup_entry) -> None:
    await setup_entry([with_reported(TELICA_AC, mode="heat", modeState="heat")])
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "unknown"
    assert "heat" not in state.attributes["hvac_modes"]
    assert state.attributes.get("hvac_action") is None


@pytest.mark.parametrize("mode_state", [None, "fanOnly"])
async def test_requested_heat_without_opt_in_does_not_use_the_cooling_estimator(
    hass: HomeAssistant, setup_entry, mode_state
) -> None:
    await setup_entry(
        [with_reported(TELICA_AC, mode="heat", modeState=mode_state, ambientTemperatureF=80, targetTemperatureF=72)],
        options={"AC-TELICA-1": {"compressor": True}},
    )
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "unknown"
    assert state.attributes.get("hvac_action") is None


@pytest.mark.parametrize(
    "mode, mode_state, power, expected",
    [("unrecognized", "cool", "running", "cooling"), ("heat", "heat", "DELAYED_START", "idle")],
)
async def test_heat_safety_does_not_change_other_unknown_mode_or_nonrunning_actions(
    hass: HomeAssistant, setup_entry, mode, mode_state, power, expected
) -> None:
    await setup_entry([with_reported(TELICA_AC, mode=mode, modeState=mode_state, applianceState=power)])
    assert hass.states.get(heat_climate_id(hass)).attributes.get("hvac_action") == expected


@pytest.mark.parametrize("compressor", [None, "on"])
@pytest.mark.parametrize("mode_state", ["heat", "HEAT"])
async def test_heat_activity_without_opt_in_does_not_fall_back_to_cooling(
    hass: HomeAssistant, setup_entry, compressor, mode_state
) -> None:
    await setup_entry([with_reported(TELICA_AC, mode="eco", modeState=mode_state, compressorState=compressor)])
    state = hass.states.get(heat_climate_id(hass))
    assert state.state == "auto"
    assert state.attributes.get("hvac_action") is None


@pytest.mark.parametrize(
    "ha_mode, library_mode",
    [
        ("cool", frigidaire.Mode.COOL),
        ("auto", frigidaire.Mode.ECO),
        ("fan_only", frigidaire.Mode.FAN),
        ("dry", frigidaire.Mode.DRY),
        ("off", frigidaire.Mode.OFF),
    ],
)
async def test_heat_opt_in_preserves_existing_mode_commands(
    hass: HomeAssistant, setup_entry, ha_mode, library_mode
) -> None:
    _entry, stub = await setup_entry([TELICA_AC], options={"AC-TELICA-1": {"heat_supported": True}})
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": heat_climate_id(hass), "hvac_mode": ha_mode}, blocking=True
    )
    expected = [] if ha_mode == "off" else [("executeCommand", frigidaire.Power.ON)]
    assert stub.commands == [*expected, ("mode", library_mode)]


@pytest.mark.parametrize(
    "unit, target, expected_setpoint",
    [
        ("celsius", 20, [("temperatureRepresentation", frigidaire.Unit.CELSIUS), ("targetTemperatureC", 20)]),
        ("fahrenheit", None, []),
    ],
)
async def test_heat_from_off_preserves_temperature_units_and_skips_missing_setpoint(
    hass: HomeAssistant, setup_entry, unit, target, expected_setpoint
) -> None:
    record = with_reported(
        TELICA_AC,
        applianceState="off",
        mode="off",
        temperatureRepresentation=unit,
        targetTemperatureF=None,
        targetTemperatureC=target,
    )
    _entry, stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True}})
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": heat_climate_id(hass), "hvac_mode": "heat"}, blocking=True
    )
    assert stub.commands == [
        ("executeCommand", frigidaire.Power.ON),
        ("mode", frigidaire.Mode.HEAT),
        *expected_setpoint,
    ]


async def test_polling_heat_activity_changes_does_not_change_requested_heat(hass: HomeAssistant, setup_entry) -> None:
    record = with_reported(TELICA_AC, mode="heat", modeState="heat")
    entry, stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True}})
    for mode_state, action in [("heat", "heating"), ("fanOnly", "fan"), ("idle", "idle"), (None, None)]:
        stub.records["AC-TELICA-1"] = with_reported(record, modeState=mode_state)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        state = hass.states.get(heat_climate_id(hass))
        assert state.state == "heat"
        assert state.attributes.get("hvac_action") == action
    assert stub.commands == []


@pytest.mark.parametrize("failure_step", [1, 2, 3])
async def test_failed_heat_command_is_not_optimistically_accepted(
    hass: HomeAssistant, setup_entry, failure_step
) -> None:
    from unittest.mock import patch

    from homeassistant.components.climate.const import HVACMode

    from custom_components.frigidaire.climate import FrigidaireClimate

    record = with_reported(TELICA_AC, applianceState="off", mode="off") if failure_step == 3 else TELICA_AC
    entry, stub = await setup_entry([record], options={"AC-TELICA-1": {"heat_supported": True}})
    entity = FrigidaireClimate(entry.runtime_data, entry.runtime_data.data["AC-TELICA-1"])
    with (
        patch.object(
            stub,
            "execute_action",
            side_effect=[None] * (failure_step - 1) + [frigidaire.FrigidaireException("command failed")],
        ) as execute,
        pytest.raises(frigidaire.FrigidaireException, match="command failed"),
    ):
        entity.set_hvac_mode(HVACMode.HEAT)
    assert execute.call_count == failure_step
    assert entity.hvac_mode == (HVACMode.OFF if failure_step == 3 else HVACMode.FAN_ONLY)

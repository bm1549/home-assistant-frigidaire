"""A command the appliance refuses in its current state becomes an error the user sees."""

import frigidaire
import pytest
from frigidaire.testing import DEHUMIDIFIER, LEGACY_AC, with_reported
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.frigidaire.auth import METHODS

DOMAIN = "frigidaire"

every_method = pytest.mark.parametrize("auth_method", list(METHODS))


def entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def rejected() -> frigidaire.CommandRejectedError:
    return frigidaire.CommandRejectedError("The appliance refused the request in its current state", status_code=406)


@every_method
async def test_a_rejected_humidity_target_says_which_modes_allow_it(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, stub = await setup_entry([DEHUMIDIFIER])
    stub.command_error = rejected()
    # What the appliance reports after the refusal; the entity must show it, not a held value.
    stub.records["DH-1"]["properties"]["reported"]["targetHumidity"] = 40

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "humidifier",
            "set_humidity",
            {"entity_id": entity_id(hass, "humidifier", "DH-1"), "humidity": 50},
            blocking=True,
        )
    await settle()

    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "humidity_rejected"
    assert raised.value.translation_placeholders == {"device_name": "Basement Dehumidifier"}
    assert stub.commands == []
    # Earlier steps of a sequence may have applied, so the appliance is read back.
    assert stub.record_fetch_count == 1
    assert entry.runtime_data.data["DH-1"].target_humidity == 40


@every_method
async def test_any_other_rejected_command_raises_the_generic_error(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([with_reported(LEGACY_AC, mode="OFF")])
    stub.command_error = rejected()
    climate = entity_id(hass, "climate", "AC-LEGACY-1")

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": climate, "hvac_mode": "cool"}, blocking=True
        )

    assert raised.value.translation_key == "command_rejected"
    assert raised.value.translation_placeholders == {"device_name": "Bedroom AC"}
    # No optimistic value is held for a refused command.
    assert hass.states.get(climate).state == "off"


async def test_the_rejection_messages_are_translated(hass: HomeAssistant, setup_entry) -> None:
    _entry, stub = await setup_entry([DEHUMIDIFIER])
    stub.command_error = rejected()

    with pytest.raises(ServiceValidationError, match="only in Dry or Continuous mode"):
        await hass.services.async_call(
            "humidifier",
            "set_humidity",
            {"entity_id": entity_id(hass, "humidifier", "DH-1"), "humidity": 50},
            blocking=True,
        )

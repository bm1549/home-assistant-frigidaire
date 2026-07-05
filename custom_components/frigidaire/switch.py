"""Switch entities for frigidaire integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire
from frigidaire import Component, Detail, Setting

from .const import DOMAIN
from .helpers import suggest_area

_LOGGER = logging.getLogger(__name__)


def _normalize(value):
    if isinstance(value, str):
        return value.upper()
    return value


@dataclass
class SwitchDescription:
    key: str
    name: str
    detail: Detail
    setting: Setting
    on_value: Any
    off_value: Any
    device_class: SwitchDeviceClass | None = None
    icon: str | None = None

    def make_action(self, turn_on: bool) -> list[Component]:
        return [Component(self.setting, self.on_value if turn_on else self.off_value)]


SWITCH_DESCRIPTIONS: dict[str, SwitchDescription] = {
    d.key: d
    for d in [
        SwitchDescription(
            key="clean_air_mode",
            name="Ionizer",
            detail=Detail.CLEAN_AIR_MODE,
            setting=Setting.CLEAN_AIR_MODE,
            on_value="ON",
            off_value="OFF",
            icon="mdi:air-purifier",
        ),
        SwitchDescription(
            key="display_light",
            name="Display Light",
            detail=Detail.DISPLAY_LIGHT,
            setting=Setting.DISPLAY_LIGHT,
            on_value="ON",
            off_value="OFF",
            icon="mdi:lightbulb-outline",
        ),
        SwitchDescription(
            key="ui_lock",
            name="Child Lock",
            detail=Detail.UI_LOCK_MODE,
            setting=Setting.UI_LOCK_MODE,
            on_value=True,
            off_value=False,
            device_class=SwitchDeviceClass.SWITCH,
            icon="mdi:lock",
        ),
    ]
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire switch entities from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    # options is keyed by appliance_id -> {switch_key: bool}
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities = [
        FrigidaireSwitch(client, appliance, SWITCH_DESCRIPTIONS[key], suggest_area(hass, appliance.nickname))
        for appliance in appliances
        for key, enabled in options.get(appliance.appliance_id, {}).items()
        if enabled and key in SWITCH_DESCRIPTIONS
    ]

    async_add_entities(entities, update_before_add=True)


class FrigidaireSwitch(SwitchEntity):
    """A switch for a single Frigidaire boolean setting."""

    def __init__(
        self,
        client: frigidaire.Frigidaire,
        appliance: frigidaire.Appliance,
        desc: SwitchDescription,
        suggested_area: str | None = None,
    ) -> None:
        self._client = client
        self._appliance = appliance
        self._desc = desc
        self._details: dict = {}
        self._attr_unique_id = f"{appliance.appliance_id}_{desc.key}"
        self._attr_name = desc.name
        self._attr_device_class = desc.device_class
        self._attr_icon = desc.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def is_on(self) -> bool | None:
        raw = self._details.get(self._desc.detail)
        if raw is None:
            return None
        on_val = self._desc.on_value
        if isinstance(on_val, bool):
            # API may return a bool or a string "true"/"false"
            if isinstance(raw, bool):
                return raw == on_val
            return str(raw).upper() == "TRUE" if on_val else str(raw).upper() == "FALSE"
        return _normalize(raw) == str(on_val).upper()

    def turn_on(self, **kwargs: Any) -> None:
        self._client.execute_action(self._appliance, self._desc.make_action(True))

    def turn_off(self, **kwargs: Any) -> None:
        self._client.execute_action(self._appliance, self._desc.make_action(False))

    def update(self) -> None:
        try:
            self._details = self._client.get_appliance_details(self._appliance)
            self._attr_available = True
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False

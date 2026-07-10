"""Binary sensor entities for frigidaire integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import frigidaire

from .const import DOMAIN
from .helpers import suggest_area

_LOGGER = logging.getLogger(__name__)


def _normalize(value):
    if isinstance(value, str):
        return value.upper()
    return value


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up frigidaire binary sensor entities from a config entry."""
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    appliances: list[frigidaire.Appliance] = hass.data[DOMAIN][entry.entry_id]["appliances"]
    options: dict[str, dict[str, bool]] = entry.options

    if not options:
        return

    entities = [
        FrigidaireCheckFilterSensor(client, appliance, suggest_area(hass, appliance.nickname))
        for appliance in appliances
        if options.get(appliance.appliance_id, {}).get("check_filter", False)
    ]

    async_add_entities(entities, update_before_add=True)


class FrigidaireCheckFilterSensor(BinarySensorEntity):
    """Binary sensor that is ON when the filter needs attention."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, client: frigidaire.Frigidaire, appliance: frigidaire.Appliance, suggested_area: str | None = None
    ) -> None:
        self._client = client
        self._appliance = appliance
        self._details: dict = {}
        self._attr_unique_id = f"{appliance.appliance_id}_check_filter"
        self._attr_name = "Check Filter"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            suggested_area=suggested_area,
        )

    @property
    def is_on(self) -> bool | None:
        filter_state = _normalize(self._details.get(frigidaire.Detail.FILTER_STATE))
        if filter_state is None:
            return None
        return filter_state != frigidaire.FilterState.GOOD

    def update(self) -> None:
        try:
            self._details = self._client.get_appliance_details(self._appliance)
            self._attr_available = True
        except frigidaire.FrigidaireException:
            if self.available:
                _LOGGER.error("Failed to connect to Frigidaire servers")
            self._attr_available = False

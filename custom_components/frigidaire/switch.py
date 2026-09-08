"""Switch entities for opt-in on/off settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from frigidaire import Appliance, Frigidaire

from .coordinator import FrigidaireConfigEntry, FrigidaireCoordinator
from .entity import FrigidaireEntity


@dataclass(frozen=True, kw_only=True)
class SwitchDescription:
    key: str  # must match a SWITCH_OPTIONS key in const.py
    name: str
    icon: str
    is_on: Callable[[Appliance], bool | None]
    set: Callable[[Frigidaire, Appliance, bool], None]


SWITCH_DESCRIPTIONS = (
    SwitchDescription(
        key="clean_air_mode",
        name="Ionizer",
        icon="mdi:air-purifier",
        is_on=lambda appliance: appliance.clean_air_mode,
        set=lambda client, appliance, on: client.set_clean_air_mode(appliance, on),
    ),
    SwitchDescription(
        key="display_light",
        name="Display Light",
        icon="mdi:lightbulb-outline",
        is_on=lambda appliance: appliance.display_light,
        set=lambda client, appliance, on: client.set_display_light(appliance, on),
    ),
    SwitchDescription(
        key="ui_lock",
        name="Child Lock",
        icon="mdi:lock",
        is_on=lambda appliance: appliance.ui_locked,
        set=lambda client, appliance, on: client.set_ui_lock(appliance, on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: FrigidaireConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the switches enabled per device in the entry options."""
    coordinator = entry.runtime_data
    async_add_entities(
        FrigidaireSwitch(coordinator, appliance, description)
        for appliance in coordinator.data.values()
        for description in SWITCH_DESCRIPTIONS
        if entry.options.get(appliance.appliance_id, {}).get(description.key, False)
    )


class FrigidaireSwitch(FrigidaireEntity, SwitchEntity):
    """A switch for a single on/off setting."""

    def __init__(self, coordinator: FrigidaireCoordinator, appliance: Appliance, description: SwitchDescription):
        super().__init__(
            coordinator, appliance, unique_id=f"{appliance.appliance_id}_{description.key}", name=description.name
        )
        self._description = description
        self._attr_icon = description.icon

    @property
    def is_on(self) -> bool | None:
        return self._description.is_on(self.appliance)

    def turn_on(self, **kwargs: Any) -> None:
        self._description.set(self.client, self.appliance, True)
        self.refresh()

    def turn_off(self, **kwargs: Any) -> None:
        self._description.set(self.client, self.appliance, False)
        self.refresh()

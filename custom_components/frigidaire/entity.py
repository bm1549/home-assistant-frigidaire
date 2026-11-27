"""Base class shared by every Frigidaire entity."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from frigidaire import Appliance, AsyncFrigidaire, CommandRejectedError

from .const import DOMAIN
from .coordinator import FrigidaireCoordinator

OPTIMISTIC_WINDOW = 5  # seconds


def suggest_area(hass: HomeAssistant, nickname: str) -> str | None:
    """The longest area name that appears in the appliance nickname, or None."""
    nickname_lower = nickname.lower()
    areas = (area.name for area in ar.async_get(hass).areas.values() if area.name.lower() in nickname_lower)
    return max(areas, key=len, default=None)


def async_add_appliance_entities(
    coordinator: FrigidaireCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[Appliance], Iterable[Entity]],
) -> None:
    """Create a platform's entities for every appliance now, and for any that joins the account later.

    Each appliance is offered to ``build`` once, when first seen, so an appliance that drops off
    the account and returns keeps its existing entities.
    """
    known: set[str] = set()

    @callback
    def add_new() -> None:
        entities: list[Entity] = []
        for appliance_id, appliance in (coordinator.data or {}).items():
            if appliance_id in known:
                continue
            known.add(appliance_id)
            entities.extend(build(appliance))
        if entities:
            async_add_entities(entities)

    add_new()
    assert coordinator.config_entry is not None
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(add_new))


class Optimistic:
    """Holds commanded values for a few seconds so the UI does not snap back before the cloud catches up."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._until = 0.0

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value
        self._until = time.monotonic() + OPTIMISTIC_WINDOW

    def get(self, key: str) -> Any:
        return self._values.get(key) if time.monotonic() < self._until else None

    def expire(self) -> None:
        if time.monotonic() >= self._until:
            self._values.clear()


class FrigidaireEntity(CoordinatorEntity[FrigidaireCoordinator]):
    """An entity for one appliance, reading its latest snapshot from the coordinator."""

    def __init__(self, coordinator: FrigidaireCoordinator, appliance: Appliance, *, unique_id: str, name: str) -> None:
        super().__init__(coordinator)
        self.appliance_id = appliance.appliance_id
        self._appliance = appliance
        self._attr_unique_id = unique_id
        self._optimistic = Optimistic()
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, appliance.appliance_id)},
            name=appliance.nickname,
            manufacturer="Frigidaire",
            model=appliance.appliance_type,
            suggested_area=suggest_area(coordinator.hass, appliance.nickname),
        )

    @property
    def appliance(self) -> Appliance:
        """The latest snapshot, or the last one seen if the appliance has left the account."""
        current = (self.coordinator.data or {}).get(self.appliance_id)
        if current is not None:
            self._appliance = current
        return self._appliance

    @property
    def client(self) -> AsyncFrigidaire:
        return self.coordinator.client

    @property
    def available(self) -> bool:
        return super().available and self.appliance_id in (self.coordinator.data or {})

    async def async_command(
        self, command: Awaitable[None], *, rejected: str = "command_rejected", **optimistic: Any
    ) -> None:
        """Send one library command, then hold ``optimistic`` values and refresh this appliance.

        Every setter goes through here. A failed command raises before anything is held, so the
        UI never shows a value the appliance did not accept. An appliance refusing the command in
        its current state raises a translated error the user sees; ``rejected`` names its message
        in ``translations/en.json``'s ``exceptions``. The appliance is still refreshed then, since
        the earlier steps of a sequence (such as the mode change before a humidity target) may
        have been applied.
        """
        try:
            await command
        except CommandRejectedError as err:
            await self.coordinator.async_refresh_appliance(self.appliance)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=rejected,
                translation_placeholders={"device_name": self.appliance.nickname},
            ) from err
        for key, value in optimistic.items():
            self._optimistic.set(key, value)
        if optimistic and self.hass is not None:
            self.async_write_ha_state()
        await self.coordinator.async_refresh_appliance(self.appliance)

    async def async_update(self) -> None:
        """Fetch now, for the update_entity service."""
        if self.enabled:
            await self.coordinator.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic.expire()
        super()._handle_coordinator_update()

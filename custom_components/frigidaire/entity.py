"""Base class shared by every Frigidaire entity."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from frigidaire import Appliance, Frigidaire

from .const import DOMAIN
from .coordinator import FrigidaireCoordinator

OPTIMISTIC_WINDOW = 5  # seconds


def suggest_area(hass: HomeAssistant, nickname: str) -> str | None:
    """The longest area name that appears in the appliance nickname, or None."""
    nickname_lower = nickname.lower()
    areas = (area.name for area in ar.async_get(hass).areas.values() if area.name.lower() in nickname_lower)
    return max(areas, key=len, default=None)


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
    def client(self) -> Frigidaire:
        return self.coordinator.client

    @property
    def available(self) -> bool:
        return super().available and self.appliance_id in (self.coordinator.data or {})

    async def async_update(self) -> None:
        """Fetch now. Used after a command so the reported state catches up promptly."""
        if self.enabled:
            await self.coordinator.async_refresh()

    def refresh(self) -> None:
        """Schedule an immediate poll from a command running in the executor."""
        self.schedule_update_ha_state(force_refresh=True)

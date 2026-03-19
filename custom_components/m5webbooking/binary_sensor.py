from __future__ import annotations

from typing import Any

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import M5RuntimeData
from .m5_client import RoomStatus


_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: M5RuntimeData = entry.runtime_data
    coordinator: DataUpdateCoordinator[list[RoomStatus]] = runtime_data.coordinator

    # Create one health entity plus one entity per room based on current data
    rooms = coordinator.data or []
    entities: list[BinarySensorEntity] = [M5ProblemBinarySensor(coordinator, entry)]
    entities.extend(
        M5RoomBinarySensor(coordinator, entry, room) for room in rooms
    )

    async_add_entities(entities)


class M5ProblemBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[list[RoomStatus]],
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"m5_{entry.entry_id}_problem"
        self._attr_name = "M5 Problem"

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return not self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.last_update_success:
            return {}

        error = getattr(self.coordinator, "last_exception", None)
        reason = str(error) if error else "unknown"
        reason_type = "timeout" if "timed out" in reason.lower() or "timeout" in reason.lower() else "error"
        return {
            "reason": reason,
            "reason_type": reason_type,
        }


class M5RoomBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[list[RoomStatus]],
        entry: ConfigEntry,
        room: RoomStatus,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._room_name = room.name

        slug = self._room_name.lower().replace(" ", "_")
        # Unique ID for stable entity IDs
        self._attr_unique_id = f"m5_{self._entry.entry_id}_{slug}"
        # Friendly name and base for entity_id include the M5 prefix
        self._attr_name = f"M5 {self._room_name}"

    @property
    def is_on(self) -> bool:
        # Find this room in the latest coordinator data
        rooms = self.coordinator.data or []
        for room in rooms:
            if room.name == self._room_name:
                _LOGGER.debug("M5 %s: is_on evaluated to %s", self._room_name, room.occupied)
                return room.occupied
        # Default to False if not found
        _LOGGER.debug("M5 %s: is_on defaulting to False (room not found)", self._room_name)
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = self.coordinator.data or []
        current: RoomStatus | None = None
        for room in rooms:
            if room.name == self._room_name:
                current = room
                break

        attrs: dict[str, Any] = {}
        if current is not None:
            attrs["title"] = current.title
            attrs["booked_by_me"] = current.booked_by_me

        _LOGGER.debug(
            "M5 %s: extra_state_attributes -> %s",
            self._room_name,
            attrs,
        )

        return attrs
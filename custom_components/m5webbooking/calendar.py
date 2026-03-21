from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import M5CoordinatorData, M5RuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: M5RuntimeData = entry.runtime_data
    coordinator: DataUpdateCoordinator[M5CoordinatorData] = runtime_data.coordinator

    # We only expose a single calendar with the current user's bookings.
    async_add_entities([M5UserBookingsCalendar(coordinator, entry.entry_id)])


class M5UserBookingsCalendar(CoordinatorEntity[M5CoordinatorData], CalendarEntity):
    """Calendar entity exposing the current user's own bookings."""

    _attr_translation_key = "my_bookings"
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator[M5CoordinatorData], entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"m5_calendar_{entry_id}_my_bookings"
        self._current_event: CalendarEvent | None = None

    @staticmethod
    def _booking_to_event(booking: dict[str, Any], hass_tz: datetime.tzinfo) -> CalendarEvent:
        start: datetime = booking["start"]
        end: datetime = booking["end"]

        # Convert naive datetimes from client to timezone-aware in HA timezone
        if start.tzinfo is None:
            start = start.replace(tzinfo=hass_tz)
        else:
            start = start.astimezone(hass_tz)

        if end.tzinfo is None:
            end = end.replace(tzinfo=hass_tz)
        else:
            end = end.astimezone(hass_tz)

        return CalendarEvent(
            summary=f"{booking['name']}",
            start=start,
            end=end,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        await self.coordinator.async_request_refresh()

        # Ensure start/end window are timezone-aware in Home Assistant's timezone
        hass_tz = dt_util.get_time_zone(hass.config.time_zone)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=hass_tz)
        else:
            start_date = start_date.astimezone(hass_tz)

        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=hass_tz)
        else:
            end_date = end_date.astimezone(hass_tz)

        bookings = self.coordinator.data.my_bookings if self.coordinator.data else []
        all_events = [self._booking_to_event(b, hass_tz) for b in bookings]
        events = [
            e for e in all_events if not (e.end <= start_date or e.start >= end_date)
        ]

        now = dt_util.utcnow().astimezone(hass_tz)
        upcoming = [e for e in all_events if e.end >= now]
        upcoming.sort(key=lambda e: e.start)
        self._current_event = upcoming[0] if upcoming else None

        return events

    @property
    def event(self) -> CalendarEvent | None:  # type: ignore[override]
        return self._current_event

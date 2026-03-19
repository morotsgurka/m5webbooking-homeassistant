from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import M5RuntimeData
from .m5_client import M5Client


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data: M5RuntimeData = entry.runtime_data
    client: M5Client = runtime_data.client

    # We only expose a single calendar with the current user's bookings.
    async_add_entities([M5UserBookingsCalendar(client, entry.entry_id)])


class M5UserBookingsCalendar(CalendarEntity):
    """Calendar entity exposing the current user's own bookings."""

    _attr_translation_key = "my_bookings"
    _attr_has_entity_name = True

    def __init__(self, client: M5Client, entry_id: str) -> None:
        self._client = client
        self._attr_unique_id = f"m5_calendar_{entry_id}_my_bookings"
        self._current_event: CalendarEvent | None = None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        # Fetch current user's bookings; run blocking code in executor
        def _fetch() -> list[dict[str, Any]]:
            return self._client.fetch_user_bookings()

        bookings = await hass.async_add_executor_job(_fetch)

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

        events: list[CalendarEvent] = []
        for b in bookings:
            start: datetime = b["start"]
            end: datetime = b["end"]

            # Convert naive datetimes from client to timezone-aware in HA timezone
            if start.tzinfo is None:
                start = start.replace(tzinfo=hass_tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=hass_tz)

            if end <= start_date or start >= end_date:
                continue

            summary = f"{b['name']}"
            events.append(
                CalendarEvent(
                    summary=summary,
                    start=start,
                    end=end,
                )
            )

        now = dt_util.utcnow().astimezone(hass_tz)
        upcoming = [e for e in events if e.end >= now]
        upcoming.sort(key=lambda e: e.start)
        self._current_event = upcoming[0] if upcoming else None

        return events

    @property
    def event(self) -> CalendarEvent | None:  # type: ignore[override]
        return self._current_event

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_ADDRESS,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_VALIDATED_CLIENTS,
    DOMAIN,
    PLATFORMS,
    SCAN_INTERVAL_MINUTES,
)
from .m5_client import M5Client, RoomStatus

type M5ConfigEntry = ConfigEntry


@dataclass
class M5RuntimeData:
    """Runtime data attached to the config entry."""

    client: M5Client
    coordinator: DataUpdateCoordinator[list[RoomStatus]]


def _client_cache_key(address: str, username: str, password: str) -> tuple[str, str, str]:
    return (address, username, password)

async def async_setup_entry(hass: HomeAssistant, entry: M5ConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    domain_data = hass.data.setdefault(DOMAIN, {})
    validated_clients: dict[tuple[str, str, str], M5Client] = domain_data.setdefault(
        DATA_VALIDATED_CLIENTS, {}
    )
    client = validated_clients.pop(
        _client_cache_key(address, username, password),
        M5Client(address, username, password),
    )

    async def async_update_data() -> list[RoomStatus]:
        """Fetch status for all rooms from the shared status page."""

        try:
            return await hass.async_add_executor_job(client.fetch_status)
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator[list[RoomStatus]](
        hass,
        logger=logging.getLogger(__name__),
        name="m5webbooking",
        update_method=async_update_data,
        update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = M5RuntimeData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: M5ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok
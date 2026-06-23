"""TP-Link VIGI NVR integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VigiNvrClient
from .const import CONF_VERIFY_TLS, DOMAIN
from .coordinator import VigiNvrCoordinator

PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up VIGI NVR from a config entry."""
    client = VigiNvrClient(
        session=async_get_clientsession(hass),
        host=entry.data["host"],
        port=entry.data["port"],
        username=entry.data["username"],
        password=entry.data["password"],
        verify_tls=entry.data[CONF_VERIFY_TLS],
    )
    coordinator = VigiNvrCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a VIGI NVR config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

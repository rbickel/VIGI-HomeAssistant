"""TP-Link VIGI NVR integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr

from .api import VigiNvrClient
from .const import (
    CONF_EVENT_WEBHOOK_ID,
    CONF_VERIFY_TLS,
    DOMAIN,
    EVENT_VIGI_NVR_EVENT,
)
from .coordinator import VigiNvrCoordinator
from .events import parse_vigi_event_push

LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
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
    _register_nvr_device(hass, entry)

    webhook_id = _get_or_create_webhook_id(hass, entry)
    webhook_url = _generate_webhook_url(hass, webhook_id)
    coordinator.set_event_webhook(webhook_id, webhook_url)

    async def _async_handle_webhook(
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response:
        return await _async_handle_event_message(
            hass,
            entry,
            coordinator,
            request,
        )

    webhook.async_register(
        hass,
        DOMAIN,
        f"VIGI NVR {entry.data[CONF_HOST]} event_message",
        webhook_id,
        _async_handle_webhook,
        local_only=True,
        allowed_methods={"POST"},
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a VIGI NVR config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        webhook_id = entry.data.get(CONF_EVENT_WEBHOOK_ID)
        if webhook_id:
            webhook.async_unregister(hass, webhook_id)
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _get_or_create_webhook_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return a stable webhook ID for the config entry."""
    webhook_id = entry.data.get(CONF_EVENT_WEBHOOK_ID)
    if isinstance(webhook_id, str) and webhook_id:
        return webhook_id

    webhook_id = webhook.async_generate_id()
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_EVENT_WEBHOOK_ID: webhook_id},
    )
    return webhook_id


def _register_nvr_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure the parent NVR device exists before channel devices reference it."""
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="TP-Link",
        model="VIGI NVR",
        name=entry.title or "VIGI NVR",
    )


def _generate_webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """Generate a local webhook URL, falling back to the route path."""
    try:
        return webhook.async_generate_url(
            hass,
            webhook_id,
            allow_external=False,
            allow_ip=True,
            prefer_external=False,
        )
    except Exception as error:  # noqa: BLE001
        LOGGER.debug("Could not generate VIGI webhook URL: %s", error)
        return f"/api/webhook/{webhook_id}"


async def _async_handle_event_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: VigiNvrCoordinator,
    request: web.Request,
) -> web.Response:
    """Handle a VIGI event_message webhook POST."""
    body = await request.read()
    event_push = parse_vigi_event_push(request.headers.get("Content-Type", ""), body)
    received_at = coordinator.store_event_push(event_push, request.remote)

    event_data: dict[str, Any] = {
        **event_push.as_dict(),
        "entry_id": entry.entry_id,
        "source_ip": request.remote,
        "received_at": received_at.isoformat(),
    }
    hass.bus.async_fire(EVENT_VIGI_NVR_EVENT, event_data)
    return web.json_response({"error_code": 0})

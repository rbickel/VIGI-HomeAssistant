"""Diagnostics for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACTED_CONFIG_KEYS = {"password", "event_webhook_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "domain": DOMAIN,
        "entry": {
            "title": entry.title,
            "data": {
                key: value
                for key, value in entry.data.items()
                if key not in REDACTED_CONFIG_KEYS
            },
        },
    }

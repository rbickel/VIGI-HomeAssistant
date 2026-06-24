"""Tests for diagnostics and integration-level helper functions."""

from __future__ import annotations

import asyncio
import importlib
import json

from custom_components.vigi_nvr.const import (
    CONF_EVENT_WEBHOOK_ID,
    DOMAIN,
    EVENT_VIGI_NVR_EVENT,
)
from custom_components.vigi_nvr.diagnostics import async_get_config_entry_diagnostics

from .conftest import FakeConfigEntry, FakeHass, FakeRequest, make_coordinator

integration = importlib.import_module("custom_components.vigi_nvr")


def test_diagnostics_redacts_sensitive_config_data() -> None:
    """Diagnostics omit secrets and stable webhook ids."""
    entry = FakeConfigEntry(
        title="Kitchen NVR",
        data={
            "host": "nvr.local",
            "username": "admin",
            "password": "secret",
            CONF_EVENT_WEBHOOK_ID: "webhook-id",
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(FakeHass(), entry))

    assert diagnostics == {
        "domain": DOMAIN,
        "entry": {
            "title": "Kitchen NVR",
            "data": {"host": "nvr.local", "username": "admin"},
        },
    }


def test_get_or_create_webhook_id_reuses_existing_value() -> None:
    """Existing webhook ids are reused without mutating config entry data."""
    hass = FakeHass()
    entry = FakeConfigEntry(data={CONF_EVENT_WEBHOOK_ID: "existing-id"})

    assert integration._get_or_create_webhook_id(hass, entry) == "existing-id"
    assert hass.config_entries.updated_entries == []


def test_get_or_create_webhook_id_generates_and_stores_missing_value(
    monkeypatch,
) -> None:
    """Missing webhook ids are generated and persisted to the entry data."""
    hass = FakeHass()
    entry = FakeConfigEntry(data={"host": "nvr.local"})
    monkeypatch.setattr(integration.webhook, "async_generate_id", lambda: "new-id")

    assert integration._get_or_create_webhook_id(hass, entry) == "new-id"
    assert entry.data == {"host": "nvr.local", CONF_EVENT_WEBHOOK_ID: "new-id"}
    assert hass.config_entries.updated_entries == [(entry, entry.data)]


def test_generate_webhook_url_falls_back_to_route_path(monkeypatch) -> None:
    """Webhook URL generation falls back when Home Assistant cannot build a URL."""

    def raise_url_error(*args, **kwargs):
        raise RuntimeError("no URL available")

    monkeypatch.setattr(integration.webhook, "async_generate_url", raise_url_error)

    assert integration._generate_webhook_url(FakeHass(), "webhook-id") == (
        "/api/webhook/webhook-id"
    )


def test_event_message_webhook_stores_push_and_fires_home_assistant_event() -> None:
    """Webhook handler parses pushes, updates coordinator state, and fires the bus."""
    coordinator = make_coordinator()
    entry = FakeConfigEntry(entry_id="entry-1")
    hass = FakeHass()
    body = json.dumps(
        {"messages": [{"type": 1, "sub_type": 18, "channel": "5"}]}
    ).encode()
    request = FakeRequest(body, remote="192.0.2.60")

    response = asyncio.run(
        integration._async_handle_event_message(hass, entry, coordinator, request)
    )

    assert response.status == 200
    assert json.loads(response.text) == {"error_code": 0}
    assert coordinator.last_event_push is not None
    assert coordinator.last_event_push.alarm_related is True
    assert coordinator.last_event_client_ip == "192.0.2.60"
    assert len(hass.bus.events) == 1
    event_type, event_data = hass.bus.events[0]
    assert event_type == EVENT_VIGI_NVR_EVENT
    assert event_data["entry_id"] == "entry-1"
    assert event_data["source_ip"] == "192.0.2.60"
    assert event_data["source_channel"] == 5
    assert event_data["alarm_related"] is True
    assert "received_at" in event_data
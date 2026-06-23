"""Constants for the TP-Link VIGI NVR integration."""

from __future__ import annotations

DOMAIN = "vigi_nvr"
DEFAULT_PORT = 20443
DEFAULT_VERIFY_TLS = False
DEFAULT_SCAN_INTERVAL_SECONDS = 60

CONF_VERIFY_TLS = "verify_tls"
CONF_EVENT_WEBHOOK_ID = "event_webhook_id"

EVENT_VIGI_NVR_EVENT = "vigi_nvr_event"

ATTR_CHANNEL = "channel"
ATTR_STREAM = "stream"

STREAM_MAIN = "main"
STREAM_MINOR = "minor"

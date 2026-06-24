"""Data coordinator for TP-Link VIGI NVR."""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VigiApiError, VigiNvrClient
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN, STREAM_MAIN, STREAM_MINOR
from .events import (
    EVENT_SUBTYPE_LABELS,
    EVENT_TYPE_LABELS,
    VigiEventImage,
    VigiEventPush,
    channel_from_mapping,
    normalize_subtypes,
)

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class VigiNvrData:
    """Polled VIGI NVR state."""

    devices: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    disks: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    esata_disks: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    event_servers: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    poe_info: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    poe_status: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    poe_link_mode: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    poe_link_status: str = ""
    timing_mode: dict[str, Any] = dataclasses.field(default_factory=dict)
    ntp: dict[str, Any] = dataclasses.field(default_factory=dict)
    audio_output: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)
    audio_input: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)
    resolutions: dict[tuple[int, str], dict[str, Any]] = dataclasses.field(
        default_factory=dict
    )
    bitrates: dict[tuple[int, str], dict[str, Any]] = dataclasses.field(
        default_factory=dict
    )


@dataclasses.dataclass(slots=True)
class VigiEventState:
    """Latched VIGI event state for Home Assistant entities."""

    event_type: int
    sub_type: int
    message: dict[str, Any]
    event: dict[str, Any]
    event_push: VigiEventPush
    received_at: dt.datetime
    client_ip: str | None
    channel: int | None
    disk: int | str | None

    def as_attributes(self) -> dict[str, Any]:
        """Return entity attributes for this event without raw image bytes."""
        sub_type_labels = self.message.get("sub_type_labels")
        if not isinstance(sub_type_labels, list):
            sub_type_labels = [
                EVENT_SUBTYPE_LABELS.get(self.event_type, {}).get(
                    self.sub_type,
                    "Unknown",
                )
            ]

        return {
            "received_at": self.received_at.isoformat(),
            "source_ip": self.client_ip,
            "type": self.event_type,
            "sub_type": self.sub_type,
            "type_label": self.message.get("type_label")
            or EVENT_TYPE_LABELS.get(self.event_type, "Unknown"),
            "sub_type_labels": sub_type_labels,
            "channel": self.channel,
            "disk": self.disk,
            "event_mode": self.event_push.mode,
            "message_count": self.event_push.message_count,
            "raw_bytes": self.event_push.raw_bytes,
            "content_type": self.event_push.content_type,
            "message": self.message,
        }


class VigiNvrCoordinator(DataUpdateCoordinator[VigiNvrData]):
    """Coordinate polling for VIGI NVR state."""

    def __init__(self, hass: HomeAssistant, client: VigiNvrClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.event_webhook_id: str | None = None
        self.event_webhook_url: str | None = None
        self.last_event_push: VigiEventPush | None = None
        self.last_event_image: VigiEventImage | None = None
        self.last_event_images_by_channel: dict[int, VigiEventImage] = {}
        self.last_event_pushes_by_channel: dict[int, VigiEventPush] = {}
        self.last_event_received_at_by_channel: dict[int, dt.datetime] = {}
        self.last_event_client_ip_by_channel: dict[int, str | None] = {}
        self.last_unassigned_event_image: VigiEventImage | None = None
        self.last_unassigned_event_push: VigiEventPush | None = None
        self.last_unassigned_event_received_at: dt.datetime | None = None
        self.last_unassigned_event_client_ip: str | None = None
        self.last_event_received_at: dt.datetime | None = None
        self.last_event_client_ip: str | None = None
        self.channel_event_states: dict[tuple[int, int, int], VigiEventState] = {}
        self.nvr_event_states: dict[tuple[int, int], VigiEventState] = {}

    def set_event_webhook(self, webhook_id: str, webhook_url: str) -> None:
        """Store the Home Assistant webhook information for entities."""
        self.event_webhook_id = webhook_id
        self.event_webhook_url = webhook_url

    def store_event_push(
        self,
        event_push: VigiEventPush,
        client_ip: str | None,
    ) -> dt.datetime:
        """Store the latest VIGI event push and notify entities."""
        received_at = dt.datetime.now(dt.UTC)
        self.last_event_push = event_push
        self.last_event_image = event_push.images[0] if event_push.images else None
        self.last_event_received_at = received_at
        self.last_event_client_ip = client_ip
        if event_push.images:
            self._store_event_image(event_push, received_at, client_ip)
        self._store_event_states(event_push, received_at, client_ip)
        self.async_set_updated_data(self.data)
        return received_at

    def channel_event_state(
        self,
        channel: int,
        event_type: int,
        sub_type: int,
    ) -> VigiEventState | None:
        """Return the latest matching event state for a channel."""
        return self.channel_event_states.get((channel, event_type, sub_type))

    def nvr_event_state(
        self,
        event_type: int,
        sub_type: int,
    ) -> VigiEventState | None:
        """Return the latest matching event state for the NVR device."""
        return self.nvr_event_states.get((event_type, sub_type))

    def _store_event_image(
        self,
        event_push: VigiEventPush,
        received_at: dt.datetime,
        client_ip: str | None,
    ) -> None:
        """Store the latest event image for its source channel when known."""
        image = event_push.images[0]
        source_channel = event_push.source_channel
        if source_channel is not None and self.has_channel(source_channel):
            self.last_event_images_by_channel[source_channel] = image
            self.last_event_pushes_by_channel[source_channel] = event_push
            self.last_event_received_at_by_channel[source_channel] = received_at
            self.last_event_client_ip_by_channel[source_channel] = client_ip
            return

        self.last_unassigned_event_image = image
        self.last_unassigned_event_push = event_push
        self.last_unassigned_event_received_at = received_at
        self.last_unassigned_event_client_ip = client_ip

    def _store_event_states(
        self,
        event_push: VigiEventPush,
        received_at: dt.datetime,
        client_ip: str | None,
    ) -> None:
        """Store latched event state by type/subtype and channel when available."""
        for event in event_push.events:
            messages = event.get("messages", [])
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                event_type = as_int(message.get("type"))
                if event_type is None:
                    continue
                for sub_type in normalize_subtypes(message.get("sub_type")):
                    state = VigiEventState(
                        event_type=event_type,
                        sub_type=sub_type,
                        message=message,
                        event=event,
                        event_push=event_push,
                        received_at=received_at,
                        client_ip=client_ip,
                        channel=event_channel(event, message),
                        disk=event_disk(event, message),
                    )
                    if (
                        event_type == 1
                        and state.channel is not None
                        and self.has_channel(state.channel)
                    ):
                        self.channel_event_states[
                            (state.channel, event_type, sub_type)
                        ] = state
                    else:
                        self.nvr_event_states[(event_type, sub_type)] = state

    def has_channel(self, channel: int) -> bool:
        """Return whether the latest coordinator data contains a channel."""
        return any(as_int(device.get("id")) == channel for device in self.data.devices)

    async def _async_update_data(self) -> VigiNvrData:
        """Fetch state data from the NVR."""
        try:
            devices = await self.client.async_get_added_devices()
            data = VigiNvrData(devices=devices)
            await self._populate_global_state(data)
            await self._populate_channel_state(data)
        except VigiApiError as error:
            raise UpdateFailed(str(error)) from error
        return data

    async def _populate_global_state(self, data: VigiNvrData) -> None:
        """Populate global read-only state, tolerating unsupported endpoints."""
        data.disks = await self._optional_list(self.client.async_get_disks)
        data.esata_disks = await self._optional_list(self.client.async_get_esata_disks)
        data.event_servers = await self._optional_list(
            self.client.async_get_event_servers
        )
        data.poe_info = await self._optional_list(self.client.async_get_poe_info)
        data.poe_status = await self._optional_list(self.client.async_get_poe_status)
        data.poe_link_mode = await self._optional_list(
            self.client.async_get_poe_link_mode
        )
        data.poe_link_status = await self._optional_value(
            self.client.async_get_poe_link_status,
            default="",
        )
        data.timing_mode = await self._optional_value(
            self.client.async_get_timing_mode,
            default={},
        )
        data.ntp = await self._optional_value(self.client.async_get_ntp, default={})

    async def _populate_channel_state(self, data: VigiNvrData) -> None:
        """Populate per-channel read-only state."""
        for device in data.devices:
            channel = as_int(device.get("id"))
            if channel is None:
                continue
            data.audio_output[channel] = await self._optional_value(
                self.client.async_get_audio_output_sound,
                channel,
                default={},
            )
            data.audio_input[channel] = await self._optional_value(
                self.client.async_get_audio_input_sound,
                channel,
                default={},
            )
            for stream in (STREAM_MAIN, STREAM_MINOR):
                data.resolutions[(channel, stream)] = await self._optional_value(
                    self.client.async_get_resolution,
                    channel,
                    stream,
                    default={},
                )
                data.bitrates[(channel, stream)] = await self._optional_value(
                    self.client.async_get_bitrate,
                    channel,
                    stream,
                    default={},
                )

    async def _optional_list(self, func: Any, *args: Any) -> list[dict[str, Any]]:
        """Call an optional endpoint and return an empty list if unsupported."""
        try:
            value = await func(*args)
        except VigiApiError as error:
            LOGGER.debug("Optional VIGI endpoint failed: %s", error)
            return []
        return value if isinstance(value, list) else []

    async def _optional_value(self, func: Any, *args: Any, default: Any) -> Any:
        """Call an optional endpoint and return a default if unsupported."""
        try:
            return await func(*args)
        except VigiApiError as error:
            LOGGER.debug("Optional VIGI endpoint failed: %s", error)
            return default


def as_int(value: Any) -> int | None:
    """Convert VIGI numeric values to int when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def event_channel(event: dict[str, Any], message: dict[str, Any]) -> int | None:
    """Return the channel for a VIGI event message when present."""
    channel = channel_from_mapping(message)
    if channel is not None:
        return channel
    return channel_from_mapping(event)


def event_disk(
    event: dict[str, Any],
    message: dict[str, Any],
) -> int | str | None:
    """Return disk metadata for a VIGI event message when present."""
    value = message.get("disk")
    if value is None:
        value = event.get("disk")
    disk = as_int(value)
    return disk if disk is not None else value

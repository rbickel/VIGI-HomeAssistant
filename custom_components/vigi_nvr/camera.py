"""Camera platform for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiNvrCoordinator
from .entity import VigiChannelEntity, VigiNvrEntity, as_int
from .events import VigiEventImage, VigiEventPush


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIGI NVR cameras."""
    coordinator: VigiNvrCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[Camera] = [
        VigiUnassignedLastEventImageCamera(coordinator, entry.entry_id)
    ]
    for device in coordinator.data.devices:
        channel = as_int(device.get("id"))
        if channel is None:
            continue
        entities.extend(
            [
                VigiChannelLiveCamera(coordinator, entry.entry_id, channel, 1),
                VigiChannelLiveCamera(coordinator, entry.entry_id, channel, 2),
            ]
        )
        entities.append(
            VigiChannelLastEventImageCamera(coordinator, entry.entry_id, channel)
        )
    async_add_entities(entities)


class VigiChannelLiveCamera(VigiChannelEntity, Camera):
    """Camera exposing a documented VIGI RTSP live stream."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        stream: int,
    ) -> None:
        """Initialize a channel live stream camera."""
        VigiChannelEntity.__init__(
            self,
            coordinator,
            entry_id,
            channel,
            f"live_stream_{stream}",
        )
        Camera.__init__(self)
        self._stream = stream
        self._attr_name = f"Live stream {stream}"

    @property
    def available(self) -> bool:
        """Return whether the live stream source can be generated."""
        return self.coordinator.last_update_success and bool(self.channel_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return live stream metadata."""
        return {
            "channel": self.channel,
            "stream": self._stream,
            "rtsp_url": self.coordinator.client.live_stream_url(
                self.channel,
                self._stream,
            ),
        }

    async def stream_source(self) -> str | None:
        """Return the RTSP source URL for Home Assistant stream handling."""
        if not self.available:
            return None
        return self.coordinator.client.live_stream_url(
            self.channel,
            self._stream,
            include_credentials=True,
        )


class VigiEventImageCameraMixin:
    """Mixin exposing a latest image attached to a VIGI event push."""

    _attr_name = "Last event image"

    @property
    def event_image(self) -> VigiEventImage | None:
        """Return the latest event image for this entity."""
        raise NotImplementedError

    @property
    def event_push(self) -> VigiEventPush | None:
        """Return the event push associated with the latest image."""
        raise NotImplementedError

    @property
    def received_at(self) -> Any:
        """Return the timestamp associated with the latest image."""
        raise NotImplementedError

    @property
    def source_ip(self) -> str | None:
        """Return the source IP associated with the latest image."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Return whether a latest event image is available."""
        return self.coordinator.last_update_success and self.event_image is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return metadata for the latest event image."""
        image = self.event_image
        event_push = self.event_push
        received_at = self.received_at
        return {
            "image": image.as_dict() if image else None,
            "received_at": received_at.isoformat() if received_at else None,
            "source_ip": self.source_ip,
            "source_channel": event_push.source_channel if event_push else None,
            "last_message": event_push.last_message if event_push else None,
        }

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return bytes for the latest VIGI event image."""
        image = self.event_image
        if image is None:
            return None
        self.content_type = image.content_type
        return image.data


class VigiChannelLastEventImageCamera(
    VigiEventImageCameraMixin,
    VigiChannelEntity,
    Camera,
):
    """Camera exposing the latest event image for a VIGI channel."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
    ) -> None:
        """Initialize a channel latest event image camera."""
        VigiChannelEntity.__init__(
            self, coordinator, entry_id, channel, "last_event_image"
        )
        Camera.__init__(self)

    @property
    def event_image(self) -> VigiEventImage | None:
        """Return the latest event image for this channel."""
        return self.coordinator.last_event_images_by_channel.get(self.channel)

    @property
    def event_push(self) -> VigiEventPush | None:
        """Return the event push associated with the latest channel image."""
        return self.coordinator.last_event_pushes_by_channel.get(self.channel)

    @property
    def received_at(self) -> Any:
        """Return the timestamp associated with the latest channel image."""
        return self.coordinator.last_event_received_at_by_channel.get(self.channel)

    @property
    def source_ip(self) -> str | None:
        """Return the source IP associated with the latest channel image."""
        return self.coordinator.last_event_client_ip_by_channel.get(self.channel)


class VigiUnassignedLastEventImageCamera(
    VigiEventImageCameraMixin,
    VigiNvrEntity,
    Camera,
):
    """Camera exposing event images that cannot be mapped to a known channel."""

    _attr_name = "Unassigned event image"

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        """Initialize the unassigned latest event image camera."""
        VigiNvrEntity.__init__(self, coordinator, entry_id, "unassigned_event_image")
        Camera.__init__(self)

    @property
    def event_image(self) -> VigiEventImage | None:
        """Return the latest event image without a known source channel."""
        return self.coordinator.last_unassigned_event_image

    @property
    def event_push(self) -> VigiEventPush | None:
        """Return the event push associated with the latest unassigned image."""
        return self.coordinator.last_unassigned_event_push

    @property
    def received_at(self) -> Any:
        """Return the timestamp associated with the latest unassigned image."""
        return self.coordinator.last_unassigned_event_received_at

    @property
    def source_ip(self) -> str | None:
        """Return the source IP associated with the latest unassigned image."""
        return self.coordinator.last_unassigned_event_client_ip

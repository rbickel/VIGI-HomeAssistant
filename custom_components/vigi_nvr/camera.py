"""Camera platform for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiNvrCoordinator
from .entity import VigiNvrEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIGI NVR cameras."""
    coordinator: VigiNvrCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VigiLastEventImageCamera(coordinator, entry.entry_id)])


class VigiLastEventImageCamera(VigiNvrEntity, Camera):
    """Camera exposing the latest image attached to a VIGI event push."""

    _attr_name = "Last event image"

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        """Initialize the latest event image camera."""
        VigiNvrEntity.__init__(self, coordinator, entry_id, "last_event_image")
        Camera.__init__(self)

    @property
    def available(self) -> bool:
        """Return whether a latest event image is available."""
        return super().available and self.coordinator.last_event_image is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return metadata for the latest event image."""
        image = self.coordinator.last_event_image
        return {
            "image": image.as_dict() if image else None,
            "received_at": (
                self.coordinator.last_event_received_at.isoformat()
                if self.coordinator.last_event_received_at
                else None
            ),
            "source_ip": self.coordinator.last_event_client_ip,
            "last_message": (
                self.coordinator.last_event_push.last_message
                if self.coordinator.last_event_push
                else None
            ),
        }

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return bytes for the latest VIGI event image."""
        image = self.coordinator.last_event_image
        if image is None:
            return None
        self.content_type = image.content_type
        return image.data

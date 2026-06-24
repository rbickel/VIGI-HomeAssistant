"""Base entities for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VigiNvrCoordinator


class VigiNvrEntity(CoordinatorEntity[VigiNvrCoordinator]):
    """Base VIGI NVR entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: VigiNvrCoordinator, entry_id: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._entry_id = entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return NVR device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="VIGI NVR",
            manufacturer="TP-Link",
            model="VIGI NVR",
        )


class VigiChannelEntity(VigiNvrEntity):
    """Base VIGI channel entity."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        key: str,
    ) -> None:
        super().__init__(coordinator, entry_id, f"channel_{channel}_{key}")
        self.channel = channel

    @property
    def channel_data(self) -> dict[str, Any]:
        """Return the latest data for this channel."""
        for device in self.coordinator.data.devices:
            if as_int(device.get("id")) == self.channel:
                return device
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return channel device information."""
        channel = self.channel_data
        name = (
            channel.get("name")
            or channel.get("alias")
            or f"VIGI Channel {self.channel}"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_channel_{self.channel}")},
            name=str(name),
            manufacturer="TP-Link",
            model="VIGI Camera Channel",
            via_device=(DOMAIN, self._entry_id),
        )


def as_int(value: Any) -> int | None:
    """Convert a VIGI value to int when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

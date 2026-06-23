"""Binary sensor platform for TP-Link VIGI NVR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VigiNvrCoordinator
from .entity import VigiChannelEntity, VigiNvrEntity, as_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIGI NVR binary sensors."""
    coordinator: VigiNvrCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []

    for device in coordinator.data.devices:
        channel = as_int(device.get("id"))
        if channel is None:
            continue
        entities.append(VigiChannelOnlineBinarySensor(coordinator, entry.entry_id, channel))

    for port in poe_ports(coordinator.data):
        entities.append(VigiPoePortLinkedBinarySensor(coordinator, entry.entry_id, port))

    entities.append(VigiAlarmEventServerConfiguredBinarySensor(coordinator, entry.entry_id))
    entities.append(VigiLastEventAlarmRelatedBinarySensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class VigiChannelOnlineBinarySensor(VigiChannelEntity, BinarySensorEntity):
    """Channel online binary sensor."""

    entity_description = BinarySensorEntityDescription(
        key="online",
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    )
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, "online")

    @property
    def is_on(self) -> bool | None:
        value = self.channel_data.get("online")
        if value is None:
            return None
        return str(value) == "1"


class VigiPoePortLinkedBinarySensor(VigiNvrEntity, BinarySensorEntity):
    """PoE port link binary sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        port: int,
    ) -> None:
        super().__init__(coordinator, entry_id, f"poe_port_{port}_linked")
        self.entity_description = BinarySensorEntityDescription(
            key="poe_port_linked",
            name=f"PoE port {port} linked",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        )
        self._port = port

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data.poe_link_status
        if not status or self._port < 1 or self._port > len(status):
            return None
        return status[self._port - 1] == "1"


class VigiAlarmEventServerConfiguredBinarySensor(VigiNvrEntity, BinarySensorEntity):
    """Whether an NVR event push server is configured."""

    entity_description = BinarySensorEntityDescription(
        key="event_server_configured",
        name="Event server configured",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    )
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "event_server_configured")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.event_servers)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "event_servers": self.coordinator.data.event_servers,
            "webhook_url": self.coordinator.event_webhook_url,
            "webhook_id": self.coordinator.event_webhook_id,
        }


class VigiLastEventAlarmRelatedBinarySensor(VigiNvrEntity, BinarySensorEntity):
    """Whether the latest pushed event is alarm-related."""

    entity_description = BinarySensorEntityDescription(
        key="last_event_alarm_related",
        name="Last event alarm related",
    )

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "last_event_alarm_related")

    @property
    def is_on(self) -> bool | None:
        event_push = self.coordinator.last_event_push
        return event_push.alarm_related if event_push is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event_push = self.coordinator.last_event_push
        last_message = event_push.last_message if event_push is not None else None
        return {
            "received_at": (
                self.coordinator.last_event_received_at.isoformat()
                if self.coordinator.last_event_received_at
                else None
            ),
            "source_ip": self.coordinator.last_event_client_ip,
            "last_message": last_message,
        }


def poe_ports(data: Any) -> set[int]:
    """Return known PoE ports from info/status/link status data."""
    ports: set[int] = set()
    for item in data.poe_info:
        port = as_int(item.get("port"))
        if port is not None:
            ports.add(port)
    if data.poe_link_status:
        ports.update(range(1, len(data.poe_link_status) + 1))
    return ports

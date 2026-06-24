"""Binary sensor platform for TP-Link VIGI NVR."""

from __future__ import annotations

import dataclasses
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
from .coordinator import VigiEventState, VigiNvrCoordinator
from .entity import VigiChannelEntity, VigiNvrEntity, as_int


@dataclasses.dataclass(frozen=True, kw_only=True)
class VigiEventBinarySensorDescription(BinarySensorEntityDescription):
    """Description for a latched VIGI event binary sensor."""

    event_type: int
    sub_type: int


CHANNEL_EVENT_BINARY_SENSOR_DESCRIPTIONS: tuple[
    VigiEventBinarySensorDescription,
    ...,
] = (
    VigiEventBinarySensorDescription(
        key="event_motion_detection",
        name="Motion detection",
        device_class=BinarySensorDeviceClass.MOTION,
        event_type=1,
        sub_type=2,
    ),
    VigiEventBinarySensorDescription(
        key="event_human_detection",
        name="Human detection",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        event_type=1,
        sub_type=21,
    ),
    VigiEventBinarySensorDescription(
        key="event_vehicle_detection",
        name="Vehicle detection",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        event_type=1,
        sub_type=22,
    ),
    VigiEventBinarySensorDescription(
        key="event_camera_tampering",
        name="Camera tampering",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=1,
        sub_type=3,
    ),
    VigiEventBinarySensorDescription(
        key="event_line_crossing_detection",
        name="Line crossing detection",
        device_class=BinarySensorDeviceClass.MOTION,
        event_type=1,
        sub_type=4,
    ),
    VigiEventBinarySensorDescription(
        key="event_intrusion_detection",
        name="Intrusion detection",
        device_class=BinarySensorDeviceClass.MOTION,
        event_type=1,
        sub_type=5,
    ),
    VigiEventBinarySensorDescription(
        key="event_video_loss",
        name="Video loss",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=1,
        sub_type=19,
    ),
    VigiEventBinarySensorDescription(
        key="event_alarm_signal",
        name="Alarm signal",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=1,
        sub_type=18,
    ),
)


NVR_EVENT_BINARY_SENSOR_DESCRIPTIONS: tuple[
    VigiEventBinarySensorDescription,
    ...,
] = (
    VigiEventBinarySensorDescription(
        key="event_disk_missing",
        name="Disk missing",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=3,
    ),
    VigiEventBinarySensorDescription(
        key="event_disk_full",
        name="Disk full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=4,
    ),
    VigiEventBinarySensorDescription(
        key="event_device_offline",
        name="Device offline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=5,
    ),
    VigiEventBinarySensorDescription(
        key="event_disk_error",
        name="Disk error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=7,
    ),
    VigiEventBinarySensorDescription(
        key="event_poe_port_short",
        name="PoE port short",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=9,
    ),
    VigiEventBinarySensorDescription(
        key="event_poe_port_overload",
        name="PoE port overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=10,
    ),
    VigiEventBinarySensorDescription(
        key="event_poe_temperature_error",
        name="PoE temperature error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=11,
    ),
    VigiEventBinarySensorDescription(
        key="event_poe_total_overload",
        name="PoE total overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=12,
    ),
    VigiEventBinarySensorDescription(
        key="event_alarm_input",
        name="Alarm input",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=13,
    ),
    VigiEventBinarySensorDescription(
        key="event_fan_abnormal",
        name="Fan abnormal",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=2,
        sub_type=14,
    ),
    VigiEventBinarySensorDescription(
        key="event_raid_offline",
        name="RAID offline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=7,
        sub_type=1,
    ),
    VigiEventBinarySensorDescription(
        key="event_raid_degraded",
        name="RAID degraded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=7,
        sub_type=2,
    ),
    VigiEventBinarySensorDescription(
        key="event_storage_full",
        name="Storage full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=7,
        sub_type=6,
    ),
    VigiEventBinarySensorDescription(
        key="event_no_hd",
        name="No HD",
        device_class=BinarySensorDeviceClass.PROBLEM,
        event_type=7,
        sub_type=7,
    ),
)


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
        entities.append(
            VigiChannelOnlineBinarySensor(coordinator, entry.entry_id, channel)
        )
        entities.extend(
            VigiChannelEventBinarySensor(
                coordinator,
                entry.entry_id,
                channel,
                description,
            )
            for description in CHANNEL_EVENT_BINARY_SENSOR_DESCRIPTIONS
        )

    for port in poe_ports(coordinator.data):
        entities.append(
            VigiPoePortLinkedBinarySensor(coordinator, entry.entry_id, port)
        )

    entities.append(
        VigiAlarmEventServerConfiguredBinarySensor(coordinator, entry.entry_id)
    )
    entities.append(VigiLastEventAlarmRelatedBinarySensor(coordinator, entry.entry_id))
    entities.extend(
        VigiNvrEventBinarySensor(coordinator, entry.entry_id, description)
        for description in NVR_EVENT_BINARY_SENSOR_DESCRIPTIONS
    )
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


class VigiChannelEventBinarySensor(VigiChannelEntity, BinarySensorEntity):
    """Latched per-channel VIGI event binary sensor."""

    entity_description: VigiEventBinarySensorDescription

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        description: VigiEventBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return True if self.event_state is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return event_state_attributes(self.event_state)

    @property
    def event_state(self) -> VigiEventState | None:
        return self.coordinator.channel_event_state(
            self.channel,
            self.entity_description.event_type,
            self.entity_description.sub_type,
        )


class VigiNvrEventBinarySensor(VigiNvrEntity, BinarySensorEntity):
    """Latched NVR-level VIGI exception event binary sensor."""

    entity_description: VigiEventBinarySensorDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        description: VigiEventBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return True if self.event_state is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return event_state_attributes(self.event_state)

    @property
    def event_state(self) -> VigiEventState | None:
        return self.coordinator.nvr_event_state(
            self.entity_description.event_type,
            self.entity_description.sub_type,
        )


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


def event_state_attributes(event_state: VigiEventState | None) -> dict[str, Any]:
    """Return attributes for a latched event binary sensor."""
    if event_state is None:
        return {
            "received_at": None,
            "source_ip": None,
            "type": None,
            "sub_type": None,
            "type_label": None,
            "sub_type_labels": [],
            "channel": None,
            "disk": None,
            "message": None,
        }
    return event_state.as_attributes()

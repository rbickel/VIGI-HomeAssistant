"""Sensor platform for TP-Link VIGI NVR."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STREAM_MAIN, STREAM_MINOR
from .coordinator import VigiNvrCoordinator
from .entity import VigiChannelEntity, VigiNvrEntity, as_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up VIGI NVR sensors."""
    coordinator: VigiNvrCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        VigiNvrCountSensor(coordinator, entry.entry_id, "channels", "Channels", "devices"),
        VigiNvrCountSensor(coordinator, entry.entry_id, "disks", "Disks", "disks"),
        VigiNvrCountSensor(
            coordinator,
            entry.entry_id,
            "event_servers",
            "Event servers",
            "event_servers",
        ),
        VigiNvrTimingModeSensor(coordinator, entry.entry_id),
        VigiNvrNtpServerSensor(coordinator, entry.entry_id),
        VigiNvrPoeTotalPowerSensor(coordinator, entry.entry_id),
        VigiNvrPoeCostPowerSensor(coordinator, entry.entry_id),
    ]

    for disk in coordinator.data.disks:
        disk_id = as_int(disk.get("id"))
        if disk_id is None:
            disk_id = as_int(disk.get("slot"))
        if disk_id is None:
            continue
        entities.extend(
            [
                VigiDiskSensor(
                    coordinator,
                    entry.entry_id,
                    disk_id,
                    "status",
                    "Status",
                    lambda value: value.get("status"),
                ),
                VigiDiskSensor(
                    coordinator,
                    entry.entry_id,
                    disk_id,
                    "free_space",
                    "Free space",
                    lambda value: value.get("free_space"),
                ),
                VigiDiskSensor(
                    coordinator,
                    entry.entry_id,
                    disk_id,
                    "total_space",
                    "Total space",
                    lambda value: value.get("total_space"),
                ),
            ]
        )

    for device in coordinator.data.devices:
        channel = as_int(device.get("id"))
        if channel is None:
            continue
        entities.extend(
            [
                VigiChannelStaticSensor(
                    coordinator,
                    entry.entry_id,
                    channel,
                    "ip",
                    "IP address",
                    lambda value: value.get("ip"),
                ),
                VigiChannelStaticSensor(
                    coordinator,
                    entry.entry_id,
                    channel,
                    "mac",
                    "MAC address",
                    lambda value: value.get("mac"),
                ),
                VigiChannelAudioSensor(
                    coordinator,
                    entry.entry_id,
                    channel,
                    "output_volume",
                    "Output volume",
                    lambda value: value.get("volume"),
                ),
                VigiChannelAudioSensor(
                    coordinator,
                    entry.entry_id,
                    channel,
                    "system_volume",
                    "System volume",
                    lambda value: value.get("system_volume"),
                ),
                VigiChannelAudioInputSensor(
                    coordinator,
                    entry.entry_id,
                    channel,
                    "input_volume",
                    "Input volume",
                    lambda value: value.get("volume"),
                ),
                VigiChannelRtspSensor(coordinator, entry.entry_id, channel, 1),
                VigiChannelRtspSensor(coordinator, entry.entry_id, channel, 2),
            ]
        )
        for stream in (STREAM_MAIN, STREAM_MINOR):
            entities.extend(
                [
                    VigiChannelStreamSensor(
                        coordinator,
                        entry.entry_id,
                        channel,
                        stream,
                        "resolution",
                        f"{stream.title()} resolution",
                        lambda value: value.get("resolution"),
                    ),
                    VigiChannelStreamSensor(
                        coordinator,
                        entry.entry_id,
                        channel,
                        stream,
                        "bitrate",
                        f"{stream.title()} bitrate",
                        lambda value: value.get("maximun_bitrate"),
                    ),
                ]
            )

    async_add_entities(entities)


class VigiNvrCountSensor(VigiNvrEntity, SensorEntity):
    """Count sensor for a top-level VIGI list."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        key: str,
        name: str,
        data_key: str,
    ) -> None:
        super().__init__(coordinator, entry_id, key)
        self.entity_description = SensorEntityDescription(key=key, name=name)
        self._data_key = data_key
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int:
        return len(getattr(self.coordinator.data, self._data_key))


class VigiNvrTimingModeSensor(VigiNvrEntity, SensorEntity):
    """Timing mode sensor."""

    entity_description = SensorEntityDescription(key="timing_mode", name="Timing mode")
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "timing_mode")

    @property
    def native_value(self) -> str | None:
        value = self.coordinator.data.timing_mode.get("mode")
        return str(value) if value is not None else None


class VigiNvrNtpServerSensor(VigiNvrEntity, SensorEntity):
    """NTP server sensor."""

    entity_description = SensorEntityDescription(key="ntp_server", name="NTP server")
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "ntp_server")

    @property
    def native_value(self) -> str | None:
        value = self.coordinator.data.ntp.get("server")
        return str(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        port = self.coordinator.data.ntp.get("port")
        return {"port": port} if port is not None else {}


class VigiNvrPoeTotalPowerSensor(VigiNvrEntity, SensorEntity):
    """PoE total power sensor."""

    entity_description = SensorEntityDescription(
        key="poe_total_power",
        name="PoE total power",
        native_unit_of_measurement=UnitOfPower.WATT,
    )
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "poe_total_power")

    @property
    def native_value(self) -> float | None:
        global_status = poe_global_status(self.coordinator.data.poe_status)
        value = global_status.get("sys_power")
        return value / 10 if isinstance(value, int) else None


class VigiNvrPoeCostPowerSensor(VigiNvrEntity, SensorEntity):
    """PoE consumed power sensor."""

    entity_description = SensorEntityDescription(
        key="poe_cost_power",
        name="PoE used power",
        native_unit_of_measurement=UnitOfPower.WATT,
    )
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigiNvrCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "poe_cost_power")

    @property
    def native_value(self) -> float | None:
        global_status = poe_global_status(self.coordinator.data.poe_status)
        value = global_status.get("cost_power")
        return value / 10 if isinstance(value, int) else None


class VigiDiskSensor(VigiNvrEntity, SensorEntity):
    """Disk metadata sensor."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        disk_id: int,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        super().__init__(coordinator, entry_id, f"disk_{disk_id}_{key}")
        self.entity_description = SensorEntityDescription(key=key, name=f"Disk {disk_id} {name}")
        self._disk_id = disk_id
        self._value_fn = value_fn
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.disk_data)

    @property
    def disk_data(self) -> dict[str, Any]:
        for disk in self.coordinator.data.disks:
            if as_int(disk.get("id")) == self._disk_id or as_int(disk.get("slot")) == self._disk_id:
                return disk
        return {}


class VigiChannelStaticSensor(VigiChannelEntity, SensorEntity):
    """Channel metadata sensor."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        super().__init__(coordinator, entry_id, channel, key)
        self.entity_description = SensorEntityDescription(key=key, name=name)
        self._value_fn = value_fn
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.channel_data)


class VigiChannelAudioSensor(VigiChannelEntity, SensorEntity):
    """Channel audio output sensor."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        super().__init__(coordinator, entry_id, channel, key)
        self.entity_description = SensorEntityDescription(key=key, name=name)
        self._value_fn = value_fn
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.coordinator.data.audio_output.get(self.channel, {}))


class VigiChannelAudioInputSensor(VigiChannelAudioSensor):
    """Channel audio input sensor."""

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.coordinator.data.audio_input.get(self.channel, {}))


class VigiChannelStreamSensor(VigiChannelEntity, SensorEntity):
    """Channel stream metadata sensor."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        stream: str,
        key: str,
        name: str,
        value_fn: Callable[[dict[str, Any]], Any],
    ) -> None:
        super().__init__(coordinator, entry_id, channel, f"{stream}_{key}")
        self.entity_description = SensorEntityDescription(key=f"{stream}_{key}", name=name)
        self._stream = stream
        self._value_fn = value_fn
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        if self.entity_description.key.endswith("resolution"):
            source = self.coordinator.data.resolutions
        else:
            source = self.coordinator.data.bitrates
        return self._value_fn(source.get((self.channel, self._stream), {}))


class VigiChannelRtspSensor(VigiChannelEntity, SensorEntity):
    """RTSP stream URL sensor."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
        stream: int,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, f"rtsp_stream_{stream}")
        self.entity_description = SensorEntityDescription(
            key=f"rtsp_stream_{stream}",
            name=f"RTSP stream {stream}",
        )
        self._stream = stream
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.client.live_stream_url(self.channel, self._stream)


def poe_global_status(status: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the global PoE status object."""
    for item in status:
        value = item.get("global")
        if isinstance(value, dict):
            return value
    return {}

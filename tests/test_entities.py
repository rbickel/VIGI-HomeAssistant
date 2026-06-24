"""Tests for entity value logic."""

from __future__ import annotations

import asyncio
import datetime as dt

from custom_components.vigi_nvr.binary_sensor import (
    VigiAlarmEventServerConfiguredBinarySensor,
    VigiChannelOnlineBinarySensor,
    VigiLastEventAlarmRelatedBinarySensor,
    VigiPoePortLinkedBinarySensor,
    poe_ports as binary_sensor_poe_ports,
)
from custom_components.vigi_nvr.camera import (
    VigiChannelLastEventImageCamera,
    VigiUnassignedLastEventImageCamera,
)
from custom_components.vigi_nvr.coordinator import VigiNvrData
from custom_components.vigi_nvr.entity import VigiChannelEntity
from custom_components.vigi_nvr.events import VigiEventImage, VigiEventPush
from custom_components.vigi_nvr.sensor import (
    VigiChannelRtspSensor,
    VigiChannelStaticSensor,
    VigiChannelStreamSensor,
    VigiDiskSensor,
    VigiEventWebhookUrlSensor,
    VigiLastEventReceivedSensor,
    VigiLastEventSensor,
    VigiNvrCountSensor,
    VigiNvrNtpServerSensor,
    VigiNvrPoeCostPowerSensor,
    VigiNvrPoeTotalPowerSensor,
    VigiNvrTimingModeSensor,
    poe_global_status,
)
from custom_components.vigi_nvr.switch import (
    VigiAudioInputMuteSwitch,
    VigiAudioNoiseCancellingSwitch,
    VigiAudioOutputMuteSwitch,
    VigiPoePortEnableSwitch,
)

from .conftest import RecordingClient, make_coordinator, populated_data


def test_channel_entity_returns_matching_channel_data_and_device_info() -> None:
    """Channel entities resolve numeric string ids and expose device metadata."""
    coordinator = make_coordinator(data=populated_data())
    entity = VigiChannelEntity(coordinator, "entry-1", 1, "metadata")
    missing_entity = VigiChannelEntity(coordinator, "entry-1", 99, "metadata")

    assert entity.channel_data["name"] == "Front Door"
    assert missing_entity.channel_data == {}
    assert entity.device_info["name"] == "Front Door"
    assert entity.device_info["via_device"] == ("vigi_nvr", "entry-1")


def test_binary_sensors_calculate_values_and_attributes() -> None:
    """Binary sensors expose channel, PoE, event server, and last-event state."""
    coordinator = make_coordinator(data=populated_data())
    coordinator.set_event_webhook("webhook-id", "http://ha.local/api/webhook/id")
    event_push = VigiEventPush(
        mode="json",
        event={"messages": [{"alarm_related": True, "type_label": "Alarm"}]},
        events=[{"messages": [{"alarm_related": True, "type_label": "Alarm"}]}],
        images=[],
        raw_bytes=1,
        content_type="application/json",
    )
    coordinator.last_event_push = event_push
    coordinator.last_event_received_at = dt.datetime(2026, 6, 24, tzinfo=dt.UTC)
    coordinator.last_event_client_ip = "192.0.2.25"

    assert VigiChannelOnlineBinarySensor(coordinator, "entry-1", 1).is_on is True
    assert VigiChannelOnlineBinarySensor(coordinator, "entry-1", 99).is_on is None
    assert VigiPoePortLinkedBinarySensor(coordinator, "entry-1", 1).is_on is True
    assert VigiPoePortLinkedBinarySensor(coordinator, "entry-1", 2).is_on is False
    assert VigiPoePortLinkedBinarySensor(coordinator, "entry-1", 4).is_on is None
    assert binary_sensor_poe_ports(coordinator.data) == {1, 2, 3}

    event_server = VigiAlarmEventServerConfiguredBinarySensor(coordinator, "entry-1")
    assert event_server.is_on is True
    assert event_server.extra_state_attributes == {
        "event_servers": [{"id": 1, "url": "/api/webhook/test"}],
        "webhook_url": "http://ha.local/api/webhook/id",
        "webhook_id": "webhook-id",
    }

    alarm_sensor = VigiLastEventAlarmRelatedBinarySensor(coordinator, "entry-1")
    assert alarm_sensor.is_on is True
    assert alarm_sensor.extra_state_attributes == {
        "received_at": "2026-06-24T00:00:00+00:00",
        "source_ip": "192.0.2.25",
        "last_message": {"alarm_related": True, "type_label": "Alarm"},
    }


def test_sensors_calculate_static_power_event_and_url_values() -> None:
    """Sensor entities compute values from coordinator data and client helpers."""
    coordinator = make_coordinator(data=populated_data())
    coordinator.set_event_webhook(
        "webhook-id",
        "http://ha.local:8123/api/webhook/webhook-id",
    )
    event_push = VigiEventPush(
        mode="json",
        event={"messages": [{"sub_type_labels": ["Motion", "Alarm"]}]},
        events=[{"messages": [{"sub_type_labels": ["Motion", "Alarm"]}]}],
        images=[],
        raw_bytes=1,
        content_type="application/json",
    )
    coordinator.last_event_push = event_push
    coordinator.last_event_received_at = dt.datetime(2026, 6, 24, 12, tzinfo=dt.UTC)
    coordinator.last_event_client_ip = "192.0.2.30"

    assert VigiNvrCountSensor(
        coordinator,
        "entry-1",
        "channels",
        "Channels",
        "devices",
    ).native_value == 2
    assert VigiNvrTimingModeSensor(coordinator, "entry-1").native_value == "ntp"
    assert VigiNvrNtpServerSensor(coordinator, "entry-1").native_value == "pool.ntp.org"
    assert VigiNvrNtpServerSensor(coordinator, "entry-1").extra_state_attributes == {
        "port": 123
    }
    assert poe_global_status(coordinator.data.poe_status) == {
        "sys_power": 123,
        "cost_power": 45,
    }
    assert VigiNvrPoeTotalPowerSensor(coordinator, "entry-1").native_value == 12.3
    assert VigiNvrPoeCostPowerSensor(coordinator, "entry-1").native_value == 4.5
    assert VigiDiskSensor(
        coordinator,
        "entry-1",
        2,
        "status",
        "Status",
        lambda value: value.get("status"),
    ).native_value == "missing"
    assert VigiChannelStaticSensor(
        coordinator,
        "entry-1",
        1,
        "ip",
        "IP address",
        lambda value: value.get("ip"),
    ).native_value == "192.0.2.20"
    assert VigiChannelStreamSensor(
        coordinator,
        "entry-1",
        1,
        "main",
        "resolution",
        "Main resolution",
        lambda value: value.get("resolution"),
    ).native_value == "2560x1440"
    assert VigiChannelStreamSensor(
        coordinator,
        "entry-1",
        1,
        "minor",
        "bitrate",
        "Minor bitrate",
        lambda value: value.get("maximun_bitrate"),
    ).native_value == "1024"
    assert VigiChannelRtspSensor(coordinator, "entry-1", 1, 2).native_value == (
        "rtsp://nvr.local/live/1/2/avm"
    )

    webhook_sensor = VigiEventWebhookUrlSensor(coordinator, "entry-1")
    assert webhook_sensor.native_value == "http://ha.local:8123/api/webhook/webhook-id"
    assert webhook_sensor.extra_state_attributes == {
        "webhook_id": "webhook-id",
        "event_server_protocol": "HTTP",
        "event_server_host": "ha.local",
        "event_server_port": 8123,
        "event_server_url": "/api/webhook/webhook-id",
    }
    assert VigiLastEventSensor(coordinator, "entry-1").native_value == "Motion, Alarm"
    assert VigiLastEventReceivedSensor(coordinator, "entry-1").native_value == (
        dt.datetime(2026, 6, 24, 12, tzinfo=dt.UTC)
    )


def test_last_event_sensor_falls_back_to_type_or_mode() -> None:
    """Last-event sensor chooses labels, type metadata, then mode."""
    coordinator = make_coordinator(data=VigiNvrData())
    sensor = VigiLastEventSensor(coordinator, "entry-1")

    assert sensor.native_value is None

    coordinator.last_event_push = VigiEventPush(
        mode="raw",
        event={"messages": [{"type_label": "Device exception"}]},
        events=[{"messages": [{"type_label": "Device exception"}]}],
        images=[],
        raw_bytes=1,
        content_type="application/json",
    )
    assert sensor.native_value == "Device exception"

    coordinator.last_event_push = VigiEventPush(
        mode="raw",
        event={"messages": [{}]},
        events=[{"messages": [{}]}],
        images=[],
        raw_bytes=1,
        content_type="application/json",
    )
    assert sensor.native_value == "raw"


def test_switches_call_client_with_existing_state_and_refresh() -> None:
    """Switch commands preserve companion settings and request refreshes."""
    client = RecordingClient()
    coordinator = make_coordinator(data=populated_data(), client=client)

    asyncio.run(VigiAudioOutputMuteSwitch(coordinator, "entry-1", 1).async_turn_on())
    asyncio.run(VigiAudioInputMuteSwitch(coordinator, "entry-1", 1).async_turn_off())
    asyncio.run(
        VigiAudioNoiseCancellingSwitch(coordinator, "entry-1", 1).async_turn_on()
    )
    asyncio.run(VigiPoePortEnableSwitch(coordinator, "entry-1", 2).async_turn_off())

    assert client.calls == [
        ("async_set_audio_output_sound", (1, "on", 7, 9)),
        ("async_set_audio_input_sound", (1, "off", 3, "off")),
        ("async_set_audio_input_sound", (1, "on", 3, "on")),
        ("async_set_poe_info", (2, "off", "2", 150)),
    ]
    assert coordinator.refresh_count == 4
    assert VigiAudioOutputMuteSwitch(coordinator, "entry-1", 1).is_on is False
    assert VigiAudioInputMuteSwitch(coordinator, "entry-1", 1).is_on is True
    assert VigiAudioNoiseCancellingSwitch(coordinator, "entry-1", 1).is_on is False
    assert VigiPoePortEnableSwitch(coordinator, "entry-1", 2).is_on is True


def test_camera_entities_expose_latest_event_images() -> None:
    """Latest event image cameras expose availability, metadata, and bytes."""
    coordinator = make_coordinator(data=populated_data())
    received_at = dt.datetime(2026, 6, 24, 12, 30, tzinfo=dt.UTC)
    image = VigiEventImage(
        part_index=2,
        part_name="picture",
        filename="alarm.jpg",
        content_type="image/jpeg",
        data=b"image-data",
    )
    event_push = VigiEventPush(
        mode="multipart",
        event={"messages": [{"channel": "1", "type_label": "Alarm"}]},
        events=[{"messages": [{"channel": "1", "type_label": "Alarm"}]}],
        images=[image],
        raw_bytes=10,
        content_type="multipart/form-data",
    )
    coordinator.last_event_images_by_channel[1] = image
    coordinator.last_event_pushes_by_channel[1] = event_push
    coordinator.last_event_received_at_by_channel[1] = received_at
    coordinator.last_event_client_ip_by_channel[1] = "192.0.2.40"

    camera = VigiChannelLastEventImageCamera(coordinator, "entry-1", 1)

    assert camera.available is True
    assert asyncio.run(camera.async_camera_image()) == b"image-data"
    assert camera.content_type == "image/jpeg"
    assert camera.extra_state_attributes == {
        "image": image.as_dict(),
        "received_at": "2026-06-24T12:30:00+00:00",
        "source_ip": "192.0.2.40",
        "source_channel": 1,
        "last_message": {"channel": "1", "type_label": "Alarm"},
    }

    unassigned = VigiUnassignedLastEventImageCamera(coordinator, "entry-1")
    assert unassigned.available is False
    assert asyncio.run(unassigned.async_camera_image()) is None
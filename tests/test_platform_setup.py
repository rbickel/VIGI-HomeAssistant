"""Tests for platform entity setup functions."""

from __future__ import annotations

import asyncio

from custom_components.vigi_nvr import binary_sensor, camera, sensor, switch
from custom_components.vigi_nvr.const import DOMAIN

from .conftest import FakeConfigEntry, FakeHass, make_coordinator, populated_data


def test_platform_setup_creates_entities_for_valid_channels_and_resources() -> None:
    """Platform setup functions add entities based on coordinator data."""
    coordinator = make_coordinator(data=populated_data())
    entry = FakeConfigEntry(entry_id="entry-1")
    hass = FakeHass(data={DOMAIN: {entry.entry_id: coordinator}})

    binary_entities: list[object] = []
    camera_entities: list[object] = []
    sensor_entities: list[object] = []
    switch_entities: list[object] = []

    asyncio.run(binary_sensor.async_setup_entry(hass, entry, binary_entities.extend))
    asyncio.run(camera.async_setup_entry(hass, entry, camera_entities.extend))
    asyncio.run(sensor.async_setup_entry(hass, entry, sensor_entities.extend))
    asyncio.run(switch.async_setup_entry(hass, entry, switch_entities.extend))

    assert len(binary_entities) == 6
    assert len(camera_entities) == 4
    assert len(sensor_entities) == 27
    assert len(switch_entities) == 4
    assert {getattr(entity, "_attr_unique_id", None) for entity in binary_entities} == {
        "entry-1_channel_1_online",
        "entry-1_poe_port_1_linked",
        "entry-1_poe_port_2_linked",
        "entry-1_poe_port_3_linked",
        "entry-1_event_server_configured",
        "entry-1_last_event_alarm_related",
    }
    assert {getattr(entity, "_attr_unique_id", None) for entity in camera_entities} == {
        "entry-1_unassigned_event_image",
        "entry-1_channel_1_live_stream_1",
        "entry-1_channel_1_live_stream_2",
        "entry-1_channel_1_last_event_image",
    }
    assert {getattr(entity, "_attr_unique_id", None) for entity in switch_entities} == {
        "entry-1_channel_1_output_mute",
        "entry-1_channel_1_input_mute",
        "entry-1_channel_1_noise_cancelling",
        "entry-1_poe_port_2_enable",
    }
    assert "entry-1_channel_not-a-channel_online" not in {
        getattr(entity, "_attr_unique_id", None) for entity in binary_entities
    }

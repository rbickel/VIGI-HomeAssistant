"""Tests for the VIGI data coordinator."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.vigi_nvr.api import VigiApiError
from custom_components.vigi_nvr.const import STREAM_MAIN, STREAM_MINOR
from custom_components.vigi_nvr.coordinator import VigiNvrData
from custom_components.vigi_nvr.events import VigiEventImage, VigiEventPush

from .conftest import make_coordinator


class PollingClient:
    """Client fake for coordinator polling tests."""

    async def async_get_added_devices(self) -> list[dict[str, object]]:
        """Return one valid channel and one invalid channel."""
        return [{"id": "1", "name": "Front"}, {"id": "bad"}]

    async def async_get_disks(self) -> list[dict[str, object]]:
        """Return disk data."""
        return [{"id": 1, "status": "normal"}]

    async def async_get_esata_disks(self) -> list[dict[str, object]]:
        """Simulate an unsupported optional endpoint."""
        raise VigiApiError("unsupported")

    async def async_get_event_servers(self) -> list[dict[str, object]]:
        """Return event server data."""
        return [{"id": 1}]

    async def async_get_poe_info(self) -> list[dict[str, object]]:
        """Return PoE info."""
        return [{"port": "1", "enable": "on"}]

    async def async_get_poe_status(self) -> list[dict[str, object]]:
        """Return PoE status."""
        return [{"global": {"sys_power": 110, "cost_power": 20}}]

    async def async_get_poe_link_mode(self) -> list[dict[str, object]]:
        """Return PoE link mode data."""
        return [{"port": 1, "link_mode": "auto"}]

    async def async_get_poe_link_status(self) -> str:
        """Return compact PoE link state."""
        return "10"

    async def async_get_timing_mode(self) -> dict[str, object]:
        """Return timing mode."""
        return {"mode": "ntp"}

    async def async_get_ntp(self) -> dict[str, object]:
        """Return NTP configuration."""
        return {"server": "pool.ntp.org"}

    async def async_get_audio_output_sound(
        self,
        channel: int,
    ) -> dict[str, object]:
        """Return output audio state."""
        return {"channel": channel, "mute": "off"}

    async def async_get_audio_input_sound(
        self,
        channel: int,
    ) -> dict[str, object]:
        """Return input audio state."""
        return {"channel": channel, "mute": "on"}

    async def async_get_resolution(
        self,
        channel: int,
        stream: str,
    ) -> dict[str, object]:
        """Return stream resolution."""
        return {"channel": channel, "stream": stream, "resolution": "1920x1080"}

    async def async_get_bitrate(
        self,
        channel: int,
        stream: str,
    ) -> dict[str, object]:
        """Return stream bitrate."""
        return {"channel": channel, "stream": stream, "maximun_bitrate": "2048"}


class FailingAddedDevicesClient(PollingClient):
    """Client fake whose required device endpoint fails."""

    async def async_get_added_devices(self) -> list[dict[str, object]]:
        """Raise a required endpoint failure."""
        raise VigiApiError("cannot connect")


def test_optional_helpers_return_defaults_for_unsupported_endpoints() -> None:
    """Optional endpoint helpers normalize failures and unexpected payloads."""
    coordinator = make_coordinator()

    async def list_endpoint() -> list[dict[str, object]]:
        return [{"id": 1}]

    async def dict_endpoint() -> dict[str, object]:
        return {"id": 1}

    async def failing_endpoint() -> dict[str, object]:
        raise VigiApiError("unsupported")

    assert asyncio.run(coordinator._optional_list(list_endpoint)) == [{"id": 1}]
    assert asyncio.run(coordinator._optional_list(dict_endpoint)) == []
    assert asyncio.run(coordinator._optional_list(failing_endpoint)) == []
    assert asyncio.run(
        coordinator._optional_value(failing_endpoint, default={"fallback": True})
    ) == {"fallback": True}


def test_async_update_data_populates_global_and_channel_state() -> None:
    """Coordinator polling fills global state and valid per-channel state."""
    coordinator = make_coordinator(client=PollingClient())

    data = asyncio.run(coordinator._async_update_data())

    assert data.devices == [{"id": "1", "name": "Front"}, {"id": "bad"}]
    assert data.disks == [{"id": 1, "status": "normal"}]
    assert data.esata_disks == []
    assert data.event_servers == [{"id": 1}]
    assert data.poe_info == [{"port": "1", "enable": "on"}]
    assert data.poe_link_status == "10"
    assert data.timing_mode == {"mode": "ntp"}
    assert data.audio_output[1] == {"channel": 1, "mute": "off"}
    assert data.audio_input[1] == {"channel": 1, "mute": "on"}
    assert data.resolutions[(1, STREAM_MAIN)]["resolution"] == "1920x1080"
    assert data.bitrates[(1, STREAM_MINOR)]["maximun_bitrate"] == "2048"
    assert len(data.audio_output) == 1


def test_async_update_data_wraps_required_api_failures() -> None:
    """Required polling failures are converted to Home Assistant UpdateFailed."""
    coordinator = make_coordinator(client=FailingAddedDevicesClient())

    with pytest.raises(UpdateFailed, match="cannot connect"):
        asyncio.run(coordinator._async_update_data())


def test_store_event_push_tracks_channel_and_unassigned_images() -> None:
    """Event storage maps known channels and keeps an unassigned fallback."""
    coordinator = make_coordinator(data=VigiNvrData(devices=[{"id": "1"}]))
    channel_image = VigiEventImage(
        part_index=1,
        part_name="picture",
        filename="known.jpg",
        content_type="image/jpeg",
        data=b"known",
    )
    channel_push = VigiEventPush(
        mode="json",
        event={"messages": [{"channel": "1"}]},
        events=[{"messages": [{"channel": "1"}]}],
        images=[channel_image],
        raw_bytes=5,
        content_type="application/json",
    )

    received_at = coordinator.store_event_push(channel_push, "192.0.2.50")

    assert coordinator.last_event_push is channel_push
    assert coordinator.last_event_image is channel_image
    assert coordinator.last_event_images_by_channel[1] is channel_image
    assert coordinator.last_event_pushes_by_channel[1] is channel_push
    assert coordinator.last_event_received_at_by_channel[1] == received_at
    assert coordinator.last_event_client_ip_by_channel[1] == "192.0.2.50"
    assert coordinator.updated_data is coordinator.data

    unassigned_image = VigiEventImage(
        part_index=1,
        part_name="picture",
        filename="unknown.jpg",
        content_type="image/jpeg",
        data=b"unknown",
    )
    unassigned_push = VigiEventPush(
        mode="json",
        event={"messages": [{"channel": "9"}]},
        events=[{"messages": [{"channel": "9"}]}],
        images=[unassigned_image],
        raw_bytes=7,
        content_type="application/json",
    )

    unassigned_received_at = coordinator.store_event_push(unassigned_push, None)

    assert coordinator.last_unassigned_event_image is unassigned_image
    assert coordinator.last_unassigned_event_push is unassigned_push
    assert coordinator.last_unassigned_event_received_at == unassigned_received_at
    assert coordinator.last_unassigned_event_client_ip is None


def test_has_channel_accepts_integer_and_numeric_string_ids() -> None:
    """Channel lookup handles VIGI numeric strings."""
    coordinator = make_coordinator(data=VigiNvrData(devices=[{"id": "1"}, {"id": 2}]))

    assert coordinator.has_channel(1) is True
    assert coordinator.has_channel(2) is True
    assert coordinator.has_channel(3) is False
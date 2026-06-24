"""Shared test helpers for the VIGI NVR integration."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import types
from typing import Any

turbojpeg_module = types.ModuleType("turbojpeg")


class TurboJPEG:
    """Test shim for optional Home Assistant camera acceleration dependency."""

    def __init__(self) -> None:
        raise OSError("libturbojpeg is not available in unit tests")


turbojpeg_module.TurboJPEG = TurboJPEG
sys.modules.setdefault("turbojpeg", turbojpeg_module)


def _shim_optional_numpy() -> None:
    """Let camera tests import Home Assistant stream without numpy installed."""
    if "numpy" in sys.modules or importlib.util.find_spec("numpy") is not None:
        return

    def _unavailable_numpy(*args: object, **kwargs: object) -> object:
        raise ModuleNotFoundError("numpy is not available in unit tests")

    numpy_module = types.ModuleType("numpy")
    numpy_module.ndarray = object
    numpy_module.fliplr = _unavailable_numpy
    numpy_module.flipud = _unavailable_numpy
    numpy_module.rot90 = _unavailable_numpy
    sys.modules["numpy"] = numpy_module


_shim_optional_numpy()

from custom_components.vigi_nvr.coordinator import (  # noqa: E402
    VigiNvrCoordinator,
    VigiNvrData,
)


@dataclasses.dataclass
class FakeConfigEntry:
    """Minimal config entry used by platform tests."""

    entry_id: str = "entry-1"
    title: str = "VIGI Test NVR"
    data: dict[str, Any] = dataclasses.field(default_factory=dict)


class FakeConfigEntries:
    """Capture config entry updates from helper functions."""

    def __init__(self) -> None:
        self.updated_entries: list[tuple[FakeConfigEntry, dict[str, Any]]] = []

    def async_update_entry(
        self,
        entry: FakeConfigEntry,
        *,
        data: dict[str, Any],
    ) -> None:
        """Record an entry update and mirror Home Assistant's data mutation."""
        self.updated_entries.append((entry, data))
        entry.data = data


class FakeBus:
    """Capture Home Assistant events fired by the integration."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Record a fired event."""
        self.events.append((event_type, event_data))


class FakeHass:
    """Small Home Assistant stand-in for unit tests."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}
        self.bus = FakeBus()
        self.config_entries = FakeConfigEntries()


class FakeRequest:
    """Minimal aiohttp request stand-in for webhook tests."""

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "application/json",
        remote: str | None = "192.0.2.10",
    ) -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}
        self.remote = remote

    async def read(self) -> bytes:
        """Return the configured request body."""
        return self._body


class RecordingClient:
    """Client fake that records mutating platform service calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def live_stream_url(self, channel: int, stream: int = 1) -> str:
        """Return a deterministic RTSP URL for sensor tests."""
        return f"rtsp://nvr.local/live/{channel}/{stream}/avm"

    async def async_set_audio_output_sound(
        self,
        channel: int,
        mute: str,
        volume: int,
        system_volume: int,
    ) -> None:
        """Record an audio output mutation."""
        self.calls.append(
            ("async_set_audio_output_sound", (channel, mute, volume, system_volume))
        )

    async def async_set_audio_input_sound(
        self,
        channel: int,
        mute: str,
        volume: int,
        noise_cancelling: str,
    ) -> None:
        """Record an audio input mutation."""
        self.calls.append(
            ("async_set_audio_input_sound", (channel, mute, volume, noise_cancelling))
        )

    async def async_set_poe_info(
        self,
        port: int,
        enable: str,
        priority: str,
        max_port_power: int,
    ) -> None:
        """Record a PoE mutation."""
        self.calls.append(
            ("async_set_poe_info", (port, enable, priority, max_port_power))
        )


def make_coordinator(
    data: VigiNvrData | None = None,
    *,
    client: Any | None = None,
) -> VigiNvrCoordinator:
    """Build a coordinator-like object without a full Home Assistant instance."""
    coordinator = object.__new__(VigiNvrCoordinator)
    coordinator.client = client or RecordingClient()
    coordinator.data = data or VigiNvrData()
    coordinator.last_update_success = True
    coordinator.event_webhook_id = None
    coordinator.event_webhook_url = None
    coordinator.last_event_push = None
    coordinator.last_event_image = None
    coordinator.last_event_images_by_channel = {}
    coordinator.last_event_pushes_by_channel = {}
    coordinator.last_event_received_at_by_channel = {}
    coordinator.last_event_client_ip_by_channel = {}
    coordinator.last_unassigned_event_image = None
    coordinator.last_unassigned_event_push = None
    coordinator.last_unassigned_event_received_at = None
    coordinator.last_unassigned_event_client_ip = None
    coordinator.last_event_received_at = None
    coordinator.last_event_client_ip = None
    coordinator.refresh_count = 0
    coordinator.updated_data = None

    def async_set_updated_data(new_data: VigiNvrData) -> None:
        coordinator.data = new_data
        coordinator.updated_data = new_data

    async def async_request_refresh() -> None:
        coordinator.refresh_count += 1

    coordinator.async_set_updated_data = async_set_updated_data
    coordinator.async_request_refresh = async_request_refresh
    return coordinator


def populated_data() -> VigiNvrData:
    """Return representative coordinator data used by entity tests."""
    return VigiNvrData(
        devices=[
            {
                "id": "1",
                "name": "Front Door",
                "online": "1",
                "ip": "192.0.2.20",
                "mac": "00:11:22:33:44:55",
            },
            {"id": "not-a-channel", "name": "Ignored"},
        ],
        disks=[
            {"id": "1", "status": "normal", "free_space": "10 GB"},
            {"slot": "2", "status": "missing", "total_space": "0 GB"},
        ],
        event_servers=[{"id": 1, "url": "/api/webhook/test"}],
        poe_info=[
            {"port": "2", "enable": "on", "priority": "2", "max_port_power": 150}
        ],
        poe_status=[{"global": {"sys_power": 123, "cost_power": 45}}],
        poe_link_status="101",
        timing_mode={"mode": "ntp"},
        ntp={"server": "pool.ntp.org", "port": 123},
        audio_output={1: {"mute": "off", "volume": "7", "system_volume": "9"}},
        audio_input={1: {"mute": "on", "volume": "3", "noise_cancelling": "off"}},
        resolutions={(1, "main"): {"resolution": "2560x1440"}},
        bitrates={(1, "minor"): {"maximun_bitrate": "1024"}},
    )

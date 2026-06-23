"""Switch platform for TP-Link VIGI NVR."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
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
    """Set up VIGI NVR switches."""
    coordinator: VigiNvrCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []

    for device in coordinator.data.devices:
        channel = as_int(device.get("id"))
        if channel is None:
            continue
        entities.extend(
            [
                VigiAudioOutputMuteSwitch(coordinator, entry.entry_id, channel),
                VigiAudioInputMuteSwitch(coordinator, entry.entry_id, channel),
                VigiAudioNoiseCancellingSwitch(coordinator, entry.entry_id, channel),
            ]
        )

    for port in poe_ports(coordinator):
        entities.append(VigiPoePortEnableSwitch(coordinator, entry.entry_id, port))

    async_add_entities(entities)


class VigiAudioOutputMuteSwitch(VigiChannelEntity, SwitchEntity):
    """Camera audio output mute switch."""

    entity_description = SwitchEntityDescription(key="output_mute", name="Output mute")

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, "output_mute")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.audio_output.get(self.channel, {}).get("mute")
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_mute("on")

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_mute("off")

    async def _set_mute(self, mute: str) -> None:
        current = self.coordinator.data.audio_output.get(self.channel, {})
        await self.coordinator.client.async_set_audio_output_sound(
            self.channel,
            mute,
            int(current.get("volume") or 0),
            int(current.get("system_volume") or 0),
        )
        await self.coordinator.async_request_refresh()


class VigiAudioInputMuteSwitch(VigiChannelEntity, SwitchEntity):
    """Camera audio input mute switch."""

    entity_description = SwitchEntityDescription(key="input_mute", name="Input mute")

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, "input_mute")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.audio_input.get(self.channel, {}).get("mute")
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_mute("on")

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_mute("off")

    async def _set_mute(self, mute: str) -> None:
        current = self.coordinator.data.audio_input.get(self.channel, {})
        await self.coordinator.client.async_set_audio_input_sound(
            self.channel,
            mute,
            int(current.get("volume") or 0),
            str(current.get("noise_cancelling") or "off"),
        )
        await self.coordinator.async_request_refresh()


class VigiAudioNoiseCancellingSwitch(VigiChannelEntity, SwitchEntity):
    """Camera audio input noise cancelling switch."""

    entity_description = SwitchEntityDescription(
        key="noise_cancelling",
        name="Noise cancelling",
    )

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        channel: int,
    ) -> None:
        super().__init__(coordinator, entry_id, channel, "noise_cancelling")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.audio_input.get(self.channel, {}).get(
            "noise_cancelling"
        )
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_noise_cancelling("on")

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_noise_cancelling("off")

    async def _set_noise_cancelling(self, value: str) -> None:
        current = self.coordinator.data.audio_input.get(self.channel, {})
        await self.coordinator.client.async_set_audio_input_sound(
            self.channel,
            str(current.get("mute") or "off"),
            int(current.get("volume") or 0),
            value,
        )
        await self.coordinator.async_request_refresh()


class VigiPoePortEnableSwitch(VigiNvrEntity, SwitchEntity):
    """PoE port enable switch."""

    def __init__(
        self,
        coordinator: VigiNvrCoordinator,
        entry_id: str,
        port: int,
    ) -> None:
        super().__init__(coordinator, entry_id, f"poe_port_{port}_enable")
        self.entity_description = SwitchEntityDescription(
            key="poe_port_enable",
            name=f"PoE port {port}",
        )
        self._port = port

    @property
    def is_on(self) -> bool | None:
        value = self._poe_info.get("enable")
        if value is None:
            return None
        return value == "on"

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._set_enable("on")

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._set_enable("off")

    async def _set_enable(self, enable: str) -> None:
        info = self._poe_info
        await self.coordinator.client.async_set_poe_info(
            self._port,
            enable,
            str(info.get("priority") or "1"),
            int(info.get("max_port_power") or 300),
        )
        await self.coordinator.async_request_refresh()

    @property
    def _poe_info(self) -> dict[str, object]:
        for item in self.coordinator.data.poe_info:
            if as_int(item.get("port")) == self._port:
                return item
        return {}


def poe_ports(coordinator: VigiNvrCoordinator) -> set[int]:
    """Return known PoE ports."""
    ports: set[int] = set()
    for item in coordinator.data.poe_info:
        port = as_int(item.get("port"))
        if port is not None:
            ports.add(port)
    return ports

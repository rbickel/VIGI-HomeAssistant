"""VIGI event push parsing helpers."""

from __future__ import annotations

import dataclasses
import email.parser
import email.policy
import json
from typing import Any

EVENT_TYPE_LABELS = {
    1: "Channel event",
    2: "Device exception",
    7: "Store exception",
}

EVENT_SUBTYPE_LABELS = {
    1: {
        1: "Time",
        2: "Motion detection",
        3: "Camera tampering",
        4: "Line crossing detection",
        5: "Intrusion detection",
        6: "Region entering detection",
        7: "Region exiting detection",
        8: "Loitering detection",
        9: "Crowd detection",
        10: "Fast motion detection",
        11: "Park detection",
        12: "Object abandoned detection",
        13: "Object removal detection",
        14: "Audio error",
        15: "Out of focus",
        16: "Scene change detection",
        17: "Face detection",
        18: "Alarm signal",
        19: "Video loss",
        20: "Video message",
        21: "Human detection",
        22: "Vehicle detection",
        23: "Abandon or take",
        24: "Doorbell",
        25: "Cry detection",
        26: "Emergency call",
        36: "Push I frame",
    },
    2: {
        1: "SD card missing",
        2: "SD card full",
        3: "Disk missing",
        4: "Disk full",
        5: "Device offline",
        6: "SD card error",
        7: "Disk error",
        8: "Log in error",
        9: "POE single port shortcut",
        10: "POE single port overload",
        11: "POE chip temperature error",
        12: "POE total overload",
        13: "Alarm input",
        14: "Fan abnormal",
        15: "IP conflict",
        17: "Disk disable",
    },
    7: {
        1: "RAID offline",
        2: "RAID degraded",
        3: "RAID disk abnormal",
        4: "RAID spare abnormal",
        5: "No array",
        6: "Array full",
        7: "No HD",
        8: "HD password error",
    },
}

CHANNEL_KEYS = ("channel", "channel_id", "channelId")


@dataclasses.dataclass(slots=True)
class VigiEventImage:
    """Image part attached to a VIGI event push."""

    part_index: int
    part_name: str | None
    filename: str | None
    content_type: str
    data: bytes

    @property
    def bytes(self) -> int:
        """Return the image byte length."""
        return len(self.data)

    def as_dict(self) -> dict[str, Any]:
        """Return serializable image metadata without the raw bytes."""
        return {
            "part_index": self.part_index,
            "part_name": self.part_name,
            "filename": self.filename,
            "content_type": self.content_type,
            "bytes": self.bytes,
        }


@dataclasses.dataclass(slots=True)
class VigiEventPush:
    """Parsed VIGI event push."""

    mode: str
    event: dict[str, Any] | None
    events: list[dict[str, Any]]
    images: list[VigiEventImage]
    raw_bytes: int
    content_type: str

    @property
    def message_count(self) -> int:
        """Return the total event message count."""
        return sum(len(event.get("messages", [])) for event in self.events)

    @property
    def alarm_related(self) -> bool:
        """Return whether the push contains an alarm-related message."""
        return any(
            isinstance(message, dict) and message.get("alarm_related")
            for event in self.events
            for message in event.get("messages", [])
        )

    @property
    def last_message(self) -> dict[str, Any] | None:
        """Return the last parsed event message."""
        for event in reversed(self.events):
            messages = event.get("messages", [])
            if messages:
                message = messages[-1]
                return message if isinstance(message, dict) else None
        return None

    @property
    def source_channel(self) -> int | None:
        """Return the best channel associated with this event push."""
        message = self.last_message
        if message is not None:
            channel = channel_from_mapping(message)
            if channel is not None:
                return channel

        for event in reversed(self.events):
            channel = channel_from_mapping(event)
            if channel is not None:
                return channel
            messages = event.get("messages", [])
            if isinstance(messages, list):
                for event_message in reversed(messages):
                    if not isinstance(event_message, dict):
                        continue
                    channel = channel_from_mapping(event_message)
                    if channel is not None:
                        return channel
        return None

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable event push dictionary."""
        return {
            "mode": self.mode,
            "event": self.event,
            "events": self.events,
            "images": [image.as_dict() for image in self.images],
            "raw_bytes": self.raw_bytes,
            "content_type": self.content_type,
            "message_count": self.message_count,
            "alarm_related": self.alarm_related,
            "last_message": self.last_message,
            "source_channel": self.source_channel,
        }


def parse_vigi_event_push(content_type: str, body: bytes) -> VigiEventPush:
    """Parse a VIGI event push body."""
    if "multipart/form-data" in content_type.lower():
        events, images = parse_multipart_event_push(content_type, body)
        return VigiEventPush(
            mode="multipart",
            event=events[0] if events else None,
            events=events,
            images=images,
            raw_bytes=len(body),
            content_type=content_type,
        )

    payload = try_parse_json(body)
    if isinstance(payload, dict):
        event = annotate_event_payload(payload)
        return VigiEventPush(
            mode="json",
            event=event,
            events=[event],
            images=[],
            raw_bytes=len(body),
            content_type=content_type,
        )

    return VigiEventPush(
        mode="raw",
        event=None,
        events=[],
        images=[],
        raw_bytes=len(body),
        content_type=content_type,
    )


def parse_multipart_event_push(
    content_type: str,
    body: bytes,
) -> tuple[list[dict[str, Any]], list[VigiEventImage]]:
    """Parse VIGI multipart event push payloads."""
    header_blob = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode()
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        header_blob + body
    )

    events: list[dict[str, Any]] = []
    images: list[VigiEventImage] = []
    if not message.is_multipart():
        return events, images

    for index, part in enumerate(message.iter_parts(), start=1):
        part_body = part.get_payload(decode=True) or b""
        part_name = part.get_param("name", header="Content-Disposition")
        filename = part.get_filename()
        media_type = part.get_content_type()

        parsed_json = try_parse_json(part_body)
        if isinstance(parsed_json, dict):
            event = annotate_event_payload(parsed_json)
            event["part_index"] = index
            event["part_name"] = part_name
            events.append(event)
            continue

        if media_type.startswith("image/"):
            images.append(
                VigiEventImage(
                    part_index=index,
                    part_name=part_name,
                    filename=filename,
                    content_type=media_type,
                    data=part_body,
                )
            )

    return events, images


def try_parse_json(body: bytes) -> Any | None:
    """Try to parse bytes as JSON."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def annotate_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add labels and alarm flags to VIGI event message payloads."""
    annotated = json.loads(json.dumps(payload))
    messages = annotated.get("messages")
    if not isinstance(messages, list):
        return annotated

    for message in messages:
        if not isinstance(message, dict):
            continue
        event_type = as_int(message.get("type"))
        if event_type is None:
            continue
        message["type_label"] = EVENT_TYPE_LABELS.get(event_type, "Unknown")
        sub_types = normalize_subtypes(message.get("sub_type"))
        message["sub_type_labels"] = [
            EVENT_SUBTYPE_LABELS.get(event_type, {}).get(sub_type, "Unknown")
            for sub_type in sub_types
        ]
        message["alarm_related"] = is_alarm_related(event_type, sub_types, message)

    return annotated


def normalize_subtypes(value: Any) -> list[int]:
    """Normalize VIGI subtype values to ints."""
    if isinstance(value, list):
        return [sub_type for item in value if (sub_type := as_int(item)) is not None]
    sub_type = as_int(value)
    return [sub_type] if sub_type is not None else []


def is_alarm_related(
    event_type: int, sub_types: list[int], message: dict[str, Any]
) -> bool:
    """Return whether a VIGI message is alarm-related."""
    if event_type == 1 and 18 in sub_types:
        return True
    if event_type == 2 and 13 in sub_types:
        return True
    return "alarm_output" in message or "alarm_input" in message


def channel_from_mapping(value: dict[str, Any]) -> int | None:
    """Return a VIGI channel id from a mapping when present."""
    for key in CHANNEL_KEYS:
        channel = as_int(value.get(key))
        if channel is not None:
            return channel
    return None


def as_int(value: Any) -> int | None:
    """Convert VIGI numeric values to int when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

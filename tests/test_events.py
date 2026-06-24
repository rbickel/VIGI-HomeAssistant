"""Tests for VIGI event push parsing."""

from __future__ import annotations

import json

from custom_components.vigi_nvr.events import (
    channel_from_mapping,
    normalize_subtypes,
    parse_vigi_event_push,
)


def test_parse_json_event_push_annotates_messages() -> None:
    """JSON pushes are decoded and annotated with labels and alarm flags."""
    body = json.dumps(
        {
            "messages": [
                {
                    "type": "1",
                    "sub_type": ["2", "18"],
                    "channel": "3",
                    "alarm_output": "1",
                }
            ]
        }
    ).encode()

    event_push = parse_vigi_event_push("application/json", body)
    message = event_push.last_message

    assert event_push.mode == "json"
    assert event_push.message_count == 1
    assert event_push.alarm_related is True
    assert event_push.source_channel == 3
    assert message is not None
    assert message["type_label"] == "Channel event"
    assert message["sub_type_labels"] == ["Motion detection", "Alarm signal"]
    assert message["alarm_related"] is True


def test_parse_multipart_event_push_extracts_event_and_image() -> None:
    """Multipart pushes keep JSON metadata and image attachments separately."""
    boundary = "----pytest-boundary"
    event = json.dumps({"channel_id": "4", "messages": [{"type": 2, "sub_type": 13}]})
    image_data = b"\xff\xd8fake-jpeg\xff\xd9"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="event"\r\n'
            "Content-Type: application/json\r\n\r\n"
            f"{event}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="picture"; filename="alarm.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + image_data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    event_push = parse_vigi_event_push(
        f"multipart/form-data; boundary={boundary}",
        body,
    )

    assert event_push.mode == "multipart"
    assert event_push.message_count == 1
    assert event_push.alarm_related is True
    assert event_push.source_channel == 4
    assert event_push.events[0]["part_index"] == 1
    assert event_push.events[0]["part_name"] == "event"
    assert len(event_push.images) == 1
    assert event_push.images[0].as_dict() == {
        "part_index": 2,
        "part_name": "picture",
        "filename": "alarm.jpg",
        "content_type": "image/jpeg",
        "bytes": len(image_data),
    }
    assert event_push.images[0].data == image_data


def test_parse_raw_event_push_preserves_payload_metadata() -> None:
    """Non-JSON non-multipart pushes are represented as raw payloads."""
    body = b"not-json"

    event_push = parse_vigi_event_push("text/plain", body)

    assert event_push.mode == "raw"
    assert event_push.event is None
    assert event_push.events == []
    assert event_push.images == []
    assert event_push.raw_bytes == len(body)
    assert event_push.content_type == "text/plain"


def test_normalize_subtypes_and_channel_helpers_ignore_invalid_values() -> None:
    """Parsing helpers coerce numeric strings and ignore invalid values."""
    assert normalize_subtypes(["1", "bad", 3, None]) == [1, 3]
    assert normalize_subtypes("7") == [7]
    assert normalize_subtypes("bad") == []
    assert channel_from_mapping({"channelId": "12"}) == 12
    assert channel_from_mapping({"channel": "not-a-number"}) is None

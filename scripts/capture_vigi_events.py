"""Capture TP-Link VIGI NVR OpenAPI event pushes over HTTP.

The VIGI NVR Open API document shows event pushes as HTTP multipart/form-data
POST requests to /event_message, with a JSON part named "event" and optional JPEG
parts. This script also accepts raw JSON bodies so it can capture firmware
variants while we learn the exact payload shape.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.parser
import email.policy
import http.server
import json
import os
import re
import socket
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any

DEFAULT_PATH = "/event_message"
DEFAULT_OUTPUT_DIR = Path("docs/discovery/event-captures")

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


@dataclasses.dataclass(slots=True)
class ServerConfig:
    bind: str
    port: int
    path: str
    output_dir: Path
    max_body_bytes: int


class VigiEventCaptureServer(http.server.ThreadingHTTPServer):
    """HTTP server carrying capture configuration."""

    config: ServerConfig

    def __init__(self, address: tuple[str, int], config: ServerConfig) -> None:
        super().__init__(address, VigiEventCaptureHandler)
        self.config = config


class VigiEventCaptureHandler(http.server.BaseHTTPRequestHandler):
    """Capture VIGI event push POST requests."""

    server: VigiEventCaptureServer

    def do_GET(self) -> None:
        """Return a small health/check page."""
        if self.path.rstrip("/") in {"", "/", "/health"}:
            payload = {
                "status": "ok",
                "event_path": self.server.config.path,
                "output_dir": str(self.server.config.output_dir),
            }
            self._send_json(200, payload)
            return
        self._send_json(
            404, {"error": "not_found", "event_path": self.server.config.path}
        )

    def do_POST(self) -> None:
        """Capture an event POST body."""
        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path != self.server.config.path:
            self._send_json(
                404, {"error": "not_found", "event_path": self.server.config.path}
            )
            return

        try:
            body = self._read_body()
        except ValueError as error:
            self._send_json(413, {"error": str(error)})
            return

        capture_dir = next_capture_dir(self.server.config.output_dir)
        capture_dir.mkdir(parents=True, exist_ok=True)

        headers = {key: value for key, value in self.headers.items()}
        (capture_dir / "request-body.bin").write_bytes(body)
        (capture_dir / "headers.json").write_text(
            json.dumps(headers, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        parsed = parse_event_request(headers, body, capture_dir)
        summary = build_capture_summary(
            client_address=self.client_address[0],
            request_path=self.path,
            headers=headers,
            body=body,
            parsed=parsed,
        )
        (capture_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        print_capture_summary(capture_dir, summary)
        self._send_json(200, {"error_code": 0, "capture": capture_dir.name})

    def _read_body(self) -> bytes:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return b""
        try:
            length = int(content_length)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        max_body_bytes = self.server.config.max_body_bytes
        if length > max_body_bytes:
            raise ValueError(
                f"body too large: {length} bytes exceeds {max_body_bytes}"
            )
        return self.rfile.read(length)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Use a compact access log line."""
        sys.stdout.write(
            f"{dt.datetime.now().isoformat(timespec='seconds')} "
            f"{self.client_address[0]} {format % args}\n"
        )


def parse_event_request(
    headers: dict[str, str],
    body: bytes,
    capture_dir: Path,
) -> dict[str, Any]:
    """Parse a VIGI event request body into saved parts and JSON summaries."""
    content_type = headers.get("Content-Type", "")
    parsed: dict[str, Any] = {"content_type": content_type, "parts": []}

    if "multipart/form-data" in content_type.lower():
        parsed["mode"] = "multipart"
        parsed["parts"] = parse_multipart(content_type, body, capture_dir)
        return parsed

    event_payload = try_parse_json(body)
    if event_payload is not None:
        parsed["mode"] = "json"
        parsed["event"] = annotate_event_payload(event_payload)
        (capture_dir / "event.json").write_text(
            json.dumps(parsed["event"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return parsed

    parsed["mode"] = "raw"
    parsed["body_preview"] = body[:200].decode("utf-8", errors="replace")
    return parsed


def parse_multipart(
    content_type: str, body: bytes, capture_dir: Path
) -> list[dict[str, Any]]:
    """Parse multipart/form-data without third-party dependencies."""
    header_blob = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode()
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        header_blob + body
    )

    parts: list[dict[str, Any]] = []
    if not message.is_multipart():
        return parts

    for index, part in enumerate(message.iter_parts(), start=1):
        part_body = part.get_payload(decode=True) or b""
        disposition = part.get("Content-Disposition", "")
        part_name = part.get_param("name", header="Content-Disposition")
        filename = part.get_filename()
        media_type = part.get_content_type()
        suffix = suffix_for_part(media_type, part_name, filename)
        part_file = (
            capture_dir / f"part-{index:02d}-{safe_name(part_name or 'body')}{suffix}"
        )
        part_file.write_bytes(part_body)

        summary: dict[str, Any] = {
            "index": index,
            "name": part_name,
            "filename": filename,
            "content_type": media_type,
            "content_disposition": disposition,
            "bytes": len(part_body),
            "file": part_file.name,
        }

        parsed_json = try_parse_json(part_body)
        if parsed_json is not None:
            annotated = annotate_event_payload(parsed_json)
            summary["json"] = annotated
            json_file = part_file.with_suffix(".json")
            json_file.write_text(
                json.dumps(annotated, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            summary["json_file"] = json_file.name

        parts.append(summary)

    return parts


def try_parse_json(body: bytes) -> Any | None:
    """Try to parse bytes as JSON."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def annotate_event_payload(payload: Any) -> Any:
    """Add human labels to documented VIGI event type/subtype IDs."""
    if not isinstance(payload, dict):
        return payload

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
    """Normalize VIGI subtype values to a list of ints."""
    if isinstance(value, list):
        return [sub_type for item in value if (sub_type := as_int(item)) is not None]
    sub_type = as_int(value)
    return [sub_type] if sub_type is not None else []


def is_alarm_related(
    event_type: int, sub_types: list[int], message: dict[str, Any]
) -> bool:
    """Return whether the event message looks alarm-related."""
    if event_type == 1 and 18 in sub_types:
        return True
    if event_type == 2 and 13 in sub_types:
        return True
    return "alarm_output" in message or "alarm_input" in message


def build_capture_summary(
    *,
    client_address: str,
    request_path: str,
    headers: dict[str, str],
    body: bytes,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    """Build a summary JSON document for a capture."""
    return {
        "captured_at": dt.datetime.now(dt.UTC).isoformat(),
        "client_address": client_address,
        "request_path": request_path,
        "method": "POST",
        "content_type": headers.get("Content-Type"),
        "content_length": headers.get("Content-Length"),
        "body_bytes": len(body),
        "parsed": parsed,
    }


def print_capture_summary(capture_dir: Path, summary: dict[str, Any]) -> None:
    """Print a short capture summary to stdout."""
    parsed = summary["parsed"]
    alarm_count = 0
    for event in iter_event_objects(parsed):
        for message in event.get("messages", []):
            if isinstance(message, dict) and message.get("alarm_related"):
                alarm_count += 1

    print(
        f"Captured {summary['body_bytes']} bytes from {summary['client_address']} "
        f"to {capture_dir} ({parsed.get('mode')}, alarm_related_messages={alarm_count})"
    )


def iter_event_objects(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Return parsed event JSON objects from a capture summary."""
    events: list[dict[str, Any]] = []
    event = parsed.get("event")
    if isinstance(event, dict):
        events.append(event)
    for part in parsed.get("parts", []):
        if isinstance(part, dict) and isinstance(part.get("json"), dict):
            events.append(part["json"])
    return events


def suffix_for_part(media_type: str, name: str | None, filename: str | None) -> str:
    """Choose a useful file suffix for a multipart part."""
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    if media_type == "application/json" or name == "event":
        return ".json"
    if media_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if media_type == "image/png":
        return ".png"
    return ".bin"


def next_capture_dir(output_dir: Path) -> Path:
    """Return a unique capture directory path."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return output_dir / stamp


def safe_name(value: str) -> str:
    """Return a filesystem-safe filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return cleaned or "part"


def as_int(value: Any) -> int | None:
    """Convert a VIGI value to int when possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def local_ip_hint() -> str | None:
    """Best-effort local IP hint for configuring the NVR."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.50.206", 20443))
            return sock.getsockname()[0]
    except OSError:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default=os.environ.get("VIGI_EVENT_BIND", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("VIGI_EVENT_PORT", "3001"))
    )
    parser.add_argument(
        "--path", default=os.environ.get("VIGI_EVENT_PATH", DEFAULT_PATH)
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("VIGI_EVENT_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))),
    )
    parser.add_argument(
        "--max-body-mb",
        type=int,
        default=int(os.environ.get("VIGI_EVENT_MAX_BODY_MB", "25")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ServerConfig(
        bind=args.bind,
        port=args.port,
        path=args.path,
        output_dir=args.output_dir,
        max_body_bytes=args.max_body_mb * 1024 * 1024,
    )
    config.output_dir.mkdir(parents=True, exist_ok=True)

    server = VigiEventCaptureServer((config.bind, config.port), config)
    ip_hint = local_ip_hint()
    print(f"Listening on http://{config.bind}:{config.port}{config.path}")
    if ip_hint:
        print(f"NVR event server hint: HTTP {ip_hint}:{config.port}{config.path}")
    print(f"Writing captures to {config.output_dir}")
    print("Press Ctrl+C to stop.")

    shutdown_requested = threading.Event()
    try:
        while not shutdown_requested.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        print("Stopping capture server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

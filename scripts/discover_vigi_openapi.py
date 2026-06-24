"""Discover TP-Link VIGI NVR OpenAPI endpoint behavior.

This script implements the authentication flow documented in TP-Link FAQ 4797:

1. Send a no-auth request to /openapi/token and read the Digest challenge.
2. Calculate the SHA-256 digest response.
3. Call /openapi/token with the Digest Authorization header.
4. Decode the returned access_token and use it as a Bearer token.

Credentials are read from environment variables and are never written to disk.
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

READ_ONLY_ENDPOINTS = (
    ("GET", "/openapi/added_devices", None),
    ("GET", "/openapi/timing_mode", None),
    ("GET", "/openapi/ntp", None),
    ("GET", "/openapi/disks", None),
    ("GET", "/openapi/esata_disks", None),
    ("GET", "/openapi/poe/info", None),
    ("GET", "/openapi/poe/link_mode", None),
    ("GET", "/openapi/poe/status", None),
    ("GET", "/openapi/poe/link_status", None),
    ("GET", "/openapi/event_server", None),
    ("GET", "/openapi/record/search/free_process", None),
)

CHANNEL_ENDPOINTS = (
    ("GET", "/openapi/audio/output/sound", {"channel": "{channel}"}),
    ("GET", "/openapi/audio/input/sound", {"channel": "{channel}"}),
    (
        "GET",
        "/openapi/resolution",
        {"channel": "{channel}", "stream": "minor"},
    ),
    (
        "GET",
        "/openapi/valid_resolutions",
        {"channel": "{channel}", "stream": "minor"},
    ),
    (
        "GET",
        "/openapi/bitrate",
        {"channel": "{channel}", "stream": "minor"},
    ),
    (
        "GET",
        "/openapi/bitrate_capability",
        {"channel": "{channel}", "stream": "minor"},
    ),
)

MUTATING_ENDPOINTS = (
    ("POST", "/openapi/resolution"),
    ("POST", "/openapi/bitrate"),
    ("PUT", "/openapi/timing_mode"),
    ("PUT", "/openapi/ntp"),
    ("POST", "/openapi/audio/output/sound"),
    ("POST", "/openapi/audio/input/sound"),
    ("POST", "/openapi/smartctl_process"),
    ("POST", "/openapi/smartctl_process/test"),
    ("POST", "/openapi/poe/info"),
    ("POST", "/openapi/poe/link_mode"),
    ("POST", "/openapi/event_server/new_server"),
    ("POST", "/openapi/event_server/delete_server"),
    ("POST", "/openapi/systemctl"),
)

ALARM_KEYWORDS = (
    "alarm",
    "arming",
    "armed",
    "arm",
    "disarm",
    "siren",
    "sound",
    "buzzer",
    "horn",
    "strobe",
    "alert",
    "event",
    "trigger",
    "linkage",
    "defence",
    "defense",
)


@dataclasses.dataclass(frozen=True)
class HttpResult:
    method: str
    path: str
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class VigiOpenApiDiscovery:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        verify_tls: bool,
        timeout: float,
    ) -> None:
        self.base_url = f"https://{host}:{port}"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.ssl_context = None if verify_tls else ssl._create_unverified_context()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResult:
        request = urllib.request.Request(
            urllib.parse.urljoin(self.base_url, path),
            data=body,
            headers=headers or {},
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self.ssl_context,
            ) as response:
                return HttpResult(
                    method=method,
                    path=path,
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResult(
                method=method,
                path=path,
                status=error.code,
                headers=dict(error.headers.items()),
                body=error.read(),
            )

    def get_access_token(self) -> str:
        challenge_response = self.request("GET", "/openapi/token")
        if challenge_response.status != 401:
            raise RuntimeError(
                "Expected /openapi/token to return a Digest challenge, "
                f"got HTTP {challenge_response.status}."
            )

        challenge = parse_digest_challenge(
            challenge_response.headers.get("WWW-Authenticate", "")
        )
        if not challenge:
            raise RuntimeError("/openapi/token did not return a Digest challenge.")

        token_path = challenge.get("url") or "/openapi/token"
        auth_headers = build_digest_authorization_variants(
            username=self.username,
            password=self.password,
            method="GET",
            uri=token_path,
            challenge=challenge,
        )

        errors: list[str] = []
        for authorization in auth_headers:
            result = self.request(
                "GET",
                token_path,
                headers={"Authorization": authorization},
            )
            if result.status == 200:
                token = extract_access_token(result)
                if token:
                    return urllib.parse.unquote(token)
                errors.append("HTTP 200 response did not include an access token")
            else:
                errors.append(f"Digest token request returned HTTP {result.status}")

        raise RuntimeError("; ".join(errors))

    def fetch_spec_candidates(
        self, token: str, paths: Iterable[str]
    ) -> list[HttpResult]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, */*",
        }
        return [self.request("GET", path, headers=headers) for path in paths]

    def fetch_endpoint(
        self,
        token: str,
        method: str,
        path: str,
        params: dict[str, str] | None,
    ) -> HttpResult:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, */*",
        }
        target = path
        if params:
            target = f"{path}?{urllib.parse.urlencode(params)}"
        return self.request(method, target, headers=headers)


def parse_digest_challenge(header: str) -> dict[str, str]:
    if not header.lower().startswith("digest"):
        return {}

    values: dict[str, str] = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header):
        values[match.group(1).lower()] = match.group(2) or match.group(3) or ""
    return values


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_digest_authorization_variants(
    *,
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: dict[str, str],
) -> list[str]:
    realm = challenge["realm"]
    nonce = challenge["nonce"]
    algorithm = challenge.get("algorithm", "SHA-256")

    if algorithm.upper() != "SHA-256":
        raise RuntimeError(f"Unsupported VIGI Digest algorithm: {algorithm}")

    a1 = sha256_hex(f"{username}:{realm}:{password}")
    a2 = sha256_hex(f"{method}:{uri}")
    response = sha256_hex(f"{a1}:{nonce}:{a2}")

    base_fields = (
        f'username="{username}"',
        f'nonce="{nonce}"',
        f'realm="{realm}"',
        f'response="{response}"',
    )

    return [
        "Digest " + ", ".join(base_fields),
        "Digest "
        + ", ".join(
            (
                *base_fields,
                f'uri="{uri}"',
                'algorithm="SHA-256"',
            )
        ),
    ]


def extract_access_token(result: HttpResult) -> str | None:
    text = result.text.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"access_token[=:]\s*['\"]?([^'\"\s,}]+)", text)
        return match.group(1) if match else text

    if isinstance(payload, dict):
        for key in ("access_token", "accessToken", "token"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("access_token", "accessToken", "token"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value

    return None


def parse_openapi_document(result: HttpResult) -> dict[str, Any] | None:
    content_type = result.headers.get("Content-Type", "")
    text = result.text.strip()
    if not text:
        return None

    if "json" in content_type or text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    return None


def endpoint_rows(openapi_doc: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    paths = openapi_doc.get("paths")
    if not isinstance(paths, dict):
        return rows

    for path, operations in sorted(paths.items()):
        if not isinstance(operations, dict):
            continue
        for method, operation in sorted(operations.items()):
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            summary = ""
            operation_id = ""
            tags = ""
            if isinstance(operation, dict):
                summary = str(
                    operation.get("summary") or operation.get("description") or ""
                )
                operation_id = str(operation.get("operationId") or "")
                tags_value = operation.get("tags")
                if isinstance(tags_value, list):
                    tags = ", ".join(str(tag) for tag in tags_value)
            rows.append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": operation_id,
                    "summary": one_line(summary),
                    "tags": tags,
                }
            )
    return rows


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def is_alarm_candidate(row: dict[str, str]) -> bool:
    haystack = " ".join(row.values()).lower()
    return any(keyword in haystack for keyword in ALARM_KEYWORDS)


def safe_filename(path: str) -> str:
    slug = path.strip("/").replace("/", "-") or "root"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", slug)


def write_outputs(
    output_dir: Path,
    spec_results: list[HttpResult],
    documents: list[tuple[HttpResult, dict[str, Any]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, str]] = []
    for result, document in documents:
        all_rows.extend(endpoint_rows(document))
        suffix = "json" if result.text.strip().startswith("{") else "yaml"
        output_file = output_dir / f"openapi-{safe_filename(result.path)}.{suffix}"
        output_file.write_text(result.text, encoding="utf-8")

    alarm_rows = [row for row in all_rows if is_alarm_candidate(row)]
    summary = {
        "probes": [
            {
                "method": result.method,
                "path": result.path,
                "status": result.status,
                "content_type": result.headers.get("Content-Type"),
                "bytes": len(result.body),
            }
            for result in spec_results
        ],
        "endpoint_count": len(all_rows),
        "alarm_candidate_count": len(alarm_rows),
        "alarm_candidates": alarm_rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "endpoints.md").write_text(
        render_endpoints_markdown(all_rows, alarm_rows, spec_results),
        encoding="utf-8",
    )


def write_endpoint_probe_outputs(
    output_dir: Path,
    results: list[HttpResult],
    mutating_endpoints: Iterable[tuple[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "probes": [probe_summary(result) for result in results],
        "mutating_endpoints_not_called": [
            {"method": method, "path": path} for method, path in mutating_endpoints
        ],
        "alarm_control_supported": False,
        "alarm_notes": (
            "The VIGI NVR Open API Document exposes event push and alarm-related "
            "event payload fields, but no documented arm/disarm/activate/deactivate "
            "control endpoint."
        ),
    }
    (output_dir / "endpoint-probes.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "endpoint-probes.md").write_text(
        render_endpoint_probe_markdown(results, mutating_endpoints),
        encoding="utf-8",
    )


def probe_summary(result: HttpResult) -> dict[str, Any]:
    text = result.text.strip()
    parsed: Any = None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

    body_summary: str | dict[str, Any]
    if isinstance(parsed, dict):
        body_summary = {
            key: value
            for key, value in parsed.items()
            if key in {"error_code", "sub_code", "mode", "link_status"}
        }
        for key, value in parsed.items():
            if isinstance(value, list):
                body_summary[f"{key}_count"] = len(value)
    else:
        body_summary = text[:200]

    return {
        "method": result.method,
        "path": result.path,
        "status": result.status,
        "content_type": result.headers.get("Content-Type"),
        "bytes": len(result.body),
        "body_summary": body_summary,
    }


def render_endpoint_probe_markdown(
    results: list[HttpResult],
    mutating_endpoints: Iterable[tuple[str, str]],
) -> str:
    lines = [
        "# VIGI Endpoint Probes",
        "",
        "Generated by `scripts/discover_vigi_openapi.py` using the fixed "
        "endpoint list from the VIGI NVR Open API Document.",
        "",
        "## Read-Only Probes",
        "",
        "| Method | Path | Status | Content type | Bytes | Summary |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for result in results:
        summary = json.dumps(probe_summary(result)["body_summary"], sort_keys=True)
        lines.append(
            f"| {result.method} | `{result.path}` | {result.status} | "
            f"{result.headers.get('Content-Type', '')} | {len(result.body)} | "
            f"{escape_cell(summary)} |"
        )
    lines.extend(
        [
            "",
            "## Mutating Endpoints Not Called",
            "",
            "These endpoints are documented but intentionally not called by discovery.",
            "",
            "| Method | Path |",
            "| --- | --- |",
        ]
    )
    for method, path in mutating_endpoints:
        lines.append(f"| {method} | `{path}` |")
    lines.extend(
        [
            "",
            "## Alarm Finding",
            "",
            "The PDF exposes event push configuration and alarm-related event "
            "payload fields (`alarm_output`, `alarm_input`, event subtype "
            "`Alarm signal`, and device exception subtype `Alarm input`). It "
            "does not document arm/disarm/activate/deactivate control endpoints.",
            "",
        ]
    )
    return "\n".join(lines)


def render_endpoints_markdown(
    rows: list[dict[str, str]],
    alarm_rows: list[dict[str, str]],
    spec_results: list[HttpResult],
) -> str:
    lines = [
        "# VIGI OpenAPI Discovery",
        "",
        "Generated by `scripts/discover_vigi_openapi.py`.",
        "",
        "## Probe Results",
        "",
        "| Method | Path | Status | Content type | Bytes |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for result in spec_results:
        lines.append(
            f"| {result.method} | `{result.path}` | {result.status} | "
            f"{result.headers.get('Content-Type', '')} | {len(result.body)} |"
        )

    lines.extend(
        [
            "",
            "## Alarm Candidates",
            "",
            "These endpoints match alarm-related keywords and need behavioral "
            "validation before Home Assistant services call mutating methods.",
            "",
        ]
    )

    if alarm_rows:
        append_endpoint_table(lines, alarm_rows)
    else:
        lines.append(
            "No alarm candidates were found in the downloaded OpenAPI documents."
        )

    lines.extend(["", "## All Endpoints", ""])
    if rows:
        append_endpoint_table(lines, rows)
    else:
        lines.append("No OpenAPI paths were parsed from the successful responses.")

    lines.append("")
    return "\n".join(lines)


def append_endpoint_table(lines: list[str], rows: list[dict[str, str]]) -> None:
    lines.extend(
        [
            "| Method | Path | Operation | Tags | Summary |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['method']} | `{row['path']}` | "
            f"{escape_cell(row['operation_id'])} | "
            f"{escape_cell(row['tags'])} | {escape_cell(row['summary'])} |"
        )


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("VIGI_HOST", "192.168.50.206"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("VIGI_PORT", "20443"))
    )
    parser.add_argument("--username", default=os.environ.get("VIGI_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("VIGI_PASSWORD"))
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/discovery"),
    )
    parser.add_argument(
        "--spec-path",
        action="append",
        dest="spec_paths",
        help="Additional OpenAPI candidate path to fetch after authentication.",
    )
    parser.add_argument(
        "--probe-known-endpoints",
        action="store_true",
        default=True,
        help="Probe documented read-only endpoints from the PDF.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.username:
        print("Set VIGI_USERNAME before running discovery.", file=sys.stderr)
        return 2
    if not args.password:
        args.password = getpass.getpass("VIGI password: ")

    client = VigiOpenApiDiscovery(
        args.host,
        args.port,
        args.username,
        args.password,
        verify_tls=args.verify_tls,
        timeout=args.timeout,
    )

    token = client.get_access_token()
    endpoint_results: list[HttpResult] = []
    if args.probe_known_endpoints:
        added_devices = client.fetch_endpoint(
            token, "GET", "/openapi/added_devices", None
        )
        endpoint_results.append(added_devices)
        channels = channels_from_added_devices(added_devices)
        for method, path, params in READ_ONLY_ENDPOINTS:
            if path == "/openapi/added_devices":
                continue
            endpoint_results.append(client.fetch_endpoint(token, method, path, params))
        for channel in channels:
            for method, path, params in CHANNEL_ENDPOINTS:
                rendered_params = {
                    key: value.format(channel=channel)
                    for key, value in (params or {}).items()
                }
                endpoint_results.append(
                    client.fetch_endpoint(token, method, path, rendered_params)
                )
        write_endpoint_probe_outputs(
            args.output_dir, endpoint_results, MUTATING_ENDPOINTS
        )

    paths = tuple(dict.fromkeys(args.spec_paths or ()))
    spec_results = client.fetch_spec_candidates(token, paths) if paths else []
    documents = [
        (result, document)
        for result in spec_results
        if result.status == 200
        if (document := parse_openapi_document(result)) is not None
    ]
    write_outputs(args.output_dir, spec_results, documents)

    endpoint_count = sum(len(endpoint_rows(document)) for _, document in documents)
    alarm_count = sum(
        1
        for _, document in documents
        for row in endpoint_rows(document)
        if is_alarm_candidate(row)
    )
    print(f"Probed {len(endpoint_results)} documented read-only endpoint(s).")
    print(f"Fetched {len(documents)} OpenAPI document(s).")
    print(f"Parsed {endpoint_count} endpoint(s); {alarm_count} alarm candidate(s).")
    print(f"Wrote discovery output to {args.output_dir}.")
    return 0


def channels_from_added_devices(result: HttpResult) -> list[int]:
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError:
        return []
    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(devices, list):
        return []
    channels: list[int] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        value = device.get("id")
        if isinstance(value, int):
            channels.append(value)
        elif isinstance(value, str) and value.isdigit():
            channels.append(int(value))
    return channels


if __name__ == "__main__":
    raise SystemExit(main())

"""Client for TP-Link VIGI NVR OpenAPI."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
import ssl
import time
import urllib.parse
from typing import Any

import aiohttp


class VigiApiError(Exception):
    """Base VIGI API error."""


class VigiAuthError(VigiApiError):
    """Raised when VIGI authentication fails."""


@dataclasses.dataclass(slots=True)
class VigiToken:
    """Bearer token returned by the VIGI OpenAPI token endpoint."""

    access_token: str
    refresh_token: str | None
    expires_at: float | None


@dataclasses.dataclass
class VigiNvrClient:
    """Small async client for VIGI NVR OpenAPI."""

    session: aiohttp.ClientSession
    host: str
    port: int
    username: str
    password: str
    verify_tls: bool = False
    token: VigiToken | None = None
    token_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)

    @property
    def base_url(self) -> str:
        """Return the NVR OpenAPI base URL."""
        return f"https://{self.host}:{self.port}"

    @property
    def ssl_context(self) -> ssl.SSLContext | bool:
        """Return the TLS verification mode for aiohttp."""
        return bool(self.verify_tls)

    async def authenticate(self) -> str:
        """Authenticate with Digest auth and cache the bearer token."""
        async with self.token_lock:
            if self.token and not self._token_is_expiring(self.token):
                return self.token.access_token

            if self.token and self.token.refresh_token:
                try:
                    refreshed = await self._refresh_token(self.token.refresh_token)
                except VigiApiError:
                    refreshed = None
                if refreshed is not None:
                    self.token = refreshed
                    return refreshed.access_token

            self.token = await self._authenticate_with_digest()
            return self.token.access_token

    async def _authenticate_with_digest(self) -> VigiToken:
        challenge_response = await self.session.get(
            f"{self.base_url}/openapi/token",
            ssl=self.ssl_context,
        )
        async with challenge_response:
            challenge_header = challenge_response.headers.get("WWW-Authenticate", "")
            if not challenge_header:
                text = await challenge_response.text()
                raise VigiAuthError(
                    "VIGI token endpoint did not return a Digest challenge: "
                    f"HTTP {challenge_response.status}: {text}"
                )
            challenge = parse_digest_challenge(challenge_header)

        token_path = challenge.get("url") or "/openapi/token"
        errors: list[str] = []
        for authorization in build_digest_authorization_variants(
            username=self.username,
            password=self.password,
            method="GET",
            uri=token_path,
            challenge=challenge,
        ):
            token_response = await self.session.get(
                f"{self.base_url}{token_path}",
                headers={"Authorization": authorization},
                ssl=self.ssl_context,
            )
            async with token_response:
                if token_response.status != 200:
                    text = await token_response.text()
                    errors.append(f"HTTP {token_response.status}: {text}")
                    continue
                payload = await token_response.json(content_type=None)
                return token_from_payload(payload)

        raise VigiAuthError("VIGI Digest token request failed: " + "; ".join(errors))

    async def _refresh_token(self, refresh_token: str) -> VigiToken | None:
        response = await self.session.get(
            f"{self.base_url}/openapi/token",
            params={"grant_type": "refresh_token", "refresh_token": refresh_token},
            ssl=self.ssl_context,
        )
        async with response:
            if response.status != 200:
                return None
            payload = await response.json(content_type=None)
            return token_from_payload(payload)

    def _token_is_expiring(self, token: VigiToken) -> bool:
        return token.expires_at is not None and token.expires_at <= time.time() + 60

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        check_error: bool = True,
    ) -> Any:
        """Call a VIGI OpenAPI endpoint with bearer token auth."""
        for attempt in range(2):
            access_token = await self.authenticate()
            response = await self.session.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                json=encode_json_strings(json_body) if json_body is not None else None,
                ssl=self.ssl_context,
            )
            async with response:
                if response.status == 401 and attempt == 0:
                    self.token = None
                    continue
                if response.status >= 400:
                    text = await response.text()
                    raise VigiApiError(
                        f"VIGI API {method} {path} returned HTTP "
                        f"{response.status}: {text}"
                    )

                payload = await read_json_response(response)

            if check_error and isinstance(payload, dict):
                error_code = payload.get("error_code")
                if isinstance(error_code, int) and error_code != 0:
                    raise VigiApiError(
                        f"VIGI API {method} {path} returned error_code {error_code}"
                    )
            return payload

        raise VigiAuthError("VIGI bearer token refresh failed.")

    async def async_get_added_devices(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/added_devices")
        return as_list(payload, "devices")

    async def async_get_resolution(self, channel: int, stream: str) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/resolution",
            params={"channel": channel, "stream": stream},
        )

    async def async_get_valid_resolutions(
        self,
        channel: int,
        stream: str,
    ) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            "/openapi/valid_resolutions",
            params={"channel": channel, "stream": stream},
        )
        return as_list(payload, "resolutions")

    async def async_set_resolution(
        self,
        channel: int,
        stream: str,
        resolution: str,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/resolution",
            json_body={"channel": channel, "stream": stream, "resolution": resolution},
        )

    async def async_get_bitrate(self, channel: int, stream: str) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/bitrate",
            params={"channel": channel, "stream": stream},
        )

    async def async_get_bitrate_capability(
        self,
        channel: int,
        stream: str,
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/bitrate_capability",
            params={"channel": channel, "stream": stream},
        )

    async def async_set_bitrate(
        self,
        channel: int,
        stream: str,
        maximum_bitrate: str,
        bitrate_type: str,
        quality: str,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/bitrate",
            json_body={
                "channel": channel,
                "stream": stream,
                "maximun_bitrate": maximum_bitrate,
                "type": bitrate_type,
                "quality": quality,
            },
        )

    async def async_get_timing_mode(self) -> dict[str, Any]:
        return await self.request("GET", "/openapi/timing_mode")

    async def async_set_timing_mode(self, mode: str) -> Any:
        return await self.request(
            "PUT",
            "/openapi/timing_mode",
            json_body={"mode": mode},
        )

    async def async_get_ntp(self) -> dict[str, Any]:
        return await self.request("GET", "/openapi/ntp")

    async def async_set_ntp(self, server: str, port: int) -> Any:
        return await self.request(
            "PUT",
            "/openapi/ntp",
            json_body={"server": server, "port": port},
        )

    async def async_get_audio_output_sound(self, channel: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/audio/output/sound",
            params={"channel": channel},
        )

    async def async_set_audio_output_sound(
        self,
        channel: int,
        mute: str,
        volume: int,
        system_volume: int,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/audio/output/sound",
            json_body={
                "channel": channel,
                "mute": mute,
                "volume": volume,
                "system_volume": system_volume,
            },
        )

    async def async_get_audio_input_sound(self, channel: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/audio/input/sound",
            params={"channel": channel},
        )

    async def async_set_audio_input_sound(
        self,
        channel: int,
        mute: str,
        volume: int,
        noise_cancelling: str,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/audio/input/sound",
            json_body={
                "channel": channel,
                "mute": mute,
                "volume": volume,
                "noise_cancelling": noise_cancelling,
            },
        )

    async def async_get_disks(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/disks")
        return as_list(payload, "disks")

    async def async_get_esata_disks(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/esata_disks")
        return as_list(payload, "disks")

    async def async_start_smartctl_process(self) -> Any:
        return await self.request(
            "POST",
            "/openapi/smartctl_process",
            json_body={"action": "start"},
        )

    async def async_stop_smartctl_process(self) -> Any:
        return await self.request(
            "POST",
            "/openapi/smartctl_process",
            json_body={"action": "stop"},
        )

    async def async_get_smart_capability(self, disk: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/smartctl_process/capability",
            params={"disk": disk},
        )

    async def async_start_smart_test(self, disk: int, test_type: str) -> Any:
        return await self.request(
            "POST",
            "/openapi/smartctl_process/test",
            json_body={"disk": disk, "type": test_type},
        )

    async def async_get_smart_schedule(self, disk: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/smartctl_process/schedule",
            params={"disk": disk},
        )

    async def async_get_smart_attribute(self, disk: int) -> dict[str, Any]:
        return await self.request(
            "GET",
            "/openapi/smartctl_process/attribute",
            params={"disk": disk},
        )

    async def async_get_poe_info(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/poe/info")
        return as_list(payload, "info")

    async def async_set_poe_info(
        self,
        port: int,
        enable: str,
        priority: str,
        max_port_power: int,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/poe/info",
            json_body={
                "port": port,
                "enable": enable,
                "priority": priority,
                "max_port_power": max_port_power,
            },
        )

    async def async_get_poe_link_mode(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/poe/link_mode")
        return as_list(payload, "link_mode")

    async def async_set_poe_link_mode(self, port: int, link_mode: str) -> Any:
        return await self.request(
            "POST",
            "/openapi/poe/link_mode",
            json_body={"port": port, "link_mode": link_mode},
        )

    async def async_get_poe_status(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/poe/status")
        return as_list(payload, "status")

    async def async_get_poe_link_status(self) -> str:
        payload = await self.request("GET", "/openapi/poe/link_status")
        if isinstance(payload, dict):
            return str(payload.get("link_status", ""))
        return ""

    async def async_get_event_servers(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "/openapi/event_server")
        return as_list(payload, "event_server")

    async def async_add_event_server(
        self,
        server_id: int,
        ip_or_domain: str,
        port: int,
        protocol: str,
        url: str,
        picture_switch: str,
    ) -> Any:
        return await self.request(
            "POST",
            "/openapi/event_server/new_server",
            json_body={
                "id": server_id,
                "ip_or_domain": ip_or_domain,
                "port": port,
                "protocol": protocol,
                "url": url,
                "picture_switch": picture_switch,
            },
        )

    async def async_delete_event_server(self, server_id: int) -> Any:
        return await self.request(
            "POST",
            "/openapi/event_server/delete_server",
            json_body={"id": server_id},
        )

    async def async_get_record_days(
        self,
        channel: int,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            "/openapi/record/days",
            params={"channel": channel, "start": start, "end": end},
        )
        return as_list(payload, "days")

    async def async_get_record_search_free_process(self) -> int | None:
        payload = await self.request("GET", "/openapi/record/search/free_process")
        if isinstance(payload, dict) and isinstance(payload.get("process"), int):
            return payload["process"]
        return None

    async def async_get_record_search_results(
        self,
        channel: int,
        process: int,
        day: str,
        start_index: int,
        end_index: int,
    ) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            "/openapi/record/search/results",
            params={
                "channel": channel,
                "process": process,
                "day": day,
                "start_index": start_index,
                "end_index": end_index,
            },
        )
        return as_list(payload, "results")

    async def async_systemctl(self, action: str) -> Any:
        return await self.request(
            "POST",
            "/openapi/systemctl",
            json_body={"action": action},
        )

    def live_stream_url(
        self,
        channel: int,
        stream: int = 1,
        *,
        include_credentials: bool = False,
    ) -> str:
        """Return the documented RTSP live stream URL for a channel."""
        authority = self.host
        if include_credentials:
            username = urllib.parse.quote(self.username, safe="")
            password = urllib.parse.quote(self.password, safe="")
            authority = f"{username}:{password}@{self.host}"
        return f"rtsp://{authority}/live/{channel}/{stream}/avm"

    def replay_stream_url(
        self,
        channel: int,
        start_time: str,
        end_time: str,
        stream: int = 1,
    ) -> str:
        """Return the documented RTSP replay stream URL for a channel."""
        return (
            f"rtsp://{self.host}/replay/{channel}/{stream}/avm?"
            f"starttime={start_time}&endtime={end_time}"
        )


async def read_json_response(response: aiohttp.ClientResponse) -> Any:
    """Read and decode a VIGI JSON response."""
    text = await response.text()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return decode_json_strings(text)
    return decode_json_strings(payload)


def parse_digest_challenge(header: str) -> dict[str, str]:
    """Parse a Digest authentication challenge."""
    if not header.lower().startswith("digest"):
        raise VigiAuthError("Missing VIGI Digest challenge.")

    values: dict[str, str] = {}
    for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header):
        values[match.group(1).lower()] = match.group(2) or match.group(3) or ""

    if "realm" not in values or "nonce" not in values:
        raise VigiAuthError("VIGI Digest challenge did not include realm and nonce.")
    return values


def build_digest_authorization_variants(
    *,
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: dict[str, str],
) -> list[str]:
    """Build Digest Authorization header variants accepted by VIGI firmware."""
    realm = challenge["realm"]
    nonce = challenge["nonce"]
    algorithm = challenge.get("algorithm", "SHA-256")
    if algorithm.upper() != "SHA-256":
        raise VigiAuthError(f"Unsupported VIGI Digest algorithm: {algorithm}")

    a1 = sha256_hex(f"{username}:{realm}:{password}")
    a2 = sha256_hex(f"{method}:{uri}")
    response = sha256_hex(f"{a1}:{nonce}:{a2}")
    fields = (
        f'username="{username}"',
        f'nonce="{nonce}"',
        f'realm="{realm}"',
        f'response="{response}"',
    )
    return [
        "Digest " + ", ".join(fields),
        "Digest " + ", ".join((*fields, f'uri="{uri}"', 'algorithm="SHA-256"')),
    ]


def sha256_hex(value: str) -> str:
    """Return a SHA-256 hex digest."""
    return hashlib.sha256(value.encode()).hexdigest()


def token_from_payload(payload: Any) -> VigiToken:
    """Extract and decode a token payload."""
    if not isinstance(payload, dict):
        raise VigiAuthError("VIGI token response was not JSON object.")

    access_token = extract_string(payload, "access_token", "accessToken", "token")
    if access_token is None:
        raise VigiAuthError("VIGI token response did not include access_token.")

    refresh_token = extract_string(payload, "refresh_token", "refreshToken")
    expires_in = payload.get("expires_in")
    expires_at = time.time() + expires_in if isinstance(expires_in, int) else None
    return VigiToken(
        access_token=urllib.parse.unquote(access_token),
        refresh_token=urllib.parse.unquote(refresh_token) if refresh_token else None,
        expires_at=expires_at,
    )


def extract_string(payload: dict[str, Any], *keys: str) -> str | None:
    """Extract a string from a nested token response."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value

    data = payload.get("data")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def as_list(payload: Any, key: str) -> list[dict[str, Any]]:
    """Return a list payload key as a list of objects."""
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def encode_json_strings(value: Any) -> Any:
    """Percent-encode JSON string values as required by the VIGI spec."""
    if isinstance(value, str):
        return urllib.parse.quote(value, safe="")
    if isinstance(value, list):
        return [encode_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: encode_json_strings(item) for key, item in value.items()}
    return value


def decode_json_strings(value: Any) -> Any:
    """Percent-decode JSON string values returned by VIGI."""
    if isinstance(value, str):
        return urllib.parse.unquote(value)
    if isinstance(value, list):
        return [decode_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: decode_json_strings(item) for key, item in value.items()}
    return value

"""Tests for VIGI OpenAPI client helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.vigi_nvr import api
from custom_components.vigi_nvr.api import (
    VigiApiError,
    VigiAuthError,
    VigiNvrClient,
    as_list,
    build_digest_authorization_variants,
    decode_json_strings,
    encode_json_strings,
    parse_digest_challenge,
    sha256_hex,
    token_from_payload,
)


class FakeResponse:
    """Async context manager that looks like an aiohttp response."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None

    async def text(self) -> str:
        """Return response text."""
        return self._body


class FakeSession:
    """Session fake that returns preconfigured responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        """Record a request and return the next response."""
        self.requests.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0)


def test_parse_digest_challenge_accepts_quoted_and_bare_values() -> None:
    """Digest challenges are parsed into lower-case field names."""
    challenge = parse_digest_challenge(
        'Digest realm="VIGI", nonce="abc123", algorithm=SHA-256, '
        'url="/openapi/token"'
    )

    assert challenge == {
        "realm": "VIGI",
        "nonce": "abc123",
        "algorithm": "SHA-256",
        "url": "/openapi/token",
    }


@pytest.mark.parametrize(
    "header",
    [
        "Basic realm=VIGI",
        'Digest realm="VIGI"',
        'Digest nonce="abc123"',
    ],
)
def test_parse_digest_challenge_rejects_invalid_headers(header: str) -> None:
    """Invalid or incomplete Digest challenges raise auth errors."""
    with pytest.raises(VigiAuthError):
        parse_digest_challenge(header)


def test_build_digest_authorization_variants_include_expected_response() -> None:
    """Digest Authorization variants use the documented SHA-256 calculation."""
    challenge = {"realm": "VIGI", "nonce": "nonce-value", "algorithm": "SHA-256"}
    variants = build_digest_authorization_variants(
        username="admin",
        password="secret",
        method="GET",
        uri="/openapi/token",
        challenge=challenge,
    )
    digest_a1 = sha256_hex("admin:VIGI:secret")
    digest_a2 = sha256_hex("GET:/openapi/token")
    expected_response = sha256_hex(f"{digest_a1}:nonce-value:{digest_a2}")

    assert len(variants) == 2
    assert all(variant.startswith("Digest ") for variant in variants)
    assert f'response="{expected_response}"' in variants[0]
    assert 'uri="/openapi/token"' in variants[1]
    assert 'algorithm="SHA-256"' in variants[1]


def test_build_digest_authorization_rejects_unknown_algorithm() -> None:
    """Unsupported Digest algorithms are rejected before making a request."""
    with pytest.raises(VigiAuthError, match="Unsupported VIGI Digest algorithm"):
        build_digest_authorization_variants(
            username="admin",
            password="secret",
            method="GET",
            uri="/openapi/token",
            challenge={"realm": "VIGI", "nonce": "abc", "algorithm": "MD5"},
        )


def test_token_from_payload_accepts_nested_and_encoded_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token extraction handles alternate keys, nested data, and URL encoding."""
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)

    token = token_from_payload(
        {
            "data": {
                "accessToken": "access%20token",
                "refreshToken": "refresh%20token",
            },
            "expires_in": 120,
        }
    )

    assert token.access_token == "access token"
    assert token.refresh_token == "refresh token"
    assert token.expires_at == 1120.0


@pytest.mark.parametrize("payload", [[], {}, {"data": {}}])
def test_token_from_payload_requires_access_token(payload: Any) -> None:
    """Malformed token responses raise auth errors."""
    with pytest.raises(VigiAuthError):
        token_from_payload(payload)


def test_as_list_filters_to_mapping_items() -> None:
    """Only dictionaries are returned from list payload helpers."""
    assert as_list({"devices": [{"id": 1}, "bad", {"id": 2}]}, "devices") == [
        {"id": 1},
        {"id": 2},
    ]
    assert as_list({"devices": "not-list"}, "devices") == []
    assert as_list([], "devices") == []


def test_encode_and_decode_json_strings_are_recursive() -> None:
    """VIGI string percent encoding is applied recursively."""
    payload = {
        "name": "Front Door",
        "nested": ["a/b", {"value": "100%"}],
        "number": 7,
    }

    encoded = encode_json_strings(payload)

    assert encoded == {
        "name": "Front%20Door",
        "nested": ["a%2Fb", {"value": "100%25"}],
        "number": 7,
    }
    assert decode_json_strings(encoded) == payload


def test_request_reauthenticates_after_unauthorized_and_decodes_json() -> None:
    """Bearer requests retry once after HTTP 401 and decode response strings."""
    session = FakeSession(
        [
            FakeResponse(401, "expired"),
            FakeResponse(200, json.dumps({"error_code": 0, "value": "ok%20now"})),
        ]
    )
    client = VigiNvrClient(
        session=session,
        host="nvr.local",
        port=20443,
        username="admin",
        password="secret",
    )
    client.authenticate = AsyncMock(side_effect=["old-token", "new-token"])

    result = asyncio.run(
        client.request(
            "POST",
            "/openapi/example",
            json_body={"name": "Front Door"},
        )
    )

    assert result == {"error_code": 0, "value": "ok now"}
    assert [
        request["headers"]["Authorization"] for request in session.requests
    ] == ["Bearer old-token", "Bearer new-token"]
    assert session.requests[0]["json"] == {"name": "Front%20Door"}


def test_request_raises_for_vigi_error_code() -> None:
    """Non-zero VIGI error codes are surfaced as API errors."""
    session = FakeSession([FakeResponse(200, json.dumps({"error_code": 12}))])
    client = VigiNvrClient(
        session=session,
        host="nvr.local",
        port=20443,
        username="admin",
        password="secret",
    )
    client.authenticate = AsyncMock(return_value="token")

    with pytest.raises(VigiApiError, match="error_code 12"):
        asyncio.run(client.request("GET", "/openapi/example"))
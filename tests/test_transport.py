"""Tests for the private HTTP transport layer."""

import asyncio
import socket
from http import HTTPStatus

import aiohttp
import pytest
from aioresponses import aioresponses

from aioengiebelgium import _transport
from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeInvalidResponseError,
)

_URL = "https://api.example.invalid/resource"


async def test_401_raises_authentication_error_with_status() -> None:
    with aioresponses() as m:
        m.get(_URL, status=401)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeAuthenticationError) as excinfo:
                await _transport.request_json(session, method="GET", url=_URL)
    assert excinfo.value.status == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize("status", [400, 403, 404, 500, 502, 503])
async def test_error_status_raises_communication_error(status: int) -> None:
    with aioresponses() as m:
        m.get(_URL, status=status)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeCommunicationError) as excinfo:
                await _transport.request_json(session, method="GET", url=_URL)
    assert excinfo.value.status == status


async def test_error_message_omits_response_body() -> None:
    with aioresponses() as m:
        m.get(_URL, status=500, body='{"ban": "1234567890", "detail": "secret"}')
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeCommunicationError) as excinfo:
                await _transport.request_json(session, method="GET", url=_URL)
    assert str(excinfo.value) == "API error 500"


async def test_timeout_raises_communication_error() -> None:
    with aioresponses() as m:
        m.get(_URL, exception=TimeoutError("timed out"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeCommunicationError):
                await _transport.request_json(session, method="GET", url=_URL)


@pytest.mark.parametrize(
    "exception",
    [
        aiohttp.ClientError("boom"),
        aiohttp.ClientConnectionError("boom"),
        socket.gaierror("name resolution failed"),
    ],
    ids=["client_error", "client_connection_error", "gaierror"],
)
async def test_network_errors_raise_communication_error(exception: Exception) -> None:
    with aioresponses() as m:
        m.get(_URL, exception=exception)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeCommunicationError):
                await _transport.request_json(session, method="GET", url=_URL)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("not-json{", "application/json"),
        ("<html>maintenance</html>", "text/html"),
    ],
    ids=["malformed_json_body", "non_json_content_type"],
)
async def test_undecodable_body_raises_invalid_response_error(
    body: str,
    content_type: str,
) -> None:
    with aioresponses() as m:
        m.get(_URL, body=body, content_type=content_type)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeInvalidResponseError):
                await _transport.request_json(session, method="GET", url=_URL)


async def test_non_dict_json_raises_invalid_response_error() -> None:
    with aioresponses() as m:
        m.get(_URL, payload=[1, 2, 3])
        async with aiohttp.ClientSession() as session:
            with pytest.raises(EngieBeInvalidResponseError):
                await _transport.request_json(session, method="GET", url=_URL)


async def test_timeout_param_defaults_to_30s_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeout parameter reaches asyncio.timeout; default is 30 seconds."""
    captured: list[float | None] = []
    real_timeout = asyncio.timeout

    def _capturing_timeout(delay: float | None) -> asyncio.Timeout:
        captured.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", _capturing_timeout)
    with aioresponses() as m:
        m.get(_URL, payload={"ok": True})
        m.get(_URL, payload={"ok": True})
        async with aiohttp.ClientSession() as session:
            await _transport.request_json(session, method="GET", url=_URL)
            await _transport.request_json(session, method="GET", url=_URL, timeout=5.0)
    assert captured == [30.0, 5.0]


async def test_request_text_location_lookup_is_case_insensitive() -> None:
    """A server sending lowercase ``location`` still satisfies a ``Location`` lookup."""
    with aioresponses() as m:
        m.get(
            _URL,
            body="hello",
            headers={"location": "https://example.invalid/next"},
        )
        async with aiohttp.ClientSession() as session:
            text, headers = await _transport.request_text(session, method="GET", url=_URL)
    assert text == "hello"
    assert headers.get("Location") == "https://example.invalid/next"

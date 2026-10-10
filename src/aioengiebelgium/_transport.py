import asyncio
import logging
import socket
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeError,
    EngieBeInvalidResponseError,
    EngieBeTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


@dataclass(slots=True)
class OwnedSession:
    """A ClientSession plus whether this library created (and must close) it."""

    session: aiohttp.ClientSession
    owned: bool

    async def close_if_owned(self) -> None:
        if self.owned:
            await self.session.close()


@asynccontextmanager
async def request(
    session: aiohttp.ClientSession,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    allow_redirects: bool = False,
    raise_on_error: bool = True,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
) -> AsyncIterator[aiohttp.ClientResponse]:
    """Perform one HTTP request, mapping failures to library exceptions."""
    try:
        started = time.monotonic()
        async with asyncio.timeout(timeout):
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                json=json_body,
                params=params,
                allow_redirects=allow_redirects,
            ) as response:
                split = urlsplit(url)
                _LOGGER.debug(
                    "%s %s%s -> %s in %.3fs",
                    method,
                    split.netloc,
                    split.path,
                    response.status,
                    time.monotonic() - started,
                )
                if raise_on_error:
                    if response.status == HTTPStatus.UNAUTHORIZED:
                        msg = "Authentication failed (401)"
                        raise EngieBeAuthenticationError(
                            msg,
                            status=HTTPStatus.UNAUTHORIZED,
                        )
                    if response.status >= HTTPStatus.BAD_REQUEST:
                        msg = f"API error {response.status}"
                        raise EngieBeCommunicationError(
                            msg,
                            status=response.status,
                        )
                yield response
    except EngieBeError:
        raise
    except TimeoutError as exc:
        msg = f"Timeout communicating with ENGIE API ({exc.__class__.__name__})"
        raise EngieBeTimeoutError(msg) from exc
    except (aiohttp.ClientError, socket.gaierror) as exc:
        msg = f"Error communicating with ENGIE API ({exc.__class__.__name__})"
        raise EngieBeCommunicationError(msg) from exc


async def json_object(response: aiohttp.ClientResponse) -> dict[str, Any]:
    """Parse the response body as JSON and require it to be a JSON object."""
    try:
        result = await response.json()
    except (aiohttp.ContentTypeError, ValueError) as exc:
        msg = "Response body is not valid JSON or has a non-JSON content type"
        raise EngieBeInvalidResponseError(msg) from exc
    if not isinstance(result, dict):
        msg = f"Expected JSON object, got {type(result).__name__}"
        raise EngieBeInvalidResponseError(msg)
    return result


async def request_json(
    session: aiohttp.ClientSession,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    expect_body: bool = True,
) -> dict[str, Any]:
    """Make a request and return its JSON object, or an empty dict when no body is expected."""
    async with request(
        session,
        method=method,
        url=url,
        headers=headers,
        json_body=json_body,
        params=params,
        timeout=timeout,
    ) as response:
        if not expect_body:
            if not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
                msg = f"Unexpected status {response.status} for a request without a body"
                raise EngieBeInvalidResponseError(msg)
            return {}
        return await json_object(response)


async def request_text(
    session: aiohttp.ClientSession,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    allow_redirects: bool = False,
    raise_on_error: bool = True,
    timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
) -> tuple[str, Mapping[str, str]]:
    """Make a request and return (text, response_headers)."""
    async with request(
        session,
        method=method,
        url=url,
        headers=headers,
        data=data,
        params=params,
        allow_redirects=allow_redirects,
        raise_on_error=raise_on_error,
        timeout=timeout,
    ) as response:
        return await response.text(), response.headers

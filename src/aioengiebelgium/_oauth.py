# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""OAuth token-endpoint primitive: the grant POST and its error taxonomy."""

import json
import logging
from http import HTTPStatus

import aiohttp

from ._transport import json_object, request
from .const import AUTH_BASE_URL, USER_AGENT_NATIVE
from .exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeError,
)

_LOGGER = logging.getLogger(__name__)


def _token_endpoint_error(status: int, body: str) -> EngieBeError:
    """Map a token-endpoint HTTP error to the library taxonomy."""
    if status == HTTPStatus.UNAUTHORIZED:
        msg = "Authentication failed (401)"
        return EngieBeAuthenticationError(msg, status=status)
    error_code: str | None = None
    if status in (HTTPStatus.BAD_REQUEST, HTTPStatus.FORBIDDEN):
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            raw = payload.get("error")
            if isinstance(raw, str):
                error_code = raw
    _LOGGER.debug("token endpoint error %s (%s)", status, error_code or "unparsed")
    if error_code == "invalid_grant":
        msg = "Token grant rejected (invalid_grant)"
        return EngieBeAuthenticationError(msg, status=status)
    msg = f"API error {status}"
    return EngieBeCommunicationError(msg, status=status)


async def exchange_token(
    session: aiohttp.ClientSession,
    data: dict[str, str],
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> tuple[str, str]:
    """POST the OAuth token endpoint and return (access_token, refresh_token)."""
    async with request(
        session,
        method="POST",
        url=f"{AUTH_BASE_URL}/oauth/token",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT_NATIVE,
        },
        data=data,
        raise_on_error=False,
        timeout=timeout,
    ) as response:
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise _token_endpoint_error(response.status, await response.text())
        result = await json_object(response)
    try:
        return result["access_token"], result["refresh_token"]
    except KeyError as exc:
        msg = "Token endpoint response missing tokens"
        raise EngieBeAuthenticationError(msg) from exc

# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""Token lifecycle: the OAuth token pair, its lock, rotation, and delivery."""

import asyncio
import json
import logging
from base64 import urlsafe_b64decode
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import aiohttp

from ._oauth import exchange_token
from .const import OAUTH_AUDIENCE, OAUTH_SCOPES, REDIRECT_URI
from .exceptions import EngieBeAuthenticationError

_LOGGER = logging.getLogger(__name__)

_EXPIRY_SKEW = timedelta(seconds=30)


def _jwt_expiry(token: str) -> datetime | None:
    try:
        _header, payload_b64, _signature = token.split(".")
    except ValueError:
        return None
    try:
        payload = json.loads(urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        return None
    try:
        return datetime.fromtimestamp(exp, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None


class TokenLifecycle:
    """Owns the token pair: storage, refresh, and ordered rotation delivery."""

    def __init__(
        self,
        *,
        client_id: str,
        session_provider: Callable[[], aiohttp.ClientSession],
        timeout: float,
        access_token: str | None = None,
        refresh_token: str | None = None,
        on_rotation: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._client_id = client_id
        self._session_provider = session_provider
        self._timeout = timeout
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._on_rotation = on_rotation
        self._lock = asyncio.Lock()
        self._rotation_seq = 0
        self._pending: deque[tuple[int, str, str]] = deque()
        self._delivering = False

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    @property
    def expiry(self) -> datetime | None:
        if self._access_token is None:
            return None
        return _jwt_expiry(self._access_token)

    def is_expired(self, now: datetime) -> bool:
        """Return True when the token's expiry is known and ``now`` is at or past it."""
        if now.tzinfo is None:
            msg = "timezone-aware datetimes required"
            raise ValueError(msg)
        expiry = self.expiry
        return expiry is not None and now >= expiry

    async def ensure_fresh(self) -> None:
        """Refresh proactively so the next request carries a live token."""
        if self._refresh_token is None:
            return
        if self._access_token is None:
            await self.refresh()
            return
        expiry = self.expiry
        if expiry is not None and datetime.now(UTC) >= expiry - _EXPIRY_SKEW:
            await self.refresh()

    def bearer(self) -> str:
        """The Authorization header value. Raises when unauthenticated."""
        if self._access_token is None:
            msg = "Not authenticated — call async_refresh_token() or authenticate first"
            raise EngieBeAuthenticationError(msg)
        return f"Bearer {self._access_token}"

    async def adopt(self, access_token: str, refresh_token: str) -> None:
        """Adopt a pair obtained by a completed auth flow and notify the consumer."""
        async with self._lock:
            self._record_rotation(access_token, refresh_token)
        await self._deliver_pending()

    async def refresh(self) -> tuple[str, str]:
        """Refresh tokens. Returns (new_access_token, new_refresh_token)."""
        if not self._refresh_token:
            msg = "No refresh token available"
            raise EngieBeAuthenticationError(msg)

        refresh_at_entry = self._refresh_token

        async with self._lock:
            if (
                self._refresh_token != refresh_at_entry
                and self._refresh_token is not None
                and self._access_token is not None
            ):
                return self._access_token, self._refresh_token

            _LOGGER.debug("refresh: rotating tokens")
            access_token, refresh_token = await exchange_token(
                self._session_provider(),
                {
                    "refresh_token": self._refresh_token,
                    "audience": OAUTH_AUDIENCE,
                    "grant_type": "refresh_token",
                    "scope": OAUTH_SCOPES,
                    "redirect_uri": REDIRECT_URI,
                    "client_id": self._client_id,
                },
                timeout=self._timeout,
            )

            self._record_rotation(access_token, refresh_token)
            _LOGGER.debug("refresh: tokens rotated")

        await self._deliver_pending()
        return access_token, refresh_token

    def _record_rotation(self, access_token: str, refresh_token: str) -> None:
        """Store a rotated pair and queue its delivery (the caller holds the lock)."""
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._rotation_seq += 1
        if self._on_rotation is not None:
            self._pending.append((self._rotation_seq, access_token, refresh_token))

    async def _deliver_pending(self) -> None:
        """Drain queued deliveries in rotation order, dropping superseded ones."""
        on_rotation = self._on_rotation
        if on_rotation is None or self._delivering:
            return
        self._delivering = True
        try:
            while self._pending:
                seq, access_token, refresh_token = self._pending.popleft()
                if seq < self._rotation_seq:
                    _LOGGER.debug(
                        "rotation %d superseded by rotation %d; dropping stale delivery",
                        seq,
                        self._rotation_seq,
                    )
                    continue
                try:
                    await on_rotation(access_token, refresh_token)
                except Exception:
                    _LOGGER.exception("on_token_refresh callback failed")
        finally:
            self._delivering = False

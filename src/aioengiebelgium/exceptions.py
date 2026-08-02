# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT

from http import HTTPStatus


class EngieBeError(Exception):
    """Base exception for the ENGIE Belgium API client errors."""

    def __init__(self, msg: str, *, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


class EngieBeCommunicationError(EngieBeError):
    """Communication errors (timeout, network, non-auth HTTP >= 400)."""


class EngieBeEpexNotPublishedError(EngieBeCommunicationError):
    """EPEX day-ahead prices not yet published for the requested window."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg, status=HTTPStatus.NOT_FOUND)


class EngieBeInvalidResponseError(EngieBeError):
    """A 2xx response whose body is not the expected JSON object."""


class EngieBeAuthenticationError(EngieBeError):
    """Authentication errors (bad credentials, expired token)."""


class EngieBeMfaError(EngieBeAuthenticationError):
    """MFA-related errors (invalid code)."""

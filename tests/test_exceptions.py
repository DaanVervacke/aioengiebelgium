"""Hierarchy pins for the exception taxonomy."""

from http import HTTPStatus

import pytest

from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeEpexNotPublishedError,
    EngieBeError,
    EngieBeInvalidResponseError,
    EngieBeMfaError,
)


def test_communication_handler_catches_epex_not_published() -> None:
    msg = "not published yet"
    with pytest.raises(EngieBeCommunicationError):
        raise EngieBeEpexNotPublishedError(msg)


def test_epex_not_published_carries_404_status() -> None:
    assert EngieBeEpexNotPublishedError("not published").status == HTTPStatus.NOT_FOUND


def test_authentication_handler_catches_mfa_error() -> None:
    msg = "invalid code"
    with pytest.raises(EngieBeAuthenticationError):
        raise EngieBeMfaError(msg)


@pytest.mark.parametrize(
    "exception_type",
    [
        EngieBeAuthenticationError,
        EngieBeCommunicationError,
        EngieBeEpexNotPublishedError,
        EngieBeInvalidResponseError,
        EngieBeMfaError,
    ],
)
def test_all_errors_subclass_base(exception_type: type[EngieBeError]) -> None:
    assert issubclass(exception_type, EngieBeError)

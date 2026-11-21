"""Hierarchy pins for the exception taxonomy."""

from http import HTTPStatus

import pytest

from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeClientClosedError,
    EngieBeCommunicationError,
    EngieBeEpexNotPublishedError,
    EngieBeError,
    EngieBeInvalidResponseError,
    EngieBeMfaError,
    EngieBeTimeoutError,
    _api_error_for,
)


def test_api_error_for_maps_401_to_authentication_error() -> None:
    err = _api_error_for(HTTPStatus.UNAUTHORIZED)
    assert isinstance(err, EngieBeAuthenticationError)
    assert str(err) == "Authentication failed (401)"
    assert err.status == HTTPStatus.UNAUTHORIZED


def test_api_error_for_maps_other_statuses_to_communication_error() -> None:
    err = _api_error_for(HTTPStatus.INTERNAL_SERVER_ERROR)
    assert type(err) is EngieBeCommunicationError
    assert str(err) == "API error 500"
    assert err.status == HTTPStatus.INTERNAL_SERVER_ERROR


def test_communication_handler_catches_epex_not_published() -> None:
    msg = "not published yet"
    with pytest.raises(EngieBeCommunicationError):
        raise EngieBeEpexNotPublishedError(msg)


def test_communication_handler_catches_timeout_error() -> None:
    msg = "timed out"
    with pytest.raises(EngieBeCommunicationError):
        raise EngieBeTimeoutError(msg)


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
        EngieBeClientClosedError,
        EngieBeCommunicationError,
        EngieBeEpexNotPublishedError,
        EngieBeInvalidResponseError,
        EngieBeMfaError,
        EngieBeTimeoutError,
    ],
)
def test_all_errors_subclass_base(exception_type: type[EngieBeError]) -> None:
    assert issubclass(exception_type, EngieBeError)

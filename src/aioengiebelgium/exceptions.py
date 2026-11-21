"""Exception hierarchy for the ENGIE Belgium API client."""

from http import HTTPStatus


class EngieBeError(Exception):
    """Base exception for the ENGIE Belgium API client errors."""

    def __init__(self, msg: str, *, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


class EngieBeCommunicationError(EngieBeError):
    """Communication errors (timeout, network, non-auth HTTP >= 400)."""


class EngieBeTimeoutError(EngieBeCommunicationError):
    """A request exceeded its timeout."""


class EngieBeEpexNotPublishedError(EngieBeCommunicationError):
    """EPEX day-ahead prices not yet published for the requested window."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg, status=HTTPStatus.NOT_FOUND)


class EngieBeInvalidResponseError(EngieBeError):
    """A response below HTTP 400 that the client cannot use.

    The body is not the expected JSON object, or a call that expects no body
    got a status outside 2xx.
    """


class EngieBeAuthenticationError(EngieBeError):
    """Authentication errors.

    Bad credentials, no token held, an expired or rejected token, a login page
    the flow cannot follow, or a token endpoint response without both tokens.
    """


class EngieBeMfaError(EngieBeAuthenticationError):
    """MFA-related errors (invalid code)."""


class EngieBeClientClosedError(EngieBeError):
    """The client was closed. Create a new EngieBeClient."""


def _api_error_for(status: int) -> EngieBeError:
    """Build the exception for an HTTP error status.

    Authentication at 401, communication for every other error status.
    """
    if status == HTTPStatus.UNAUTHORIZED:
        msg = "Authentication failed (401)"
        return EngieBeAuthenticationError(msg, status=status)
    msg = f"API error {status}"
    return EngieBeCommunicationError(msg, status=status)

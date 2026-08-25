"""Shared fixtures and auth-flow mock helpers for aioengiebelgium tests."""

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import ClientResponse
from aioresponses import aioresponses
from aioresponses import core as _aioresponses_core

from aioengiebelgium.const import AUTH_BASE_URL, REDIRECT_URI, MfaMethod

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_AUTH_CODE = "test-authorization-code"
_OAUTH_STATE = "test-oauth-state"
_LOGIN_STATE = "test-login-state"
_MFA_STATE = "mfaChallengeState123"
_USERNAME = "user@example.com"
_PASSWORD = "hunter2"
_TOKEN_RESPONSE = {"access_token": "new-access", "refresh_token": "new-refresh"}

_AUTHORIZE_URL = f"{AUTH_BASE_URL}/authorize"
_RESUME_URL = f"{AUTH_BASE_URL}/authorize/resume"
_TOKEN_URL = f"{AUTH_BASE_URL}/oauth/token"
_LOGIN_IDENTIFIER_URL = f"{AUTH_BASE_URL}/u/login/identifier"
_LOGIN_PASSWORD_URL = f"{AUTH_BASE_URL}/u/login/password"
_MFA_SMS_URL = f"{AUTH_BASE_URL}/u/mfa-sms-challenge"
_MFA_EMAIL_URL = f"{AUTH_BASE_URL}/u/mfa-email-challenge"
_MFA_LOGIN_OPTIONS_URL = f"{AUTH_BASE_URL}/u/mfa-login-options"

_IDENTIFIER_CAPABILITIES = {
    "allow-passkeys": "true",
    "js-available": "false",
    "webauthn-available": "false",
    "is-brave": "false",
    "webauthn-platform-available": "false",
    "ulp-remember-me-present": "true",
}
_PASSWORD_CAPABILITIES = {
    "js-available": "false",
    "webauthn-available": "false",
    "is-brave": "false",
    "webauthn-platform-available": "false",
}


def _q(url: str) -> re.Pattern[str]:
    """Match ``url`` regardless of query string."""
    return re.compile(rf"^{re.escape(url)}(\?.*)?$")


def _hidden_inputs(fields: dict[str, str]) -> str:
    return "".join(
        f'<input type="hidden" name="{name}" value="{value}"/>' for name, value in fields.items()
    )


def _redirect_body(state: str, path: str = "/u/x") -> str:
    """Auth0-style ``Redirecting to <a href=?state=...>`` body used when a POST returns 302."""
    return (
        f'<html><body><p>Found. Redirecting to '
        f'<a href="{path}?state={state}&amp;ui_locales=nl">go</a></p></body></html>'
    )


def _identifier_body(state: str) -> str:
    """GET /u/login/identifier: primary form carrying capability flags + state."""
    return (
        f'<html><form class="_form-login-id" data-form-primary="true" method="POST">'
        f"{_hidden_inputs({'state': state, **_IDENTIFIER_CAPABILITIES})}"
        f"</form></html>"
    )


def _password_body(state: str) -> str:
    """GET /u/login/password: primary form carrying capability flags + state."""
    return (
        f'<html><form class="_form-login-password" data-form-primary="true" method="POST">'
        f"{_hidden_inputs({'state': state, **_PASSWORD_CAPABILITIES})}"
        f"</form></html>"
    )


def _mfa_sms_body(state: str) -> str:
    """GET /u/mfa-sms-challenge: primary form + a pick-authenticator secondary form."""
    return (
        f'<html>'
        f'<form data-form-primary="true" method="POST">{_hidden_inputs({"state": state})}</form>'
        f'<form class="ulp-action-form-pick-authenticator" method="POST">'
        f'{_hidden_inputs({"state": state})}</form>'
        f'</html>'
    )


def _mfa_email_body(state: str) -> str:
    return (
        f'<html><form data-form-primary="true" method="POST">'
        f"{_hidden_inputs({'state': state})}</form></html>"
    )


def _mfa_login_options_body(state: str) -> str:
    return (
        f'<html><form data-form-primary="true" method="POST">'
        f"{_hidden_inputs({'state': state})}</form></html>"
    )


def _callback_url(code: str = _AUTH_CODE, state: str = _OAUTH_STATE) -> str:
    return f"{REDIRECT_URI}?code={code}&state={state}"


def _mfa_submit_url(mfa: MfaMethod) -> str:
    return f"{AUTH_BASE_URL}/u/mfa-{mfa.value}-challenge"


def _register_auth_steps_1_to_7(m: aioresponses, *, mfa: MfaMethod = MfaMethod.SMS) -> None:
    """Register mocks for the credentials half of the flow (steps 1-7)."""
    m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
    m.get(_q(_LOGIN_IDENTIFIER_URL), body=_identifier_body(_OAUTH_STATE))
    m.post(_q(_LOGIN_IDENTIFIER_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/password"))
    m.get(_q(_LOGIN_PASSWORD_URL), body=_password_body(_OAUTH_STATE))
    m.post(_q(_LOGIN_PASSWORD_URL), body=_redirect_body(_LOGIN_STATE, "/authorize/resume"))
    m.get(_q(_RESUME_URL), body=_redirect_body(_MFA_STATE, f"/u/mfa-{mfa.value}-challenge"))
    if mfa is MfaMethod.SMS:
        m.get(_q(_MFA_SMS_URL), body=_mfa_sms_body(_MFA_STATE))
    else:
        m.get(_q(_MFA_SMS_URL), body=_mfa_sms_body(_MFA_STATE))
        m.post(_q(_MFA_SMS_URL), body=_redirect_body(_MFA_STATE, "/u/mfa-login-options"))
        m.get(_q(_MFA_LOGIN_OPTIONS_URL), body=_mfa_login_options_body(_MFA_STATE))
        m.post(
            _q(_MFA_LOGIN_OPTIONS_URL),
            body=_redirect_body(_MFA_STATE, "/u/mfa-email-challenge"),
        )
        m.get(_q(_MFA_EMAIL_URL), body=_mfa_email_body(_MFA_STATE))


def _register_submit_shortcircuit(
    m: aioresponses,
    *,
    state: str,
    mfa: MfaMethod = MfaMethod.SMS,
) -> None:
    """Steps 8-13: MFA POST 302s, resume 302s to the callback URI, token exchange succeeds."""
    m.post(_q(_mfa_submit_url(mfa)), body=_redirect_body("postmfastate", "/authorize/resume"))
    m.get(
        _q(_RESUME_URL),
        status=302,
        headers={"Location": _callback_url(state=state)},
        body="",
    )
    m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, Any]]:
    """Return a helper that loads a JSON fixture by name."""

    def _load(name: str) -> dict[str, Any]:
        return cast("dict[str, Any]", json.loads((FIXTURES_DIR / name).read_text()))

    return _load


@pytest.fixture
def created_sessions(monkeypatch: pytest.MonkeyPatch) -> list[aiohttp.ClientSession]:
    """Track every aiohttp session the code under test creates.

    Lets ownership tests observe session closure through public state instead
    of reaching into ``flow._session``.
    """
    created: list[aiohttp.ClientSession] = []
    real_session_cls = aiohttp.ClientSession

    def _tracking_factory(*args: Any, **kwargs: Any) -> aiohttp.ClientSession:
        session = real_session_cls(*args, **kwargs)
        created.append(session)
        return session

    monkeypatch.setattr(aiohttp, "ClientSession", _tracking_factory)
    return created


# aioresponses<=0.7.9 misses aiohttp>=3.14's stream_writer kwarg (aioresponses#288, unreleased).
# Delete this shim when the dev pin can move past 0.7.9.
_original_build_response = _aioresponses_core.RequestMatch._build_response


def _build_response_with_stream_writer(self: Any, *args: Any, **kwargs: Any) -> Any:
    response_class = kwargs.get("response_class") or ClientResponse
    if "stream_writer" in inspect.signature(response_class).parameters:

        class _StreamWriterCompatResponse(response_class):  # type: ignore[misc, valid-type]
            def __init__(self, *a: Any, **kw: Any) -> None:
                kw.setdefault("stream_writer", Mock(output_size=0))
                super().__init__(*a, **kw)

        kwargs["response_class"] = _StreamWriterCompatResponse
    return _original_build_response(self, *args, **kwargs)


_aioresponses_core.RequestMatch._build_response = _build_response_with_stream_writer  # type: ignore[method-assign]

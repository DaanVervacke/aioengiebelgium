"""Tests for the OAuth2/PKCE + MFA authentication flow."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses
from aioresponses.core import RequestCall

import aioengiebelgium
from aioengiebelgium import _tokens
from aioengiebelgium._auth import (
    _FIELD_ERROR_MARKER,
    AuthFlow,
    _base64url,
    _generate_pkce,
    _harvest_hidden_inputs,
    _state_from_body,
)
from aioengiebelgium._oauth import exchange_token
from aioengiebelgium.client import EngieBeClient
from aioengiebelgium.const import (
    BILLING_BASE_URL,
    DEFAULT_CLIENT_ID,
    OAUTH_AUDIENCE,
    OAUTH_SCOPES,
    REDIRECT_URI,
    MfaMethod,
)
from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeClientClosedError,
    EngieBeCommunicationError,
    EngieBeError,
    EngieBeInvalidResponseError,
    EngieBeMfaError,
)
from tests.conftest import (
    _AUTH_CODE,
    _AUTHORIZE_URL,
    _IDENTIFIER_CAPABILITIES,
    _LOGIN_IDENTIFIER_URL,
    _LOGIN_PASSWORD_URL,
    _LOGIN_STATE,
    _MFA_SMS_URL,
    _MFA_STATE,
    _OAUTH_STATE,
    _PASSWORD,
    _PASSWORD_CAPABILITIES,
    _RESUME_URL,
    _TOKEN_RESPONSE,
    _TOKEN_URL,
    _USERNAME,
    _callback_url,
    _identifier_body,
    _mfa_sms_body,
    _mfa_submit_url,
    _password_body,
    _q,
    _redirect_body,
    _register_auth_steps_1_to_7,
    _register_submit_shortcircuit,
)


def _html_fixture(name: str) -> str:
    """Load a sanitized real HTML trace from tests/fixtures."""
    return (Path(__file__).parent / "fixtures" / name).read_text()


def _capture_body(name: str) -> str:
    """Body of a sanitized .http capture, minus the capture-note first line."""
    return (Path(__file__).parent / "fixtures" / name).read_text().split("\n", 1)[1]


def _recorded(m: aioresponses, method: str, path: str) -> list[RequestCall]:
    """All recorded calls with ``method`` whose URL path is exactly ``path``."""
    return [
        call
        for (request_method, url), calls in m.requests.items()
        if request_method == method and url.path == path
        for call in calls
    ]


async def _start_flow(
    client: EngieBeClient,
    mfa: MfaMethod = MfaMethod.SMS,
    auth_session: aiohttp.ClientSession | None = None,
) -> AuthFlow:
    return await client.async_start_authentication(
        _USERNAME,
        _PASSWORD,
        mfa,
        auth_session=auth_session,
    )


def test_base64url_is_urlsafe_and_unpadded() -> None:
    assert _base64url(b"\xfb\xff\xfe") == "-__-"
    assert "=" not in _base64url(b"\x00")


def test_generate_pkce_returns_distinct_well_formed_values() -> None:
    state, nonce, verifier, challenge = _generate_pkce()

    assert len(state) == 32
    assert len(nonce) == 32
    assert state != nonce
    int(state, 16)
    int(nonce, 16)

    assert len(verifier) == 43
    assert "=" not in verifier

    expected_challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    assert challenge == expected_challenge

    assert _generate_pkce()[0] != state


def test_mfa_method_enum_replaces_string_constants() -> None:
    assert MfaMethod.SMS.value == "sms"
    assert MfaMethod.EMAIL.value == "email"
    assert "MfaMethod" in aioengiebelgium.__all__
    assert "AuthFlow" in aioengiebelgium.__all__
    assert not hasattr(aioengiebelgium, "MFA_METHOD_SMS")
    assert not hasattr(aioengiebelgium, "MFA_METHOD_EMAIL")
    assert not hasattr(aioengiebelgium, "AuthFlowState")


async def test_refresh_token_without_token_raises() -> None:
    client = EngieBeClient()
    with pytest.raises(EngieBeAuthenticationError):
        await client.async_refresh_token()


async def test_refresh_token_happy_path() -> None:
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh")
        access, refresh = await client.async_refresh_token()
        await client.close()

    assert access == "new-access"
    assert refresh == "new-refresh"
    assert client.access_token == "new-access"
    assert client.refresh_token == "new-refresh"


async def test_refresh_request_carries_grant_fields_and_rotates_token() -> None:
    """The refresh POST pins the wire contract, and the next refresh uses the rotated token."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        m.post(
            _q(_TOKEN_URL),
            payload={"access_token": "second-access", "refresh_token": "second-refresh"},
        )
        client = EngieBeClient(refresh_token="old-refresh")
        await client.async_refresh_token()
        await client.async_refresh_token()
        await client.close()
        first, second = _recorded(m, "POST", "/oauth/token")

    assert first.kwargs["data"] == {
        "refresh_token": "old-refresh",
        "audience": OAUTH_AUDIENCE,
        "grant_type": "refresh_token",
        "scope": OAUTH_SCOPES,
        "redirect_uri": REDIRECT_URI,
        "client_id": DEFAULT_CLIENT_ID,
    }
    assert second.kwargs["data"]["refresh_token"] == "new-refresh"
    assert client.refresh_token == "second-refresh"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"access_token": "a", "refresh_token": None}, id="null_refresh"),
        pytest.param({"access_token": None, "refresh_token": "r"}, id="null_access"),
        pytest.param({"access_token": "", "refresh_token": "r"}, id="empty_access"),
        pytest.param({"access_token": 5, "refresh_token": ["x"]}, id="wrong_types"),
    ],
)
async def test_refresh_token_response_with_unusable_tokens_raises_auth_error(
    payload: dict[str, object],
) -> None:
    """A token response with null, empty or non-string tokens never replaces the stored pair."""
    delivered: list[tuple[str, str]] = []

    async def on_refresh(access: str, refresh: str) -> None:
        delivered.append((access, refresh))

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=payload)
        client = EngieBeClient(refresh_token="old-refresh", on_token_refresh=on_refresh)
        with pytest.raises(EngieBeAuthenticationError, match="missing tokens"):
            await client.async_refresh_token()
        assert client.refresh_token == "old-refresh"
        assert delivered == []
        await client.close()


async def test_refresh_token_response_missing_tokens_raises_auth_error() -> None:
    """A 200 token response without refresh_token surfaces as an auth error, not KeyError."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload={"access_token": "only-access"})
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeAuthenticationError, match="missing tokens"):
            await client.async_refresh_token()
        await client.close()


@pytest.mark.parametrize("status", [400, 403])
async def test_refresh_invalid_grant_is_authentication_error(status: int) -> None:
    """A burned refresh token (captured 403 invalid_grant) means re-authenticate.

    The captured contract (tests/fixtures/token_invalid_grant.http) is a
    token-endpoint 403 with an ``invalid_grant`` JSON body. Auth0 documents
    400 for the same rejection, so both are pinned.
    """
    body = _capture_body("token_invalid_grant.http")
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), status=status, body=body, content_type="application/json")
        client = EngieBeClient(refresh_token="burned-refresh")
        with pytest.raises(EngieBeAuthenticationError) as excinfo:
            await client.async_refresh_token()
        await client.close()

    assert excinfo.value.status == status
    assert not isinstance(excinfo.value, EngieBeMfaError)
    assert "Unknown or invalid refresh token" not in str(excinfo.value)
    assert client.access_token is None
    assert client.refresh_token == "burned-refresh"


@pytest.mark.parametrize("status", [400, 403])
async def test_auto_refresh_invalid_grant_surfaces_authentication_error(status: int) -> None:
    """The 401 -> refresh -> invalid_grant getter path surfaces reauth, chaining the 401."""
    url = f"{BILLING_BASE_URL}/business-agreements/123/supplier-energy-prices"
    body = _capture_body("token_invalid_grant.http")
    with aioresponses() as m:
        m.get(_q(url), status=401)
        m.post(_q(_TOKEN_URL), status=status, body=body, content_type="application/json")
        client = EngieBeClient(access_token="stale", refresh_token="burned-refresh")
        with pytest.raises(EngieBeAuthenticationError) as excinfo:
            await client.async_get_prices("123")
        await client.close()

    assert excinfo.value.status == status
    cause = excinfo.value.__cause__
    assert isinstance(cause, EngieBeAuthenticationError)
    assert cause.status == HTTPStatus.UNAUTHORIZED
    assert "Unknown or invalid refresh token" not in str(excinfo.value)
    assert client.access_token == "stale"
    assert client.refresh_token == "burned-refresh"


async def test_refresh_token_endpoint_401_maps_to_authentication_error() -> None:
    """A token-endpoint 401 keeps its pre-050 authentication mapping."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), status=401, body="")
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeAuthenticationError, match=r"^Authentication failed \(401\)$"):
            await client.async_refresh_token()
        await client.close()


@pytest.mark.parametrize(
    ("status", "body", "content_type"),
    [
        (400, '{"error":"invalid_request"}', "application/json"),
        (403, "denied", "text/plain"),
        (400, "[1, 2, 3]", "application/json"),
        (403, '"denied"', "application/json"),
        (400, '{"error": 42}', "application/json"),
    ],
    ids=[
        "json_other_error",
        "non_json_body",
        "json_non_object_400",
        "json_non_object_403",
        "json_non_string_error",
    ],
)
async def test_refresh_token_endpoint_4xx_without_invalid_grant_stays_communication_error(
    status: int,
    body: str,
    content_type: str,
) -> None:
    """A token-endpoint 400/403 that is not invalid_grant keeps the communication mapping."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), status=status, body=body, content_type=content_type)
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeCommunicationError, match=rf"^API error {status}$") as excinfo:
            await client.async_refresh_token()
        await client.close()

    assert excinfo.value.status == status
    assert client.refresh_token == "old-refresh"


async def test_refresh_token_endpoint_500_is_communication_error() -> None:
    """A token-endpoint server failure is an outage, never a reauth signal."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), status=500, body='{"error":"invalid_grant"}')
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeCommunicationError, match=r"^API error 500$"):
            await client.async_refresh_token()
        await client.close()


async def test_refresh_token_response_not_json_raises_invalid_response() -> None:
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), body="<html>totally fine</html>", content_type="text/html")
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeInvalidResponseError, match="not valid JSON"):
            await client.async_refresh_token()
        await client.close()


async def test_refresh_token_response_non_object_json_raises_invalid_response() -> None:
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=[1, 2, 3])
        client = EngieBeClient(refresh_token="old-refresh")
        with pytest.raises(EngieBeInvalidResponseError, match="Expected JSON object, got list"):
            await client.async_refresh_token()
        await client.close()


def _jwt_with_exp(exp: float, sub: str | None = None) -> str:
    payload_dict: dict[str, Any] = {"exp": exp}
    if sub is not None:
        payload_dict["sub"] = sub
    payload = _base64url(json.dumps(payload_dict).encode("ascii"))
    return f"e30.{payload}.fakesig"


def test_token_attributes_are_read_only() -> None:
    client = EngieBeClient(access_token="a", refresh_token="b")
    with pytest.raises(AttributeError):
        client.access_token = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        client.refresh_token = "y"  # type: ignore[misc]
    assert client.access_token == "a"
    assert client.refresh_token == "b"


def test_access_token_expiry_from_jwt() -> None:
    exp = 1893456000
    client = EngieBeClient(access_token=_jwt_with_exp(exp))
    assert client.access_token_expiry == datetime.fromtimestamp(exp, tz=UTC)
    assert EngieBeClient(access_token="not-a-jwt").access_token_expiry is None
    assert EngieBeClient(access_token="a.!!!.c").access_token_expiry is None
    assert EngieBeClient().access_token_expiry is None

    list_payload = _base64url(b"[1]")
    assert EngieBeClient(access_token=f"e30.{list_payload}.s").access_token_expiry is None
    string_exp = _base64url(b'{"exp": "soon"}')
    assert EngieBeClient(access_token=f"e30.{string_exp}.s").access_token_expiry is None
    assert EngieBeClient(access_token=_jwt_with_exp(1e300)).access_token_expiry is None


def test_is_access_token_expired() -> None:
    exp = 1893456000
    client = EngieBeClient(access_token=_jwt_with_exp(exp))
    expiry = datetime.fromtimestamp(exp, tz=UTC)

    assert not client.is_access_token_expired(expiry - timedelta(seconds=1))
    assert client.is_access_token_expired(expiry)
    assert client.is_access_token_expired(expiry + timedelta(hours=1))

    with pytest.raises(ValueError, match="timezone-aware"):
        client.is_access_token_expired(datetime(2030, 1, 1))  # noqa: DTZ001

    assert not EngieBeClient(access_token="opaque").is_access_token_expired(expiry)


def test_subject_from_jwt() -> None:
    client = EngieBeClient(access_token=_jwt_with_exp(1893456000, sub="auth0|abc123"))
    assert client.subject == "auth0|abc123"
    assert EngieBeClient(access_token="not-a-jwt").subject is None
    assert EngieBeClient(access_token="a.!!!.c").subject is None
    assert EngieBeClient().subject is None

    assert EngieBeClient(access_token=_jwt_with_exp(1893456000)).subject is None

    int_sub = _base64url(json.dumps({"sub": 12345}).encode("ascii"))
    assert EngieBeClient(access_token=f"e30.{int_sub}.s").subject is None

    list_payload = _base64url(b"[1]")
    assert EngieBeClient(access_token=f"e30.{list_payload}.s").subject is None


def test_subject_allows_empty_string() -> None:
    assert EngieBeClient(access_token=_jwt_with_exp(1893456000, sub="")).subject == ""


async def test_concurrent_refreshes_do_exactly_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two racing refreshes serialize on the lock, and the loser adopts the winner's tokens."""
    real_exchange_token = exchange_token

    async def yielding_exchange_token(*args: Any, **kwargs: Any) -> tuple[str, str]:
        await asyncio.sleep(0)
        return await real_exchange_token(*args, **kwargs)

    monkeypatch.setattr(_tokens, "exchange_token", yielding_exchange_token)

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh")
        results = await asyncio.gather(
            client.async_refresh_token(),
            client.async_refresh_token(),
        )
        await client.close()
        total_requests = sum(len(reqs) for reqs in m.requests.values())

    assert total_requests == 1
    assert results[0] == results[1] == ("new-access", "new-refresh")


async def test_concurrent_401_refresh_is_single_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two gathered requests both hitting 401 trigger exactly one token refresh."""
    real_exchange_token = exchange_token

    async def yielding_exchange_token(*args: Any, **kwargs: Any) -> tuple[str, str]:
        await asyncio.sleep(0)
        return await real_exchange_token(*args, **kwargs)

    monkeypatch.setattr(_tokens, "exchange_token", yielding_exchange_token)

    url_a = f"{BILLING_BASE_URL}/business-agreements/1/supplier-energy-prices"
    url_b = f"{BILLING_BASE_URL}/business-agreements/2/supplier-energy-prices"
    with aioresponses() as m:
        m.get(_q(url_a), status=401)
        m.get(_q(url_b), status=401)
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        m.get(_q(url_a), payload={"items": []})
        m.get(_q(url_b), payload={"items": []})
        client = EngieBeClient(access_token="stale", refresh_token="old-refresh")
        await asyncio.gather(client.async_get_prices("1"), client.async_get_prices("2"))
        await client.close()
        token_posts = _recorded(m, "POST", "/oauth/token")

    assert len(token_posts) == 1
    assert client.refresh_token == "new-refresh"


@pytest.mark.parametrize("mfa", MfaMethod)
async def test_start_authentication_happy_path(mfa: MfaMethod) -> None:
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m, mfa=mfa)
        client = EngieBeClient()
        flow = await _start_flow(client, mfa)

    assert isinstance(flow, AuthFlow)
    await flow.async_abort()


async def test_authorize_request_carries_pkce_and_oauth_params() -> None:
    """The /authorize GET pins the PKCE challenge and OAuth wire parameters."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        (authorize,) = _recorded(m, "GET", "/authorize")
        await flow.async_abort()

    params = authorize.kwargs["params"]
    expected_challenge = _base64url(hashlib.sha256(flow._code_verifier.encode("ascii")).digest())
    assert len(params["code_challenge"]) == 43
    assert params["code_challenge"] == expected_challenge
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == flow._expected_state
    assert len(params["nonce"]) == 32
    int(params["nonce"], 16)
    assert params["client_id"] == DEFAULT_CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["response_type"] == "code"
    assert params["scope"] == OAUTH_SCOPES
    assert params["audience"] == OAUTH_AUDIENCE


async def test_login_posts_carry_credentials_and_form_fields() -> None:
    """The identifier and password POSTs pin the exact form fields sent."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        (identifier_post,) = _recorded(m, "POST", "/u/login/identifier")
        (password_post,) = _recorded(m, "POST", "/u/login/password")
        await flow.async_abort()

    assert identifier_post.kwargs["params"] == {"state": _OAUTH_STATE, "ui_locales": "nl"}
    assert identifier_post.kwargs["data"] == {
        "state": _OAUTH_STATE,
        **_IDENTIFIER_CAPABILITIES,
        "username": _USERNAME,
    }
    assert password_post.kwargs["params"] == {"state": _OAUTH_STATE, "ui_locales": "nl"}
    assert password_post.kwargs["data"] == {
        "state": _OAUTH_STATE,
        **_PASSWORD_CAPABILITIES,
        "username": _USERNAME,
        "password": _PASSWORD,
    }


async def test_entity_encoded_hidden_input_is_decoded_and_reposted() -> None:
    """An entity-encoded hidden input is html-unescaped before it is re-posted."""
    with aioresponses() as m:
        m.get(
            _q(_LOGIN_IDENTIFIER_URL),
            body=_html_fixture("auth_page_identifier_entity_encoded.html"),
        )
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        (identifier_post,) = _recorded(m, "POST", "/u/login/identifier")
        await flow.async_abort()

    assert identifier_post.kwargs["data"]["extra-context"] == '{"k":"v"}'


async def test_start_authentication_failure_closes_created_session(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A failing start closes the session the client created internally."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body="<html>no state here</html>")
        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError):
            await client.async_start_authentication(_USERNAME, _PASSWORD)

    assert len(created_sessions) == 1
    assert created_sessions[0].closed


async def test_start_authentication_failure_keeps_injected_session_open() -> None:
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body="<html>no state here</html>")
        async with aiohttp.ClientSession() as injected:
            client = EngieBeClient()
            with pytest.raises(EngieBeAuthenticationError):
                await _start_flow(client, auth_session=injected)
            assert not injected.closed


async def test_start_authentication_cancelled_closes_created_session(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A start cancelled mid-flow still closes the session the client created."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), exception=asyncio.CancelledError())
        client = EngieBeClient()
        with pytest.raises(asyncio.CancelledError):
            await client.async_start_authentication(_USERNAME, _PASSWORD)

    assert len(created_sessions) == 1
    assert created_sessions[0].closed


async def test_auth_flow_context_exit_closes_created_session(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """Leaving the flow's ``async with`` block without a code aborts the flow."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        async with await _start_flow(client):
            assert not created_sessions[0].closed

    assert created_sessions[0].closed


async def test_auth_flow_context_exit_after_submit_keeps_tokens(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """Exiting the block after a successful submit is harmless."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        async with await _start_flow(client) as flow:
            _register_submit_shortcircuit(m, state=flow._expected_state)
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed
    assert client.access_token == _TOKEN_RESPONSE["access_token"]
    await client.close()


async def test_auth_flow_context_exit_keeps_injected_session_open() -> None:
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        async with aiohttp.ClientSession() as injected:
            client = EngieBeClient()
            async with await _start_flow(client, auth_session=injected):
                pass
            assert not injected.closed


async def test_start_authentication_missing_login_state_raises() -> None:
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), body="<html>bad credentials</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match="bad credentials"):
            await client.async_start_authentication(_USERNAME, _PASSWORD)


async def test_start_authentication_wrong_password_raises_invalid_credentials() -> None:
    """The real wrong-password trace (HTTP 400 re-render) maps to a clean auth error."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(
            _q(_LOGIN_PASSWORD_URL),
            status=400,
            body=_html_fixture("auth_wrong_password.html"),
        )

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match=r"^Invalid credentials$") as excinfo:
            await client.async_start_authentication(_USERNAME, _PASSWORD)

    assert not isinstance(excinfo.value, EngieBeCommunicationError)
    assert excinfo.value.status == 400


def test_state_from_body_falls_back_to_link_when_action_stateless() -> None:
    """A stateless form action no longer masks a state carried in a body link."""
    body = '<form action="/toggle"></form><a href="/continue?state=linkstate">go</a>'
    assert _state_from_body(body) == "linkstate"


def test_state_from_body_prefers_primary_form_state_over_link() -> None:
    """A page carrying the state in both places yields the primary form's value."""
    body = (
        '<form data-form-primary="true">'
        '<input type="hidden" name="state" value="formstate"/>'
        "</form>"
        '<a href="/continue?state=linkstate">go</a>'
    )
    assert _state_from_body(body) == "formstate"


def test_state_from_body_reads_link_when_no_form() -> None:
    assert _state_from_body('<a href="/x?state=abc123">x</a>') == "abc123"


def test_state_from_body_returns_none_without_state() -> None:
    assert _state_from_body("<html>no state here</html>") is None


def test_state_from_body_ignores_links_outside_the_primary_form() -> None:
    """A primary form without a state input must not adopt a foreign link's state."""
    body = (
        '<form data-form-primary="true">'
        '<input type="hidden" name="action" value="default"/>'
        "</form>"
        '<a href="/elsewhere?state=foreign">go</a>'
    )
    assert _state_from_body(body) is None


def test_state_from_body_falls_back_to_state_within_the_form_scope() -> None:
    """A primary form without a hidden state yields a state carried inside that form."""
    body = (
        '<form data-form-primary="true">'
        '<a href="/x?state=inscope">go</a>'
        "</form>"
        '<a href="/y?state=foreign">elsewhere</a>'
    )
    assert _state_from_body(body) == "inscope"


def test_state_from_body_ignores_state_outside_anchor_hrefs() -> None:
    """A formless redirect body yields state from an anchor href only, not loose text."""
    assert _state_from_body("<p>?state=loose-text</p>") is None


def test_state_from_body_reads_first_stateful_anchor_in_redirect_body() -> None:
    body = '<a href="/x">first</a><a href="/y?state=second">go</a>'
    assert _state_from_body(body) == "second"


def test_harvest_scopes_to_primary_form_and_ignores_secondary() -> None:
    """Multi-form pages must not leak sibling-form fields into the primary POST body."""
    body = (
        '<form data-form-primary="true">'
        '<input type="hidden" name="state" value="primary"/>'
        '<input type="hidden" name="allow-passkeys" value="true"/>'
        "</form>"
        '<form data-form-secondary="true">'
        '<input type="hidden" name="state" value="secondary"/>'
        '<input type="hidden" name="connection" value="itsme"/>'
        "</form>"
    )
    assert _harvest_hidden_inputs(body) == {"state": "primary", "allow-passkeys": "true"}
    assert _harvest_hidden_inputs(body, form_marker='data-form-secondary="true"') == {
        "state": "secondary",
        "connection": "itsme",
    }


def test_harvest_returns_empty_when_no_matching_form() -> None:
    assert _harvest_hidden_inputs("<html>no forms</html>") == {}


def test_harvest_keeps_missing_value_as_empty_string() -> None:
    body = (
        '<form data-form-primary="true"><input type="hidden" id="passkey" name="passkey"/></form>'
    )
    assert _harvest_hidden_inputs(body) == {"passkey": ""}


def test_harvest_skips_hidden_input_without_name() -> None:
    body = (
        '<form data-form-primary="true">'
        '<input type="hidden" value="nameless"/>'
        '<input type="hidden" name="state" value="named"/>'
        "</form>"
    )
    assert _harvest_hidden_inputs(body) == {"state": "named"}


def test_harvest_accepts_single_quoted_value_attributes() -> None:
    body = (
        '<form data-form-primary="true">'
        '<input type="hidden" name="state" value=\'single-quoted\'/>'
        "</form>"
    )
    assert _harvest_hidden_inputs(body) == {"state": "single-quoted"}


async def test_wrong_password_detected_before_state_extraction() -> None:
    """The error marker is checked before extraction, so a re-render still carrying a
    usable state is not mistaken for a successful login."""
    body = f'<span {_FIELD_ERROR_MARKER}>wrong</span><form action="/x?state=deadbeef01"></form>'
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), status=200, body=body)

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match=r"^Invalid credentials$"):
            await client.async_start_authentication(_USERNAME, _PASSWORD)


async def test_login_400_without_error_marker_raises_invalid_credentials() -> None:
    """A 400 with neither the error marker nor a usable state is still a credential error."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), status=400, body="<html>no state</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match=r"^Invalid credentials$") as excinfo:
            await client.async_start_authentication(_USERNAME, _PASSWORD)
    assert excinfo.value.status == 400


async def test_login_200_without_state_raises_login_failed() -> None:
    """A 200 password response with no marker and no extractable state is an unrecognized page."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), status=200, body="<html>no state</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match="could not extract login state"):
            await client.async_start_authentication(_USERNAME, _PASSWORD)


async def test_start_authentication_password_post_500_is_communication_error() -> None:
    """A server-side failure on the password POST is not misread as bad credentials."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), status=500, body="<html>upstream broke</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeCommunicationError, match="API error 500"):
            await client.async_start_authentication(_USERNAME, _PASSWORD)


async def test_start_authentication_password_post_429_is_communication_error() -> None:
    """A rate limit on the password POST is not misread as bad credentials."""
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), status=429, body="<html>slow down</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeCommunicationError, match="API error 429") as excinfo:
            await client.async_start_authentication(_USERNAME, _PASSWORD)
    assert excinfo.value.status == 429


async def test_submit_mfa_server_error_is_communication_error(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A server error on the MFA POST is a communication error, not an authentication error."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(_q(_mfa_submit_url(MfaMethod.SMS)), status=503, body="<html>down</html>")
        with pytest.raises(EngieBeCommunicationError, match="API error 503") as excinfo:
            await flow.async_submit_mfa("123456")
        assert excinfo.value.status == 503
        assert created_sessions[0].closed


async def test_start_authentication_missing_mfa_state_raises() -> None:
    with aioresponses() as m:
        m.get(_q(_AUTHORIZE_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/identifier"))
        m.get(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.post(_q(_LOGIN_IDENTIFIER_URL), body="")
        m.get(_q(_LOGIN_PASSWORD_URL), body="")
        m.post(_q(_LOGIN_PASSWORD_URL), body=_redirect_body(_LOGIN_STATE, "/authorize/resume"))
        m.get(_q(_RESUME_URL), body="<html>no mfa state</html>")

        client = EngieBeClient()
        with pytest.raises(EngieBeAuthenticationError, match="MFA challenge state"):
            await client.async_start_authentication(_USERNAME, _PASSWORD)


@pytest.mark.parametrize("mfa", MfaMethod)
async def test_submit_mfa_callback_shortcircuit(
    mfa: MfaMethod,
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """Outcome A: the resume Location is the callback URI, skips passkey."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m, mfa=mfa)
        client = EngieBeClient()
        flow = await _start_flow(client, mfa)
        _register_submit_shortcircuit(m, state=flow._expected_state, mfa=mfa)
        access, refresh = await flow.async_submit_mfa("123456")

    assert (access, refresh) == ("new-access", "new-refresh")
    assert client.access_token == "new-access"
    assert client.refresh_token == "new-refresh"
    assert created_sessions[0].closed


async def test_token_exchange_carries_code_and_verifier_matching_challenge() -> None:
    """The code exchange pins its form fields, and the verifier matches the sent challenge."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        _register_submit_shortcircuit(m, state=flow._expected_state)
        await flow.async_submit_mfa("123456")
        (authorize,) = _recorded(m, "GET", "/authorize")
        (token_post,) = _recorded(m, "POST", "/oauth/token")

    data = token_post.kwargs["data"]
    assert data == {
        "code": _AUTH_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": flow._code_verifier,
        "client_id": DEFAULT_CLIENT_ID,
    }
    sent_challenge = authorize.kwargs["params"]["code_challenge"]
    recomputed = _base64url(hashlib.sha256(data["code_verifier"].encode("ascii")).digest())
    assert sent_challenge == recomputed


async def test_custom_client_id_reaches_authorize_and_token_endpoints() -> None:
    """A caller-supplied client_id is used on both the authorize GET and the token POST."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient(client_id="custom-id")
        flow = await _start_flow(client)
        _register_submit_shortcircuit(m, state=flow._expected_state)
        await flow.async_submit_mfa("123456")
        (authorize,) = _recorded(m, "GET", "/authorize")
        (token_post,) = _recorded(m, "POST", "/oauth/token")

    assert authorize.kwargs["params"]["client_id"] == "custom-id"
    assert token_post.kwargs["data"]["client_id"] == "custom-id"


async def test_request_timeout_reaches_every_auth_flow_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client's request_timeout is applied to each login-flow HTTP step."""
    captured: list[float | None] = []
    real_timeout = asyncio.timeout

    def _capturing_timeout(delay: float | None) -> asyncio.Timeout:
        captured.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", _capturing_timeout)
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient(request_timeout=7.5)
        flow = await _start_flow(client)
        _register_submit_shortcircuit(m, state=flow._expected_state)
        await flow.async_submit_mfa("123456")

    assert len(captured) == 10
    assert set(captured) == {7.5}


async def test_submit_mfa_injected_auth_session_stays_open() -> None:
    """A successful flow never closes an injected auth session."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        async with aiohttp.ClientSession() as injected:
            client = EngieBeClient()
            flow = await _start_flow(client, auth_session=injected)
            _register_submit_shortcircuit(m, state=flow._expected_state)
            access, _refresh = await flow.async_submit_mfa("123456")
            assert not injected.closed

    assert access == "new-access"


async def test_submit_mfa_state_mismatch_raises(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A callback echoing a foreign OAuth state is rejected and ends the flow."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            body=_redirect_body("postmfastate", "/authorize/resume"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": _callback_url(state="attacker-state")},
            body="",
        )
        with pytest.raises(EngieBeAuthenticationError, match="OAuth state mismatch"):
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed
    assert client.access_token is None


async def test_submit_mfa_resume_to_non_callback_location_raises(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A resume Location that is not the callback URI is the resume-guard error."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            body=_redirect_body("postmfastate", "/authorize/resume"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": "https://auth.example.invalid/u/interstitial"},
            body="",
        )
        with pytest.raises(
            EngieBeAuthenticationError, match="Resume did not redirect to the callback"
        ):
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed
    assert client.access_token is None


async def test_submit_mfa_callback_prefix_without_query_raises(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A Location extending the callback URI without a query separator is not the callback."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            body=_redirect_body("postmfastate", "/authorize/resume"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": f"{REDIRECT_URI}attacker"},
            body="",
        )
        with pytest.raises(
            EngieBeAuthenticationError, match="Resume did not redirect to the callback"
        ):
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed
    assert client.access_token is None


async def test_submit_mfa_callback_missing_code_raises(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            body=_redirect_body("postmfastate", "/authorize/resume"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": f"{REDIRECT_URI}?state={flow._expected_state}"},
            body="",
        )
        with pytest.raises(EngieBeAuthenticationError, match="missing authorization code"):
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed


@pytest.mark.parametrize("mfa", MfaMethod)
async def test_submit_mfa_invalid_code_keeps_flow_alive_for_retry(
    mfa: MfaMethod,
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """The real wrong-code trace raises EngieBeMfaError, keeps the session open for a retry."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m, mfa=mfa)
        client = EngieBeClient()
        flow = await _start_flow(client, mfa)
        m.post(
            _q(_mfa_submit_url(mfa)),
            status=400,
            body=_html_fixture("auth_wrong_mfa_code.html"),
        )
        with pytest.raises(EngieBeMfaError):
            await flow.async_submit_mfa("000000")
        assert not created_sessions[0].closed

        _register_submit_shortcircuit(m, state=flow._expected_state, mfa=mfa)
        access, _refresh = await flow.async_submit_mfa("123456")

    assert access == "new-access"
    assert created_sessions[0].closed


async def test_submit_mfa_same_state_back_raises_mfa_error(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A challenge re-render echoing the submitted state is a wrong code, even error-marker-free."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        echoed_form = (
            '<html><form data-form-primary="true" method="POST">'
            f'<input type="hidden" name="state" value="{_MFA_STATE}"/>'
            "</form></html>"
        )
        m.post(_q(_mfa_submit_url(MfaMethod.SMS)), status=400, body=echoed_form)
        with pytest.raises(EngieBeMfaError):
            await flow.async_submit_mfa("000000")
        assert not created_sessions[0].closed
        await flow.async_abort()


async def test_submit_mfa_unrecognized_page_is_not_a_wrong_code(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """A body without echoed state, error marker, or fresh state is a broken flow, not MFA retry."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(_q(_mfa_submit_url(MfaMethod.SMS)), body="<html>wrong code, form returned</html>")
        with pytest.raises(EngieBeAuthenticationError, match="unrecognized page") as excinfo:
            await flow.async_submit_mfa("000000")

    assert not isinstance(excinfo.value, EngieBeMfaError)
    assert created_sessions[0].closed


async def test_submit_mfa_token_response_missing_tokens_raises(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    """The auth-code exchange missing tokens surfaces as an auth error, not KeyError."""
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)

        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            body=_redirect_body("postmfastate", "/authorize/resume"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": _callback_url(state=flow._expected_state)},
            body="",
        )
        m.post(_q(_TOKEN_URL), payload={"access_token": "only-access"})

        with pytest.raises(EngieBeAuthenticationError, match="missing tokens"):
            await flow.async_submit_mfa("123456")

    assert created_sessions[0].closed


async def test_abort_closes_owned_session(
    created_sessions: list[aiohttp.ClientSession],
) -> None:
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        assert not created_sessions[0].closed
        await flow.async_abort()
        assert created_sessions[0].closed


async def test_abort_keeps_injected_auth_session_open() -> None:
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        async with aiohttp.ClientSession() as injected:
            client = EngieBeClient()
            flow = await _start_flow(client, auth_session=injected)
            await flow.async_abort()
            assert not injected.closed


async def test_refresh_token_invokes_callback() -> None:
    """on_token_refresh callback fires after successful refresh."""
    callback_calls: list[tuple[str, str]] = []

    async def callback(access: str, refresh: str) -> None:
        callback_calls.append((access, refresh))

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh", on_token_refresh=callback)
        await client.async_refresh_token()
        await client.close()

    assert callback_calls == [("new-access", "new-refresh")]


async def test_refresh_token_no_callback_is_fine() -> None:
    """Refresh works when no callback is set (default None)."""
    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh")
        access, refresh = await client.async_refresh_token()
        await client.close()

    assert access == "new-access"
    assert refresh == "new-refresh"


async def test_submit_mfa_invokes_callback() -> None:
    """on_token_refresh callback fires when the auth flow completes."""
    callback_calls: list[tuple[str, str]] = []

    async def callback(access: str, refresh: str) -> None:
        callback_calls.append((access, refresh))

    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient(on_token_refresh=callback)
        flow = await _start_flow(client)
        _register_submit_shortcircuit(m, state=flow._expected_state)
        await flow.async_submit_mfa("123456")

    assert callback_calls == [("new-access", "new-refresh")]


async def test_submit_mfa_raising_callback_is_logged_not_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken callback does not break a successful login."""

    async def callback(_access: str, _refresh: str) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient(on_token_refresh=callback)
        flow = await _start_flow(client)
        _register_submit_shortcircuit(m, state=flow._expected_state)
        access, refresh = await flow.async_submit_mfa("123456")

    assert (access, refresh) == ("new-access", "new-refresh")
    assert client.access_token == "new-access"
    assert "on_token_refresh callback failed" in caplog.text


async def test_raising_callback_does_not_break_getter(
    load_fixture: Callable[[str], dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising callback during auto-refresh is logged, and the getter still succeeds."""

    async def callback(_access: str, _refresh: str) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    url = f"{BILLING_BASE_URL}/business-agreements/123/supplier-energy-prices"
    with aioresponses() as m:
        m.get(_q(url), status=401)
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        m.get(_q(url), payload=load_fixture("prices_sample.json"))
        client = EngieBeClient(
            access_token="expired-token",
            refresh_token="old-refresh",
            on_token_refresh=callback,
        )
        with caplog.at_level(logging.ERROR):
            result = await client.async_get_prices("123")
        await client.close()

    assert result is not None
    assert client.access_token == "new-access"
    assert "on_token_refresh callback failed" in caplog.text


async def test_reentrant_callback_does_not_deadlock() -> None:
    """The callback runs outside the token lock, so it may re-enter the client."""
    reentered = asyncio.Event()

    async def callback(_access: str, _refresh: str) -> None:
        if not reentered.is_set():
            reentered.set()
            await client.async_refresh_token()

    client = EngieBeClient(refresh_token="old-refresh", on_token_refresh=callback)

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE, repeat=True)
        access, refresh = await asyncio.wait_for(client.async_refresh_token(), timeout=5)
        await client.close()

    assert reentered.is_set()
    assert (access, refresh) == ("new-access", "new-refresh")


async def test_stale_rotation_delivery_dropped(caplog: pytest.LogCaptureFixture) -> None:
    """A delivery superseded by newer rotations is dropped. The newest pair lands last.

    The first rotation's delivery stalls (asyncio event) past two further
    rotations.  Deliveries stay in rotation order: the stalled one finishes
    first, the superseded middle one never fires, and the newest pair is the
    last thing the consumer observes, and an older pair never overwrites it.
    """
    deliveries: list[tuple[str, str]] = []
    first_delivery_started = asyncio.Event()
    release_first_delivery = asyncio.Event()

    async def callback(access: str, refresh: str) -> None:
        if not first_delivery_started.is_set():
            first_delivery_started.set()
            await release_first_delivery.wait()
        deliveries.append((access, refresh))

    with aioresponses() as m:
        for n in (1, 2, 3):
            m.post(
                _q(_TOKEN_URL),
                payload={"access_token": f"access-{n}", "refresh_token": f"refresh-{n}"},
            )
        client = EngieBeClient(refresh_token="refresh-0", on_token_refresh=callback)
        first = asyncio.ensure_future(client.async_refresh_token())
        await first_delivery_started.wait()
        assert await client.async_refresh_token() == ("access-2", "refresh-2")
        assert await client.async_refresh_token() == ("access-3", "refresh-3")
        release_first_delivery.set()
        with caplog.at_level(logging.DEBUG, logger="aioengiebelgium"):
            assert await asyncio.wait_for(first, timeout=5) == ("access-1", "refresh-1")
        await client.close()

    assert client.refresh_token == "refresh-3"
    assert deliveries == [("access-1", "refresh-1"), ("access-3", "refresh-3")]
    assert "dropping stale delivery" in caplog.text


async def test_cancelled_delivery_still_delivers_newest_pair() -> None:
    """Cancelling the task that runs a delivery does not strand a newer queued pair."""
    deliveries: list[tuple[str, str]] = []
    first_delivery_started = asyncio.Event()
    release_first_delivery = asyncio.Event()

    async def callback(access: str, refresh: str) -> None:
        if not first_delivery_started.is_set():
            first_delivery_started.set()
            await release_first_delivery.wait()
        deliveries.append((access, refresh))

    with aioresponses() as m:
        for n in (1, 2):
            m.post(
                _q(_TOKEN_URL),
                payload={"access_token": f"access-{n}", "refresh_token": f"refresh-{n}"},
            )
        client = EngieBeClient(refresh_token="refresh-0", on_token_refresh=callback)
        first = asyncio.ensure_future(client.async_refresh_token())
        await first_delivery_started.wait()
        assert await client.async_refresh_token() == ("access-2", "refresh-2")
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release_first_delivery.set()
        delivery = client._tokens._delivery
        assert delivery is not None
        await asyncio.wait_for(delivery, timeout=5)
        await client.close()

    assert deliveries[-1] == ("access-2", "refresh-2")


async def test_callback_raising_cancelled_error_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A callback that raises CancelledError on its own is logged like any other failure."""

    async def callback(_access: str, _refresh: str) -> None:
        raise asyncio.CancelledError

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh", on_token_refresh=callback)
        with caplog.at_level(logging.ERROR):
            assert await client.async_refresh_token() == ("new-access", "new-refresh")
        await client.close()
    assert "on_token_refresh callback failed" in caplog.text


async def test_cancelling_the_delivery_task_stops_it() -> None:
    """Cancelling the delivery task itself still cancels it."""
    started = asyncio.Event()

    async def callback(_access: str, _refresh: str) -> None:
        started.set()
        await asyncio.Event().wait()

    with aioresponses() as m:
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        client = EngieBeClient(refresh_token="old-refresh", on_token_refresh=callback)
        refresh = asyncio.ensure_future(client.async_refresh_token())
        await started.wait()
        delivery = client._tokens._delivery
        assert delivery is not None
        delivery.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        assert delivery.cancelled()
        await client.close()


async def test_close_closes_owned_session() -> None:
    client = EngieBeClient()
    session = client._ensure_session()
    assert not session.closed
    await client.close()
    assert session.closed


async def test_close_keeps_injected_session_open() -> None:
    async with aiohttp.ClientSession() as session:
        client = EngieBeClient(session)
        await client.close()
        assert not session.closed


async def test_context_manager_closes_owned_session() -> None:
    async with EngieBeClient() as client:
        session = client._ensure_session()
        assert not session.closed
    assert session.closed


async def test_context_manager_keeps_injected_session_open() -> None:
    async with aiohttp.ClientSession() as session:
        async with EngieBeClient(session) as client:
            assert isinstance(client, EngieBeClient)
        assert not session.closed


async def test_closed_client_raises_engiebe_error() -> None:
    """Any use after close() raises the library's error, not aiohttp's RuntimeError."""
    client = EngieBeClient(access_token="stored-access", refresh_token="stored-refresh")
    await client.close()

    for attempt in (
        client.async_get_customer_account_relations(),
        client.async_refresh_token(),
        client.async_start_authentication(_USERNAME, _PASSWORD),
    ):
        with pytest.raises(EngieBeError, match=r"^Client is closed. Create a new EngieBeClient$"):
            await attempt


async def test_closed_client_raises_client_closed_error() -> None:
    """The closed-client guard raises the dedicated EngieBeClientClosedError."""
    client = EngieBeClient(access_token="stored-access", refresh_token="stored-refresh")
    await client.close()
    with pytest.raises(EngieBeClientClosedError, match=r"^Client is closed"):
        await client.async_get_customer_account_relations()


async def test_closed_client_without_tokens_raises_client_closed_error() -> None:
    """A closed client with no tokens reports the closed state, not a missing login."""
    client = EngieBeClient()
    await client.close()
    with pytest.raises(EngieBeClientClosedError, match=r"^Client is closed"):
        await client.async_get_customer_account_relations()
    with pytest.raises(EngieBeClientClosedError, match=r"^Client is closed"):
        await client.async_refresh_token()


async def test_closed_client_context_manager() -> None:
    """A client is unusable after its context exits, and re-entry raises too."""
    async with EngieBeClient(access_token="stored-access") as client:
        pass

    with pytest.raises(EngieBeError, match="Client is closed"):
        await client.async_get_customer_account_relations()
    with pytest.raises(EngieBeError, match="Client is closed"):
        async with client:
            pass


async def test_closed_client_leaves_injected_session_usable() -> None:
    """close() rejects further client use but never touches a caller-supplied session."""
    async with aiohttp.ClientSession() as session:
        client = EngieBeClient(session, access_token="stored-access")
        await client.close()
        assert not session.closed
        with pytest.raises(EngieBeError, match="Client is closed"):
            await client.async_get_customer_account_relations()
        assert not session.closed


def _location_stub(path: str) -> str:
    """Auth0's anchor-less redirect stub as served live, state sanitized."""
    return f"<p>Found. Redirecting to {path}</p>"


async def test_authorize_state_read_from_location_header() -> None:
    """Live Auth0 serves the authorize redirect as an anchor-less stub.

    The continuation state comes from the Location header, not the body.
    """
    with aioresponses() as m:
        m.get(
            _q(_AUTHORIZE_URL),
            status=302,
            headers={"Location": f"/u/login/identifier?state={_OAUTH_STATE}&ui_locales=nl"},
            body=_html_fixture("auth_redirect_stub_no_anchor.html"),
        )
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await _start_flow(client)
        await flow.async_abort()
        await client.close()

    assert flow._mfa_challenge_state == _MFA_STATE


async def test_full_flow_with_location_only_redirects() -> None:
    """Every redirect stub carries its state in the Location header only.

    The full login still completes.
    """
    with aioresponses() as m:
        m.get(
            _q(_AUTHORIZE_URL),
            status=302,
            headers={"Location": f"/u/login/identifier?state={_OAUTH_STATE}&ui_locales=nl"},
            body=_location_stub("/u/login/identifier?state=FAKESTATE&amp;ui_locales=nl"),
        )
        m.get(_q(_LOGIN_IDENTIFIER_URL), body=_identifier_body(_OAUTH_STATE))
        m.post(_q(_LOGIN_IDENTIFIER_URL), body=_redirect_body(_OAUTH_STATE, "/u/login/password"))
        m.get(_q(_LOGIN_PASSWORD_URL), body=_password_body(_OAUTH_STATE))
        m.post(
            _q(_LOGIN_PASSWORD_URL),
            status=302,
            headers={"Location": f"/authorize/resume?state={_LOGIN_STATE}"},
            body=_location_stub("/authorize/resume?state=FAKESTATE"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": f"/u/mfa-sms-challenge?state={_MFA_STATE}"},
            body=_location_stub("/u/mfa-sms-challenge?state=FAKESTATE"),
        )
        m.get(_q(_MFA_SMS_URL), body=_mfa_sms_body(_MFA_STATE))
        client = EngieBeClient()
        flow = await _start_flow(client)
        m.post(
            _q(_mfa_submit_url(MfaMethod.SMS)),
            status=302,
            headers={"Location": "/authorize/resume?state=postmfastate"},
            body=_location_stub("/authorize/resume?state=FAKESTATE"),
        )
        m.get(
            _q(_RESUME_URL),
            status=302,
            headers={"Location": _callback_url(state=flow._expected_state)},
            body="",
        )
        m.post(_q(_TOKEN_URL), payload=_TOKEN_RESPONSE)
        access, refresh = await flow.async_submit_mfa("123456")
        await client.close()

    assert (access, refresh) == ("new-access", "new-refresh")
    assert client.access_token == "new-access"
    assert client.refresh_token == "new-refresh"

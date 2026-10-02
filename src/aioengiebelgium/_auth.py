"""OAuth2/PKCE + MFA authentication flow for the ENGIE Belgium API."""

import hashlib
import html
import logging
import os
import re
from base64 import urlsafe_b64encode
from collections.abc import Awaitable, Callable, Mapping
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import aiohttp

from ._oauth import exchange_token
from ._transport import OwnedSession, request, request_text
from .const import (
    AUTH_BASE_URL,
    OAUTH_AUDIENCE,
    OAUTH_SCOPES,
    REDIRECT_URI,
    USER_AGENT_BROWSER,
    MfaMethod,
)
from .exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeMfaError,
)

_LOGGER = logging.getLogger(__name__)

_BROWSER_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "User-Agent": USER_AGENT_BROWSER,
    "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
}

_STATE_IN_URL_RE = re.compile(r"[?&]state=([a-zA-Z0-9_-]+)")
_ANCHOR_HREF_RE = re.compile(r'<a\b[^>]*\bhref="([^"]*)"', re.IGNORECASE)
_HIDDEN_INPUT_RE = re.compile(r'<input\b[^>]*\btype="hidden"[^>]*>', re.IGNORECASE)
_INPUT_NAME_RE = re.compile(r'\bname="([^"]+)"')
_INPUT_VALUE_RE = re.compile(r"""\bvalue=(["'])(.*?)\1""")

_PRIMARY_FORM = 'data-form-primary="true"'
_PICK_AUTHENTICATOR_FORM = "ulp-action-form-pick-authenticator"

_FIELD_ERROR_MARKER = 'class="ulp-input-error-message"'


def _base64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str, str, str]:
    state = os.urandom(16).hex()
    nonce = os.urandom(16).hex()
    code_verifier = _base64url(os.urandom(32))
    code_challenge = _base64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    return state, nonce, code_verifier, code_challenge


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(name)
    return values[0] if values else None


def _form_scope(body: str, *, form_marker: str = _PRIMARY_FORM) -> str | None:
    """Inner HTML of the first form matching ``form_marker``, or None when absent."""
    pattern = re.compile(
        rf"<form\b[^>]*\b{re.escape(form_marker)}(?![\w-])[^>]*>(.*?)</form>",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(body)
    return match.group(1) if match else None


def _hidden_inputs_in(scope: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for tag_match in _HIDDEN_INPUT_RE.finditer(scope):
        tag = tag_match.group(0)
        name_match = _INPUT_NAME_RE.search(tag)
        if not name_match:
            continue
        value_match = _INPUT_VALUE_RE.search(tag)
        result[name_match.group(1)] = html.unescape(value_match.group(2)) if value_match else ""
    return result


def _harvest_hidden_inputs(body: str, *, form_marker: str = _PRIMARY_FORM) -> dict[str, str]:
    """Return {name: value} for all hidden inputs inside the first form matching form_marker."""
    scope = _form_scope(body, form_marker=form_marker)
    return {} if scope is None else _hidden_inputs_in(scope)


def _state_from_body(body: str) -> str | None:
    """Extract state: the primary form's hidden ``state`` input, else ``?state=``
    within that form's scope. A formless Auth0 redirect body carries the state
    in its redirect link only."""
    scope = _form_scope(body)
    if scope is None:
        for href_match in _ANCHOR_HREF_RE.finditer(body):
            state_match = _STATE_IN_URL_RE.search(href_match.group(1))
            if state_match:
                return state_match.group(1)
        return None
    state = _hidden_inputs_in(scope).get("state")
    if state:
        return state
    match = _STATE_IN_URL_RE.search(scope)
    return match.group(1) if match else None


def _state_from_redirect(body: str, headers: Mapping[str, str]) -> str | None:
    """Continuation state of a redirect stub: the Location header first, the body second."""
    state = _query_param(headers.get("Location", ""), "state")
    if state:
        return state
    return _state_from_body(body)


async def _auth_request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    state: str,
    *,
    data: dict[str, str] | None = None,
    raise_on_error: bool = True,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> tuple[str, Mapping[str, str]]:
    return await request_text(
        session,
        method=method,
        url=f"{AUTH_BASE_URL}{path}",
        params={"state": state, "ui_locales": "nl"},
        headers=_BROWSER_HEADERS,
        data=data,
        allow_redirects=False,
        raise_on_error=raise_on_error,
        timeout=timeout,
    )


async def _resume_authorization(
    session: aiohttp.ClientSession,
    login_state: str,
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> tuple[str, Mapping[str, str]]:
    return await request_text(
        session,
        method="GET",
        url=f"{AUTH_BASE_URL}/authorize/resume",
        params={"state": login_state},
        headers=_BROWSER_HEADERS,
        allow_redirects=False,
        timeout=timeout,
    )


class AuthFlow:
    """An in-progress login: credentials accepted (steps 1-7), MFA pending."""

    def __init__(
        self,
        *,
        owned_session: OwnedSession,
        login_state: str,
        mfa_challenge_state: str,
        mfa_form_inputs: dict[str, str],
        code_verifier: str,
        expected_state: str,
        mfa_method: MfaMethod,
        client_id: str,
        token_adopter: Callable[[str, str], Awaitable[None]],
        timeout: float = 30.0,
    ) -> None:
        self._owned = owned_session
        self._session = owned_session.session
        self._login_state = login_state
        self._mfa_challenge_state = mfa_challenge_state
        self._mfa_form_inputs = mfa_form_inputs
        self._code_verifier = code_verifier
        self._expected_state = expected_state
        self._mfa_method = mfa_method
        self._client_id = client_id
        self._token_adopter = token_adopter
        self._timeout = timeout

    async def async_submit_mfa(self, code: str) -> tuple[str, str]:
        """Submit the MFA code and finish the login."""
        try:
            access_token, refresh_token = await self._run_steps_8_to_13(code)
        except EngieBeMfaError:
            raise
        except BaseException:
            await self._close_owned_session()
            raise
        await self._close_owned_session()
        await self._token_adopter(access_token, refresh_token)
        return access_token, refresh_token

    async def async_abort(self) -> None:
        """Abandon the flow, closing the session if the flow created it."""
        await self._close_owned_session()

    async def _close_owned_session(self) -> None:
        await self._owned.close_if_owned()

    async def _run_steps_8_to_13(self, mfa_code: str) -> tuple[str, str]:
        body, mfa_headers = await _submit_mfa_code(
            self._session,
            self._mfa_challenge_state,
            mfa_code,
            self._mfa_method,
            self._mfa_form_inputs,
            timeout=self._timeout,
        )
        _LOGGER.debug("auth step: MFA code submitted (%s)", self._mfa_method.value)

        echoed = _harvest_hidden_inputs(body).get("state")
        if echoed == self._mfa_challenge_state or _FIELD_ERROR_MARKER in body:
            msg = "Invalid MFA code"
            raise EngieBeMfaError(msg)

        if not _state_from_redirect(body, mfa_headers):
            msg = "MFA submission returned an unrecognized page (no continuation state)"
            raise EngieBeAuthenticationError(msg)

        _body, resp_headers = await _resume_authorization(
            self._session, self._login_state, timeout=self._timeout
        )

        location = resp_headers.get("Location", "")
        if not location.startswith(f"{REDIRECT_URI}?"):
            msg = "Resume did not redirect to the callback"
            raise EngieBeAuthenticationError(msg)
        auth_code = self._extract_callback_code(location)
        _LOGGER.debug("auth step: authorization code received")

        return await self._exchange_code_for_tokens(auth_code)

    def _extract_callback_code(self, location: str) -> str:
        if _query_param(location, "state") != self._expected_state:
            msg = "OAuth state mismatch"
            raise EngieBeAuthenticationError(msg)
        auth_code = _query_param(location, "code")
        if not auth_code:
            msg = "Callback redirect missing authorization code"
            raise EngieBeAuthenticationError(msg)
        return auth_code

    async def _exchange_code_for_tokens(self, auth_code: str) -> tuple[str, str]:
        access_token, refresh_token = await exchange_token(
            self._session,
            {
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code_verifier": self._code_verifier,
                "client_id": self._client_id,
            },
            timeout=self._timeout,
        )
        _LOGGER.debug("auth step: tokens received")
        return access_token, refresh_token


async def start_auth_flow(
    owned_session: OwnedSession,
    *,
    client_id: str,
    username: str,
    password: str,
    mfa_method: MfaMethod,
    token_adopter: Callable[[str, str], Awaitable[None]],
    timeout: float = 30.0,  # noqa: ASYNC109
) -> AuthFlow:
    """Execute OAuth2/PKCE authorization steps 1-7 and return the pending flow."""
    session = owned_session.session
    state, nonce, code_verifier, code_challenge = _generate_pkce()

    authorize_params = {
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "response_type": "code",
        "ui_locales": "nl",
        "state": state,
        "nonce": nonce,
        "scope": OAUTH_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "audience": OAUTH_AUDIENCE,
        "app_scheme": "be-engie-smart",
        "cancel_redirect": "be-engie-smart://cancel-registration-redirect",
    }
    body, authorize_headers = await request_text(
        session,
        method="GET",
        url=f"{AUTH_BASE_URL}/authorize",
        params=authorize_params,
        headers=_BROWSER_HEADERS,
        allow_redirects=False,
        timeout=timeout,
    )
    authorize_state = _state_from_redirect(body, authorize_headers)
    if not authorize_state:
        msg = "Failed to extract authorize state from response"
        raise EngieBeAuthenticationError(msg)
    _LOGGER.debug("auth step: authorize page fetched")

    identifier_body, _ = await _auth_request(
        session, "GET", "/u/login/identifier", authorize_state, timeout=timeout
    )
    identifier_inputs = _harvest_hidden_inputs(identifier_body)

    await _auth_request(
        session,
        "POST",
        "/u/login/identifier",
        authorize_state,
        data={**identifier_inputs, "username": username},
        timeout=timeout,
    )
    _LOGGER.debug("auth step: username submitted")

    password_body, _ = await _auth_request(
        session, "GET", "/u/login/password", authorize_state, timeout=timeout
    )
    password_inputs = _harvest_hidden_inputs(password_body)

    async with request(
        session,
        method="POST",
        url=f"{AUTH_BASE_URL}/u/login/password",
        params={"state": authorize_state, "ui_locales": "nl"},
        headers=_BROWSER_HEADERS,
        data={**password_inputs, "username": username, "password": password},
        allow_redirects=False,
        raise_on_error=False,
        timeout=timeout,
    ) as response:
        password_status = response.status
        password_headers = response.headers
        body = await response.text()

    if password_status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        _LOGGER.debug(
            "password submit error: status %s, body length %s", password_status, len(body)
        )
        msg = f"API error {password_status}"
        raise EngieBeCommunicationError(msg, status=password_status)
    if _FIELD_ERROR_MARKER in body:
        msg = "Invalid credentials"
        raise EngieBeAuthenticationError(msg, status=password_status)
    login_state = _state_from_redirect(body, password_headers)
    if not login_state:
        if password_status == HTTPStatus.BAD_REQUEST:
            msg = "Invalid credentials"
            raise EngieBeAuthenticationError(msg, status=password_status)
        msg = "Login failed: could not extract login state (bad credentials?)"
        raise EngieBeAuthenticationError(msg)
    _LOGGER.debug("auth step: password submitted")

    body, resume_headers = await _resume_authorization(session, login_state, timeout=timeout)
    mfa_challenge_state = _state_from_redirect(body, resume_headers)
    if not mfa_challenge_state:
        msg = "Failed to extract MFA challenge state"
        raise EngieBeAuthenticationError(msg)

    mfa_form_inputs = await _prime_mfa_challenge(
        session, mfa_challenge_state, mfa_method, timeout=timeout
    )
    _LOGGER.debug("auth step: MFA challenge requested (%s)", mfa_method.value)

    return AuthFlow(
        owned_session=owned_session,
        login_state=login_state,
        mfa_challenge_state=mfa_challenge_state,
        mfa_form_inputs=mfa_form_inputs,
        code_verifier=code_verifier,
        expected_state=state,
        mfa_method=mfa_method,
        client_id=client_id,
        token_adopter=token_adopter,
        timeout=timeout,
    )


async def _prime_mfa_challenge(
    session: aiohttp.ClientSession,
    challenge_state: str,
    mfa_method: MfaMethod,
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> dict[str, str]:
    """Trigger the MFA challenge and return the primary form's hidden inputs for the code POST."""
    match mfa_method:
        case MfaMethod.SMS:
            body, _ = await _auth_request(
                session,
                "GET",
                "/u/mfa-sms-challenge",
                challenge_state,
                timeout=timeout,
            )
        case MfaMethod.EMAIL:
            body = await _switch_to_email_mfa(session, challenge_state, timeout=timeout)
    return _harvest_hidden_inputs(body)


async def _submit_mfa_code(
    session: aiohttp.ClientSession,
    challenge_state: str,
    mfa_code: str,
    mfa_method: MfaMethod,
    mfa_form_inputs: dict[str, str],
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> tuple[str, Mapping[str, str]]:
    match mfa_method:
        case MfaMethod.SMS:
            path = "/u/mfa-sms-challenge"
            data = {**mfa_form_inputs, "code": mfa_code}
        case MfaMethod.EMAIL:
            path = "/u/mfa-email-challenge"
            data = {**mfa_form_inputs, "code": mfa_code, "action": "default"}
    return await _auth_request(
        session,
        "POST",
        path,
        challenge_state,
        data=data,
        raise_on_error=False,
        timeout=timeout,
    )


async def _switch_to_email_mfa(
    session: aiohttp.ClientSession,
    challenge_state: str,
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> str:
    """Switch MFA method to email; return the email-challenge page body for input harvest."""
    sms_body, _ = await _auth_request(
        session, "GET", "/u/mfa-sms-challenge", challenge_state, timeout=timeout
    )
    pick_inputs = _harvest_hidden_inputs(sms_body, form_marker=_PICK_AUTHENTICATOR_FORM)
    await _auth_request(
        session,
        "POST",
        "/u/mfa-sms-challenge",
        challenge_state,
        data={**pick_inputs, "action": "pick-authenticator"},
        timeout=timeout,
    )
    options_body, _ = await _auth_request(
        session, "GET", "/u/mfa-login-options", challenge_state, timeout=timeout
    )
    options_inputs = _harvest_hidden_inputs(options_body)
    await _auth_request(
        session,
        "POST",
        "/u/mfa-login-options",
        challenge_state,
        data={**options_inputs, "action": "email::1"},
        timeout=timeout,
    )
    email_body, _ = await _auth_request(
        session, "GET", "/u/mfa-email-challenge", challenge_state, timeout=timeout
    )
    return email_body

"""Redaction guard: debug logging never leaks secrets."""

import logging
from collections.abc import Callable
from typing import Any

import pytest
from aioresponses import aioresponses

from aioengiebelgium.client import EngieBeClient
from aioengiebelgium.const import API_BASE_URL
from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
)
from tests.conftest import (
    _AUTH_CODE,
    _LOGIN_STATE,
    _MFA_STATE,
    _OAUTH_STATE,
    _PASSKEY_STATE,
    _PASSWORD,
    _RESUME_URL,
    _TOKEN_URL,
    _USERNAME,
    _callback_url,
    _q,
    _register_auth_steps_1_to_7,
    _register_submit_shortcircuit,
)
from tests.test_client_auth import _capture_body, _register_passkey_redirect

_MFA_CODE = "654321"
_ERROR_BODY_SENTINEL = "sekrit-token-DEADBEEF"

MfaDriver = Callable[[aioresponses, str], None]


def _drive_mfa_shortcircuit(m: aioresponses, state: str) -> None:
    """Outcome A: the resume 302s straight to the callback URI."""
    _register_submit_shortcircuit(m, state=state)


def _drive_mfa_passkey(m: aioresponses, state: str) -> None:
    """Outcome B: the resume 302s through the passkey-enrollment interstitial."""
    _register_passkey_redirect(m)
    m.get(
        _q(_RESUME_URL),
        status=302,
        headers={"Location": _callback_url(state=state)},
        body=_capture_body("passkey_resume_3.http"),
    )
    m.post(
        _q(_TOKEN_URL),
        payload={"access_token": "new-access", "refresh_token": "new-refresh"},
    )


@pytest.mark.parametrize(
    "drive_mfa",
    [_drive_mfa_shortcircuit, _drive_mfa_passkey],
    ids=["mfa_shortcircuit", "mfa_passkey"],
)
async def test_debug_logs_never_contain_secrets(
    drive_mfa: MfaDriver,
    caplog: pytest.LogCaptureFixture,
    load_fixture: Callable[[str], dict[str, Any]],
) -> None:
    """A full mocked auth flow + refresh + getters + error bodies leaks no secret."""
    caplog.set_level(logging.DEBUG, logger="aioengiebelgium")

    prices_url = f"{API_BASE_URL}/business-agreements/123/supplier-energy-prices"
    with aioresponses() as m:
        _register_auth_steps_1_to_7(m)
        client = EngieBeClient()
        flow = await client.async_start_authentication(_USERNAME, _PASSWORD)
        code_verifier = flow._code_verifier
        expected_state = flow._expected_state
        drive_mfa(m, expected_state)
        await flow.async_submit_mfa(_MFA_CODE)

        m.post(
            _q(_TOKEN_URL),
            payload={"access_token": "second-access", "refresh_token": "second-refresh"},
        )
        await client.async_refresh_token()

        m.get(_q(prices_url), status=401)
        m.post(
            _q(_TOKEN_URL),
            payload={"access_token": "third-access", "refresh_token": "third-refresh"},
        )
        m.get(_q(prices_url), payload=load_fixture("prices_sample.json"))
        await client.async_get_prices("123")

        m.get(_q(prices_url), status=500, body=_ERROR_BODY_SENTINEL)
        with pytest.raises(EngieBeCommunicationError):
            await client.async_get_prices("123")

        m.post(
            _q(_TOKEN_URL),
            status=400,
            body=f'{{"error": "invalid_grant", "hint": "{_ERROR_BODY_SENTINEL}"}}',
            content_type="application/json",
        )
        with pytest.raises(EngieBeAuthenticationError):
            await client.async_refresh_token()

        await client.close()

    messages = [record.getMessage() for record in caplog.records]

    library_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("aioengiebelgium")
    ]
    assert any("auth step: password submitted" in message for message in library_messages)
    assert any("refresh: rotating tokens" in message for message in library_messages)
    assert any("request unauthorized (401)" in message for message in library_messages)

    secrets = [
        _USERNAME,
        _PASSWORD,
        _MFA_CODE,
        _AUTH_CODE,
        _OAUTH_STATE,
        _LOGIN_STATE,
        _MFA_STATE,
        _PASSKEY_STATE,
        "postmfastate",
        code_verifier,
        expected_state,
        "new-access",
        "new-refresh",
        "second-access",
        "second-refresh",
        "third-access",
        "third-refresh",
        _ERROR_BODY_SENTINEL,
    ]
    for message in messages:
        for secret in secrets:
            assert secret not in message, f"secret leaked into log output: {message!r}"

"""Tests for EngieBeClient's data-fetching methods."""

import asyncio
import base64
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses
from syrupy.assertion import SnapshotAssertion
from yarl import URL

from aioengiebelgium._endpoints import CATALOG, BanArgs, Endpoint, EpexArgs, MonthArgs
from aioengiebelgium.client import EngieBeClient
from aioengiebelgium.const import (
    ACCOUNTS_BASE_URL,
    AUTH_BASE_URL,
    BILLING_BASE_URL,
    BOOLEAN_FEATURE_FLAG_BASE_URL,
    BUSINESS_AGREEMENTS_BASE_URL,
    ENERGY_INSIGHTS_V2_BASE_URL,
    EPEX_BASE_URL,
    FEATURE_FLAG_APP_VERSION,
    FEATURE_FLAG_PLATFORM,
    FEATURE_FLAG_PLATFORM_VERSION,
    HAPPY_HOUR_BASE_URL,
    PEAKS_BASE_URL,
    PREMISES_BASE_URL,
    USER_AGENT_BROWSER,
    USER_AGENT_NATIVE,
    EpexGranularity,
    FeatureFlagKey,
    UsageGranularity,
)
from aioengiebelgium.exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
)
from aioengiebelgium.models import PricesResponse

LoadFixture = Callable[[str], dict[str, Any]]
_ClientCall = Callable[[EngieBeClient], Awaitable[object]]

_BAN = "000000000001"
_EAN = "541448860000000001_ID1"
_DELIVERY_POINT_ID = "DP001"
_TOKEN = "test-token"

_PRICES_URL = f"{BILLING_BASE_URL}/business-agreements/{_BAN}/supplier-energy-prices"
_RELATIONS_URL = f"{ACCOUNTS_BASE_URL}/customer-account-relations"
_TOKEN_URL = f"{AUTH_BASE_URL}/oauth/token"
_USAGE_DETAILS_URL = f"{ENERGY_INSIGHTS_V2_BASE_URL}/business-agreements/{_BAN}/usage-details"
_ENERGY_CONTRACTS_URL = (
    f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{_BAN}/energy-contracts"
)


def _any_query(url: str) -> re.Pattern[str]:
    """Match ``url`` regardless of query string, so param order never matters."""
    return re.compile(rf"^{re.escape(url)}(\?.*)?$")


def _feature_flag_body(flag: FeatureFlagKey) -> dict[str, Any]:
    """The exact JSON body async_get_feature_flag sends for ``flag``."""
    return {
        "name": flag.value,
        "additionalContext": {
            "contractAccountId": _BAN,
            "platform": FEATURE_FLAG_PLATFORM,
            "platformVersion": FEATURE_FLAG_PLATFORM_VERSION,
            "appVersion": FEATURE_FLAG_APP_VERSION,
        },
    }


def _feature_flag_call(flag: FeatureFlagKey) -> _ClientCall:
    """A getter call bound to ``flag`` (closure keeps the parametrize list flat)."""

    def _call(client: EngieBeClient) -> Awaitable[object]:
        return client.async_get_feature_flag(flag, _BAN)

    return _call


@dataclass(frozen=True)
class _WireCase:
    """One getter call plus the exact wire request and payload expectations it pins.

    Expectations are literals held here, independent of the catalog, so a
    catalog regression cannot silently rewrite what the test demands.
    """

    id: str
    fixture_name: str
    call: _ClientCall
    request_method: str
    url: str
    expected_params: dict[str, str]
    expected_user_agent: str
    expected_json: dict[str, Any] | None = None


_WIRE_CASES: dict[str, tuple[_WireCase, ...]] = {
    "prices": (
        _WireCase(
            id="prices",
            fixture_name="prices_sample.json",
            call=lambda c: c.async_get_prices(_BAN),
            request_method="GET",
            url=_PRICES_URL,
            expected_params={"maxGranularity": "MONTHLY"},
            expected_user_agent=USER_AGENT_BROWSER,
        ),
    ),
    "energy_contracts": (
        _WireCase(
            id="energy_contracts_active_only",
            fixture_name="energy_contracts_dynamic_plus_fixed_gas.json",
            call=lambda c: c.async_get_energy_contracts(_BAN),
            request_method="GET",
            url=_ENERGY_CONTRACTS_URL,
            expected_params={
                "filter": "ONLY_ACTIVE_ENERGY_CONTRACTS",
                "includeActions": "true",
                "includeSapData": "true",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
        _WireCase(
            id="energy_contracts_include_inactive",
            fixture_name="energy_contracts_dynamic_plus_fixed_gas.json",
            call=lambda c: c.async_get_energy_contracts(_BAN, include_inactive=True),
            request_method="GET",
            url=_ENERGY_CONTRACTS_URL,
            expected_params={
                "filter": "ALL_ENERGY_CONTRACTS",
                "includeActions": "true",
                "includeSapData": "true",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
        _WireCase(
            id="energy_contracts_dynamic_elec_only",
            fixture_name="energy_contracts_dynamic_elec_only.json",
            call=lambda c: c.async_get_energy_contracts(_BAN),
            request_method="GET",
            url=_ENERGY_CONTRACTS_URL,
            expected_params={
                "filter": "ONLY_ACTIVE_ENERGY_CONTRACTS",
                "includeActions": "true",
                "includeSapData": "true",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
        _WireCase(
            id="energy_contracts_empty",
            fixture_name="energy_contracts_empty.json",
            call=lambda c: c.async_get_energy_contracts(_BAN),
            request_method="GET",
            url=_ENERGY_CONTRACTS_URL,
            expected_params={
                "filter": "ONLY_ACTIVE_ENERGY_CONTRACTS",
                "includeActions": "true",
                "includeSapData": "true",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
        _WireCase(
            id="energy_contracts_fixed_dual_fuel",
            fixture_name="energy_contracts_fixed_dual_fuel.json",
            call=lambda c: c.async_get_energy_contracts(_BAN),
            request_method="GET",
            url=_ENERGY_CONTRACTS_URL,
            expected_params={
                "filter": "ONLY_ACTIVE_ENERGY_CONTRACTS",
                "includeActions": "true",
                "includeSapData": "true",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
    ),
    "service_point": (
        _WireCase(
            id="service_point",
            fixture_name="service_points_sample.json",
            call=lambda c: c.async_get_service_point(_EAN),
            request_method="GET",
            url=f"{PREMISES_BASE_URL}/service-points/{_EAN}",
            expected_params={},
            expected_user_agent=USER_AGENT_BROWSER,
        ),
    ),
    "customer_account_relations": (
        _WireCase(
            id="customer_account_relations",
            fixture_name="customer_account_relations_sample.json",
            call=lambda c: c.async_get_customer_account_relations(),
            request_method="GET",
            url=_RELATIONS_URL,
            expected_params={"withBusinessAgreements": "SMART_APP"},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="customer_account_relations_multi_ban_single_can",
            fixture_name="relations_multi_ban_single_can.json",
            call=lambda c: c.async_get_customer_account_relations(),
            request_method="GET",
            url=_RELATIONS_URL,
            expected_params={"withBusinessAgreements": "SMART_APP"},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "monthly_peaks": (
        _WireCase(
            id="monthly_peaks",
            fixture_name="peaks_2026_04.json",
            call=lambda c: c.async_get_monthly_peaks(_BAN, 2026, 4),
            request_method="GET",
            url=(
                f"{PEAKS_BASE_URL}/private/customers/me/contract-accounts/"
                f"{_BAN}/energy-insights/peaks"
            ),
            expected_params={"year": "2026", "month": "4"},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "happy_hour_event": (
        _WireCase(
            id="happy_hour_event",
            fixture_name="happy_hour_event.json",
            call=lambda c: c.async_get_happy_hour_event(_BAN),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/happy-hour-event",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="happy_hour_event_empty",
            fixture_name="happy_hour_event_empty.json",
            call=lambda c: c.async_get_happy_hour_event(_BAN),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/happy-hour-event",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "happy_hour_month_report": (
        _WireCase(
            id="happy_hour_month_report",
            fixture_name="happy_hour_month_report.json",
            call=lambda c: c.async_get_happy_hour_month_report(_BAN, 2026, 4),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/month-report/2026-04",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="happy_hour_month_report_energy",
            fixture_name="happy_hour_month_report_energy.json",
            call=lambda c: c.async_get_happy_hour_month_report(_BAN, 2026, 8),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/month-report/2026-08",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "usage_details": (
        _WireCase(
            id="usage_details",
            fixture_name="usage_details_hourly.json",
            call=lambda c: c.async_get_usage_details(_BAN, date(2026, 4, 1), date(2026, 4, 30)),
            request_method="GET",
            url=_USAGE_DETAILS_URL,
            expected_params={
                "startDate": "2026-04-01",
                "endDate": "2026-04-30",
                "granularity": "HOURLY",
                "includeSimulation": "false",
            },
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="usage_details_include_simulation",
            fixture_name="usage_details_hourly.json",
            call=lambda c: c.async_get_usage_details(
                _BAN,
                date(2026, 4, 1),
                date(2026, 4, 30),
                include_simulation=True,
            ),
            request_method="GET",
            url=_USAGE_DETAILS_URL,
            expected_params={
                "startDate": "2026-04-01",
                "endDate": "2026-04-30",
                "granularity": "HOURLY",
                "includeSimulation": "true",
            },
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="usage_details_daily",
            fixture_name="usage_details_daily.json",
            call=lambda c: c.async_get_usage_details(
                _BAN,
                date(2026, 7, 1),
                date(2026, 8, 1),
                UsageGranularity.DAILY,
            ),
            request_method="GET",
            url=_USAGE_DETAILS_URL,
            expected_params={
                "startDate": "2026-07-01",
                "endDate": "2026-08-01",
                "granularity": "DAILY",
                "includeSimulation": "false",
            },
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="usage_details_monthly",
            fixture_name="usage_details_monthly.json",
            call=lambda c: c.async_get_usage_details(
                _BAN,
                date(2026, 7, 1),
                date(2026, 8, 1),
                UsageGranularity.MONTHLY,
            ),
            request_method="GET",
            url=_USAGE_DETAILS_URL,
            expected_params={
                "startDate": "2026-07-01",
                "endDate": "2026-08-01",
                "granularity": "MONTHLY",
                "includeSimulation": "false",
            },
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="usage_details_tou_simulated",
            fixture_name="usage_details_tou_simulated.json",
            call=lambda c: c.async_get_usage_details(
                _BAN,
                date(2026, 6, 1),
                date(2026, 8, 2),
                UsageGranularity.MONTHLY,
                include_simulation=True,
            ),
            request_method="GET",
            url=_USAGE_DETAILS_URL,
            expected_params={
                "startDate": "2026-06-01",
                "endDate": "2026-08-02",
                "granularity": "MONTHLY",
                "includeSimulation": "true",
            },
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "solar_surplus_forecasts": (
        _WireCase(
            id="solar_surplus_forecasts",
            fixture_name="solar_surplus_high.json",
            call=lambda c: c.async_get_solar_surplus_forecasts(_BAN, _DELIVERY_POINT_ID),
            request_method="GET",
            url=(
                f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}"
                f"/solar-surplus/{_DELIVERY_POINT_ID}/forecasts"
            ),
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="solar_surplus_forecasts_no_data",
            fixture_name="solar_surplus_no_data.json",
            call=lambda c: c.async_get_solar_surplus_forecasts(_BAN, _DELIVERY_POINT_ID),
            request_method="GET",
            url=(
                f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}"
                f"/solar-surplus/{_DELIVERY_POINT_ID}/forecasts"
            ),
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "feature_flag": (
        *(
            _WireCase(
                id=f"feature_flag_{flag.name.lower()}",
                fixture_name="feature_flags_enrolled.json",
                call=_feature_flag_call(flag),
                request_method="POST",
                url=BOOLEAN_FEATURE_FLAG_BASE_URL,
                expected_params={},
                expected_user_agent=USER_AGENT_NATIVE,
                expected_json=_feature_flag_body(flag),
            )
            for flag in FeatureFlagKey
        ),
        _WireCase(
            id="feature_flag_not_enrolled",
            fixture_name="feature_flags_not_enrolled.json",
            call=_feature_flag_call(FeatureFlagKey.HAPPY_HOURS_SERVICE_ENABLED),
            request_method="POST",
            url=BOOLEAN_FEATURE_FLAG_BASE_URL,
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
            expected_json=_feature_flag_body(FeatureFlagKey.HAPPY_HOURS_SERVICE_ENABLED),
        ),
    ),
    "tou_schedules": (
        _WireCase(
            id="tou_schedules",
            fixture_name="tou_schedules_bihoraire.json",
            call=lambda c: c.async_get_tou_schedules(_BAN),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/tou-schedules",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="tou_schedules_flat_all_offpeak",
            fixture_name="tou_schedules_flat_all_offpeak.json",
            call=lambda c: c.async_get_tou_schedules(_BAN),
            request_method="GET",
            url=f"{HAPPY_HOUR_BASE_URL}/business-agreements/{_BAN}/tou-schedules",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "account_balance": (
        _WireCase(
            id="account_balance",
            fixture_name="billing_open_debit.json",
            call=lambda c: c.async_get_account_balance(_BAN),
            request_method="GET",
            url=f"{BILLING_BASE_URL}/business-agreements/{_BAN}/account-balance",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
        _WireCase(
            id="account_balance_cleared",
            fixture_name="billing_cleared.json",
            call=lambda c: c.async_get_account_balance(_BAN),
            request_method="GET",
            url=f"{BILLING_BASE_URL}/business-agreements/{_BAN}/account-balance",
            expected_params={},
            expected_user_agent=USER_AGENT_NATIVE,
        ),
    ),
    "epex_prices": (
        _WireCase(
            id="epex_prices",
            fixture_name="epex_24h.json",
            call=lambda c: c.async_get_epex_prices(
                datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
                datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
            ),
            request_method="GET",
            url=EPEX_BASE_URL,
            expected_params={
                "from": "2026-05-03T22:00:00.000Z",
                "to": "2026-05-04T22:00:00.000Z",
                "granularity": "HOURLY",
            },
            expected_user_agent=USER_AGENT_BROWSER,
        ),
    ),
}


def test_every_catalog_endpoint_has_wire_cases() -> None:
    """The wire table and the endpoint catalog cover each other exactly."""
    assert set(_WIRE_CASES) == {endpoint.name for endpoint in CATALOG}


@pytest.mark.parametrize(
    ("endpoint", "case"),
    [
        pytest.param(endpoint, case, id=case.id)
        for endpoint in CATALOG
        for case in _WIRE_CASES[endpoint.name]
    ],
)
async def test_getter_parses_payload_and_sends_expected_request(
    endpoint: Endpoint[Any, Any],
    case: _WireCase,
    load_fixture: LoadFixture,
    snapshot: SnapshotAssertion,
) -> None:
    """Every getter parses its fixture into the snapshotted model and pins its wire request."""
    with aioresponses() as m:
        m.add(
            _any_query(case.url),
            method=case.request_method,
            payload=load_fixture(case.fixture_name),
        )
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            result = await case.call(client)
        (((_method, request_url), calls),) = m.requests.items()
        (request,) = calls
    assert dict(request_url.query) == case.expected_params
    assert request.kwargs["json"] == case.expected_json
    assert request.kwargs["headers"]["User-Agent"] == case.expected_user_agent
    if not endpoint.optional_auth:
        assert request.kwargs["headers"]["authorization"] == f"Bearer {_TOKEN}"
    assert result == snapshot


@pytest.mark.parametrize(
    "endpoint",
    [pytest.param(endpoint, id=endpoint.name) for endpoint in CATALOG],
)
async def test_tokenless_call_matches_auth_mode(
    endpoint: Endpoint[Any, Any],
    load_fixture: LoadFixture,
) -> None:
    """Auth-required rows fail fast with no request; the optional-auth row omits the header."""
    case = _WIRE_CASES[endpoint.name][0]
    with aioresponses() as m:
        m.add(
            _any_query(case.url),
            method=case.request_method,
            payload=load_fixture(case.fixture_name),
        )
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session)
            if endpoint.optional_auth:
                await case.call(client)
                (((_method, _url), calls),) = m.requests.items()
                (request,) = calls
                assert "authorization" not in request.kwargs["headers"]
            else:
                with pytest.raises(EngieBeAuthenticationError):
                    await case.call(client)
                assert not m.requests


async def test_feature_flag_401_retry_preserves_body_and_headers(
    load_fixture: LoadFixture,
) -> None:
    """The post-refresh retry re-sends the same body, Content-Type, and new token."""
    flag = FeatureFlagKey.HAPPY_HOURS_SERVICE_ENABLED
    with aioresponses() as m:
        m.post(BOOLEAN_FEATURE_FLAG_BASE_URL, status=401)
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.post(
            BOOLEAN_FEATURE_FLAG_BASE_URL,
            payload=load_fixture("feature_flags_enrolled.json"),
        )
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session,
                access_token="expired-token",
                refresh_token="valid-refresh",
            )
            result = await client.async_get_feature_flag(flag, _BAN)
        first, retry = m.requests["POST", URL(BOOLEAN_FEATURE_FLAG_BASE_URL)]
        assert retry.kwargs["json"] == first.kwargs["json"]
        assert retry.kwargs["json"]["name"] == flag.value
        assert retry.kwargs["headers"]["Content-Type"] == "application/json"
        assert retry.kwargs["headers"]["authorization"] == "Bearer new-access"
    assert result is not None


async def test_get_prices_ban_with_spaces(load_fixture: LoadFixture) -> None:
    """Spaces in BAN are stripped before URL interpolation."""
    fixture = load_fixture("prices_sample.json")
    with aioresponses() as m:
        m.get(_any_query(_PRICES_URL), payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            ban_with_spaces = f"{_BAN[:4]} {_BAN[4:8]} {_BAN[8:]}"
            result = await client.async_get_prices(ban_with_spaces)
    assert result is not None


def test_ban_args_strip_spaces_on_construction() -> None:
    """BAN normalization is an Args invariant, independent of the getter path."""
    assert BanArgs(ban="123 456").ban == "123456"
    assert MonthArgs(ban="000 000 000 001", year=2026, month=1).ban == "000000000001"


def test_epex_args_reject_naive_datetimes() -> None:
    """EpexArgs enforces timezone-aware bounds regardless of construction path."""
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    naive = datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware datetimes required"):
        EpexArgs(from_dt=naive, to_dt=aware, granularity=EpexGranularity.HOURLY)
    with pytest.raises(ValueError, match="timezone-aware datetimes required"):
        EpexArgs(from_dt=aware, to_dt=naive, granularity=EpexGranularity.HOURLY)


async def test_unauthenticated_call_raises_immediately() -> None:
    async with aiohttp.ClientSession() as session:
        client = EngieBeClient(session)
        with pytest.raises(EngieBeAuthenticationError):
            await client.async_get_customer_account_relations()


async def test_refresh_only_client_auto_refreshes(load_fixture: LoadFixture) -> None:
    """A client restored with only a refresh token refreshes once, then the getter succeeds."""
    with aioresponses() as m:
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, refresh_token="stored-refresh")
            result = await client.async_get_prices(_BAN)
        token_posts = m.requests["POST", URL(_TOKEN_URL)]
        (request,) = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
    assert isinstance(result, PricesResponse)
    assert len(token_posts) == 1
    assert request.kwargs["headers"]["authorization"] == "Bearer new-access"
    assert client.access_token == "new-access"
    assert client.refresh_token == "new-refresh"


async def test_no_tokens_fast_fails() -> None:
    """With neither token the getter raises immediately and sends zero HTTP requests."""
    with aioresponses() as m:
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session)
            with pytest.raises(EngieBeAuthenticationError, match="Not authenticated"):
                await client.async_get_prices(_BAN)
        assert not m.requests


async def test_error_response_raises_communication_error() -> None:
    """End-to-end: a 500 from the API surfaces as EngieBeCommunicationError.

    Exhaustive status/exception mapping lives in test_transport.py.
    """
    with aioresponses() as m:
        m.get(_any_query(_RELATIONS_URL), status=500)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN)
            with pytest.raises(EngieBeCommunicationError):
                await client.async_get_customer_account_relations()


async def test_request_timeout_is_threaded_to_transport(
    load_fixture: LoadFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The constructor's request_timeout reaches asyncio.timeout per request."""
    captured: list[float | None] = []
    real_timeout = asyncio.timeout

    def _capturing_timeout(delay: float | None) -> asyncio.Timeout:
        captured.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", _capturing_timeout)
    fixture = load_fixture("customer_account_relations_sample.json")
    with aioresponses() as m:
        m.get(_any_query(_RELATIONS_URL), payload=fixture)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=_TOKEN, request_timeout=7.5)
            await client.async_get_customer_account_relations()
    assert captured == [7.5]


async def test_auto_refresh_on_401(load_fixture: LoadFixture) -> None:
    """Client retries with fresh token after 401."""
    with aioresponses() as m:
        m.get(_any_query(_PRICES_URL), status=401)
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session=session,
                access_token="expired-token",
                refresh_token="valid-refresh",
            )
            result = await client.async_get_prices(_BAN)
            assert isinstance(result, PricesResponse)
            assert client.access_token == "new-access"
        first, retry = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
        assert first.kwargs["headers"]["authorization"] == "Bearer expired-token"
        assert retry.kwargs["headers"]["authorization"] == "Bearer new-access"


@pytest.mark.parametrize(
    "refresh_token",
    ["valid-refresh", None],
    ids=["with_refresh_token", "without_refresh_token"],
)
async def test_403_raises_communication_error_and_does_not_rotate_tokens(
    refresh_token: str | None,
) -> None:
    """403 is a permission problem, not an auth failure: no token refresh."""
    with aioresponses() as m:
        m.get(_any_query(_RELATIONS_URL), status=403)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session,
                access_token=_TOKEN,
                refresh_token=refresh_token,
            )
            with pytest.raises(EngieBeCommunicationError) as excinfo:
                await client.async_get_customer_account_relations()
        assert all(str(url) != _TOKEN_URL for _method, url in m.requests)
    assert excinfo.value.status == HTTPStatus.FORBIDDEN
    assert not isinstance(excinfo.value, EngieBeAuthenticationError)
    assert client.access_token == _TOKEN
    assert client.refresh_token == refresh_token


async def test_401_refresh_failure_chains_original_auth_error() -> None:
    """A failed refresh after a 401 keeps the triggering 401 as __cause__."""
    with aioresponses() as m:
        m.get(_any_query(_RELATIONS_URL), status=401)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token="expired-token")
            with pytest.raises(EngieBeAuthenticationError) as excinfo:
                await client.async_get_customer_account_relations()
    cause = excinfo.value.__cause__
    assert isinstance(cause, EngieBeAuthenticationError)
    assert cause.status == HTTPStatus.UNAUTHORIZED


async def test_auto_refresh_fails_on_second_401() -> None:
    """If refresh succeeds but retry still gets 401, raise."""
    with aioresponses() as m:
        m.get(_any_query(_PRICES_URL), status=401)
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.get(_any_query(_PRICES_URL), status=401)
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session=session,
                access_token="expired",
                refresh_token="also-expired",
            )
            with pytest.raises(EngieBeAuthenticationError):
                await client.async_get_prices(_BAN)
        first, retry = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
        assert first.kwargs["headers"]["authorization"] == "Bearer expired"
        assert retry.kwargs["headers"]["authorization"] == "Bearer new-access"


def _jwt_with_exp(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"e30.{payload}.fakesig"


async def test_proactive_refresh_when_token_expired(load_fixture: LoadFixture) -> None:
    """An expired JWT refreshes before the data request, with no wasted 401 leg."""
    past = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    with aioresponses() as m:
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session,
                access_token=_jwt_with_exp(past),
                refresh_token="stored-refresh",
            )
            result = await client.async_get_prices(_BAN)
        token_posts = m.requests["POST", URL(_TOKEN_URL)]
        (request,) = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
    assert isinstance(result, PricesResponse)
    assert len(token_posts) == 1
    assert request.kwargs["headers"]["authorization"] == "Bearer new-access"


async def test_proactive_refresh_within_skew_margin(load_fixture: LoadFixture) -> None:
    """A token expiring inside the skew margin is refreshed before use."""
    soon = (datetime.now(UTC) + timedelta(seconds=10)).timestamp()
    with aioresponses() as m:
        m.post(
            _TOKEN_URL,
            payload={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
            },
        )
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session,
                access_token=_jwt_with_exp(soon),
                refresh_token="stored-refresh",
            )
            await client.async_get_prices(_BAN)
        token_posts = m.requests["POST", URL(_TOKEN_URL)]
        (request,) = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
    assert len(token_posts) == 1
    assert request.kwargs["headers"]["authorization"] == "Bearer new-access"


async def test_fresh_token_is_not_proactively_refreshed(load_fixture: LoadFixture) -> None:
    """A token expiring comfortably in the future is used without a refresh."""
    token = _jwt_with_exp(datetime(2100, 1, 1, tzinfo=UTC).timestamp())
    with aioresponses() as m:
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(session, access_token=token, refresh_token="stored-refresh")
            await client.async_get_prices(_BAN)
        (request,) = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
    assert ("POST", URL(_TOKEN_URL)) not in m.requests
    assert request.kwargs["headers"]["authorization"] == f"Bearer {token}"


async def test_opaque_token_is_not_proactively_refreshed(load_fixture: LoadFixture) -> None:
    """A non-JWT access token has unknown expiry, so it is sent unchanged."""
    with aioresponses() as m:
        m.get(_any_query(_PRICES_URL), payload=load_fixture("prices_sample.json"))
        async with aiohttp.ClientSession() as session:
            client = EngieBeClient(
                session,
                access_token="opaque-token",
                refresh_token="stored-refresh",
            )
            await client.async_get_prices(_BAN)
        (request,) = m.requests["GET", URL(f"{_PRICES_URL}?maxGranularity=MONTHLY")]
    assert ("POST", URL(_TOKEN_URL)) not in m.requests
    assert request.kwargs["headers"]["authorization"] == "Bearer opaque-token"

# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""The public EngieBeClient entry point."""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any, Self

import aiohttp

from . import _transport
from ._auth import AuthFlow, start_auth_flow
from ._endpoints import (
    ACCOUNT_BALANCE,
    CUSTOMER_ACCOUNT_RELATIONS,
    ENERGY_CONTRACTS,
    EPEX_PRICES,
    FEATURE_FLAG,
    HAPPY_HOUR_EVENT,
    HAPPY_HOUR_MONTH_REPORT,
    MONTHLY_PEAKS,
    PRICES,
    SERVICE_POINT,
    SOLAR_SURPLUS_FORECASTS,
    TOU_SCHEDULES,
    USAGE_DETAILS,
    BanArgs,
    ContractsArgs,
    EanArgs,
    Endpoint,
    EpexArgs,
    FlagArgs,
    MonthArgs,
    NoArgs,
    SolarArgs,
    UsageArgs,
    WireRequest,
)
from ._tokens import TokenLifecycle
from .const import (
    DEFAULT_CLIENT_ID,
    EpexGranularity,
    FeatureFlagKey,
    MfaMethod,
    UsageGranularity,
)
from .exceptions import (
    EngieBeAuthenticationError,
    EngieBeCommunicationError,
    EngieBeError,
)
from .models import (
    AccountBalance,
    CustomerAccountRelations,
    EnergyContractsResponse,
    EpexPayload,
    FeatureFlag,
    HappyHourEvent,
    HappyHourMonthReport,
    MonthlyPeaks,
    PricesResponse,
    ServicePoint,
    SolarSurplusForecasts,
    TouSchedulesResponse,
    UsageDetailsResponse,
)

_LOGGER = logging.getLogger(__name__)


class EngieBeClient:
    """ENGIE Belgium API client with OAuth2/PKCE + MFA authentication."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        client_id: str = DEFAULT_CLIENT_ID,
        access_token: str | None = None,
        refresh_token: str | None = None,
        on_token_refresh: Callable[[str, str], Awaitable[None]] | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self._api = _transport.OwnedSession(session, owned=False) if session is not None else None
        self._client_id = client_id
        self._request_timeout = request_timeout
        self._tokens = TokenLifecycle(
            client_id=client_id,
            session_provider=self._ensure_session,
            timeout=request_timeout,
            access_token=access_token,
            refresh_token=refresh_token,
            on_rotation=on_token_refresh,
        )
        self._closed = False

    @property
    def access_token(self) -> str | None:
        """The current access token, or None when unauthenticated."""
        return self._tokens.access_token

    @property
    def refresh_token(self) -> str | None:
        """The current refresh token, or None when unauthenticated."""
        return self._tokens.refresh_token

    @property
    def access_token_expiry(self) -> datetime | None:
        """Expiry of the access token from its JWT ``exp`` claim, or None when unknown."""
        return self._tokens.expiry

    @property
    def subject(self) -> str | None:
        """JWT ``sub`` claim of the access token, or None when unauthenticated or unparseable."""
        return self._tokens.subject

    def is_access_token_expired(self, now: datetime) -> bool:
        """Return True when the token's expiry is known and ``now`` is at or past it."""
        return self._tokens.is_expired(now)

    async def close(self) -> None:
        """Close the client. The session is closed only if this client created it."""
        self._closed = True
        if self._api is not None:
            await self._api.close_if_owned()

    async def __aenter__(self) -> Self:
        self._raise_if_closed()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def async_start_authentication(
        self,
        username: str,
        password: str,
        mfa_method: MfaMethod = MfaMethod.SMS,
        *,
        auth_session: aiohttp.ClientSession | None = None,
    ) -> AuthFlow:
        """Run login steps 1-7 and return an AuthFlow awaiting the MFA code."""
        self._raise_if_closed()
        auth = _transport.OwnedSession(
            auth_session if auth_session is not None else aiohttp.ClientSession(),
            owned=auth_session is None,
        )
        try:
            return await start_auth_flow(
                auth,
                client_id=self._client_id,
                username=username,
                password=password,
                mfa_method=mfa_method,
                token_adopter=self._tokens.adopt,
                timeout=self._request_timeout,
            )
        except Exception:
            await auth.close_if_owned()
            raise

    async def async_refresh_token(self) -> tuple[str, str]:
        """Refresh tokens. Returns (new_access_token, new_refresh_token)."""
        return await self._tokens.refresh()

    async def async_get_prices(self, business_agreement_number: str) -> PricesResponse:
        """Fetch supplier energy prices for a business agreement."""
        return await self._call(PRICES, BanArgs(ban=business_agreement_number))

    async def async_get_energy_contracts(
        self,
        business_agreement_number: str,
        *,
        include_inactive: bool = False,
    ) -> EnergyContractsResponse:
        """Fetch energy contracts for a business agreement."""
        args = ContractsArgs(ban=business_agreement_number, include_inactive=include_inactive)
        return await self._call(ENERGY_CONTRACTS, args)

    async def async_get_service_point(self, ean: str) -> ServicePoint:
        """Fetch service point details for an EAN with its delivery-point suffix (e.g. _ID1)."""
        return await self._call(SERVICE_POINT, EanArgs(ean=ean))

    async def async_get_customer_account_relations(self) -> CustomerAccountRelations:
        """Fetch customer account relations for the authenticated user."""
        return await self._call(CUSTOMER_ACCOUNT_RELATIONS, NoArgs())

    async def async_get_monthly_peaks(
        self,
        business_agreement_number: str,
        year: int,
        month: int,
    ) -> MonthlyPeaks:
        """Fetch capacity tariff peaks for a given month."""
        args = MonthArgs(ban=business_agreement_number, year=year, month=month)
        return await self._call(MONTHLY_PEAKS, args)

    async def async_get_happy_hour_event(
        self,
        business_agreement_number: str,
    ) -> HappyHourEvent:
        """Fetch today's and tomorrow's happy hour windows."""
        return await self._call(HAPPY_HOUR_EVENT, BanArgs(ban=business_agreement_number))

    async def async_get_happy_hour_month_report(
        self,
        business_agreement_number: str,
        year: int,
        month: int,
    ) -> HappyHourMonthReport:
        """Fetch the happy hour month report."""
        args = MonthArgs(ban=business_agreement_number, year=year, month=month)
        return await self._call(HAPPY_HOUR_MONTH_REPORT, args)

    async def async_get_usage_details(
        self,
        business_agreement_number: str,
        start_date: date,
        end_date: date,
        granularity: UsageGranularity = UsageGranularity.HOURLY,
        *,
        include_simulation: bool = False,
    ) -> UsageDetailsResponse:
        """Fetch energy usage details for a date range."""
        args = UsageArgs(
            ban=business_agreement_number,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            include_simulation=include_simulation,
        )
        return await self._call(USAGE_DETAILS, args)

    async def async_get_solar_surplus_forecasts(
        self,
        business_agreement_number: str,
        delivery_point_id: str,
    ) -> SolarSurplusForecasts:
        """Fetch solar surplus forecasts for a delivery point."""
        args = SolarArgs(ban=business_agreement_number, delivery_point_id=delivery_point_id)
        return await self._call(SOLAR_SURPLUS_FORECASTS, args)

    async def async_get_feature_flag(
        self,
        flag: FeatureFlagKey,
        business_agreement_number: str,
    ) -> FeatureFlag:
        """Query a boolean feature flag for a business agreement."""
        args = FlagArgs(flag=flag, ban=business_agreement_number)
        return await self._call(FEATURE_FLAG, args)

    async def async_get_tou_schedules(
        self,
        business_agreement_number: str,
    ) -> TouSchedulesResponse:
        """Fetch time-of-use tariff schedules."""
        return await self._call(TOU_SCHEDULES, BanArgs(ban=business_agreement_number))

    async def async_get_account_balance(
        self,
        business_agreement_number: str,
    ) -> AccountBalance:
        """Fetch the billing account balance."""
        return await self._call(ACCOUNT_BALANCE, BanArgs(ban=business_agreement_number))

    async def async_get_epex_prices(
        self,
        from_dt: datetime,
        to_dt: datetime,
        *,
        granularity: EpexGranularity = EpexGranularity.HOURLY,
    ) -> EpexPayload:
        """Fetch EPEX day-ahead market prices."""
        args = EpexArgs(from_dt=from_dt, to_dt=to_dt, granularity=granularity)
        return await self._call(EPEX_PRICES, args)

    def _raise_if_closed(self) -> None:
        if self._closed:
            msg = "Client is closed — create a new EngieBeClient"
            raise EngieBeError(msg)

    def _ensure_session(self) -> aiohttp.ClientSession:
        self._raise_if_closed()
        if self._api is None:
            self._api = _transport.OwnedSession(aiohttp.ClientSession(), owned=True)
        return self._api.session

    def _build_headers(
        self,
        user_agent: str,
        extra: dict[str, str] | None,
        *,
        with_auth: bool,
    ) -> dict[str, str]:
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, application/problem+json",
        }
        if with_auth:
            headers["authorization"] = self._tokens.bearer()
        if extra:
            headers.update(extra)
        return headers

    async def _call[ArgsT, ModelT](self, endpoint: Endpoint[ArgsT, ModelT], args: ArgsT) -> ModelT:
        try:
            raw = await self._request_json_authenticated(endpoint.build(args))
        except EngieBeCommunicationError as err:
            endpoint.raise_error(err, args)
        return endpoint.parse(raw, args)

    async def _request_json_authenticated(self, wire: WireRequest) -> dict[str, Any]:
        """Make an authenticated JSON request, refreshing proactively then on 401."""
        if not wire.optional_auth:
            await self._tokens.ensure_fresh()
        for attempt in range(2):
            with_auth = not wire.optional_auth or self._tokens.access_token is not None
            headers = self._build_headers(wire.user_agent, wire.extra_headers, with_auth=with_auth)
            try:
                return await _transport.request_json(
                    self._ensure_session(),
                    method=wire.method,
                    url=wire.url,
                    headers=headers,
                    params=wire.params,
                    json_body=wire.json_body,
                    timeout=self._request_timeout,
                )
            except EngieBeAuthenticationError as err:
                if attempt or not with_auth:
                    raise
                _LOGGER.debug("request unauthorized (401); refreshing tokens and retrying")
                try:
                    await self.async_refresh_token()
                except EngieBeError as refresh_err:
                    raise refresh_err from err
        raise AssertionError  # pragma: no cover

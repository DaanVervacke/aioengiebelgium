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
    ACTIVATE_HAPPY_HOUR_SERVICE,
    BILLING_PERIOD_USAGE,
    BUDGET_BILLING_PLAN,
    CANCEL_HAPPY_HOUR_SERVICE,
    CUSTOMER_ACCOUNT_RELATIONS,
    ELECTRIC_VEHICLES,
    ENERGY_CONTRACTS,
    ENERGY_SCORE,
    EPEX_PRICES,
    FEATURE_FLAG,
    HAPPY_HOUR_ELIGIBILITY,
    HAPPY_HOUR_EVENT,
    HAPPY_HOUR_MONTH_REPORT,
    HAPPY_HOUR_SERVICE_STATUS,
    LATEST_CHARGING_SESSION,
    LATEST_CHARGING_SESSION_CHARGE_SETTINGS,
    METER_READS,
    MONTHLY_BILLED_BUDGET,
    MONTHLY_PEAKS,
    PRICES,
    SERVICE_POINT,
    SERVICE_POINTS,
    SMART_CHARGE_SERVICES,
    SOLAR_SURPLUS_FORECASTS,
    TOU_SCHEDULES,
    USAGE_DETAILS,
    VEHICLE_CHARGE_SETTINGS,
    BanArgs,
    CanArgs,
    ContractsArgs,
    EanArgs,
    Endpoint,
    EpexArgs,
    FlagArgs,
    MeterReadsArgs,
    MonthArgs,
    NoArgs,
    PeaksArgs,
    SolarArgs,
    UsageArgs,
    VehicleArgs,
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
    EngieBeClientClosedError,
    EngieBeCommunicationError,
    EngieBeError,
)
from .models import (
    AccountBalance,
    BillingPeriodUsage,
    BudgetBillingPlanDetails,
    ChargingSessionChargeSettings,
    ChargingSessionDetails,
    CustomerAccountRelations,
    ElectricVehiclesResponse,
    EnergyContractsResponse,
    EnergyScore,
    EpexPayload,
    EvServiceInfo,
    FeatureFlag,
    HappyHourEligibility,
    HappyHourEvent,
    HappyHourMonthReport,
    HappyHourServiceStatus,
    MeterReadsResponse,
    MonthlyBilledBudget,
    MonthlyPeaks,
    PricesResponse,
    ServicePoint,
    ServicePointsResponse,
    SolarSurplusForecasts,
    TouSchedulesResponse,
    UsageDetailsResponse,
    VehicleChargeSettings,
    ean_with_delivery_point_suffix,
)

_LOGGER = logging.getLogger(__name__)


class EngieBeClient:
    """ENGIE Belgium API client with OAuth2/PKCE + MFA authentication."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
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
        """Fetch service point details for an EAN, bare or with delivery-point suffix."""
        normalized = ean if "_" in ean else ean_with_delivery_point_suffix(ean)
        return await self._call(SERVICE_POINT, EanArgs(ean=normalized))

    async def async_get_customer_account_relations(self) -> CustomerAccountRelations:
        """Fetch customer account relations for the authenticated user."""
        return await self._call(CUSTOMER_ACCOUNT_RELATIONS, NoArgs())

    async def async_get_monthly_peaks(
        self,
        business_agreement_number: str,
        year: int,
        month: int,
        *,
        day: int | None = None,
    ) -> MonthlyPeaks:
        """Fetch capacity tariff peaks for a month, with daily peaks limited to ``day`` if given."""
        args = PeaksArgs(ban=business_agreement_number, year=year, month=month, day=day)
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
        business_agreement_number: str,
        flag: FeatureFlagKey,
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

    async def async_get_service_points(
        self,
        business_agreement_number: str,
    ) -> ServicePointsResponse:
        """Fetch the service points of a business agreement with their metering data sources."""
        return await self._call(SERVICE_POINTS, BanArgs(ban=business_agreement_number))

    async def async_get_meter_reads(
        self,
        business_agreement_number: str,
        *,
        latest: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> MeterReadsResponse:
        """Fetch meter reads: the latest only, a date range, or the full history by default."""
        args = MeterReadsArgs(
            ban=business_agreement_number,
            latest=latest,
            start_date=start_date,
            end_date=end_date,
        )
        return await self._call(METER_READS, args)

    async def async_get_monthly_billed_budget(
        self,
        business_agreement_number: str,
    ) -> MonthlyBilledBudget:
        """Fetch the costs and monthly payments of the current billed budget period."""
        return await self._call(MONTHLY_BILLED_BUDGET, BanArgs(ban=business_agreement_number))

    async def async_get_billing_period_usage(
        self,
        business_agreement_number: str,
    ) -> BillingPeriodUsage:
        """Fetch the cost used so far in the billing period against the expected yearly invoice."""
        return await self._call(BILLING_PERIOD_USAGE, BanArgs(ban=business_agreement_number))

    async def async_get_budget_billing_plan_details(
        self,
        business_agreement_number: str,
    ) -> BudgetBillingPlanDetails:
        """Fetch the budget billing plan of the billing period with its limits and proposal."""
        return await self._call(BUDGET_BILLING_PLAN, BanArgs(ban=business_agreement_number))

    async def async_get_happy_hour_eligibility(
        self,
        business_agreement_number: str,
    ) -> HappyHourEligibility:
        """Fetch whether the business agreement can activate the happy hour service."""
        return await self._call(HAPPY_HOUR_ELIGIBILITY, BanArgs(ban=business_agreement_number))

    async def async_get_happy_hour_service_status(
        self,
        business_agreement_number: str,
    ) -> HappyHourServiceStatus:
        """Fetch the status of the happy hour service."""
        return await self._call(HAPPY_HOUR_SERVICE_STATUS, BanArgs(ban=business_agreement_number))

    async def async_activate_happy_hour_service(
        self,
        business_agreement_number: str,
    ) -> HappyHourServiceStatus:
        """Activate the happy hour service. This changes the customer's ENGIE service."""
        return await self._call(ACTIVATE_HAPPY_HOUR_SERVICE, BanArgs(ban=business_agreement_number))

    async def async_cancel_happy_hour_service(self, business_agreement_number: str) -> None:
        """Cancel the happy hour service. This changes the customer's ENGIE service."""
        await self._call(CANCEL_HAPPY_HOUR_SERVICE, BanArgs(ban=business_agreement_number))

    async def async_get_energy_score(
        self,
        business_agreement_number: str,
        year: int,
        month: int,
    ) -> EnergyScore:
        """Fetch the energy score grade for a month with the criteria behind it."""
        args = MonthArgs(ban=business_agreement_number, year=year, month=month)
        return await self._call(ENERGY_SCORE, args)

    async def async_get_smart_charge_services(
        self,
        customer_account_number: str,
    ) -> EvServiceInfo:
        """Fetch the Smart Charge onboarding state and service status of a customer account."""
        return await self._call(SMART_CHARGE_SERVICES, CanArgs(can=customer_account_number))

    async def async_get_electric_vehicles(
        self,
        customer_account_number: str,
    ) -> ElectricVehiclesResponse:
        """Fetch the vehicles of a customer account with their capabilities and charge state.

        Inactive vehicles are included. Check ``active`` on each vehicle.
        """
        return await self._call(ELECTRIC_VEHICLES, CanArgs(can=customer_account_number))

    async def async_get_vehicle_charge_settings(self, vehicle_id: int) -> VehicleChargeSettings:
        """Fetch the Smart Charge settings of a vehicle: departure times and battery levels."""
        return await self._call(VEHICLE_CHARGE_SETTINGS, VehicleArgs(vehicle_id=vehicle_id))

    async def async_get_latest_charging_session(self, vehicle_id: int) -> ChargingSessionDetails:
        """Fetch the latest charging session of a vehicle with its energy per interval."""
        return await self._call(LATEST_CHARGING_SESSION, VehicleArgs(vehicle_id=vehicle_id))

    async def async_get_latest_charging_session_charge_settings(
        self,
        vehicle_id: int,
    ) -> ChargingSessionChargeSettings:
        """Fetch the target battery level and departure time of the latest charging session."""
        args = VehicleArgs(vehicle_id=vehicle_id)
        return await self._call(LATEST_CHARGING_SESSION_CHARGE_SETTINGS, args)

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
            msg = "Client is closed. Create a new EngieBeClient"
            raise EngieBeClientClosedError(msg)

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
                    expect_body=wire.expect_body,
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

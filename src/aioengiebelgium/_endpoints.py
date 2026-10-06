"""Endpoint catalog: every wire fact for each API endpoint lives in one descriptor."""

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any, NoReturn

from .const import (
    ACCOUNTS_BASE_URL,
    BILLING_BASE_URL,
    BILLING_V2_BASE_URL,
    BOOLEAN_FEATURE_FLAG_BASE_URL,
    BUSINESS_AGREEMENTS_BASE_URL,
    ENERGY_INSIGHTS_V2_BASE_URL,
    EPEX_BASE_URL,
    EV_BASE_URL,
    EV_V2_BASE_URL,
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
from .exceptions import (
    EngieBeCommunicationError,
    EngieBeEpexNotPublishedError,
)
from .models import (
    AccountBalance,
    BillingPeriodUsage,
    BudgetBillingPlanDetails,
    ChargingSessionChargeSettings,
    ChargingSessionDetails,
    ChargingSessionsPage,
    ChargingSessionsSummary,
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
)
from .parsers import (
    parse_account_balance,
    parse_billing_period_usage,
    parse_budget_billing_plan_details,
    parse_charging_session_charge_settings,
    parse_charging_session_details,
    parse_charging_sessions_page,
    parse_charging_sessions_summary,
    parse_customer_account_relations,
    parse_electric_vehicles,
    parse_energy_contracts,
    parse_energy_score,
    parse_epex_prices,
    parse_ev_service_info,
    parse_feature_flag,
    parse_happy_hour_eligibility,
    parse_happy_hour_event,
    parse_happy_hour_month_report,
    parse_happy_hour_service_status,
    parse_meter_reads,
    parse_monthly_billed_budget,
    parse_monthly_peaks,
    parse_prices,
    parse_service_point,
    parse_service_points,
    parse_solar_surplus_forecasts,
    parse_tou_schedules,
    parse_usage_details,
    parse_vehicle_charge_settings,
)


@dataclass(frozen=True, slots=True)
class WireRequest:
    method: str
    url: str
    user_agent: str
    optional_auth: bool
    params: dict[str, str] | None
    json_body: dict[str, Any] | None
    extra_headers: dict[str, str] | None
    expect_body: bool = True


@dataclass(frozen=True, slots=True)
class Endpoint[ArgsT, ModelT]:
    """One API endpoint: the wire facts to call it and parse its response."""

    name: str
    method: str
    url: str | Callable[[ArgsT], str]
    parse: Callable[[dict[str, Any], ArgsT], ModelT]
    user_agent: str = USER_AGENT_NATIVE
    params: dict[str, str] | Callable[[ArgsT], dict[str, str]] | None = None
    json_body: Callable[[ArgsT], dict[str, Any]] | None = None
    optional_auth: bool = False
    not_found_error: Callable[[ArgsT], EngieBeCommunicationError] | None = None
    expect_body: bool = True

    def build(self, args: ArgsT) -> WireRequest:
        json_body = None if self.json_body is None else self.json_body(args)
        return WireRequest(
            method=self.method,
            url=self.url if isinstance(self.url, str) else self.url(args),
            user_agent=self.user_agent,
            optional_auth=self.optional_auth,
            params=self.params(args) if callable(self.params) else self.params,
            json_body=json_body,
            extra_headers=None if json_body is None else {"Content-Type": "application/json"},
            expect_body=self.expect_body,
        )

    def raise_error(self, err: EngieBeCommunicationError, args: ArgsT) -> NoReturn:
        """Re-raise ``err``, applying the endpoint's 404 remap when configured."""
        if self.not_found_error is not None and err.status == HTTPStatus.NOT_FOUND:
            raise self.not_found_error(args) from err
        raise err


def _normalize_ban(value: str) -> str:
    return value.replace(" ", "")


_BAN_RE = re.compile(r"[0-9]+")
_EAN_RE = re.compile(r"[0-9]+(?:_ID[0-9]+)?")
_MIN_MONTH = 1
_MAX_MONTH = 12
_MIN_YEAR = 2000
_MAX_YEAR = 2100
_MIN_DAY = 1


def _validate_ban(ban: str) -> None:
    if not _BAN_RE.fullmatch(ban):
        msg = f"business agreement number must be digits: {ban!r}"
        raise ValueError(msg)


def _validate_positive_id(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{label} must be a positive integer: {value!r}"
        raise ValueError(msg)


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        msg = f"start_date {start_date} is after end_date {end_date}"
        raise ValueError(msg)


def _validate_year_month(year: int, month: int) -> None:
    if not _MIN_MONTH <= month <= _MAX_MONTH:
        msg = f"month must be between {_MIN_MONTH} and {_MAX_MONTH}: {month}"
        raise ValueError(msg)
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        msg = f"year must be between {_MIN_YEAR} and {_MAX_YEAR}: {year}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NoArgs:
    """Args for endpoints that take no caller input."""


@dataclass(frozen=True, slots=True)
class BanArgs:
    ban: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)


@dataclass(frozen=True, slots=True)
class CanArgs:
    can: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "can", _normalize_ban(self.can))
        if not _BAN_RE.fullmatch(self.can):
            msg = f"customer account number must be digits: {self.can!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class VehicleArgs:
    vehicle_id: int

    def __post_init__(self) -> None:
        _validate_positive_id("vehicle id", self.vehicle_id)


@dataclass(frozen=True, slots=True)
class ChargingSessionArgs:
    session_id: int

    def __post_init__(self) -> None:
        _validate_positive_id("charging session id", self.session_id)


@dataclass(frozen=True, slots=True)
class ChargingSessionsArgs:
    can: str
    start_date: date
    end_date: date
    page_number: int
    page_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "can", CanArgs(can=self.can).can)
        _validate_date_range(self.start_date, self.end_date)
        if self.page_number < 0:
            msg = f"page_number must not be negative: {self.page_number}"
            raise ValueError(msg)
        if self.page_size < 1:
            msg = f"page_size must be at least 1: {self.page_size}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CanDateRangeArgs:
    can: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "can", CanArgs(can=self.can).can)
        _validate_date_range(self.start_date, self.end_date)


@dataclass(frozen=True, slots=True)
class EanArgs:
    ean: str

    def __post_init__(self) -> None:
        if not _EAN_RE.fullmatch(self.ean):
            msg = f"EAN must be digits with an optional _ID<n> suffix: {self.ean!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MonthArgs:
    ban: str
    year: int
    month: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)
        _validate_year_month(self.year, self.month)


@dataclass(frozen=True, slots=True)
class PeaksArgs:
    ban: str
    year: int
    month: int
    day: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)
        _validate_year_month(self.year, self.month)
        if self.day is None:
            return
        last_day = calendar.monthrange(self.year, self.month)[1]
        if not _MIN_DAY <= self.day <= last_day:
            msg = f"day must be between {_MIN_DAY} and {last_day}: {self.day}"
            raise ValueError(msg)


def _peaks_params(args: PeaksArgs) -> dict[str, str]:
    params = {"year": str(args.year), "month": str(args.month)}
    if args.day is not None:
        params["day"] = str(args.day)
    return params


@dataclass(frozen=True, slots=True)
class ContractsArgs:
    ban: str
    include_inactive: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)


@dataclass(frozen=True, slots=True)
class UsageArgs:
    ban: str
    start_date: date
    end_date: date
    granularity: UsageGranularity
    include_simulation: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))


@dataclass(frozen=True, slots=True)
class SolarArgs:
    ban: str
    delivery_point_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)


@dataclass(frozen=True, slots=True)
class FlagArgs:
    flag: FeatureFlagKey
    ban: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)


@dataclass(frozen=True, slots=True)
class MeterReadsArgs:
    ban: str
    latest: bool
    start_date: date | None
    end_date: date | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))
        _validate_ban(self.ban)
        if (self.start_date is None) != (self.end_date is None):
            msg = "start_date and end_date must be given together"
            raise ValueError(msg)
        if self.latest and self.start_date is not None:
            msg = "latest cannot be combined with a date range"
            raise ValueError(msg)
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            msg = f"start_date {self.start_date} is after end_date {self.end_date}"
            raise ValueError(msg)


def _meter_reads_params(args: MeterReadsArgs) -> dict[str, str]:
    if args.latest:
        return {"latest": "true"}
    if args.start_date is not None and args.end_date is not None:
        return {"startDate": args.start_date.isoformat(), "endDate": args.end_date.isoformat()}
    return {}


@dataclass(frozen=True, slots=True)
class EpexArgs:
    from_dt: datetime
    to_dt: datetime
    granularity: EpexGranularity

    def __post_init__(self) -> None:
        if self.from_dt.tzinfo is None or self.to_dt.tzinfo is None:
            msg = "timezone-aware datetimes required"
            raise ValueError(msg)


def _iso_ms_z(value: datetime) -> str:
    """UTC ISO-8601 with milliseconds and a literal Z suffix, as EPEX expects."""
    utc_value = value.astimezone(UTC)
    iso = utc_value.isoformat(timespec="milliseconds").removesuffix("+00:00")
    return f"{iso}Z"


def _epex_params(args: EpexArgs) -> dict[str, str]:
    return {
        "from": _iso_ms_z(args.from_dt),
        "to": _iso_ms_z(args.to_dt),
        "granularity": args.granularity.wire_value,
    }


def _epex_not_published(args: EpexArgs) -> EngieBeEpexNotPublishedError:
    window = f"{_iso_ms_z(args.from_dt)}..{_iso_ms_z(args.to_dt)}"
    msg = f"EPEX prices not yet published for {window}"
    return EngieBeEpexNotPublishedError(msg)


def _feature_flag_body(args: FlagArgs) -> dict[str, Any]:
    return {
        "name": args.flag.value,
        "additionalContext": {
            "contractAccountId": args.ban,
            "platform": FEATURE_FLAG_PLATFORM,
            "platformVersion": FEATURE_FLAG_PLATFORM_VERSION,
            "appVersion": FEATURE_FLAG_APP_VERSION,
        },
    }


PRICES: Endpoint[BanArgs, PricesResponse] = Endpoint(
    name="prices",
    method="GET",
    url=lambda a: f"{BILLING_BASE_URL}/business-agreements/{a.ban}/supplier-energy-prices",
    params={"maxGranularity": "MONTHLY"},
    user_agent=USER_AGENT_BROWSER,
    parse=lambda raw, _a: parse_prices(raw),
)

ENERGY_CONTRACTS: Endpoint[ContractsArgs, EnergyContractsResponse] = Endpoint(
    name="energy_contracts",
    method="GET",
    url=lambda a: f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{a.ban}/energy-contracts",
    params=lambda a: {
        "filter": (
            "ALL_ENERGY_CONTRACTS" if a.include_inactive else "ONLY_ACTIVE_ENERGY_CONTRACTS"
        ),
        "includeActions": "true",
        "includeSapData": "true",
    },
    user_agent=USER_AGENT_BROWSER,
    parse=lambda raw, _a: parse_energy_contracts(raw),
)

SERVICE_POINT: Endpoint[EanArgs, ServicePoint] = Endpoint(
    name="service_point",
    method="GET",
    url=lambda a: f"{PREMISES_BASE_URL}/service-points/{a.ean}",
    user_agent=USER_AGENT_BROWSER,
    parse=lambda raw, a: parse_service_point(raw, a.ean),
)

CUSTOMER_ACCOUNT_RELATIONS: Endpoint[NoArgs, CustomerAccountRelations] = Endpoint(
    name="customer_account_relations",
    method="GET",
    url=f"{ACCOUNTS_BASE_URL}/customer-account-relations",
    params={"withBusinessAgreements": "SMART_APP"},
    parse=lambda raw, _a: parse_customer_account_relations(raw),
)

MONTHLY_PEAKS: Endpoint[PeaksArgs, MonthlyPeaks] = Endpoint(
    name="monthly_peaks",
    method="GET",
    url=lambda a: (
        f"{PEAKS_BASE_URL}/private/customers/me/contract-accounts/{a.ban}/energy-insights/peaks"
    ),
    params=_peaks_params,
    parse=lambda raw, _a: parse_monthly_peaks(raw),
)

HAPPY_HOUR_EVENT: Endpoint[BanArgs, HappyHourEvent] = Endpoint(
    name="happy_hour_event",
    method="GET",
    url=lambda a: f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/happy-hour-event",
    parse=lambda raw, _a: parse_happy_hour_event(raw),
)

HAPPY_HOUR_MONTH_REPORT: Endpoint[MonthArgs, HappyHourMonthReport] = Endpoint(
    name="happy_hour_month_report",
    method="GET",
    url=lambda a: (
        f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/month-report/{a.year:04d}-{a.month:02d}"
    ),
    parse=lambda raw, _a: parse_happy_hour_month_report(raw),
)

USAGE_DETAILS: Endpoint[UsageArgs, UsageDetailsResponse] = Endpoint(
    name="usage_details",
    method="GET",
    url=lambda a: f"{ENERGY_INSIGHTS_V2_BASE_URL}/business-agreements/{a.ban}/usage-details",
    params=lambda a: {
        "startDate": a.start_date.isoformat(),
        "endDate": a.end_date.isoformat(),
        "granularity": str(a.granularity),
        "includeSimulation": "true" if a.include_simulation else "false",
    },
    parse=lambda raw, _a: parse_usage_details(raw),
)

SOLAR_SURPLUS_FORECASTS: Endpoint[SolarArgs, SolarSurplusForecasts] = Endpoint(
    name="solar_surplus_forecasts",
    method="GET",
    url=lambda a: (
        f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}"
        f"/solar-surplus/{a.delivery_point_id}/forecasts"
    ),
    parse=lambda raw, _a: parse_solar_surplus_forecasts(raw),
)

FEATURE_FLAG: Endpoint[FlagArgs, FeatureFlag] = Endpoint(
    name="feature_flag",
    method="POST",
    url=BOOLEAN_FEATURE_FLAG_BASE_URL,
    json_body=_feature_flag_body,
    parse=lambda raw, _a: parse_feature_flag(raw),
)

TOU_SCHEDULES: Endpoint[BanArgs, TouSchedulesResponse] = Endpoint(
    name="tou_schedules",
    method="GET",
    url=lambda a: f"{BILLING_BASE_URL}/business-agreements/{a.ban}/tou-schedules",
    parse=lambda raw, _a: parse_tou_schedules(raw),
)

ACCOUNT_BALANCE: Endpoint[BanArgs, AccountBalance] = Endpoint(
    name="account_balance",
    method="GET",
    url=lambda a: f"{BILLING_BASE_URL}/business-agreements/{a.ban}/account-balance",
    parse=lambda raw, _a: parse_account_balance(raw),
)

SERVICE_POINTS: Endpoint[BanArgs, ServicePointsResponse] = Endpoint(
    name="service_points",
    method="GET",
    url=lambda a: f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/service-points",
    params={"loadMeteringSourcesStatus": "true"},
    parse=lambda raw, _a: parse_service_points(raw),
)

METER_READS: Endpoint[MeterReadsArgs, MeterReadsResponse] = Endpoint(
    name="meter_reads",
    method="GET",
    url=lambda a: f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/meter-reads",
    params=_meter_reads_params,
    parse=lambda raw, _a: parse_meter_reads(raw),
)

MONTHLY_BILLED_BUDGET: Endpoint[BanArgs, MonthlyBilledBudget] = Endpoint(
    name="monthly_billed_budget",
    method="GET",
    url=lambda a: f"{BILLING_V2_BASE_URL}/business-agreements/{a.ban}/monthly-billed-budgets",
    parse=lambda raw, _a: parse_monthly_billed_budget(raw),
)

BILLING_PERIOD_USAGE: Endpoint[BanArgs, BillingPeriodUsage] = Endpoint(
    name="billing_period_usage",
    method="GET",
    url=lambda a: f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/billing-period-usage-details",
    parse=lambda raw, _a: parse_billing_period_usage(raw),
)

BUDGET_BILLING_PLAN: Endpoint[BanArgs, BudgetBillingPlanDetails] = Endpoint(
    name="budget_billing_plan",
    method="GET",
    url=lambda a: f"{BILLING_V2_BASE_URL}/business-agreements/{a.ban}/billing-period-bbp-details",
    parse=lambda raw, _a: parse_budget_billing_plan_details(raw),
)

HAPPY_HOUR_ELIGIBILITY: Endpoint[BanArgs, HappyHourEligibility] = Endpoint(
    name="happy_hour_eligibility",
    method="GET",
    url=lambda a: (
        f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{a.ban}/happy-hour-eligibility"
    ),
    parse=lambda raw, _a: parse_happy_hour_eligibility(raw),
)

HAPPY_HOUR_SERVICE_STATUS: Endpoint[BanArgs, HappyHourServiceStatus] = Endpoint(
    name="happy_hour_service_status",
    method="GET",
    url=lambda a: f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{a.ban}/happy-hour-service",
    parse=lambda raw, _a: parse_happy_hour_service_status(raw),
)

ACTIVATE_HAPPY_HOUR_SERVICE: Endpoint[BanArgs, HappyHourServiceStatus] = Endpoint(
    name="activate_happy_hour_service",
    method="POST",
    url=lambda a: (
        f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{a.ban}/happy-hour-service/_activate"
    ),
    parse=lambda raw, _a: parse_happy_hour_service_status(raw),
)

CANCEL_HAPPY_HOUR_SERVICE: Endpoint[BanArgs, None] = Endpoint(
    name="cancel_happy_hour_service",
    method="DELETE",
    url=lambda a: f"{BUSINESS_AGREEMENTS_BASE_URL}/business-agreements/{a.ban}/happy-hour-service",
    expect_body=False,
    parse=lambda _raw, _a: None,
)

ENERGY_SCORE: Endpoint[MonthArgs, EnergyScore] = Endpoint(
    name="energy_score",
    method="GET",
    url=lambda a: f"{ENERGY_INSIGHTS_V2_BASE_URL}/business-agreements/{a.ban}/energy-score",
    params=lambda a: {"year": str(a.year), "month": str(a.month)},
    parse=lambda raw, _a: parse_energy_score(raw),
)

SMART_CHARGE_SERVICES: Endpoint[CanArgs, EvServiceInfo] = Endpoint(
    name="smart_charge_services",
    method="GET",
    url=lambda a: f"{EV_BASE_URL}/customer-accounts/{a.can}/services",
    params={"type": "SMART_CHARGE"},
    parse=lambda raw, _a: parse_ev_service_info(raw),
)

ELECTRIC_VEHICLES: Endpoint[CanArgs, ElectricVehiclesResponse] = Endpoint(
    name="electric_vehicles",
    method="GET",
    url=lambda a: f"{EV_V2_BASE_URL}/customer-accounts/{a.can}/vehicles",
    params={"includeInactive": "true"},
    parse=lambda raw, _a: parse_electric_vehicles(raw),
)

VEHICLE_CHARGE_SETTINGS: Endpoint[VehicleArgs, VehicleChargeSettings] = Endpoint(
    name="vehicle_charge_settings",
    method="GET",
    url=lambda a: f"{EV_V2_BASE_URL}/vehicles/{a.vehicle_id}/charge-settings",
    parse=lambda raw, _a: parse_vehicle_charge_settings(raw),
)

LATEST_CHARGING_SESSION: Endpoint[VehicleArgs, ChargingSessionDetails] = Endpoint(
    name="latest_charging_session",
    method="GET",
    url=lambda a: f"{EV_V2_BASE_URL}/vehicles/{a.vehicle_id}/charging-sessions/latest",
    parse=lambda raw, _a: parse_charging_session_details(raw),
)

LATEST_CHARGING_SESSION_CHARGE_SETTINGS: Endpoint[VehicleArgs, ChargingSessionChargeSettings] = (
    Endpoint(
        name="latest_charging_session_charge_settings",
        method="GET",
        url=lambda a: (
            f"{EV_V2_BASE_URL}/vehicles/{a.vehicle_id}/charging-sessions/latest/charge-settings"
        ),
        parse=lambda raw, _a: parse_charging_session_charge_settings(raw),
    )
)

CHARGING_SESSIONS: Endpoint[ChargingSessionsArgs, ChargingSessionsPage] = Endpoint(
    name="charging_sessions",
    method="GET",
    url=lambda a: f"{EV_V2_BASE_URL}/customer-accounts/{a.can}/charging-sessions",
    params=lambda a: {
        "startDate": a.start_date.isoformat(),
        "endDate": a.end_date.isoformat(),
        "pageSize": str(a.page_size),
        "pageNumber": str(a.page_number),
    },
    parse=lambda raw, _a: parse_charging_sessions_page(raw),
)

CHARGING_SESSION: Endpoint[ChargingSessionArgs, ChargingSessionDetails] = Endpoint(
    name="charging_session",
    method="GET",
    url=lambda a: f"{EV_V2_BASE_URL}/charging-sessions/{a.session_id}",
    parse=lambda raw, _a: parse_charging_session_details(raw),
)

CHARGING_SESSIONS_SUMMARY: Endpoint[CanDateRangeArgs, ChargingSessionsSummary] = Endpoint(
    name="charging_sessions_summary",
    method="GET",
    url=lambda a: f"{EV_BASE_URL}/customer-accounts/{a.can}/charging-sessions-summary",
    params=lambda a: {
        "granularity": "MONTHLY",
        "startDate": a.start_date.isoformat(),
        "endDate": a.end_date.isoformat(),
    },
    parse=lambda raw, _a: parse_charging_sessions_summary(raw),
)

EPEX_PRICES: Endpoint[EpexArgs, EpexPayload] = Endpoint(
    name="epex_prices",
    method="GET",
    url=EPEX_BASE_URL,
    params=_epex_params,
    user_agent=USER_AGENT_BROWSER,
    optional_auth=True,
    not_found_error=_epex_not_published,
    parse=lambda raw, a: parse_epex_prices(raw, granularity_minutes=a.granularity.value),
)

CATALOG: tuple[Endpoint[Any, Any], ...] = (
    PRICES,
    ENERGY_CONTRACTS,
    SERVICE_POINT,
    CUSTOMER_ACCOUNT_RELATIONS,
    MONTHLY_PEAKS,
    HAPPY_HOUR_EVENT,
    HAPPY_HOUR_MONTH_REPORT,
    USAGE_DETAILS,
    SOLAR_SURPLUS_FORECASTS,
    FEATURE_FLAG,
    TOU_SCHEDULES,
    ACCOUNT_BALANCE,
    SERVICE_POINTS,
    METER_READS,
    MONTHLY_BILLED_BUDGET,
    BILLING_PERIOD_USAGE,
    BUDGET_BILLING_PLAN,
    HAPPY_HOUR_ELIGIBILITY,
    HAPPY_HOUR_SERVICE_STATUS,
    ACTIVATE_HAPPY_HOUR_SERVICE,
    CANCEL_HAPPY_HOUR_SERVICE,
    ENERGY_SCORE,
    SMART_CHARGE_SERVICES,
    ELECTRIC_VEHICLES,
    VEHICLE_CHARGE_SETTINGS,
    LATEST_CHARGING_SESSION,
    LATEST_CHARGING_SESSION_CHARGE_SETTINGS,
    CHARGING_SESSIONS,
    CHARGING_SESSION,
    CHARGING_SESSIONS_SUMMARY,
    EPEX_PRICES,
)
"""Every endpoint descriptor. The wire-contract tests iterate this registry."""

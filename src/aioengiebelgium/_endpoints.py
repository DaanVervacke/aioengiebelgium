# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT
"""Endpoint catalog: every wire fact for each API endpoint lives in one descriptor."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any, NoReturn

from .const import (
    ACCOUNTS_BASE_URL,
    API_BASE_URL,
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
from .exceptions import (
    EngieBeCommunicationError,
    EngieBeEpexNotPublishedError,
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
from .parsers import (
    parse_account_balance,
    parse_customer_account_relations,
    parse_energy_contracts,
    parse_epex_prices,
    parse_feature_flag,
    parse_happy_hour_event,
    parse_happy_hour_month_report,
    parse_monthly_peaks,
    parse_prices,
    parse_service_point,
    parse_solar_surplus_forecasts,
    parse_tou_schedules,
    parse_usage_details,
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
        )

    def raise_error(self, err: EngieBeCommunicationError, args: ArgsT) -> NoReturn:
        """Re-raise ``err``, applying the endpoint's 404 remap when configured."""
        if self.not_found_error is not None and err.status == HTTPStatus.NOT_FOUND:
            raise self.not_found_error(args) from err
        raise err


def _normalize_ban(value: str) -> str:
    return value.replace(" ", "")


@dataclass(frozen=True, slots=True)
class NoArgs:
    """Args for endpoints that take no caller input."""


@dataclass(frozen=True, slots=True)
class BanArgs:
    ban: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))


@dataclass(frozen=True, slots=True)
class EanArgs:
    ean: str


@dataclass(frozen=True, slots=True)
class MonthArgs:
    ban: str
    year: int
    month: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))


@dataclass(frozen=True, slots=True)
class ContractsArgs:
    ban: str
    include_inactive: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))


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


@dataclass(frozen=True, slots=True)
class FlagArgs:
    flag: FeatureFlagKey
    ban: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ban", _normalize_ban(self.ban))


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
    url=lambda a: f"{API_BASE_URL}/business-agreements/{a.ban}/supplier-energy-prices",
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

MONTHLY_PEAKS: Endpoint[MonthArgs, MonthlyPeaks] = Endpoint(
    name="monthly_peaks",
    method="GET",
    url=lambda a: (
        f"{PEAKS_BASE_URL}/private/customers/me/contract-accounts/{a.ban}/energy-insights/peaks"
    ),
    params=lambda a: {"year": str(a.year), "month": str(a.month)},
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
    url=lambda a: f"{HAPPY_HOUR_BASE_URL}/business-agreements/{a.ban}/tou-schedules",
    parse=lambda raw, _a: parse_tou_schedules(raw),
)

ACCOUNT_BALANCE: Endpoint[BanArgs, AccountBalance] = Endpoint(
    name="account_balance",
    method="GET",
    url=lambda a: f"{BILLING_BASE_URL}/business-agreements/{a.ban}/account-balance",
    parse=lambda raw, _a: parse_account_balance(raw),
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
    EPEX_PRICES,
)
"""Every endpoint descriptor; the wire-contract tests iterate this registry."""

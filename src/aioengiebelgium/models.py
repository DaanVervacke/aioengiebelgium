# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .const import DELIVERY_POINT_SUFFIX, DYNAMIC_ENERGY_PRODUCTS, SolarSurplusLevel


def bare_ean(ean: str) -> str:
    """Strip a trailing delivery-point suffix (_ID1) from an EAN."""
    return ean.split("_", maxsplit=1)[0]


def ean_with_delivery_point_suffix(ean: str) -> str:
    """Append the delivery-point suffix ENGIE endpoints expect."""
    return f"{ean}{DELIVERY_POINT_SUFFIX}"


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None:
        msg = "timezone-aware datetimes required"
        raise ValueError(msg)


def _parse_hhmm(raw: str) -> time | None:
    parts = raw.split(":", 1)
    if len(parts) != 2:  # noqa: PLR2004
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):  # noqa: PLR2004
        return None
    return time(hour=h, minute=m)


@dataclass(frozen=True, slots=True)
class ConsumptionAddress:
    """Consumption address for a business agreement."""

    street: str | None = None
    house_number: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    country_code: str | None = None
    premises_number: str | None = None
    box_number: str | None = None
    floor: str | None = None
    room_number: str | None = None
    supplement: str | None = None
    location_supplement: str | None = None

    def format(self) -> str:
        """Format as 'street houseNumber, postalCode city'."""
        line1 = " ".join(part for part in (self.street, self.house_number) if part).strip()
        line2 = " ".join(part for part in (self.postal_code, self.city) if part).strip()
        return ", ".join(part for part in (line1, line2) if part)


@dataclass(frozen=True, slots=True)
class ContractInfo:
    """Contract info nested within a business agreement."""

    has_smart_meter: bool = False
    active: bool = False
    has_solar: bool = False


@dataclass(frozen=True, slots=True)
class BusinessAgreement:
    """A single business agreement within a customer account."""

    business_agreement_number: str
    active: bool
    consumption_address: ConsumptionAddress | None = None
    electricity_contract: ContractInfo | None = None
    gas_contract: ContractInfo | None = None


@dataclass(frozen=True, slots=True)
class CustomerAccount:
    """A customer account with its business agreements."""

    customer_account_number: str
    name: str | None = None
    segment: str | None = None
    language: str | None = None
    business_agreements: tuple[BusinessAgreement, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountRelation:
    """A single relation item linking a user to a customer account."""

    id: str
    admin: bool
    customer_account: CustomerAccount


@dataclass(frozen=True, slots=True)
class CustomerAccountRelations:
    """Response from the customer-account-relations endpoint."""

    accounts: tuple[AccountRelation, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceSlot:
    """A single time-of-use price slot."""

    time_of_use_slot_code: str
    price_value: float
    price_value_excl_vat: float


@dataclass(frozen=True, slots=True)
class PricePeriod:
    """A price period with offtake and injection slots."""

    valid_from: str
    valid_to: str
    vat_tariff: float
    offtake: tuple[PriceSlot, ...] = ()
    injection: tuple[PriceSlot, ...] = ()


@dataclass(frozen=True, slots=True)
class EanPrices:
    """Prices for a single EAN."""

    ean: str
    periods: tuple[PricePeriod, ...] = ()


@dataclass(frozen=True, slots=True)
class PricesResponse:
    """Response from the supplier-energy-prices endpoint."""

    items: tuple[EanPrices, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductConfiguration:
    """Product configuration for an energy contract."""

    energy_product: str | None = None
    type: str | None = None


@dataclass(frozen=True, slots=True)
class EnergyContract:
    """A single energy contract."""

    business_agreement_number: str
    service_point_number: str
    division: str
    status: str
    product_configuration: ProductConfiguration | None = None


@dataclass(frozen=True, slots=True)
class EnergyContractsResponse:
    """Response from the energy-contracts endpoint."""

    items: tuple[EnergyContract, ...] = ()

    def energy_products_by_ean(self) -> dict[str, str]:
        """Return a mapping of bare EAN to energy product for active contracts."""
        result: dict[str, str] = {}
        for c in self.items:
            if (
                c.status == "ACTIVE"
                and c.service_point_number
                and c.product_configuration is not None
                and c.product_configuration.energy_product is not None
            ):
                result[bare_ean(c.service_point_number)] = c.product_configuration.energy_product
        return result

    def service_points_by_ean(self) -> dict[str, str]:
        """Return a mapping of bare EAN to division for active contracts."""
        result: dict[str, str] = {}
        for c in self.items:
            if c.status == "ACTIVE" and c.service_point_number and c.division:
                result[bare_ean(c.service_point_number)] = c.division
        return result

    def is_dynamic(self) -> bool:
        """Return True when any active electricity contract has a dynamic product."""
        return any(
            c.status == "ACTIVE"
            and c.division == "ELECTRICITY"
            and c.product_configuration is not None
            and c.product_configuration.energy_product in DYNAMIC_ENERGY_PRODUCTS
            for c in self.items
        )


@dataclass(frozen=True, slots=True)
class Peak:
    """A single capacity tariff peak measurement."""

    peak_kw: float
    peak_kwh: float
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class MonthlyPeaks:
    """Response from the monthly peaks endpoint."""

    year: int
    month: int
    peak_of_the_month: Peak | None = None
    daily_peaks: tuple[Peak, ...] = ()


@dataclass(frozen=True, slots=True)
class FinancialTransaction:
    """A single financial transaction."""

    type: str | None = None
    due_amount: float = 0.0
    open_amount: float = 0.0
    due_date: str | None = None
    invoice_type: str | None = None


@dataclass(frozen=True, slots=True)
class BillingOverview:
    """Billing overview with aggregated amounts."""

    total_amount: float = 0.0
    open_amount: float = 0.0
    due_amount: float = 0.0
    pending_online_payments_amount: float = 0.0
    installment_plan_amount: float = 0.0


@dataclass(frozen=True, slots=True)
class BillingDetails:
    """Billing details including transactions."""

    financial_transactions: tuple[FinancialTransaction, ...] = ()
    invoice_structured_communication: str | None = None


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Response from the account-balance endpoint."""

    status: str | None = None
    overview: BillingOverview | None = None
    details: BillingDetails | None = None
    refund_blocked: bool = False

    def earliest_due_date(self, tz: ZoneInfo) -> datetime | None:
        """Return the earliest due date among open transactions, or ``None``."""
        if self.details is None:
            return None
        earliest: datetime | None = None
        for tx in self.details.financial_transactions:
            if tx.open_amount <= 0 or tx.due_date is None:
                continue
            try:
                due_dt = datetime.fromisoformat(tx.due_date)
            except ValueError:
                continue
            due_dt = due_dt.replace(tzinfo=tz) if due_dt.tzinfo is None else due_dt.astimezone(tz)
            if earliest is None or due_dt < earliest:
                earliest = due_dt
        return earliest


@dataclass(frozen=True, slots=True)
class EpexSlot:
    """Single EPEX day-ahead market price slot."""

    start: datetime
    end: datetime
    value_eur_per_kwh: float

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass(frozen=True, slots=True)
class EpexPayload:
    """Parsed EPEX day-ahead price data."""

    slots: tuple[EpexSlot, ...] = ()
    publication_time: datetime | None = None
    market_date: str | None = None
    slot_duration: timedelta = timedelta(minutes=60)

    def next_slot_boundary(self, now: datetime) -> datetime | None:
        """Return the next instant at which the current EPEX slot changes."""
        _require_aware(now)
        if not self.slots:
            return None
        candidates: list[datetime] = []
        for slot in self.slots:
            if slot.start <= now < slot.end:
                candidates.append(slot.end)
            elif slot.start > now:
                candidates.append(slot.start)
        return min(candidates) if candidates else None


@dataclass(frozen=True, slots=True)
class HappyHourWindow:
    """A single happy-hour time window."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class HappyHourEvent:
    """Response from the happy-hour-event endpoint."""

    windows: tuple[HappyHourWindow, ...] = ()

    def is_active(self, now: datetime) -> bool:
        """Return True when ``now`` falls inside any happy-hour window."""
        _require_aware(now)
        return any(w.start <= now < w.end for w in self.windows)


@dataclass(frozen=True, slots=True)
class HappyHourComparison:
    """Month-over-month comparison for happy hours."""

    consumption_kwh_pct_change: float = 0.0
    eligible_hours_pct_change: float = 0.0
    reward_euros_pct_change: float = 0.0


@dataclass(frozen=True, slots=True)
class HappyHourMonthData:
    """Happy hour stats for a single month."""

    consumption_kwh: float = 0.0
    eligible_hours: int = 0
    reward_euros: float = 0.0
    is_calculation_ongoing: bool = False
    comparison: HappyHourComparison | None = None


@dataclass(frozen=True, slots=True)
class EnergyCostPair:
    """A kWh/cost pair for one flow direction in a month-report history entry."""

    kwh: float | None = None
    cost: float | None = None


@dataclass(frozen=True, slots=True)
class MonthReportHistoryEntry:
    """One month in the month-report history."""

    year_month: str
    happy_hour: HappyHourMonthData | None = None
    electricity_offtake: EnergyCostPair | None = None
    electricity_injection: EnergyCostPair | None = None


@dataclass(frozen=True, slots=True)
class SimulatedEnergyFlow:
    """A simulated kWh estimate for one flow direction."""

    kwh: float | None = None


@dataclass(frozen=True, slots=True)
class SimulatedEnergy:
    """Simulated (estimated) energy for the current month."""

    electricity_offtake: SimulatedEnergyFlow | None = None
    electricity_injection: SimulatedEnergyFlow | None = None


@dataclass(frozen=True, slots=True)
class SimulatedCostFlow:
    """A simulated cost estimate for one flow direction."""

    amount: float | None = None


@dataclass(frozen=True, slots=True)
class SimulatedCost:
    """Simulated (estimated) cost for the current month."""

    electricity_offtake: SimulatedCostFlow | None = None
    electricity_injection: SimulatedCostFlow | None = None
    total: float | None = None


@dataclass(frozen=True, slots=True)
class HappyHourMonthReport:
    """Response from the happy-hour month-report endpoint."""

    current: HappyHourMonthData | None = None
    history: tuple[MonthReportHistoryEntry, ...] = ()
    year_month: str | None = None
    partial_historical_data: bool | None = None
    partial_year_month_data: bool | None = None
    simulated_energy: SimulatedEnergy | None = None
    simulated_cost: SimulatedCost | None = None


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    """A single boolean feature flag response."""

    value: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SolarSurplusSlot:
    """A single hourly solar surplus forecast slot."""

    start_time: datetime
    value: float | None = None
    level: str | None = None


@dataclass(frozen=True, slots=True)
class SolarSurplusDay:
    """One day of solar surplus forecasts."""

    forecast_date: str
    forecast_creation_date: datetime | None = None
    inference_key: str | None = None
    level: str | None = None
    details: tuple[SolarSurplusSlot, ...] = ()


@dataclass(frozen=True, slots=True)
class SolarSurplusForecasts:
    """Response from the solar-surplus forecasts endpoint."""

    forecasts: tuple[SolarSurplusDay, ...] = ()

    def all_slots(self) -> list[SolarSurplusSlot]:
        return [slot for day in self.forecasts for slot in day.details]

    def slot_covering(self, instant: datetime) -> SolarSurplusSlot | None:
        """Return the slot whose [start, start+1h) interval covers ``instant``."""
        _require_aware(instant)
        for slot in self.all_slots():
            if slot.start_time <= instant < slot.start_time + timedelta(hours=1):
                return slot
        return None

    def slots_for_local_date(
        self,
        target_date: date,
        tz: ZoneInfo,
    ) -> list[SolarSurplusSlot]:
        """Return every slot whose local date in ``tz`` matches ``target_date``."""
        return [s for s in self.all_slots() if s.start_time.astimezone(tz).date() == target_date]

    def next_hour_boundary(self, now: datetime) -> datetime | None:
        """Return the earliest slot start strictly after ``now``."""
        _require_aware(now)
        future = [s.start_time for s in self.all_slots() if s.start_time > now]
        return min(future) if future else None

    def has_solar(self) -> bool:
        """Return True when any slot carries a level other than ``no_data``."""
        return any(
            s.level is not None and s.level != SolarSurplusLevel.NO_DATA for s in self.all_slots()
        )


@dataclass(frozen=True, slots=True)
class TouSlot:
    """A single time-of-use slot within a day."""

    start_time: str
    end_time: str
    slot_code: str


@dataclass(frozen=True, slots=True)
class TouDirectionSchedule:
    """TOU schedule for one direction, per weekday, with its cheapest slot code."""

    optimal_timeslot_code: str | None = None
    monday: tuple[TouSlot, ...] = ()
    tuesday: tuple[TouSlot, ...] = ()
    wednesday: tuple[TouSlot, ...] = ()
    thursday: tuple[TouSlot, ...] = ()
    friday: tuple[TouSlot, ...] = ()
    saturday: tuple[TouSlot, ...] = ()
    sunday: tuple[TouSlot, ...] = ()

    def slots_for_weekday(self, weekday: int) -> tuple[TouSlot, ...]:
        """Return slots for a given weekday index (0=Monday)."""
        fields = (
            self.monday,
            self.tuesday,
            self.wednesday,
            self.thursday,
            self.friday,
            self.saturday,
            self.sunday,
        )
        return fields[weekday]

    def current_slot(
        self,
        now: datetime,
        tz: ZoneInfo,
    ) -> tuple[str | None, datetime | None]:
        """Return (slot_code, next_transition) or (None, None)."""
        _require_aware(now)
        now_local = now.astimezone(tz)
        for day_offset in (0, -1):
            slot_date = now_local.date() + timedelta(days=day_offset)
            weekday = (now_local.weekday() + day_offset) % 7
            for slot in self.slots_for_weekday(weekday):
                start = _parse_hhmm(slot.start_time)
                end = _parse_hhmm(slot.end_time)
                if start is None or end is None:
                    continue
                start_dt = datetime.combine(
                    slot_date,
                    start,
                    tzinfo=tz,
                ).replace(fold=now_local.fold)
                end_date = slot_date + timedelta(days=1) if end <= start else slot_date
                end_dt = datetime.combine(
                    end_date,
                    end,
                    tzinfo=tz,
                ).replace(fold=now_local.fold)
                if start_dt <= now_local < end_dt:
                    return slot.slot_code, end_dt.astimezone(now_local.tzinfo)
        return None, None

    def has_multiple_slot_codes(self) -> bool:
        """Return True when the schedule has more than one distinct slot code."""
        codes: set[str] = set()
        for weekday in range(7):
            for slot in self.slots_for_weekday(weekday):
                codes.add(slot.slot_code)
        return len(codes) > 1


@dataclass(frozen=True, slots=True)
class TouSchedule:
    """One TOU schedule (grid-operator or supplier), both directions."""

    offtake: TouDirectionSchedule | None = None
    injection: TouDirectionSchedule | None = None


@dataclass(frozen=True, slots=True)
class TouScheduleItem:
    """TOU schedules for a single EAN: the DGO/TGO and supplier schedules."""

    ean_with_suffix: str
    dgo_tgo: TouSchedule | None = None
    supplier: TouSchedule | None = None


@dataclass(frozen=True, slots=True)
class TouSchedulesResponse:
    """Response from the tou-schedules endpoint."""

    items: tuple[TouScheduleItem, ...] = ()

    def schedule_for_ean(self, ean_with_suffix: str) -> TouScheduleItem | None:
        """Return the item for the given EAN-with-suffix, or ``None``."""
        return next(
            (i for i in self.items if i.ean_with_suffix == ean_with_suffix),
            None,
        )


@dataclass(frozen=True, slots=True)
class ElectricityUsage:
    """Electricity usage breakdown."""

    offtake_kwh: float = 0.0
    injection_kwh: float = 0.0
    netto_kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class GasUsage:
    """Gas usage data."""

    kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class UsageTouPart:
    """A single TOU-slot value within a usage energy or cost breakdown."""

    slot_code: str
    value: float = 0.0


@dataclass(frozen=True, slots=True)
class UsageTouCrossPart:
    """A joint supplier/distribution TOU-slot value for the combined ``parts`` list."""

    supplier_slot_code: str
    distribution_slot_code: str
    value: float = 0.0


@dataclass(frozen=True, slots=True)
class UsageDirectionBreakdown:
    """TOU-slot breakdown for one flow direction (offtake or injection)."""

    kwh_sum: float | None = None
    amount_sum: float | None = None
    parts: tuple[UsageTouCrossPart, ...] = ()
    supplier_parts: tuple[UsageTouPart, ...] = ()
    distribution_parts: tuple[UsageTouPart, ...] = ()


@dataclass(frozen=True, slots=True)
class UsageElectricityBreakdown:
    """Electricity offtake/injection breakdown for one usage period."""

    offtake: UsageDirectionBreakdown | None = None
    injection: UsageDirectionBreakdown | None = None


@dataclass(frozen=True, slots=True)
class UsageItem:
    """A single usage period (hourly, daily, or monthly)."""

    start: datetime
    end: datetime
    partial_data: bool = False
    electricity: ElectricityUsage | None = None
    gas: GasUsage | None = None
    energy: UsageElectricityBreakdown | None = None
    costs: UsageElectricityBreakdown | None = None
    simulated_energy: UsageElectricityBreakdown | None = None
    simulated_costs: UsageElectricityBreakdown | None = None


@dataclass(frozen=True, slots=True)
class UsageDetailsResponse:
    """Response from the usage-details endpoint."""

    items: tuple[UsageItem, ...] = ()
    total: UsageItem | None = None


@dataclass(frozen=True, slots=True)
class ServicePoint:
    """Response from the service-point endpoint."""

    ean_energy_types: Mapping[str, str]

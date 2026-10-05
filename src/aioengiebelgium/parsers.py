import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from itertools import pairwise
from types import MappingProxyType
from typing import Any, Literal

from .const import EPEX_MWH_TO_KWH
from .models import (
    AccountBalance,
    AccountRelation,
    BillingDetails,
    BillingOverview,
    BillingPeriodUsage,
    BudgetBillingPlan,
    BudgetBillingPlanContractPeriod,
    BudgetBillingPlanDetails,
    BudgetBillingPlanLimits,
    BudgetBillingPlanProposal,
    BudgetBillingPlanProposalFactor,
    BusinessAgreement,
    ConsumptionAddress,
    ContractInfo,
    CustomerAccount,
    CustomerAccountRelations,
    DataAvailability,
    EanPrices,
    ElectricityUsage,
    EnergyContract,
    EnergyContractsResponse,
    EnergyCostPair,
    EpexPayload,
    EpexSlot,
    FeatureFlag,
    FinancialTransaction,
    GasUsage,
    HappyHourComparison,
    HappyHourEligibility,
    HappyHourEvent,
    HappyHourMonthData,
    HappyHourMonthReport,
    HappyHourServiceStatus,
    HappyHourWindow,
    MeasuredDataWindow,
    MeteringConfiguration,
    MeteringDataSource,
    MeteringDataSources,
    MeteringServicePoint,
    MeterRead,
    MeterReadsResponse,
    MeterRegisterRead,
    MonthlyBilledBudget,
    MonthlyPeaks,
    MonthReportHistoryEntry,
    PaymentSlice,
    Peak,
    PricePeriod,
    PriceSlot,
    PricesResponse,
    ProductConfiguration,
    ServicePoint,
    ServicePointInstallation,
    ServicePointMarketDetails,
    ServicePointsResponse,
    SimulatedCost,
    SimulatedCostFlow,
    SimulatedEnergy,
    SimulatedEnergyFlow,
    SolarSurplusDay,
    SolarSurplusForecasts,
    SolarSurplusSlot,
    TouCombinedDirectionSchedule,
    TouCombinedSchedule,
    TouCombinedSlot,
    TouDirectionSchedule,
    TouGridMeterSchedule,
    TouSchedule,
    TouScheduleItem,
    TouSchedulesResponse,
    TouSlot,
    UsageDetailsResponse,
    UsageDirectionBreakdown,
    UsageElectricityBreakdown,
    UsageItem,
    UsageTouCrossPart,
    UsageTouPart,
    bare_ean,
)

_LOGGER = logging.getLogger(__name__)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except ValueError, TypeError:
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except ValueError, TypeError:
        return 0


def _as_float_or_none(value: Any) -> float | None:
    return _as_float(value) if value is not None else None


def _as_int_or_none(value: Any) -> int | None:
    return _as_int(value) if value is not None else None


def _as_bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_date(value: Any) -> date | None:
    """Parse an ISO date or datetime string into a calendar date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            _LOGGER.debug("malformed date value: %s", value)
            return None


def _as_year_month(value: Any) -> date | None:
    """Parse a ``YYYY-MM`` wire value into the month's start date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError:
        _LOGGER.debug("malformed year-month value: %s", value)
        return None


def _as_aware_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime string, returning None for naive or invalid input."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed


def _parse_items_counted[T](
    data: object,
    item_parser: Callable[[dict[str, Any]], T | None],
    label: str,
) -> tuple[list[T], int]:
    """Parse a list defensively, returning the items and the skipped-entry count."""
    if not isinstance(data, list):
        return [], 0
    n_skipped = 0
    items: list[T] = []
    for raw in data:
        item = item_parser(raw) if isinstance(raw, dict) else None
        if item is None:
            n_skipped += 1
            continue
        items.append(item)
    if n_skipped:
        _LOGGER.debug("skipped %d malformed %s entries", n_skipped, label)
    return items, n_skipped


def _parse_items[T](
    data: object,
    item_parser: Callable[[dict[str, Any]], T | None],
    label: str,
) -> list[T]:
    """Parse a list defensively."""
    return _parse_items_counted(data, item_parser, label)[0]


def _parse_business_agreement(ag: dict[str, Any]) -> BusinessAgreement | None:
    ban = ag.get("businessAgreementNumber")
    if not isinstance(ban, str) or not ban:
        return None

    address_raw = ag.get("consumptionAddress")
    address = (
        ConsumptionAddress(
            street=address_raw.get("street"),
            house_number=address_raw.get("houseNumber"),
            postal_code=address_raw.get("postalCode"),
            city=address_raw.get("city"),
            country=address_raw.get("country"),
            country_code=address_raw.get("countryCode"),
            premises_number=address_raw.get("premisesNumber"),
            box_number=address_raw.get("boxNumber"),
            floor=address_raw.get("floor"),
            room_number=address_raw.get("roomNumber"),
            supplement=address_raw.get("supplement"),
            location_supplement=address_raw.get("locationSupplement"),
        )
        if isinstance(address_raw, dict)
        else None
    )

    elec_raw = ag.get("electricityContract")
    elec = (
        ContractInfo(
            has_smart_meter=bool(elec_raw.get("hasSmartMeter")),
            active=bool(elec_raw.get("active")),
            has_solar=bool(elec_raw.get("hasSolar")),
        )
        if isinstance(elec_raw, dict)
        else None
    )

    gas_raw = ag.get("gasContract")
    gas = (
        ContractInfo(
            has_smart_meter=bool(gas_raw.get("hasSmartMeter")),
            active=bool(gas_raw.get("active")),
        )
        if isinstance(gas_raw, dict)
        else None
    )

    return BusinessAgreement(
        business_agreement_number=ban,
        active=bool(ag.get("active")),
        consumption_address=address,
        electricity_contract=elec,
        gas_contract=gas,
    )


def _parse_account_relation(item: dict[str, Any]) -> AccountRelation | None:
    ca = item.get("customerAccount")
    if not isinstance(ca, dict):
        return None
    can = ca.get("customerAccountNumber")
    if not isinstance(can, str) or not can:
        return None
    agreements = _parse_items(
        ca.get("businessAgreements"), _parse_business_agreement, "account relation"
    )
    return AccountRelation(
        id=_as_str(item.get("id")),
        admin=bool(item.get("admin")),
        customer_account=CustomerAccount(
            customer_account_number=can,
            name=ca.get("name"),
            segment=ca.get("segment"),
            language=ca.get("language"),
            business_agreements=tuple(agreements),
        ),
    )


def parse_customer_account_relations(data: dict[str, Any]) -> CustomerAccountRelations:
    accounts, skipped = _parse_items_counted(
        data.get("items"), _parse_account_relation, "account relation"
    )
    return CustomerAccountRelations(accounts=tuple(accounts), skipped_entries=skipped)


def _parse_price_slot(s: dict[str, Any]) -> PriceSlot:
    return PriceSlot(
        time_of_use_slot_code=_as_str(s.get("timeOfUseSlotCode")),
        price_value=_as_float(s.get("priceValue")),
        price_value_excl_vat=_as_float(s.get("priceValueExclVAT")),
    )


def _parse_price_slots(raw_list: Any) -> tuple[PriceSlot, ...]:
    return tuple(_parse_items(raw_list, _parse_price_slot, "price slot"))


def _parse_price_period(period: dict[str, Any]) -> PricePeriod:
    configs_raw = period.get("proportionalPriceConfigurations")
    configs = configs_raw if isinstance(configs_raw, dict) else {}
    return PricePeriod(
        valid_from=_as_date(period.get("from")),
        valid_to=_as_date(period.get("to")),
        vat_tariff=_as_float(period.get("vatTariff")),
        offtake=_parse_price_slots(configs.get("offtake")),
        injection=_parse_price_slots(configs.get("injection")),
    )


def _parse_ean_prices(item: dict[str, Any]) -> EanPrices:
    return EanPrices(
        ean=_as_str(item.get("ean")),
        periods=tuple(_parse_items(item.get("prices"), _parse_price_period, "price")),
    )


def parse_prices(data: dict[str, Any]) -> PricesResponse:
    items, skipped = _parse_items_counted(data.get("items"), _parse_ean_prices, "price")
    return PricesResponse(items=tuple(items), skipped_entries=skipped)


def _parse_energy_contract(item: dict[str, Any]) -> EnergyContract:
    pc_raw = item.get("productConfiguration")
    pc = (
        ProductConfiguration(
            energy_product=pc_raw.get("energyProduct"),
            type=pc_raw.get("type"),
            green_level=_as_str_or_none(pc_raw.get("greenLevel")),
            green_origin=_as_str_or_none(pc_raw.get("greenOrigin")),
        )
        if isinstance(pc_raw, dict)
        else None
    )
    return EnergyContract(
        business_agreement_number=_as_str(item.get("businessAgreementNumber")),
        service_point_number=_as_str(item.get("servicePointNumber")),
        division=_as_str(item.get("division")),
        status=_as_str(item.get("status")),
        product_configuration=pc,
    )


def parse_energy_contracts(data: dict[str, Any]) -> EnergyContractsResponse:
    items, skipped = _parse_items_counted(
        data.get("items"), _parse_energy_contract, "energy contract"
    )
    return EnergyContractsResponse(items=tuple(items), skipped_entries=skipped)


def _parse_peak(data: dict[str, Any]) -> Peak | None:
    start = _as_aware_datetime(data.get("start"))
    end = _as_aware_datetime(data.get("end"))
    if start is None or end is None:
        return None
    return Peak(
        peak_kw=_as_float(data.get("peakKW")),
        peak_kwh=_as_float(data.get("peakKWh")),
        start=start,
        end=end,
    )


def _parse_optional_peak(data: Any) -> Peak | None:
    return _parse_peak(data) if isinstance(data, dict) else None


def parse_monthly_peaks(data: dict[str, Any]) -> MonthlyPeaks:
    daily, skipped = _parse_items_counted(data.get("dailyPeaks"), _parse_peak, "daily peak")
    return MonthlyPeaks(
        year=_as_int(data.get("year")),
        month=_as_int(data.get("month")),
        peak_of_the_month=_parse_optional_peak(data.get("peakOfTheMonth")),
        daily_peaks=tuple(daily),
        skipped_entries=skipped,
        previous_peak_of_the_month=_parse_optional_peak(data.get("previousPeakOfTheMonth")),
    )


def _parse_financial_transaction(tx: dict[str, Any]) -> FinancialTransaction:
    return FinancialTransaction(
        type=tx.get("type"),
        due_amount=_as_float(tx.get("dueAmount")),
        open_amount=_as_float(tx.get("openAmount")),
        due_date=_as_date(tx.get("dueDate")),
        invoice_type=tx.get("invoiceType"),
    )


def parse_account_balance(data: dict[str, Any]) -> AccountBalance:
    overview_raw = data.get("overview")
    overview = (
        BillingOverview(
            total_amount=_as_float(overview_raw.get("totalAmount")),
            open_amount=_as_float(overview_raw.get("openAmount")),
            due_amount=_as_float(overview_raw.get("dueAmount")),
            pending_online_payments_amount=_as_float(
                overview_raw.get("pendingOnlinePaymentsAmount")
            ),
            installment_plan_amount=_as_float(overview_raw.get("installmentPlanAmount")),
        )
        if isinstance(overview_raw, dict)
        else None
    )

    details_raw = data.get("details")
    details = None
    if isinstance(details_raw, dict):
        txns = _parse_items(
            details_raw.get("financialTransactions"),
            _parse_financial_transaction,
            "financial transaction",
        )
        details = BillingDetails(
            financial_transactions=tuple(txns),
            invoice_structured_communication=details_raw.get("invoiceStructuredCommunication"),
        )

    refund_raw = data.get("refundBlocked")
    if isinstance(refund_raw, bool):
        refund_blocked = refund_raw
    elif isinstance(refund_raw, str):
        refund_blocked = refund_raw.lower() == "true"
    else:
        refund_blocked = False

    return AccountBalance(
        status=data.get("status"),
        overview=overview,
        details=details,
        refund_blocked=refund_blocked,
    )


def _parse_epex_entry(entry: dict[str, Any]) -> tuple[datetime, float] | None:
    period = _as_aware_datetime(entry.get("period"))
    value_raw = entry.get("value")
    if period is None or value_raw is None:
        return None
    try:
        return (period, float(value_raw))
    except ValueError, TypeError:
        return None


def parse_epex_prices(data: dict[str, Any], *, granularity_minutes: int = 60) -> EpexPayload:
    """Parse the EPEX day-ahead prices response."""
    requested = timedelta(minutes=granularity_minutes)
    raw_slots, skipped = _parse_items_counted(data.get("timeSeries"), _parse_epex_entry, "EPEX")

    raw_slots.sort(key=lambda pair: pair[0])
    deduped: list[tuple[datetime, float]] = []
    for entry in raw_slots:
        if deduped and entry[0] == deduped[-1][0]:
            continue
        deduped.append(entry)
    dropped = len(raw_slots) - len(deduped)
    if dropped:
        _LOGGER.debug("dropped %d EPEX slot(s) with duplicate start times", dropped)
    raw_slots = deduped

    starts = [start for start, _ in raw_slots]
    spacings = [nxt - cur for cur, nxt in pairwise(starts)]
    if spacings:
        observed = Counter(spacings).most_common(1)[0][0]
        if observed != requested:
            _LOGGER.debug(
                "observed EPEX slot spacing %s differs from requested granularity %s",
                observed,
                requested,
            )
    else:
        observed = requested

    slots_list = []
    for i, (start, value) in enumerate(raw_slots):
        end = start + observed
        if i + 1 < len(starts):
            end = min(starts[i + 1], end)
        slots_list.append(
            EpexSlot(
                start=start,
                end=end,
                value_eur_per_kwh=round(value / EPEX_MWH_TO_KWH, 6),
            )
        )

    pub_time = _as_aware_datetime(data.get("publicationTime"))

    return EpexPayload(
        slots=tuple(slots_list),
        publication_time=pub_time,
        market_date=_as_date(data.get("marketDate")),
        slot_duration=observed,
        skipped_entries=skipped,
    )


def _parse_happy_hour_window(sub: Any) -> HappyHourWindow | None:
    if not isinstance(sub, dict):
        return None
    start = _as_aware_datetime(sub.get("startTime"))
    end = _as_aware_datetime(sub.get("endTime"))
    if start is None or end is None:
        return None
    return HappyHourWindow(start=start, end=end)


def parse_happy_hour_event(data: dict[str, Any]) -> HappyHourEvent:
    """Parse the happy-hour-event response."""
    n_skipped = 0
    windows: list[HappyHourWindow] = []
    for key in ("today", "tomorrow"):
        raw = data.get(key)
        if raw is None:
            continue
        window = _parse_happy_hour_window(raw)
        if window is None:
            n_skipped += 1
            continue
        windows.append(window)
    if n_skipped:
        _LOGGER.debug("skipped %d malformed happy hour window entries", n_skipped)
    windows.sort(key=lambda w: w.start)
    return HappyHourEvent(windows=tuple(windows), skipped_entries=n_skipped)


def _parse_happy_hour_data(raw: dict[str, Any]) -> HappyHourMonthData:
    comparison = None
    comp_raw = raw.get("comparisonToPreviousMonth")
    if isinstance(comp_raw, dict):
        comparison = HappyHourComparison(
            consumption_kwh_pct_change=_as_float(comp_raw.get("consumptionKWhPercentageChange")),
            eligible_hours_pct_change=_as_float(
                comp_raw.get("numberOfEligibleHappyHoursPercentageChange")
            ),
            reward_euros_pct_change=_as_float(comp_raw.get("rewardEurosPercentageChange")),
        )
    return HappyHourMonthData(
        consumption_kwh=_as_float(raw.get("consumptionKWh")),
        eligible_hours=_as_int(raw.get("numberOfEligibleHappyHours")),
        reward_euros=_as_float(raw.get("rewardEuros")),
        is_calculation_ongoing=bool(raw.get("isCalculationOngoing", False)),
        comparison=comparison,
    )


def _parse_energy_cost_pair(raw: Any) -> EnergyCostPair | None:
    if not isinstance(raw, dict):
        return None
    return EnergyCostPair(
        kwh=_as_float_or_none(raw.get("kWh")),
        cost=_as_float_or_none(raw.get("cost")),
    )


def _parse_month_report_history_entry(entry: dict[str, Any]) -> MonthReportHistoryEntry | None:
    year_month = _as_year_month(entry.get("yearMonth"))
    if year_month is None:
        return None
    hh = entry.get("happyHour")
    return MonthReportHistoryEntry(
        year_month=year_month,
        happy_hour=_parse_happy_hour_data(hh) if isinstance(hh, dict) else None,
        electricity_offtake=_parse_energy_cost_pair(entry.get("electricityOfftake")),
        electricity_injection=_parse_energy_cost_pair(entry.get("electricityInjection")),
        gas=_parse_energy_cost_pair(entry.get("gas")),
    )


def _parse_simulated_energy_flow(raw: Any) -> SimulatedEnergyFlow | None:
    if not isinstance(raw, dict):
        return None
    return SimulatedEnergyFlow(kwh=_as_float_or_none(raw.get("kWh")))


def _parse_simulated_energy(raw: Any) -> SimulatedEnergy | None:
    if not isinstance(raw, dict):
        return None
    return SimulatedEnergy(
        electricity_offtake=_parse_simulated_energy_flow(raw.get("electricityOfftake")),
        electricity_injection=_parse_simulated_energy_flow(raw.get("electricityInjection")),
        gas=_parse_simulated_energy_flow(raw.get("gas")),
    )


def _parse_simulated_cost_flow(raw: Any) -> SimulatedCostFlow | None:
    if not isinstance(raw, dict):
        return None
    return SimulatedCostFlow(amount=_as_float_or_none(raw.get("amount")))


def _parse_simulated_cost(raw: Any) -> SimulatedCost | None:
    if not isinstance(raw, dict):
        return None
    return SimulatedCost(
        electricity_offtake=_parse_simulated_cost_flow(raw.get("electricityOfftake")),
        electricity_injection=_parse_simulated_cost_flow(raw.get("electricityInjection")),
        total=_as_float_or_none(raw.get("total")),
        gas=_parse_simulated_cost_flow(raw.get("gas")),
    )


def _month_block_gas(block: Any) -> dict[str, Any] | None:
    gas = block.get("gas") if isinstance(block, dict) else None
    return gas if isinstance(gas, dict) else None


def _parse_month_gas(energy: Any, cost: Any) -> EnergyCostPair | None:
    energy_gas = _month_block_gas(energy)
    cost_gas = _month_block_gas(cost)
    if energy_gas is None and cost_gas is None:
        return None
    return EnergyCostPair(
        kwh=_as_float_or_none(energy_gas.get("kWh")) if energy_gas is not None else None,
        cost=_as_float_or_none(cost_gas.get("amount")) if cost_gas is not None else None,
    )


def parse_happy_hour_month_report(data: dict[str, Any]) -> HappyHourMonthReport:
    current = None
    simulated_energy = None
    simulated_cost = None
    gas = None
    month_raw = data.get("month")
    if isinstance(month_raw, dict):
        hh = month_raw.get("happyHour")
        if isinstance(hh, dict):
            current = _parse_happy_hour_data(hh)
        simulated_energy = _parse_simulated_energy(month_raw.get("simulatedEnergy"))
        simulated_cost = _parse_simulated_cost(month_raw.get("simulatedCost"))
        gas = _parse_month_gas(month_raw.get("energy"), month_raw.get("cost"))

    history, skipped = _parse_items_counted(
        data.get("history"), _parse_month_report_history_entry, "month report history"
    )
    year_month = data.get("yearMonth")
    partial_historical_data = data.get("partialHistoricalData")
    partial_year_month_data = data.get("partialYearMonthData")
    return HappyHourMonthReport(
        current=current,
        history=tuple(history),
        year_month=year_month if isinstance(year_month, str) else None,
        partial_historical_data=(
            partial_historical_data if isinstance(partial_historical_data, bool) else None
        ),
        partial_year_month_data=(
            partial_year_month_data if isinstance(partial_year_month_data, bool) else None
        ),
        simulated_energy=simulated_energy,
        simulated_cost=simulated_cost,
        skipped_entries=skipped,
        gas=gas,
    )


def parse_feature_flag(data: dict[str, Any]) -> FeatureFlag:
    return FeatureFlag(
        value=bool(data.get("value")),
        reason=data.get("reason") if isinstance(data.get("reason"), str) else None,
    )


def _normalize_vocab(value: Any) -> str | None:
    """Lowercase an open-vocabulary code, passing non-strings through as None."""
    return value.lower() if isinstance(value, str) else None


def _parse_solar_surplus_slot(slot: dict[str, Any]) -> SolarSurplusSlot | None:
    start_time = _as_aware_datetime(slot.get("startTime"))
    if start_time is None:
        return None
    value_raw = slot.get("value")
    try:
        value = float(value_raw) if value_raw is not None else None
    except ValueError, TypeError:
        value = None
    return SolarSurplusSlot(
        start_time=start_time,
        value=value,
        level=_normalize_vocab(slot.get("level")),
    )


def _parse_solar_surplus_day(day: dict[str, Any]) -> SolarSurplusDay:
    slots = _parse_items(day.get("details"), _parse_solar_surplus_slot, "solar surplus")
    return SolarSurplusDay(
        forecast_date=_as_date(day.get("forecastDate")),
        forecast_creation_date=_as_aware_datetime(day.get("forecastCreationDate")),
        inference_key=_normalize_vocab(day.get("inferenceKey")),
        level=_normalize_vocab(day.get("level")),
        details=tuple(slots),
    )


def parse_solar_surplus_forecasts(data: dict[str, Any]) -> SolarSurplusForecasts:
    days, skipped = _parse_items_counted(
        data.get("forecasts"), _parse_solar_surplus_day, "solar surplus"
    )
    return SolarSurplusForecasts(forecasts=tuple(days), skipped_entries=skipped)


_TOU_DIRECTION_PREFIX = re.compile(r"(?:^|_)(?:OFFTAKE|INJECTION)_")
_TOU_SLOT_CODE_ALIASES = {"HIGH_LOAD_HOURS": "PEAK", "LOW_LOAD_HOURS": "OFFPEAK"}


def _canonicalise_slot_code(raw: str) -> str:
    """Strip any OFFTAKE_/INJECTION_ prefix, alias-map, then lowercase."""
    upper = raw.upper()
    match = _TOU_DIRECTION_PREFIX.search(upper)
    if match is not None:
        upper = upper[match.end() :]
    return _TOU_SLOT_CODE_ALIASES.get(upper, upper).lower()


def _parse_tou_slot(s: dict[str, Any]) -> TouSlot | None:
    start_time = s.get("startTime")
    end_time = s.get("endTime")
    slot_code = s.get("slotCode")
    if (
        not isinstance(start_time, str)
        or not isinstance(end_time, str)
        or not isinstance(slot_code, str)
    ):
        return None
    return TouSlot(
        start_time=start_time,
        end_time=end_time,
        slot_code=_canonicalise_slot_code(slot_code),
        cost_indicator=_as_cost_indicator(s.get("costIndicator")),
    )


def _as_cost_indicator(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_tou_slots(data: Any) -> tuple[TouSlot, ...]:
    return tuple(_parse_items(data, _parse_tou_slot, "TOU slot"))


def _parse_tou_combined_slot(s: dict[str, Any]) -> TouCombinedSlot | None:
    start_time = s.get("startTime")
    end_time = s.get("endTime")
    supplier_code = s.get("supplierSlotCode")
    dgo_tgo_code = s.get("dgoTgoSlotCode")
    if (
        not isinstance(start_time, str)
        or not isinstance(end_time, str)
        or not isinstance(supplier_code, str)
        or not isinstance(dgo_tgo_code, str)
    ):
        return None
    return TouCombinedSlot(
        start_time=start_time,
        end_time=end_time,
        supplier_slot_code=_canonicalise_slot_code(supplier_code),
        dgo_tgo_slot_code=_canonicalise_slot_code(dgo_tgo_code),
        cost_indicator=_as_cost_indicator(s.get("costIndicator")),
    )


def _parse_tou_combined_slots(data: Any) -> tuple[TouCombinedSlot, ...]:
    return tuple(_parse_items(data, _parse_tou_combined_slot, "TOU combined slot"))


def _parse_tou_combined_direction(data: Any) -> TouCombinedDirectionSchedule | None:
    if not isinstance(data, dict):
        return None
    return TouCombinedDirectionSchedule(
        monday=_parse_tou_combined_slots(data.get("monday")),
        tuesday=_parse_tou_combined_slots(data.get("tuesday")),
        wednesday=_parse_tou_combined_slots(data.get("wednesday")),
        thursday=_parse_tou_combined_slots(data.get("thursday")),
        friday=_parse_tou_combined_slots(data.get("friday")),
        saturday=_parse_tou_combined_slots(data.get("saturday")),
        sunday=_parse_tou_combined_slots(data.get("sunday")),
    )


def _parse_tou_combined_schedule(data: Any) -> TouCombinedSchedule | None:
    if not isinstance(data, dict):
        return None
    return TouCombinedSchedule(
        supplier_active_configuration_id=_as_str_or_none(data.get("supplierActiveConfigurationId")),
        dgo_tgo_active_configuration_id=_as_str_or_none(data.get("dgoTgoActiveConfigurationId")),
        offtake=_parse_tou_combined_direction(data.get("offtake")),
        injection=_parse_tou_combined_direction(data.get("injection")),
    )


def _derive_optimal_slot_code(
    direction: Literal["offtake", "injection"],
    slots_by_weekday: Iterable[tuple[TouSlot, ...]],
) -> str | None:
    """Pick the week-wide cheapest (offtake) or dearest (injection) slot code by costIndicator."""
    ranked = [s for day in slots_by_weekday for s in day if s.cost_indicator is not None]
    if not ranked:
        return None
    picker = min if direction == "offtake" else max
    return picker(ranked, key=lambda s: (s.cost_indicator, s.slot_code)).slot_code


def _parse_tou_direction(
    data: Any, direction: Literal["offtake", "injection"]
) -> TouDirectionSchedule | None:
    if not isinstance(data, dict):
        return None
    weekdays = (
        _parse_tou_slots(data.get("monday")),
        _parse_tou_slots(data.get("tuesday")),
        _parse_tou_slots(data.get("wednesday")),
        _parse_tou_slots(data.get("thursday")),
        _parse_tou_slots(data.get("friday")),
        _parse_tou_slots(data.get("saturday")),
        _parse_tou_slots(data.get("sunday")),
    )
    wire_optimal = data.get("optimalTimeslotCode")
    optimal = (
        _canonicalise_slot_code(wire_optimal)
        if isinstance(wire_optimal, str) and wire_optimal
        else _derive_optimal_slot_code(direction, weekdays)
    )
    return TouDirectionSchedule(
        optimal_timeslot_code=optimal,
        monday=weekdays[0],
        tuesday=weekdays[1],
        wednesday=weekdays[2],
        thursday=weekdays[3],
        friday=weekdays[4],
        saturday=weekdays[5],
        sunday=weekdays[6],
    )


def _parse_tou_schedule(data: Any) -> TouSchedule | None:
    if not isinstance(data, dict):
        return None
    config_id = data.get("activeConfigurationId")
    return TouSchedule(
        active_configuration_id=config_id if isinstance(config_id, str) else None,
        offtake=_parse_tou_direction(data.get("offtake"), "offtake"),
        injection=_parse_tou_direction(data.get("injection"), "injection"),
    )


def _parse_tou_grid_meter(meter: Any) -> TouGridMeterSchedule | None:
    if not isinstance(meter, dict):
        return None
    grid_meter_number = meter.get("gridMeterNumber")
    exclusive_night = meter.get("exclusiveNightMeter")
    return TouGridMeterSchedule(
        grid_meter_number=grid_meter_number if isinstance(grid_meter_number, str) else None,
        exclusive_night_meter=exclusive_night if isinstance(exclusive_night, bool) else None,
        supplier=_parse_tou_schedule(meter.get("supplierSchedule")),
        dgo_tgo=_parse_tou_schedule(meter.get("dgoTgoSchedule")),
        combined=_parse_tou_combined_schedule(meter.get("combinedSchedule")),
    )


def _parse_tou_schedule_item(item: dict[str, Any]) -> TouScheduleItem | None:
    ean = item.get("eanWithSuffix")
    if not isinstance(ean, str):
        return None
    meters = tuple(
        _parse_items(
            item.get("gridMeterTimeOfUseSchedules"), _parse_tou_grid_meter, "TOU grid meter"
        )
    )
    return TouScheduleItem(ean_with_suffix=ean, grid_meter_schedules=meters)


def parse_tou_schedules(data: dict[str, Any]) -> TouSchedulesResponse:
    items, skipped = _parse_items_counted(
        data.get("items"), _parse_tou_schedule_item, "TOU schedule"
    )
    return TouSchedulesResponse(items=tuple(items), skipped_entries=skipped)


def _parse_usage_tou_parts(
    data: Any, slot_code_key: str, *, value_key: str
) -> tuple[UsageTouPart, ...]:
    def _parse_one(part: dict[str, Any]) -> UsageTouPart | None:
        slot_code = _as_str_or_none(part.get(slot_code_key))
        if slot_code is None:
            return None
        return UsageTouPart(slot_code=slot_code, value=_as_float(part.get(value_key)))

    return tuple(_parse_items(data, _parse_one, "usage TOU part"))


def _parse_usage_tou_cross_parts(data: Any, *, value_key: str) -> tuple[UsageTouCrossPart, ...]:
    """Parse the joint ``parts`` list, keeping both slot codes lossless and distinct."""

    def _parse_one(part: dict[str, Any]) -> UsageTouCrossPart | None:
        supplier_code = _as_str_or_none(part.get("supplierTimeOfUseTimeSlotCode"))
        distribution_code = _as_str_or_none(part.get("distributionTimeOfUseTimeSlotCode"))
        if supplier_code is None or distribution_code is None:
            return None
        return UsageTouCrossPart(
            supplier_slot_code=supplier_code,
            distribution_slot_code=distribution_code,
            value=_as_float(part.get(value_key)),
        )

    return tuple(_parse_items(data, _parse_one, "usage TOU cross part"))


def _parse_usage_energy_direction(data: Any) -> UsageDirectionBreakdown | None:
    if not isinstance(data, dict):
        return None
    sum_raw = data.get("kWhSum")
    return UsageDirectionBreakdown(
        kwh_sum=_as_float(sum_raw) if sum_raw is not None else None,
        parts=_parse_usage_tou_cross_parts(data.get("parts"), value_key="kWh"),
        supplier_parts=_parse_usage_tou_parts(
            data.get("supplierParts"), "timeOfUseTimeSlotCode", value_key="kWh"
        ),
        distribution_parts=_parse_usage_tou_parts(
            data.get("distributionParts"), "timeOfUseTimeSlotCode", value_key="kWh"
        ),
    )


def _parse_usage_cost_direction(data: Any) -> UsageDirectionBreakdown | None:
    if not isinstance(data, dict):
        return None
    sum_raw = data.get("amountSum")
    return UsageDirectionBreakdown(
        amount_sum=_as_float(sum_raw) if sum_raw is not None else None,
        parts=_parse_usage_tou_cross_parts(data.get("parts"), value_key="amount"),
        supplier_parts=_parse_usage_tou_parts(
            data.get("supplierParts"), "timeOfUseTimeSlotCode", value_key="amount"
        ),
        distribution_parts=_parse_usage_tou_parts(
            data.get("distributionParts"), "timeOfUseTimeSlotCode", value_key="amount"
        ),
    )


def _parse_usage_electricity_energy(data: Any) -> UsageElectricityBreakdown | None:
    if not isinstance(data, dict):
        return None
    return UsageElectricityBreakdown(
        offtake=_parse_usage_energy_direction(data.get("offtake")),
        injection=_parse_usage_energy_direction(data.get("injection")),
        netto=_as_float_or_none(data.get("netto")),
    )


def _parse_usage_electricity_costs(data: Any) -> UsageElectricityBreakdown | None:
    if not isinstance(data, dict):
        return None
    return UsageElectricityBreakdown(
        offtake=_parse_usage_cost_direction(data.get("offtake")),
        injection=_parse_usage_cost_direction(data.get("injection")),
        netto=_as_float_or_none(data.get("netto")),
    )


def _usage_electricity_block(data: Any) -> Any:
    return data.get("electricity") if isinstance(data, dict) else None


def _usage_cost_value(data: Any, key: str) -> float | None:
    return _as_float_or_none(data.get(key)) if isinstance(data, dict) else None


def _parse_usage_gas(energy: Any, costs: Any) -> GasUsage | None:
    gas_raw = energy.get("gas") if isinstance(energy, dict) else None
    if not isinstance(gas_raw, dict):
        return None
    return GasUsage(kwh=_as_float(gas_raw.get("kWh")), cost=_usage_cost_value(costs, "gas"))


def _parse_usage_item(raw: dict[str, Any]) -> UsageItem | None:
    start = _as_aware_datetime(raw.get("start"))
    end = _as_aware_datetime(raw.get("end"))
    if start is None or end is None:
        return None
    electricity = None
    energy = raw.get("energy")
    elec = _usage_electricity_block(energy)
    if isinstance(elec, dict):
        offtake = elec.get("offtake")
        injection = elec.get("injection")
        electricity = ElectricityUsage(
            offtake_kwh=_as_float(offtake.get("kWhSum") if isinstance(offtake, dict) else 0),
            injection_kwh=_as_float(injection.get("kWhSum") if isinstance(injection, dict) else 0),
            netto_kwh=_as_float(elec.get("netto")),
        )
    costs = raw.get("costs")
    simulated_energy = raw.get("simulatedEnergy")
    simulated_costs = raw.get("simulatedCosts")
    return UsageItem(
        start=start,
        end=end,
        partial_data=bool(raw.get("partialData", False)),
        electricity=electricity,
        gas=_parse_usage_gas(energy, costs),
        energy=_parse_usage_electricity_energy(elec),
        costs=_parse_usage_electricity_costs(_usage_electricity_block(costs)),
        simulated_energy=_parse_usage_electricity_energy(
            _usage_electricity_block(simulated_energy)
        ),
        simulated_costs=_parse_usage_electricity_costs(_usage_electricity_block(simulated_costs)),
        gas_and_electricity_cost=_usage_cost_value(costs, "gasAndElectricitySum"),
        simulated_gas=_parse_usage_gas(simulated_energy, simulated_costs),
        simulated_gas_and_electricity_cost=_usage_cost_value(
            simulated_costs, "gasAndElectricitySum"
        ),
    )


def parse_usage_details(data: dict[str, Any]) -> UsageDetailsResponse:
    items, skipped = _parse_items_counted(data.get("items"), _parse_usage_item, "usage")
    total_raw = data.get("total")
    total = _parse_usage_item(total_raw) if isinstance(total_raw, dict) else None
    return UsageDetailsResponse(items=tuple(items), total=total, skipped_entries=skipped)


def _parse_metering_configuration(sub: Any) -> MeteringConfiguration | None:
    if not isinstance(sub, dict):
        return None
    return MeteringConfiguration(
        metering_method_frequency=_as_str_or_none(sub.get("meteringMethodFrequency")),
        metering_method_type=_as_str_or_none(sub.get("meteringMethodType")),
        metering_reads_for_information=_as_str_or_none(sub.get("meteringReadsForInformation")),
        register_type_configuration=_as_str_or_none(sub.get("registerTypeConfiguration")),
        smart_meter_regime=_as_str_or_none(sub.get("smartMeterRegime")),
        supplier_billing_frequency=_as_str_or_none(sub.get("supplierBillingFrequency")),
    )


def _parse_service_point_installation(sub: Any) -> ServicePointInstallation | None:
    if not isinstance(sub, dict):
        return None
    return ServicePointInstallation(
        installation_id=_as_str_or_none(sub.get("installationId")),
        rtp_component_id=_as_str_or_none(sub.get("RTPComponentID")),
        budget_meter=bool(sub.get("budgetMeter")),
        service_component=_as_str_or_none(sub.get("serviceComponent")),
        metering_configuration=_parse_metering_configuration(sub.get("meteringConfiguration")),
    )


def _parse_service_point_market_details(sub: Any) -> ServicePointMarketDetails | None:
    if not isinstance(sub, dict):
        return None
    return ServicePointMarketDetails(
        dgo=_as_str_or_none(sub.get("dgo")),
        grid=_as_str_or_none(sub.get("grid")),
        installation=_parse_service_point_installation(sub.get("installation")),
    )


def parse_service_point(data: dict[str, Any], requested_ean: str) -> ServicePoint:
    division = _as_str_or_none(data.get("division"))
    if division is None:
        _LOGGER.debug("service point: missing division, energy-type mapping left empty")
    ean_map = {} if division is None else {bare_ean(requested_ean): division}
    return ServicePoint(
        ean_energy_types=MappingProxyType(ean_map),
        ean=_as_str_or_none(data.get("ean")),
        division=division,
        type=_as_str_or_none(data.get("type")),
        charging_station=bool(data.get("chargingStation")),
        premises_id=_as_str_or_none(data.get("premisesId")),
        market_details=_parse_service_point_market_details(data.get("marketDetails")),
    )


def _parse_measured_window(sub: Any) -> MeasuredDataWindow | None:
    if not isinstance(sub, dict):
        return None
    return MeasuredDataWindow(
        available=bool(sub.get("available")),
        start=_as_aware_datetime(sub.get("start")),
        end=_as_aware_datetime(sub.get("end")),
    )


def _parse_data_availability(sub: Any) -> DataAvailability | None:
    measured = sub.get("measured") if isinstance(sub, dict) else None
    if not isinstance(measured, dict):
        return None
    return DataAvailability(
        quarter_hourly=_parse_measured_window(measured.get("quarterHourly")),
        daily=_parse_measured_window(measured.get("daily")),
    )


def _parse_metering_data_source(sub: Any, status_key: str) -> MeteringDataSource | None:
    if not isinstance(sub, dict):
        return None
    return MeteringDataSource(
        active=bool(sub.get("active")),
        applicable=bool(sub.get("applicable")),
        service_start_date=_as_aware_datetime(sub.get("serviceStartDate")),
        service_end_date=_as_aware_datetime(sub.get("serviceEndDate")),
        status=_as_str_or_none(sub.get(status_key)),
        type=_as_str_or_none(sub.get("type")),
        upgradable_to=_as_str_or_none(sub.get("upgradableTo")),
    )


def _parse_metering_data_sources(sub: Any) -> MeteringDataSources | None:
    if not isinstance(sub, dict):
        return None
    return MeteringDataSources(
        p1=_parse_metering_data_source(sub.get("p1"), "dongleStatus"),
        p4=_parse_metering_data_source(sub.get("p4"), "mandateStatus"),
        billing=_parse_metering_data_source(sub.get("billing"), "status"),
        meter_reads=_parse_metering_data_source(sub.get("meterReads"), "status"),
        imv=_parse_metering_data_source(sub.get("imv"), "status"),
    )


def _parse_metering_service_point(item: dict[str, Any]) -> MeteringServicePoint | None:
    ean = _as_str_or_none(item.get("ean"))
    if ean is None:
        return None
    return MeteringServicePoint(
        ean=ean,
        ean_with_suffix=_as_str_or_none(item.get("eanWithSuffix")),
        division=_as_str_or_none(item.get("division")),
        metering_method_type=_as_str_or_none(item.get("meteringMethodType")),
        has_solar=bool(item.get("hasSolar")),
        region=_as_str_or_none(item.get("region")),
        dgo=_as_str_or_none(item.get("dgo")),
        data_availability=_parse_data_availability(item.get("dataAvailability")),
        data_sources=_parse_metering_data_sources(item.get("dataSources")),
    )


def parse_service_points(data: dict[str, Any]) -> ServicePointsResponse:
    items, skipped = _parse_items_counted(
        data.get("items"), _parse_metering_service_point, "service point"
    )
    return ServicePointsResponse(items=tuple(items), skipped_entries=skipped)


def _parse_meter_register_read(raw: dict[str, Any]) -> MeterRegisterRead | None:
    index_read = raw.get("indexRead")
    if isinstance(index_read, bool) or not isinstance(index_read, int | float):
        return None
    return MeterRegisterRead(
        meter_number=_as_str_or_none(raw.get("meterNumber")),
        register_number=_as_str_or_none(raw.get("registerNumber")),
        index_read=float(index_read),
        unit=_as_str_or_none(raw.get("unit")),
        register_type=_as_str_or_none(raw.get("registerType")),
        direction=_as_str_or_none(raw.get("direction")),
        active=bool(raw.get("active")),
        minimum_index_read_range=_as_float_or_none(raw.get("minimumIndexReadRange")),
        maximum_index_read_range=_as_float_or_none(raw.get("maximumIndexReadRange")),
    )


def _parse_meter_read(item: dict[str, Any]) -> MeterRead | None:
    ean = _as_str_or_none(item.get("ean"))
    read_date = _as_date(item.get("meterReadDate"))
    if ean is None or read_date is None:
        return None
    raw_registers = item.get("registers")
    registers = _parse_items(raw_registers, _parse_meter_register_read, "meter register")
    if raw_registers and not registers:
        return None
    return MeterRead(
        ean=ean,
        read_date=read_date,
        ean_with_suffix=_as_str_or_none(item.get("eanWithSuffix")),
        division=_as_str_or_none(item.get("division")),
        origin=_as_str_or_none(item.get("origin")),
        registers=tuple(registers),
    )


def parse_meter_reads(data: dict[str, Any]) -> MeterReadsResponse:
    items, skipped = _parse_items_counted(data.get("items"), _parse_meter_read, "meter read")
    return MeterReadsResponse(items=tuple(items), skipped_entries=skipped)


def _parse_payment_slice(raw: dict[str, Any]) -> PaymentSlice | None:
    payment_date = _as_date(raw.get("date"))
    if payment_date is None:
        return None
    return PaymentSlice(payment_date=payment_date, status=_as_str_or_none(raw.get("status")))


def parse_monthly_billed_budget(data: dict[str, Any]) -> MonthlyBilledBudget:
    payments, skipped = _parse_items_counted(
        data.get("payments"), _parse_payment_slice, "budget payment"
    )
    return MonthlyBilledBudget(
        start_date=_as_date(data.get("from")),
        end_date=_as_date(data.get("to")),
        already_used_amount=_as_float_or_none(data.get("alreadyUsedAmount")),
        already_used_amount_ratio=_as_float_or_none(data.get("alreadyUsedAmountRatio")),
        already_paid_amount=_as_float_or_none(data.get("alreadyPaidAmount")),
        expected_cost_amount=_as_float_or_none(data.get("expectedCostAmount")),
        expected_month_cost_amount=_as_float_or_none(data.get("expectedMonthCostAmount")),
        current_month_cost_amount=_as_float_or_none(data.get("currentMonthCostAmount")),
        last_invoiced_amount=_as_float_or_none(data.get("lastInvoicedAmount")),
        payments=tuple(payments),
        skipped_entries=skipped,
    )


def parse_billing_period_usage(data: dict[str, Any]) -> BillingPeriodUsage:
    return BillingPeriodUsage(
        start_date=_as_date(data.get("startDate")),
        end_date=_as_date(data.get("endDate")),
        expected_year_invoice=_as_float_or_none(data.get("expectedYearInvoice")),
        used_amount=_as_float_or_none(data.get("usedAmount")),
        used_amount_ratio=_as_float_or_none(data.get("usedAmountRatio")),
        used_amount_failure_reason=_as_str_or_none(data.get("usedAmountFailureReason")),
    )


def _parse_bbp_proposal_factor(raw: dict[str, Any]) -> BudgetBillingPlanProposalFactor:
    return BudgetBillingPlanProposalFactor(
        event=_as_str_or_none(raw.get("event")),
        weight=_as_float_or_none(raw.get("weight")),
        change_type=_as_str_or_none(raw.get("changeType")),
    )


def _parse_bbp_proposal(sub: Any) -> tuple[BudgetBillingPlanProposal | None, int]:
    if not isinstance(sub, dict):
        return None, 0
    factors, skipped = _parse_items_counted(
        sub.get("evaluationContext"), _parse_bbp_proposal_factor, "proposal factor"
    )
    proposal = BudgetBillingPlanProposal(
        change_type=_as_str_or_none(sub.get("changeType")),
        simulation_date=_as_date(sub.get("simulationDate")),
        proposed_amount=_as_float_or_none(sub.get("proposedAmount")),
        significant=bool(sub.get("significant")),
        outlier=bool(sub.get("outlier")),
        evaluation_context=tuple(factors),
    )
    return proposal, skipped


def _parse_bbp_limits(sub: Any) -> BudgetBillingPlanLimits | None:
    if not isinstance(sub, dict):
        return None
    return BudgetBillingPlanLimits(
        lower_limit=_as_float_or_none(sub.get("lowerLimit")),
        upper_limit=_as_float_or_none(sub.get("upperLimit")),
        exceptional_limit=_as_float_or_none(sub.get("exceptionalLimit")),
    )


def _parse_budget_billing_plan(sub: Any) -> tuple[BudgetBillingPlan | None, int]:
    if not isinstance(sub, dict):
        return None, 0
    raw_slices = sub.get("paymentSlices") or sub.get("slices")
    slices, skipped = _parse_items_counted(raw_slices, _parse_payment_slice, "payment slice")
    plan = BudgetBillingPlan(
        current_amount=_as_float_or_none(sub.get("currentAmount")),
        monthly_amount=_as_float_or_none(sub.get("monthlyAmount")),
        billing_cycle=_as_str_or_none(sub.get("billingCycle")),
        remaining_slices=_as_int_or_none(sub.get("remainingSlices")),
        amount_paid=_as_float_or_none(sub.get("amountPaid")),
        billing_cycle_total=_as_float_or_none(sub.get("billingCycleTotal")),
        next_partial_invoice_date=_as_date(sub.get("nextPartialInvoiceDate")),
        payment_slices=tuple(slices),
    )
    return plan, skipped


def _parse_bbp_contract_period(
    raw: dict[str, Any],
) -> tuple[BudgetBillingPlanContractPeriod, int]:
    plan, plan_skipped = _parse_budget_billing_plan(raw.get("budgetBillingPlan"))
    proposal, proposal_skipped = _parse_bbp_proposal(raw.get("bbpProposal"))
    period = BudgetBillingPlanContractPeriod(
        contract_id=_as_str_or_none(raw.get("contractId")),
        energy_contract_configuration_id=_as_str_or_none(raw.get("energyContractConfigurationId")),
        division=_as_str_or_none(raw.get("division")),
        start_date=_as_date(raw.get("startDate")),
        end_date=_as_date(raw.get("endDate")),
        is_contract_for_chm=bool(raw.get("isContractForCHM")),
        is_contract_for_bana=bool(raw.get("isContractForBANA")),
        is_contract_for_uncommon_registers=bool(raw.get("isContractForUncommonRegisters")),
        plan=plan,
        plan_updatable=bool(raw.get("budgetBillingPlanUpdatable")),
        plan_updatable_information=_as_str_or_none(
            raw.get("budgetBillingPlanUpdatableInformation")
        ),
        update_limits=_parse_bbp_limits(raw.get("bbpUpdateLimits")),
        proposal=proposal,
        proposal_evaluation_status=_as_str_or_none(raw.get("bbpProposalEvaluationStatus")),
        expected_periodic_invoice_amount=_as_float_or_none(
            raw.get("expectedPeriodicInvoiceAmount")
        ),
        remaining_amount=_as_float_or_none(raw.get("remainingAmount")),
        has_insufficient_history_after_move=bool(raw.get("hasInsufficientHistoryAfterMove")),
        has_meter_replacement=bool(raw.get("hasMeterReplacement")),
    )
    return period, plan_skipped + proposal_skipped


def parse_budget_billing_plan_details(data: dict[str, Any]) -> BudgetBillingPlanDetails:
    plan, plan_skipped = _parse_budget_billing_plan(data.get("budgetBillingPlan"))
    proposal, proposal_skipped = _parse_bbp_proposal(data.get("bbpProposal"))
    periods, periods_skipped = _parse_items_counted(
        data.get("periodDetailsPerContract"),
        _parse_bbp_contract_period,
        "budget billing plan contract period",
    )
    nested_skipped = sum(skipped for _period, skipped in periods)
    return BudgetBillingPlanDetails(
        business_agreement_id=_as_str_or_none(data.get("businessAgreementId")),
        start_date=_as_date(data.get("startDate")),
        end_date=_as_date(data.get("endDate")),
        plan=plan,
        plan_updatable=bool(data.get("budgetBillingPlanUpdatable")),
        plan_updatable_information=_as_str_or_none(
            data.get("budgetBillingPlanUpdatableInformation")
        ),
        update_limits=_parse_bbp_limits(data.get("bbpUpdateLimits")),
        proposal=proposal,
        proposal_evaluation_status=_as_str_or_none(data.get("bbpProposalEvaluationStatus")),
        expected_periodic_invoice_amount=_as_float_or_none(
            data.get("expectedPeriodicInvoiceAmount")
        ),
        remaining_amount=_as_float_or_none(data.get("remainingAmount")),
        has_different_billing_cycle=bool(data.get("hasDifferentBillingCycle")),
        has_different_invoice_frequencies=bool(data.get("hasDifferentInvoiceFrequencies")),
        has_unaligned_billing_periods=bool(data.get("hasUnalignedBillingPeriods")),
        has_chm=bool(data.get("hasCHM")),
        has_bana=bool(data.get("hasBANA")),
        has_uncommon_registers=bool(data.get("hasUncommonRegisters")),
        has_insufficient_history_after_move=bool(data.get("hasInsufficientHistoryAfterMove")),
        has_meter_replacement=bool(data.get("hasMeterReplacement")),
        contract_periods=tuple(period for period, _skipped in periods),
        skipped_entries=plan_skipped + proposal_skipped + periods_skipped + nested_skipped,
    )


def parse_happy_hour_eligibility(data: dict[str, Any]) -> HappyHourEligibility:
    raw_reasons = data.get("reasons")
    candidates = raw_reasons if isinstance(raw_reasons, list) else []
    reasons = tuple(reason for reason in candidates if isinstance(reason, str) and reason)
    skipped = len(candidates) - len(reasons)
    if skipped:
        _LOGGER.debug("skipped %d malformed happy hour eligibility reason entries", skipped)
    return HappyHourEligibility(
        eligible=_as_bool_or_none(data.get("eligible")),
        reasons=reasons,
        skipped_entries=skipped,
    )


def parse_happy_hour_service_status(data: dict[str, Any]) -> HappyHourServiceStatus:
    return HappyHourServiceStatus(
        status=_as_str_or_none(data.get("status")),
        status_date=_as_aware_datetime(data.get("statusDate")),
    )

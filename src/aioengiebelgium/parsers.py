# Copyright (c) 2026 Daan Vervacke
# SPDX-License-Identifier: MIT

import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from itertools import pairwise
from types import MappingProxyType
from typing import Any, Literal

from .const import EPEX_MWH_TO_KWH
from .models import (
    AccountBalance,
    AccountRelation,
    BillingDetails,
    BillingOverview,
    BusinessAgreement,
    ConsumptionAddress,
    ContractInfo,
    CustomerAccount,
    CustomerAccountRelations,
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
    HappyHourEvent,
    HappyHourMonthData,
    HappyHourMonthReport,
    HappyHourWindow,
    MeteringConfiguration,
    MonthlyPeaks,
    MonthReportHistoryEntry,
    Peak,
    PricePeriod,
    PriceSlot,
    PricesResponse,
    ProductConfiguration,
    ServicePoint,
    ServicePointInstallation,
    ServicePointMarketDetails,
    SimulatedCost,
    SimulatedCostFlow,
    SimulatedEnergy,
    SimulatedEnergyFlow,
    SolarSurplusDay,
    SolarSurplusForecasts,
    SolarSurplusSlot,
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


def _as_str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_aware_datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime string, returning None for naive or invalid input."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed


def _parse_items[T](
    data: object,
    item_parser: Callable[[dict[str, Any]], T | None],
    label: str,
) -> list[T]:
    """Parse a list defensively."""
    if not isinstance(data, list):
        return []
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
    return items


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
    accounts = _parse_items(data.get("items"), _parse_account_relation, "account relation")
    return CustomerAccountRelations(accounts=tuple(accounts))


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
        valid_from=_as_str(period.get("from")),
        valid_to=_as_str(period.get("to")),
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
    return PricesResponse(items=tuple(_parse_items(data.get("items"), _parse_ean_prices, "price")))


def _parse_energy_contract(item: dict[str, Any]) -> EnergyContract:
    pc_raw = item.get("productConfiguration")
    pc = (
        ProductConfiguration(
            energy_product=pc_raw.get("energyProduct"),
            type=pc_raw.get("type"),
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
    return EnergyContractsResponse(
        items=tuple(_parse_items(data.get("items"), _parse_energy_contract, "energy contract"))
    )


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


def parse_monthly_peaks(data: dict[str, Any]) -> MonthlyPeaks:
    monthly_raw = data.get("peakOfTheMonth")
    monthly = _parse_peak(monthly_raw) if isinstance(monthly_raw, dict) else None
    daily = _parse_items(data.get("dailyPeaks"), _parse_peak, "daily peak")
    return MonthlyPeaks(
        year=_as_int(data.get("year")),
        month=_as_int(data.get("month")),
        peak_of_the_month=monthly,
        daily_peaks=tuple(daily),
    )


def _parse_financial_transaction(tx: dict[str, Any]) -> FinancialTransaction:
    due_date_raw = tx.get("dueDate")
    return FinancialTransaction(
        type=tx.get("type"),
        due_amount=_as_float(tx.get("dueAmount")),
        open_amount=_as_float(tx.get("openAmount")),
        due_date=due_date_raw if isinstance(due_date_raw, str) else None,
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
    raw_slots = _parse_items(data.get("timeSeries"), _parse_epex_entry, "EPEX")

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

    slots_list = [
        EpexSlot(
            start=start,
            end=starts[i + 1] if i + 1 < len(starts) else start + observed,
            value_eur_per_kwh=value / EPEX_MWH_TO_KWH,
        )
        for i, (start, value) in enumerate(raw_slots)
    ]

    pub_time = _as_aware_datetime(data.get("publicationTime"))

    market_date = data.get("marketDate")

    return EpexPayload(
        slots=tuple(slots_list),
        publication_time=pub_time,
        market_date=market_date if isinstance(market_date, str) else None,
        slot_duration=observed,
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
    return HappyHourEvent(windows=tuple(windows))


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
    year_month = entry.get("yearMonth")
    if not isinstance(year_month, str) or not year_month:
        return None
    hh = entry.get("happyHour")
    return MonthReportHistoryEntry(
        year_month=year_month,
        happy_hour=_parse_happy_hour_data(hh) if isinstance(hh, dict) else None,
        electricity_offtake=_parse_energy_cost_pair(entry.get("electricityOfftake")),
        electricity_injection=_parse_energy_cost_pair(entry.get("electricityInjection")),
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
    )


def parse_happy_hour_month_report(data: dict[str, Any]) -> HappyHourMonthReport:
    current = None
    simulated_energy = None
    simulated_cost = None
    month_raw = data.get("month")
    if isinstance(month_raw, dict):
        hh = month_raw.get("happyHour")
        if isinstance(hh, dict):
            current = _parse_happy_hour_data(hh)
        simulated_energy = _parse_simulated_energy(month_raw.get("simulatedEnergy"))
        simulated_cost = _parse_simulated_cost(month_raw.get("simulatedCost"))

    history = _parse_items(
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
        forecast_date=_as_str(day.get("forecastDate")),
        forecast_creation_date=_as_aware_datetime(day.get("forecastCreationDate")),
        inference_key=_normalize_vocab(day.get("inferenceKey")),
        level=_normalize_vocab(day.get("level")),
        details=tuple(slots),
    )


def parse_solar_surplus_forecasts(data: dict[str, Any]) -> SolarSurplusForecasts:
    days = _parse_items(data.get("forecasts"), _parse_solar_surplus_day, "solar surplus")
    return SolarSurplusForecasts(forecasts=tuple(days))


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
    cost_raw = s.get("costIndicator")
    cost_indicator = (
        cost_raw if isinstance(cost_raw, int) and not isinstance(cost_raw, bool) else None
    )
    return TouSlot(
        start_time=start_time,
        end_time=end_time,
        slot_code=_canonicalise_slot_code(slot_code),
        cost_indicator=cost_indicator,
    )


def _parse_tou_slots(data: Any) -> tuple[TouSlot, ...]:
    return tuple(_parse_items(data, _parse_tou_slot, "TOU slot"))


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
    items = _parse_items(data.get("items"), _parse_tou_schedule_item, "TOU schedule")
    return TouSchedulesResponse(items=tuple(items))


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
    )


def _parse_usage_electricity_costs(data: Any) -> UsageElectricityBreakdown | None:
    if not isinstance(data, dict):
        return None
    return UsageElectricityBreakdown(
        offtake=_parse_usage_cost_direction(data.get("offtake")),
        injection=_parse_usage_cost_direction(data.get("injection")),
    )


def _usage_electricity_block(data: Any) -> Any:
    return data.get("electricity") if isinstance(data, dict) else None


def _parse_usage_item(raw: dict[str, Any]) -> UsageItem | None:
    start = _as_aware_datetime(raw.get("start"))
    end = _as_aware_datetime(raw.get("end"))
    if start is None or end is None:
        return None
    electricity = None
    gas = None
    energy = raw.get("energy")
    if isinstance(energy, dict):
        elec = energy.get("electricity")
        if isinstance(elec, dict):
            offtake = elec.get("offtake")
            injection = elec.get("injection")
            electricity = ElectricityUsage(
                offtake_kwh=_as_float(offtake.get("kWhSum") if isinstance(offtake, dict) else 0),
                injection_kwh=_as_float(
                    injection.get("kWhSum") if isinstance(injection, dict) else 0
                ),
                netto_kwh=_as_float(elec.get("netto")),
            )
        gas_raw = energy.get("gas")
        if isinstance(gas_raw, dict):
            gas = GasUsage(kwh=_as_float(gas_raw.get("kWh")))
    return UsageItem(
        start=start,
        end=end,
        partial_data=bool(raw.get("partialData", False)),
        electricity=electricity,
        gas=gas,
        energy=_parse_usage_electricity_energy(_usage_electricity_block(energy)),
        costs=_parse_usage_electricity_costs(_usage_electricity_block(raw.get("costs"))),
        simulated_energy=_parse_usage_electricity_energy(
            _usage_electricity_block(raw.get("simulatedEnergy"))
        ),
        simulated_costs=_parse_usage_electricity_costs(
            _usage_electricity_block(raw.get("simulatedCosts"))
        ),
    )


def parse_usage_details(data: dict[str, Any]) -> UsageDetailsResponse:
    items = _parse_items(data.get("items"), _parse_usage_item, "usage")
    total_raw = data.get("total")
    total = _parse_usage_item(total_raw) if isinstance(total_raw, dict) else None
    return UsageDetailsResponse(items=tuple(items), total=total)


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

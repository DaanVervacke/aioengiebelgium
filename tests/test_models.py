"""Tests for the pure dataclass model methods in aioengiebelgium.models."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from aioengiebelgium.models import (
    AccountBalance,
    BillingDetails,
    ConsumptionAddress,
    EnergyContract,
    EnergyContractsResponse,
    EpexPayload,
    EpexSlot,
    FinancialTransaction,
    HappyHourEvent,
    HappyHourWindow,
    ProductConfiguration,
    SolarSurplusDay,
    SolarSurplusForecasts,
    SolarSurplusSlot,
    TouDirectionSchedule,
    TouScheduleItem,
    TouSchedulesResponse,
    TouSlot,
    _parse_hhmm,
)

_BRUSSELS = ZoneInfo("Europe/Brussels")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("06:00", time(6, 0), id="normal"),
        pytest.param("23:59", time(23, 59), id="max_valid"),
        pytest.param("00:00", time(0, 0), id="sentinel"),
    ],
)
def test_parse_hhmm_valid(raw: str, expected: time) -> None:
    assert _parse_hhmm(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("0600", id="no_colon"),
        pytest.param("ab:cd", id="non_integer"),
        pytest.param("25:00", id="hour_out_of_range"),
        pytest.param("06:60", id="minute_out_of_range"),
    ],
)
def test_parse_hhmm_invalid(raw: str) -> None:
    assert _parse_hhmm(raw) is None


@pytest.mark.parametrize(
    ("duration_minutes", "expected"),
    [
        pytest.param(60, 60.0, id="hourly_slot"),
        pytest.param(15, 15.0, id="quarter_hour_slot"),
    ],
)
def test_epex_slot_duration_minutes(duration_minutes: int, expected: float) -> None:
    start = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    slot = EpexSlot(
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        value_eur_per_kwh=0.05,
    )
    assert slot.duration_minutes == expected


def _epex_slot(start: datetime, *, duration_minutes: int = 60) -> EpexSlot:
    return EpexSlot(
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        value_eur_per_kwh=0.05,
    )


def test_next_slot_boundary_when_now_inside_slot() -> None:
    start = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    payload = EpexPayload(slots=(_epex_slot(start),))
    now = datetime(2026, 5, 4, 12, 30, tzinfo=UTC)
    assert payload.next_slot_boundary(now) == start + timedelta(hours=1)


def test_next_slot_boundary_when_now_before_first_slot() -> None:
    earliest = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    later = datetime(2026, 5, 4, 13, 0, tzinfo=UTC)
    payload = EpexPayload(slots=(_epex_slot(earliest), _epex_slot(later)))
    now = datetime(2026, 5, 4, 11, 30, tzinfo=UTC)
    assert payload.next_slot_boundary(now) == earliest


def test_next_slot_boundary_when_now_after_all_slots() -> None:
    start = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    payload = EpexPayload(slots=(_epex_slot(start),))
    now = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    assert payload.next_slot_boundary(now) is None


def test_next_slot_boundary_handles_gap_between_slots() -> None:
    covering = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    after_gap = datetime(2026, 5, 4, 14, 0, tzinfo=UTC)
    payload = EpexPayload(slots=(_epex_slot(covering), _epex_slot(after_gap)))
    now = datetime(2026, 5, 4, 13, 30, tzinfo=UTC)
    assert payload.next_slot_boundary(now) == after_gap


def test_next_slot_boundary_returns_none_for_empty_slots() -> None:
    payload = EpexPayload(slots=())
    now = datetime(2026, 5, 4, 12, 30, tzinfo=UTC)
    assert payload.next_slot_boundary(now) is None


def test_happy_hour_is_active_inside_window() -> None:
    window = HappyHourWindow(
        start=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 14, 0, tzinfo=UTC),
    )
    event = HappyHourEvent(windows=(window,))
    assert event.is_active(datetime(2026, 5, 4, 13, 0, tzinfo=UTC)) is True


def test_happy_hour_is_active_outside_all_windows() -> None:
    window = HappyHourWindow(
        start=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 14, 0, tzinfo=UTC),
    )
    event = HappyHourEvent(windows=(window,))
    assert event.is_active(datetime(2026, 5, 4, 15, 0, tzinfo=UTC)) is False


def test_happy_hour_is_active_between_two_windows() -> None:
    first = HappyHourWindow(
        start=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 13, 0, tzinfo=UTC),
    )
    second = HappyHourWindow(
        start=datetime(2026, 5, 4, 14, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 15, 0, tzinfo=UTC),
    )
    event = HappyHourEvent(windows=(first, second))
    assert event.is_active(datetime(2026, 5, 4, 13, 30, tzinfo=UTC)) is False


def test_happy_hour_is_active_empty_windows() -> None:
    assert HappyHourEvent(windows=()).is_active(datetime(2026, 5, 4, tzinfo=UTC)) is False


def test_happy_hour_is_active_start_inclusive_end_exclusive() -> None:
    window = HappyHourWindow(
        start=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 14, 0, tzinfo=UTC),
    )
    event = HappyHourEvent(windows=(window,))
    assert event.is_active(window.start) is True
    assert event.is_active(window.end) is False


def test_earliest_due_date_returns_earliest_among_open_transactions() -> None:
    details = BillingDetails(
        financial_transactions=(
            FinancialTransaction(open_amount=10.0, due_date="2026-06-15"),
            FinancialTransaction(open_amount=5.0, due_date="2026-05-20"),
            FinancialTransaction(open_amount=20.0, due_date="2026-07-01"),
        ),
    )
    balance = AccountBalance(details=details)
    result = balance.earliest_due_date(_BRUSSELS)
    assert result == datetime(2026, 5, 20, tzinfo=_BRUSSELS)


def test_earliest_due_date_no_open_transactions() -> None:
    details = BillingDetails(
        financial_transactions=(
            FinancialTransaction(open_amount=0.0, due_date="2026-06-15"),
            FinancialTransaction(open_amount=-5.0, due_date="2026-05-20"),
        ),
    )
    balance = AccountBalance(details=details)
    assert balance.earliest_due_date(_BRUSSELS) is None


def test_earliest_due_date_no_details() -> None:
    balance = AccountBalance(details=None)
    assert balance.earliest_due_date(_BRUSSELS) is None


def test_earliest_due_date_skips_none_due_date() -> None:
    balance = AccountBalance(
        details=BillingDetails(
            financial_transactions=(
                FinancialTransaction(open_amount=50.0, due_date=None),
                FinancialTransaction(open_amount=30.0, due_date="2026-02-15"),
            )
        )
    )
    result = balance.earliest_due_date(_BRUSSELS)
    assert result is not None
    assert result.day == 15


def test_earliest_due_date_skips_unparseable_due_date() -> None:
    details = BillingDetails(
        financial_transactions=(
            FinancialTransaction(open_amount=10.0, due_date="not-a-date"),
            FinancialTransaction(open_amount=5.0, due_date="2026-05-20"),
        ),
    )
    balance = AccountBalance(details=details)
    assert balance.earliest_due_date(_BRUSSELS) == datetime(2026, 5, 20, tzinfo=_BRUSSELS)


def test_earliest_due_date_aware_input_converts_instead_of_replacing() -> None:
    details = BillingDetails(
        financial_transactions=(
            FinancialTransaction(open_amount=10.0, due_date="2026-05-20T10:00:00+00:00"),
        ),
    )
    balance = AccountBalance(details=details)
    result = balance.earliest_due_date(_BRUSSELS)
    assert result is not None
    assert result == datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    assert result.hour == 12
    assert result.utcoffset() == timedelta(hours=2)


def _empty_week_schedule(**overrides: tuple[TouSlot, ...]) -> TouDirectionSchedule:
    return TouDirectionSchedule(
        monday=overrides.get("monday", ()),
        tuesday=overrides.get("tuesday", ()),
        wednesday=overrides.get("wednesday", ()),
        thursday=overrides.get("thursday", ()),
        friday=overrides.get("friday", ()),
        saturday=overrides.get("saturday", ()),
        sunday=overrides.get("sunday", ()),
    )


def test_current_slot_normal_case_returns_code_and_end() -> None:
    schedule = _empty_week_schedule(
        monday=(
            TouSlot(start_time="00:00", end_time="06:00", slot_code="offpeak"),
            TouSlot(start_time="06:00", end_time="22:00", slot_code="peak"),
        ),
    )
    now = datetime(2026, 7, 6, 8, 0, tzinfo=_BRUSSELS)
    code, end_dt = schedule.current_slot(now, _BRUSSELS)
    assert code == "peak"
    assert end_dt == datetime(2026, 7, 6, 22, 0, tzinfo=_BRUSSELS)


def test_current_slot_unparseable_times() -> None:
    slot = TouSlot(start_time="bad", end_time="00:00", slot_code="peak")
    schedule = _empty_week_schedule(monday=(slot,))
    now = datetime(2026, 1, 5, 10, 0, tzinfo=_BRUSSELS)
    code, next_transition = schedule.current_slot(now, _BRUSSELS)
    assert code is None
    assert next_transition is None


def test_current_slot_returns_none_when_no_slot_covers_now() -> None:
    schedule = _empty_week_schedule()
    now = datetime(2026, 7, 6, 4, 0, tzinfo=_BRUSSELS)
    assert schedule.current_slot(now, _BRUSSELS) == (None, None)


def test_current_slot_end_of_day_sentinel_rolls_to_next_midnight() -> None:
    schedule = _empty_week_schedule(
        monday=(TouSlot(start_time="22:00", end_time="00:00", slot_code="offpeak"),),
    )
    now = datetime(2026, 7, 6, 23, 0, tzinfo=_BRUSSELS)
    code, end_dt = schedule.current_slot(now, _BRUSSELS)
    assert code == "offpeak"
    assert end_dt == datetime(2026, 7, 7, 0, 0, tzinfo=_BRUSSELS)


def test_current_slot_midnight_wrap_matches_before_and_after_midnight() -> None:
    schedule = _empty_week_schedule(
        monday=(TouSlot(start_time="22:00", end_time="07:00", slot_code="offpeak"),),
    )
    expected_end = datetime(2026, 7, 7, 7, 0, tzinfo=_BRUSSELS)

    before_midnight = datetime(2026, 7, 6, 23, 0, tzinfo=_BRUSSELS)
    code, end_dt = schedule.current_slot(before_midnight, _BRUSSELS)
    assert code == "offpeak"
    assert end_dt == expected_end

    after_midnight = datetime(2026, 7, 7, 6, 0, tzinfo=_BRUSSELS)
    code, end_dt = schedule.current_slot(after_midnight, _BRUSSELS)
    assert code == "offpeak"
    assert end_dt == expected_end


_DST_SCHEDULE = _empty_week_schedule(
    sunday=(
        TouSlot(start_time="02:00", end_time="02:45", slot_code="peak"),
        TouSlot(start_time="02:45", end_time="03:00", slot_code="offpeak"),
    ),
)


def test_current_slot_dst_fallback_fold_zero_resolves_cest_transition() -> None:
    now = datetime(2026, 10, 25, 2, 15, tzinfo=_BRUSSELS, fold=0)
    code, end_dt = _DST_SCHEDULE.current_slot(now, _BRUSSELS)
    assert code == "peak"
    assert end_dt is not None
    assert end_dt.utcoffset() == timedelta(hours=2)
    assert end_dt.astimezone(UTC) == datetime(2026, 10, 25, 0, 45, tzinfo=UTC)


def test_current_slot_dst_fallback_fold_one_resolves_cet_transition() -> None:
    now = datetime(2026, 10, 25, 2, 15, tzinfo=_BRUSSELS, fold=1)
    code, end_dt = _DST_SCHEDULE.current_slot(now, _BRUSSELS)
    assert code == "peak"
    assert end_dt is not None
    assert end_dt.utcoffset() == timedelta(hours=1)
    assert end_dt.astimezone(UTC) == datetime(2026, 10, 25, 1, 45, tzinfo=UTC)


def test_has_multiple_slot_codes_true_for_peak_and_offpeak() -> None:
    schedule = _empty_week_schedule(
        monday=(
            TouSlot(start_time="00:00", end_time="06:00", slot_code="offpeak"),
            TouSlot(start_time="06:00", end_time="00:00", slot_code="peak"),
        ),
    )
    assert schedule.has_multiple_slot_codes() is True


def test_has_multiple_slot_codes_false_for_flat_schedule() -> None:
    schedule = _empty_week_schedule(
        monday=(TouSlot(start_time="00:00", end_time="00:00", slot_code="offpeak"),),
        tuesday=(TouSlot(start_time="00:00", end_time="00:00", slot_code="offpeak"),),
    )
    assert schedule.has_multiple_slot_codes() is False


def test_schedule_for_ean_found() -> None:
    item = TouScheduleItem(ean_with_suffix="541448800000000001_1")
    response = TouSchedulesResponse(items=(item,))
    assert response.schedule_for_ean("541448800000000001_1") is item


def test_schedule_for_ean_not_found() -> None:
    item = TouScheduleItem(ean_with_suffix="541448800000000001_1")
    response = TouSchedulesResponse(items=(item,))
    assert response.schedule_for_ean("missing_1") is None


def _contract(
    *,
    service_point_number: str = "541448800000000001_1",
    division: str = "ELECTRICITY",
    status: str = "ACTIVE",
    energy_product: str | None = "DYNAMIC",
) -> EnergyContract:
    product_configuration = (
        ProductConfiguration(energy_product=energy_product) if energy_product is not None else None
    )
    return EnergyContract(
        business_agreement_number="BA1",
        service_point_number=service_point_number,
        division=division,
        status=status,
        product_configuration=product_configuration,
    )


def test_is_dynamic_true_for_active_dynamic_electricity_contract() -> None:
    response = EnergyContractsResponse(items=(_contract(),))
    assert response.is_dynamic() is True


def test_is_dynamic_false_for_fixed_contracts_only() -> None:
    response = EnergyContractsResponse(items=(_contract(energy_product="FIXED"),))
    assert response.is_dynamic() is False


def test_is_dynamic_false_for_empty_items() -> None:
    assert EnergyContractsResponse(items=()).is_dynamic() is False


def test_is_dynamic_false_when_dynamic_but_not_electricity() -> None:
    response = EnergyContractsResponse(items=(_contract(division="GAS"),))
    assert response.is_dynamic() is False


def test_energy_products_by_ean_skips_none_config() -> None:
    contracts = EnergyContractsResponse(
        items=(
            EnergyContract(
                business_agreement_number="123",
                service_point_number="541448820000000001_ID1",
                division="ELECTRICITY",
                status="ACTIVE",
                product_configuration=None,
            ),
        )
    )
    assert contracts.energy_products_by_ean() == {}


def test_energy_products_by_ean_maps_active_contracts() -> None:
    response = EnergyContractsResponse(
        items=(
            _contract(service_point_number="541448800000000001_1", energy_product="DYNAMIC"),
            _contract(
                service_point_number="541448800000000002_1",
                status="INACTIVE",
                energy_product="FIXED",
            ),
        ),
    )
    assert response.energy_products_by_ean() == {"541448800000000001": "DYNAMIC"}


def test_service_points_by_ean_maps_active_contracts() -> None:
    response = EnergyContractsResponse(
        items=(
            _contract(service_point_number="541448800000000001_1", division="ELECTRICITY"),
            _contract(
                service_point_number="541448800000000002_1",
                status="INACTIVE",
                division="GAS",
            ),
        ),
    )
    assert response.service_points_by_ean() == {"541448800000000001": "ELECTRICITY"}


def test_by_ean_maps_share_bare_ean_key_domain() -> None:
    response = EnergyContractsResponse(
        items=(
            _contract(service_point_number="541448800000000001_1", energy_product="DYNAMIC"),
            _contract(
                service_point_number="541448800000000002_ID1",
                division="GAS",
                energy_product="FIXED",
            ),
        ),
    )
    products = response.energy_products_by_ean()
    service_points = response.service_points_by_ean()
    assert products.keys() == service_points.keys()
    assert set(products) == {"541448800000000001", "541448800000000002"}


def _solar_day(forecast_date: str, day_start: datetime, levels: tuple[str, ...]) -> SolarSurplusDay:
    return SolarSurplusDay(
        forecast_date=forecast_date,
        details=tuple(
            SolarSurplusSlot(
                start_time=day_start + timedelta(hours=i),
                value=0.5,
                level=level,
            )
            for i, level in enumerate(levels)
        ),
    )


def _forecasts() -> SolarSurplusForecasts:
    day1_start = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    day2_start = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)
    return SolarSurplusForecasts(
        forecasts=(
            _solar_day("2026-05-04", day1_start, ("no_data", "low_surplus", "high_surplus")),
            _solar_day("2026-05-05", day2_start, ("no_data", "low_surplus", "high_surplus")),
        ),
    )


def test_all_slots_flattens_all_days() -> None:
    assert len(_forecasts().all_slots()) == 6


def test_slot_covering_returns_slot_inside_interval() -> None:
    forecasts = _forecasts()
    instant = datetime(2026, 5, 4, 10, 30, tzinfo=UTC)
    slot = forecasts.slot_covering(instant)
    assert slot is not None
    assert slot.start_time == datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


def test_slot_covering_returns_none_between_slots() -> None:
    forecasts = SolarSurplusForecasts(
        forecasts=(
            SolarSurplusDay(
                forecast_date="2026-05-04",
                details=(
                    SolarSurplusSlot(
                        start_time=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
                        value=0.1,
                        level="low_surplus",
                    ),
                    SolarSurplusSlot(
                        start_time=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
                        value=0.1,
                        level="low_surplus",
                    ),
                ),
            ),
        ),
    )
    instant = datetime(2026, 5, 4, 11, 30, tzinfo=UTC)
    assert forecasts.slot_covering(instant) is None


def test_slots_for_local_date_filters_by_timezone_offset() -> None:
    tz = ZoneInfo("Europe/Brussels")
    forecasts = SolarSurplusForecasts(
        forecasts=(
            SolarSurplusDay(
                forecast_date="2026-05-04",
                details=(
                    SolarSurplusSlot(
                        start_time=datetime(2026, 5, 4, 23, 0, tzinfo=UTC),
                        value=0.1,
                        level="low_surplus",
                    ),
                    SolarSurplusSlot(
                        start_time=datetime(2026, 5, 5, 10, 0, tzinfo=UTC),
                        value=0.1,
                        level="low_surplus",
                    ),
                ),
            ),
        ),
    )
    result = forecasts.slots_for_local_date(date(2026, 5, 5), tz)
    assert len(result) == 2


def test_next_hour_boundary_returns_earliest_future_start() -> None:
    forecasts = _forecasts()
    now = datetime(2026, 5, 4, 10, 30, tzinfo=UTC)
    assert forecasts.next_hour_boundary(now) == datetime(2026, 5, 4, 11, 0, tzinfo=UTC)


def test_next_hour_boundary_returns_none_when_no_future_slots() -> None:
    forecasts = _forecasts()
    now = datetime(2026, 5, 6, tzinfo=UTC)
    assert forecasts.next_hour_boundary(now) is None


def test_has_solar_true_when_high_surplus_present() -> None:
    assert _forecasts().has_solar() is True


def test_has_solar_false_when_all_no_data() -> None:
    day_start = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    forecasts = SolarSurplusForecasts(
        forecasts=(_solar_day("2026-05-04", day_start, ("no_data", "no_data")),),
    )
    assert forecasts.has_solar() is False


def test_has_solar_false_with_none_level() -> None:
    forecasts = SolarSurplusForecasts(
        forecasts=(
            SolarSurplusDay(
                forecast_date="2026-01-01",
                details=(
                    SolarSurplusSlot(
                        start_time=datetime(2026, 1, 1, 10, tzinfo=_BRUSSELS),
                        level=None,
                    ),
                ),
            ),
        )
    )
    assert forecasts.has_solar() is False


def test_has_solar_false_when_empty() -> None:
    assert SolarSurplusForecasts(forecasts=()).has_solar() is False


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param(
            {
                "street": "Kerkstraat",
                "house_number": "42",
                "postal_code": "1000",
                "city": "Brussel",
            },
            "Kerkstraat 42, 1000 Brussel",
            id="all_fields",
        ),
        pytest.param(
            {"street": "Kerkstraat", "house_number": "42"},
            "Kerkstraat 42",
            id="street_only",
        ),
        pytest.param(
            {"postal_code": "1000", "city": "Brussel"},
            "1000 Brussel",
            id="city_only",
        ),
        pytest.param(
            {"street": "Kerkstraat"},
            "Kerkstraat",
            id="single_field",
        ),
        pytest.param(
            {},
            "",
            id="all_none",
        ),
    ],
)
def test_consumption_address_format(fields: dict[str, str], expected: str) -> None:
    addr = ConsumptionAddress(**fields)
    assert addr.format() == expected


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda now: EpexPayload().next_slot_boundary(now),
            id="epex_next_slot_boundary",
        ),
        pytest.param(
            lambda now: HappyHourEvent().is_active(now),
            id="happy_hour_is_active",
        ),
        pytest.param(
            lambda now: SolarSurplusForecasts().slot_covering(now),
            id="solar_slot_covering",
        ),
        pytest.param(
            lambda now: SolarSurplusForecasts().next_hour_boundary(now),
            id="solar_next_hour_boundary",
        ),
        pytest.param(
            lambda now: TouDirectionSchedule().current_slot(now, _BRUSSELS),
            id="tou_current_slot",
        ),
    ],
)
def test_model_time_helpers_reject_naive_datetime(
    invoke: Callable[[datetime], object],
) -> None:
    naive = datetime(2026, 5, 4, 12, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware datetimes required"):
        invoke(naive)

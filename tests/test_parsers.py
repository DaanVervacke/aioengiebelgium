"""Tests for aioengiebelgium.parsers."""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, timezone
from functools import partial
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from aioengiebelgium.const import (
    ChargeSettingMode,
    ChargingSessionSource,
    ChargingSessionStatus,
    ChargingSessionType,
    SmartChargeOutcomeState,
    VehicleChargeStatus,
    VehiclePolicyState,
)
from aioengiebelgium.models import (
    BillingPeriodUsage,
    ChargeSettingValue,
    ChargingSession,
    ChargingSessionChargeSettings,
    ChargingSessionConsumption,
    ChargingSessionDetails,
    ChargingSessionsPage,
    ChargingSessionsSummary,
    ChargingSessionsSummaryEntry,
    DepartureTimes,
    ElectricVehicle,
    ElectricVehiclesResponse,
    EnergyCostPair,
    EnergyScore,
    EnergyScoreActions,
    EnergyScoreCriteria,
    EnergyScoreDataAvailability,
    EnergyScoreDetails,
    EnergyScoreQuestionAnswer,
    EvService,
    EvServiceInfo,
    GasUsage,
    HappyHourEligibility,
    HappyHourServiceStatus,
    SimulatedCost,
    SimulatedCostFlow,
    SimulatedEnergy,
    SimulatedEnergyFlow,
    SmartChargeOutcome,
    TouCombinedSlot,
    VehicleCapabilities,
    VehicleChargeSettings,
    VehicleChargeState,
    bare_ean,
    ean_with_delivery_point_suffix,
)
from aioengiebelgium.parsers import (
    _normalize_vocab,
    _parse_tou_grid_meter,
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

LoadFixture = Callable[[str], dict[str, Any]]


def test_parse_customer_account_relations_empty() -> None:
    result = parse_customer_account_relations({})
    assert result.accounts == ()


def test_parse_customer_account_relations_missing_items() -> None:
    result = parse_customer_account_relations({"items": [{"admin": True}]})
    assert result.accounts == ()


def test_parse_prices_empty_items() -> None:
    result = parse_prices({"items": []})
    assert result.items == ()


@pytest.mark.parametrize(
    ("from_value", "to_value", "expected_from", "expected_to"),
    [
        pytest.param("2026-08-01", "2026-09-01", date(2026, 8, 1), date(2026, 9, 1), id="dates"),
        pytest.param(
            "2026-08-01T12:00:00+02:00",
            "2026-09-01T12:00:00+02:00",
            date(2026, 8, 1),
            date(2026, 9, 1),
            id="datetimes",
        ),
        pytest.param("not-a-date", "2026-09-01", None, date(2026, 9, 1), id="invalid-start"),
        pytest.param("2026-08-01", "not-a-date", date(2026, 8, 1), None, id="invalid-end"),
        pytest.param(None, None, None, None, id="missing-boundaries"),
        pytest.param("not-a-date", 123, None, None, id="invalid-boundaries"),
    ],
)
def test_parse_prices_period_boundaries(
    from_value: object,
    to_value: object,
    expected_from: date | None,
    expected_to: date | None,
) -> None:
    result = parse_prices(
        {
            "items": [
                {
                    "ean": "541448820000000001_ID1",
                    "prices": [{"from": from_value, "to": to_value}],
                }
            ]
        }
    )

    period = result.items[0].periods[0]
    assert period.valid_from == expected_from
    assert period.valid_to == expected_to


@pytest.mark.parametrize(
    ("period", "expected_log"),
    [
        pytest.param({"from": "not-a-date", "to": "2026-09-01"}, True, id="malformed-start"),
        pytest.param({"from": "2026-08-01", "to": "not-a-date"}, True, id="malformed-end"),
        pytest.param({"to": "2026-09-01"}, False, id="missing-start"),
        pytest.param({"from": None, "to": "2026-09-01"}, False, id="none-start"),
        pytest.param({"from": "", "to": "2026-09-01"}, False, id="empty-start"),
        pytest.param({"from": 123, "to": "2026-09-01"}, False, id="wrong-typed-start"),
    ],
)
def test_parse_prices_period_boundaries_logs_only_malformed_values(
    period: dict[str, object],
    expected_log: bool,  # noqa: FBT001
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium.parsers"):
        parse_prices(
            {
                "items": [
                    {
                        "ean": "541448820000000001_ID1",
                        "prices": [period],
                    }
                ]
            }
        )

    assert ("malformed date value" in caplog.text) is expected_log


def test_parse_energy_contracts_empty_dict() -> None:
    result = parse_energy_contracts({})
    assert result.items == ()


def test_parse_monthly_peaks_missing_peak_of_the_month() -> None:
    result = parse_monthly_peaks({"year": 2026, "month": 4, "dailyPeaks": []})
    assert result.peak_of_the_month is None
    assert result.previous_peak_of_the_month is None


def test_parse_monthly_peaks_previous_peak_of_the_month(load_fixture: LoadFixture) -> None:
    result = parse_monthly_peaks(load_fixture("peaks_with_previous_peak.json"))

    assert result.previous_peak_of_the_month is not None
    assert result.previous_peak_of_the_month.peak_kw == 4.236
    assert result.previous_peak_of_the_month.start.isoformat() == "2024-10-02T08:30:00+02:00"
    assert result.peak_of_the_month is not None
    assert result.peak_of_the_month.peak_kw == 4.884
    assert len(result.daily_peaks) == 4


def test_parse_monthly_peaks_single_day_keeps_month_peaks(load_fixture: LoadFixture) -> None:
    result = parse_monthly_peaks(load_fixture("peaks_single_day.json"))

    assert [p.start.day for p in result.daily_peaks] == [4]
    assert result.peak_of_the_month is not None
    assert result.peak_of_the_month.start.day == 3
    assert result.previous_peak_of_the_month is not None


def test_parse_monthly_peaks_drops_naive_datetimes() -> None:
    result = parse_monthly_peaks(
        {
            "year": 2026,
            "month": 4,
            "dailyPeaks": [
                {
                    "start": "2026-04-01T00:00:00",
                    "end": "2026-04-01T00:15:00",
                    "peakKW": 3.2,
                    "peakKWh": 0.8,
                },
                {
                    "start": "2026-04-02T00:00:00+02:00",
                    "end": "2026-04-02T00:15:00+02:00",
                    "peakKW": 2.1,
                    "peakKWh": 0.5,
                },
            ],
        }
    )
    assert len(result.daily_peaks) == 1
    assert result.daily_peaks[0].peak_kw == 2.1


def test_parse_account_balance_missing_overview() -> None:
    result = parse_account_balance({"status": "CLEAR", "details": {}})
    assert result.overview is None


def test_parse_account_balance_missing_details() -> None:
    result = parse_account_balance({"status": "CLEAR", "overview": {}})
    assert result.details is None


@pytest.mark.parametrize(
    ("refund_blocked_value", "expected"),
    [
        pytest.param(True, True, id="bool_true"),
        pytest.param("true", True, id="string_true"),
        pytest.param("false", False, id="string_false"),
        pytest.param(False, False, id="bool_false"),
    ],
)
def test_parse_account_balance_refund_blocked(
    refund_blocked_value: bool | str,  # noqa: FBT001
    expected: bool,  # noqa: FBT001
) -> None:
    data = {
        "status": "OK",
        "refundBlocked": refund_blocked_value,
    }
    result = parse_account_balance(data)
    assert result.refund_blocked is expected


def test_parse_epex_prices_48h(load_fixture: LoadFixture) -> None:
    data = load_fixture("epex_48h.json")
    result = parse_epex_prices(data)
    assert len(result.slots) > 0
    starts = [s.start for s in result.slots]
    assert starts == sorted(starts)


def test_parse_epex_prices_rounds_eur_per_kwh() -> None:
    data = {
        "timeSeries": [
            {"period": "2026-05-04T01:00:00+02:00", "value": 164.87},
            {"period": "2026-05-04T02:00:00+02:00", "value": 62.0},
        ]
    }
    result = parse_epex_prices(data)
    assert result.slots[0].value_eur_per_kwh == 0.16487
    assert result.slots[1].value_eur_per_kwh == 0.062


def test_parse_epex_prices_empty_time_series() -> None:
    result = parse_epex_prices({"timeSeries": []})
    assert result.slots == ()


def test_parse_epex_prices_malformed_period() -> None:
    data = {"timeSeries": [{"period": 12345, "value": 100.0}]}
    result = parse_epex_prices(data)
    assert result.slots == ()


def test_parse_epex_prices_none_value() -> None:
    data = {"timeSeries": [{"period": "2026-05-04T00:00:00+02:00", "value": None}]}
    result = parse_epex_prices(data)
    assert result.slots == ()


def test_parse_epex_prices_drops_naive_period() -> None:
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00", "value": 50.0},
            {"period": "2026-05-04T01:00:00+02:00", "value": 60.0},
        ],
        "publicationTime": "2026-05-03T12:00:00",
    }
    result = parse_epex_prices(data)
    assert len(result.slots) == 1
    assert result.slots[0].start.isoformat() == "2026-05-04T01:00:00+02:00"
    assert result.publication_time is None


@pytest.mark.parametrize(
    ("data", "expected_window_count"),
    [
        pytest.param(
            {
                "today": {
                    "startTime": "2026-07-30T18:00:00+02:00",
                    "endTime": "2026-07-30T19:00:00+02:00",
                },
                "tomorrow": {
                    "startTime": "2026-07-31T18:00:00+02:00",
                    "endTime": "2026-07-31T19:00:00+02:00",
                },
            },
            2,
            id="today-and-tomorrow",
        ),
        pytest.param(
            {
                "today": {
                    "startTime": "2026-07-30T18:00:00+02:00",
                    "endTime": "2026-07-30T19:00:00+02:00",
                },
            },
            1,
            id="missing-tomorrow",
        ),
        pytest.param({}, 0, id="missing-both"),
        pytest.param(
            {"today": {"startTime": "not-a-date", "endTime": "also-not-a-date"}},
            0,
            id="malformed-dates",
        ),
        pytest.param(
            {"today": {"startTime": "2026-07-30T18:00:00", "endTime": "2026-07-30T19:00:00"}},
            0,
            id="naive-datetime",
        ),
    ],
)
def test_parse_happy_hour_event(
    data: dict[str, Any],
    expected_window_count: int,
) -> None:
    result = parse_happy_hour_event(data)
    assert len(result.windows) == expected_window_count


def test_parse_happy_hour_month_report_no_current(load_fixture: LoadFixture) -> None:
    data = load_fixture("happy_hour_month_report_no_current.json")
    result = parse_happy_hour_month_report(data)
    assert result.current is None

    assert len(result.history) == 2
    first = result.history[0]
    assert first.year_month == date(2026, 5, 1)
    assert first.happy_hour is not None
    assert first.happy_hour.consumption_kwh == 8.0
    assert first.happy_hour.eligible_hours == 2
    assert first.happy_hour.reward_euros == 3.0
    assert first.happy_hour.is_calculation_ongoing is False
    assert first.happy_hour.comparison is not None
    assert first.electricity_offtake is None
    assert first.electricity_injection is None


def test_parse_month_report_history_entry_with_both_blocks() -> None:
    result = parse_happy_hour_month_report(
        {
            "history": [
                {
                    "yearMonth": "2026-05",
                    "happyHour": {
                        "consumptionKWh": 8.0,
                        "numberOfEligibleHappyHours": 2,
                        "rewardEuros": 3.0,
                    },
                    "electricityOfftake": {"kWh": 15.756, "cost": 31.29},
                    "electricityInjection": {"kWh": 607.901, "cost": 26.1},
                },
            ],
        }
    )
    entry = result.history[0]
    assert entry.happy_hour is not None
    assert entry.happy_hour.consumption_kwh == 8.0
    assert entry.electricity_offtake == EnergyCostPair(kwh=15.756, cost=31.29)
    assert entry.electricity_injection == EnergyCostPair(kwh=607.901, cost=26.1)


def test_parse_happy_hour_month_report_energy_history(load_fixture: LoadFixture) -> None:
    data = load_fixture("happy_hour_month_report_energy.json")
    result = parse_happy_hour_month_report(data)
    assert result.current is None
    assert result.year_month == "2026-08"
    assert result.partial_historical_data is True
    assert result.partial_year_month_data is True
    assert len(result.history) == 13

    first = result.history[0]
    assert first.year_month == date(2025, 8, 1)
    assert first.happy_hour is None
    assert first.electricity_injection == EnergyCostPair(kwh=607.901, cost=26.1)
    assert first.electricity_offtake == EnergyCostPair(kwh=15.756, cost=31.29)

    last = result.history[-1]
    assert last.year_month == date(2026, 8, 1)
    assert last.electricity_offtake is None
    assert last.electricity_injection is None

    assert result.simulated_energy == SimulatedEnergy(
        electricity_offtake=SimulatedEnergyFlow(kwh=131.389),
        electricity_injection=SimulatedEnergyFlow(kwh=708.934),
    )
    assert result.simulated_cost == SimulatedCost(
        electricity_offtake=SimulatedCostFlow(amount=10.0),
        electricity_injection=SimulatedCostFlow(amount=10.0),
        total=52.83,
    )


def test_parse_happy_hour_month_report_missing_month_block() -> None:
    result = parse_happy_hour_month_report({"history": []})
    assert result.current is None
    assert result.simulated_energy is None
    assert result.simulated_cost is None


def test_parse_happy_hour_month_report_malformed_simulated_flows() -> None:
    result = parse_happy_hour_month_report(
        {
            "month": {
                "simulatedEnergy": {"electricityOfftake": "bogus", "electricityInjection": None},
                "simulatedCost": {"electricityOfftake": "bogus", "electricityInjection": None},
            },
        }
    )
    assert result.simulated_energy == SimulatedEnergy(
        electricity_offtake=None, electricity_injection=None
    )
    assert result.simulated_cost == SimulatedCost(
        electricity_offtake=None, electricity_injection=None, total=None
    )


def test_parse_happy_hour_month_report_neither_block_present() -> None:
    result = parse_happy_hour_month_report({"month": {}, "history": []})
    assert result.current is None
    assert result.simulated_energy is None
    assert result.simulated_cost is None
    assert result.gas is None
    assert result.history == ()


def test_parse_happy_hour_month_report_dual_fuel_gas(load_fixture: LoadFixture) -> None:
    result = parse_happy_hour_month_report(load_fixture("happy_hour_month_report_dual_fuel.json"))

    assert result.gas == EnergyCostPair(kwh=202.286, cost=25.015)
    assert result.simulated_energy is not None
    assert result.simulated_energy.gas == SimulatedEnergyFlow(kwh=314.934)
    assert result.simulated_cost is not None
    assert result.simulated_cost.gas == SimulatedCostFlow(amount=32.521)
    assert len(result.history) == 13
    first = result.history[0]
    assert first.year_month == date(2023, 9, 1)
    assert first.gas == EnergyCostPair(kwh=1192.578, cost=65.224)
    assert result.skipped_entries == 0


def test_parse_happy_hour_month_report_gas_from_one_block_only() -> None:
    energy_only = parse_happy_hour_month_report({"month": {"energy": {"gas": {"kWh": 4.5}}}})
    cost_only = parse_happy_hour_month_report({"month": {"cost": {"gas": {"amount": 1.25}}}})

    assert energy_only.gas == EnergyCostPair(kwh=4.5, cost=None)
    assert cost_only.gas == EnergyCostPair(kwh=None, cost=1.25)


def test_parse_energy_contracts_green_level_and_origin(load_fixture: LoadFixture) -> None:
    result = parse_energy_contracts(load_fixture("energy_contracts_green_dual_fuel.json"))
    by_division = {c.division: c.product_configuration for c in result.items}

    gas = by_division["GAS"]
    electricity = by_division["ELECTRICITY"]
    assert gas is not None
    assert gas.green_level == "CLASSICAL"
    assert gas.green_origin is None
    assert electricity is not None
    assert electricity.green_level == "GREENFREE"
    assert electricity.green_origin == "EUROPEAN"
    assert result.skipped_entries == 0


def test_parse_solar_surplus_forecasts_empty() -> None:
    result = parse_solar_surplus_forecasts({"forecasts": []})
    assert result.forecasts == ()


def test_parse_solar_surplus_forecasts_lowercases_levels_and_keeps_unknown() -> None:
    result = parse_solar_surplus_forecasts(
        {
            "forecasts": [
                {
                    "forecastDate": "2026-07-08",
                    "level": "HIGH_SURPLUS",
                    "details": [
                        {
                            "startTime": "2026-07-08T12:00:00+02:00",
                            "value": 2.4,
                            "level": "BRAND_NEW_LEVEL",
                        },
                    ],
                    "forecastCreationDate": "2026-07-07T22:00:00+02:00",
                    "inferenceKey": "BRAND_NEW_KEY",
                },
            ],
        },
    )
    day = result.forecasts[0]
    assert day.level == "high_surplus"
    assert day.details[0].level == "brand_new_level"
    assert day.inference_key == "brand_new_key"


def test_parse_solar_surplus_forecasts_coerces_int_value_to_float() -> None:
    result = parse_solar_surplus_forecasts(
        {
            "forecasts": [
                {
                    "forecastDate": "2026-07-08",
                    "level": "NO_DATA",
                    "details": [
                        {
                            "startTime": "2026-07-08T06:00:00+02:00",
                            "value": 0,
                            "level": "NO_DATA",
                        },
                    ],
                    "forecastCreationDate": "2026-07-07T22:00:00+02:00",
                    "inferenceKey": "no_data",
                },
            ],
        },
    )
    value = result.forecasts[0].details[0].value
    assert isinstance(value, float)
    assert value == 0.0


def test_parse_solar_surplus_forecasts_high(load_fixture: LoadFixture) -> None:
    data = load_fixture("solar_surplus_high.json")
    result = parse_solar_surplus_forecasts(data)
    day = result.forecasts[0]
    assert day.inference_key == "actuals"
    assert day.forecast_creation_date is not None
    assert day.forecast_creation_date.isoformat() == "2026-07-07T22:00:00+02:00"


def test_parse_solar_surplus_forecasts_no_data(load_fixture: LoadFixture) -> None:
    data = load_fixture("solar_surplus_no_data.json")
    result = parse_solar_surplus_forecasts(data)
    day = result.forecasts[0]
    assert day.inference_key == "no_data"


def test_parse_tou_schedules_canonicalises_slot_codes_and_keeps_unknown() -> None:
    result = parse_tou_schedules(
        {
            "items": [
                {
                    "eanWithSuffix": "541448800000000001_1",
                    "gridMeterTimeOfUseSchedules": [
                        {
                            "dgoTgoSchedule": {
                                "offtake": {
                                    "monday": [
                                        {
                                            "startTime": "00:00",
                                            "endTime": "06:00",
                                            "slotCode": "S_TOU1_OFFTAKE_HIGH_LOAD_HOURS",
                                        },
                                        {
                                            "startTime": "06:00",
                                            "endTime": "12:00",
                                            "slotCode": "LOW_LOAD_HOURS",
                                        },
                                        {
                                            "startTime": "12:00",
                                            "endTime": "00:00",
                                            "slotCode": "NEW_CODE",
                                        },
                                    ],
                                },
                            },
                        },
                    ],
                },
            ],
        },
    )
    meter = result.items[0].grid_meter_schedules[0]
    schedule = meter.dgo_tgo
    assert schedule is not None
    offtake = schedule.offtake
    assert offtake is not None
    assert [s.slot_code for s in offtake.monday] == ["peak", "offpeak", "new_code"]


def test_parse_tou_schedules_empty_items() -> None:
    result = parse_tou_schedules({"items": []})
    assert result.items == ()


def test_parse_usage_details_drops_naive_items() -> None:
    result = parse_usage_details(
        {
            "items": [
                {"start": "2026-05-04T00:00:00", "end": "2026-05-04T01:00:00"},
                {"start": "2026-05-04T01:00:00+02:00", "end": "2026-05-04T02:00:00+02:00"},
            ],
            "total": {"start": "2026-05-04T00:00:00", "end": "2026-05-05T00:00:00"},
        }
    )
    assert len(result.items) == 1
    assert result.items[0].start.isoformat() == "2026-05-04T01:00:00+02:00"
    assert result.total is None


def test_parse_usage_details_tou_slot_breakdown(load_fixture: LoadFixture) -> None:
    data = load_fixture("usage_details_tou_simulated.json")
    result = parse_usage_details(data)
    item = result.items[0]

    assert item.energy is not None
    assert item.energy.offtake is not None
    assert item.energy.offtake.kwh_sum == 9.746
    assert item.energy.offtake.amount_sum is None
    assert len(item.energy.offtake.parts) == 1
    assert item.energy.offtake.parts[0].supplier_slot_code == "TOTAL_HOURS"
    assert item.energy.offtake.parts[0].distribution_slot_code == "TOTAL_HOURS"
    assert [p.value for p in item.energy.offtake.parts] == [9.746]
    assert [p.slot_code for p in item.energy.offtake.supplier_parts] == ["TOTAL_HOURS"]
    assert [p.slot_code for p in item.energy.offtake.distribution_parts] == ["TOTAL_HOURS"]
    assert item.energy.injection is not None
    assert item.energy.injection.kwh_sum == 452.279

    assert item.costs is not None
    assert item.costs.offtake is not None
    assert item.costs.offtake.amount_sum == 28.88
    assert item.costs.offtake.kwh_sum is None
    assert len(item.costs.offtake.parts) == 1
    assert item.costs.offtake.parts[0].supplier_slot_code == "TOTAL_HOURS"
    assert item.costs.offtake.parts[0].distribution_slot_code == "TOTAL_HOURS"
    assert [p.value for p in item.costs.offtake.parts] == [10.0]

    assert item.simulated_energy is not None
    assert item.simulated_energy.offtake is not None
    assert item.simulated_energy.offtake.kwh_sum == 119.171
    assert item.simulated_costs is not None
    assert item.simulated_costs.offtake is not None
    assert item.simulated_costs.offtake.amount_sum == 55.65

    assert item.energy is not item.simulated_energy
    assert item.costs is not item.simulated_costs


def test_parse_usage_details_tou_slot_breakdown_tolerates_empty_and_missing_blocks(
    load_fixture: LoadFixture,
) -> None:
    data = load_fixture("usage_details_tou_simulated.json")
    result = parse_usage_details(data)
    item = result.items[2]

    assert item.energy is None
    assert item.costs is None
    assert item.simulated_energy is not None
    assert item.simulated_costs is not None


def test_parse_usage_details_flat_fixture_has_no_tou_parts(load_fixture: LoadFixture) -> None:
    data = load_fixture("usage_details_hourly.json")
    result = parse_usage_details(data)
    item = result.items[0]

    assert item.energy is not None
    assert item.energy.offtake is not None
    assert item.energy.offtake.parts == ()
    assert item.energy.offtake.supplier_parts == ()
    assert item.energy.offtake.distribution_parts == ()
    assert item.costs is None
    assert item.simulated_energy is None
    assert item.simulated_costs is None


def test_parse_usage_details_yearly_dual_fuel_gas_and_cost_totals(
    load_fixture: LoadFixture,
) -> None:
    result = parse_usage_details(load_fixture("usage_details_yearly_dual_fuel.json"))
    first, second = result.items[0], result.items[1]

    assert first.start == datetime(2022, 1, 1, tzinfo=ZoneInfo("Europe/Brussels"))
    assert first.end == datetime(2023, 1, 1, tzinfo=ZoneInfo("Europe/Brussels"))
    assert first.gas == GasUsage(kwh=2178.82, cost=730.39)
    assert first.gas_and_electricity_cost == 2997.35
    assert first.costs is not None
    assert first.costs.netto == 2266.96
    assert first.energy is not None
    assert first.energy.netto == 1580.05
    assert first.simulated_gas is None
    assert first.simulated_gas_and_electricity_cost is None

    assert second.simulated_gas == GasUsage(kwh=3410.34, cost=1001.83)
    assert second.simulated_gas_and_electricity_cost == 3602.79
    assert result.total is not None
    assert result.total.gas is not None
    assert result.total.gas.cost is not None


def test_parse_usage_details_electricity_only_has_no_gas_cost(load_fixture: LoadFixture) -> None:
    item = parse_usage_details(load_fixture("usage_details_tou_simulated.json")).items[0]

    assert item.gas is None
    assert item.gas_and_electricity_cost is not None
    assert item.simulated_gas is None


def test_parse_usage_details_tou_part_and_direction_tolerate_malformed_data() -> None:
    result = parse_usage_details(
        {
            "items": [
                {
                    "start": "2026-05-04T00:00:00+02:00",
                    "end": "2026-05-04T01:00:00+02:00",
                    "costs": {
                        "electricity": {
                            "injection": {
                                "amountSum": 5.0,
                                "parts": [
                                    {"amount": 1.0},
                                    {"amount": 2.0, "supplierTimeOfUseTimeSlotCode": "PEAK"},
                                    {
                                        "amount": 3.0,
                                        "supplierTimeOfUseTimeSlotCode": "PEAK",
                                        "distributionTimeOfUseTimeSlotCode": "OFFPEAK",
                                    },
                                ],
                                "supplierParts": [{"amount": 4.0}],
                            },
                        },
                    },
                },
            ],
        }
    )
    item = result.items[0]
    assert item.costs is not None
    assert item.costs.offtake is None
    assert item.costs.injection is not None
    assert len(item.costs.injection.parts) == 1
    assert item.costs.injection.parts[0].supplier_slot_code == "PEAK"
    assert item.costs.injection.parts[0].distribution_slot_code == "OFFPEAK"
    assert item.costs.injection.parts[0].value == 3.0
    assert item.costs.injection.supplier_parts == ()


def test_parse_usage_details_keeps_raw_supplier_tariff_slot_codes() -> None:
    result = parse_usage_details(
        {
            "items": [
                {
                    "start": "2026-05-04T00:00:00+02:00",
                    "end": "2026-05-04T01:00:00+02:00",
                    "energy": {
                        "electricity": {
                            "offtake": {
                                "kWhSum": 1.0,
                                "parts": [
                                    {
                                        "kWh": 1.0,
                                        "supplierTimeOfUseTimeSlotCode": "S_TOU1_OFFTAKE_PEAK",
                                        "distributionTimeOfUseTimeSlotCode": "TOTAL_HOURS",
                                    },
                                ],
                                "supplierParts": [
                                    {"kWh": 1.0, "timeOfUseTimeSlotCode": "S_TOU1_OFFTAKE_PEAK"},
                                ],
                            },
                        },
                    },
                },
            ],
        }
    )
    item = result.items[0]
    assert item.energy is not None
    offtake = item.energy.offtake
    assert offtake is not None
    assert offtake.parts[0].supplier_slot_code == "S_TOU1_OFFTAKE_PEAK"
    assert offtake.parts[0].distribution_slot_code == "TOTAL_HOURS"
    assert offtake.supplier_parts[0].slot_code == "S_TOU1_OFFTAKE_PEAK"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {
                "division": "ELECTRICITY",
                "ean": "541448820000000001_ID1",
                "premisesId": "5100000001",
                "type": "DEREGULATED",
            },
            {"541448820000000001": "ELECTRICITY"},
            id="electricity",
        ),
        pytest.param({"division": "GAS"}, {"541448820000000001": "GAS"}, id="gas"),
        pytest.param(
            {"ean": "541448820000000001_ID1", "type": "DEREGULATED"},
            {},
            id="missing_division",
        ),
        pytest.param({"division": 7}, {}, id="non_string_division"),
    ],
)
def test_parse_service_point_keys_division_by_bare_requested_ean(
    payload: dict[str, Any],
    expected: dict[str, str],
) -> None:
    result = parse_service_point(payload, "541448820000000001_ID1")
    assert dict(result.ean_energy_types) == expected


def test_parse_service_point_models_market_details() -> None:
    payload = {
        "chargingStation": False,
        "division": "ELECTRICITY",
        "ean": "541448820000000001_ID1",
        "marketDetails": {
            "dgo": "FLUVIUS",
            "grid": "FLUVIUS_WEST",
            "installation": {
                "RTPComponentID": "RTP0000001",
                "budgetMeter": False,
                "installationId": "4100000001",
                "meteringConfiguration": {
                    "meteringMethodFrequency": "MONTHLY",
                    "meteringMethodType": "SMART_READING",
                    "meteringReadsForInformation": "NOT_APPLICABLE",
                    "registerTypeConfiguration": "TOTAL_HOURS",
                    "smartMeterRegime": "THREE",
                    "supplierBillingFrequency": "MONTHLY",
                },
                "serviceComponent": "CONSTRAINT_COMMERCIALIZATION_OF_INJECTION",
            },
        },
        "premisesId": "5100000001",
        "type": "DEREGULATED",
    }
    result = parse_service_point(payload, "541448820000000001_ID1")
    assert result.ean == "541448820000000001_ID1"
    assert result.division == "ELECTRICITY"
    assert result.type == "DEREGULATED"
    assert result.charging_station is False
    assert result.premises_id == "5100000001"
    details = result.market_details
    assert details is not None
    assert details.dgo == "FLUVIUS"
    assert details.grid == "FLUVIUS_WEST"
    installation = details.installation
    assert installation is not None
    assert installation.installation_id == "4100000001"
    assert installation.rtp_component_id == "RTP0000001"
    assert installation.budget_meter is False
    assert installation.service_component == "CONSTRAINT_COMMERCIALIZATION_OF_INJECTION"
    config = installation.metering_configuration
    assert config is not None
    assert config.metering_method_frequency == "MONTHLY"
    assert config.metering_method_type == "SMART_READING"
    assert config.metering_reads_for_information == "NOT_APPLICABLE"
    assert config.register_type_configuration == "TOTAL_HOURS"
    assert config.smart_meter_regime == "THREE"
    assert config.supplier_billing_frequency == "MONTHLY"


def test_parse_service_point_partial_market_details() -> None:
    payload = {
        "division": "GAS",
        "marketDetails": {"dgo": "ORES", "installation": {"budgetMeter": True}},
    }
    result = parse_service_point(payload, "541448820000000001_ID1")
    details = result.market_details
    assert details is not None
    assert details.dgo == "ORES"
    assert details.grid is None
    installation = details.installation
    assert installation is not None
    assert installation.budget_meter is True
    assert installation.installation_id is None
    assert installation.metering_configuration is None

    no_installation = parse_service_point(
        {"division": "GAS", "marketDetails": {"dgo": "ORES"}},
        "541448820000000001_ID1",
    )
    assert no_installation.market_details is not None
    assert no_installation.market_details.installation is None


def test_parse_service_point_logs_missing_division(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium.parsers"):
        result = parse_service_point({"ean": "541448820000000001_ID1"}, "541448820000000001_ID1")
    assert dict(result.ean_energy_types) == {}
    assert "missing division" in caplog.text


def test_parse_customer_account_relations_null_consumption_address() -> None:
    data = {
        "items": [
            {
                "id": "rel-1",
                "admin": True,
                "customerAccount": {
                    "customerAccountNumber": "CA1",
                    "businessAgreements": [
                        {"businessAgreementNumber": "BA1", "consumptionAddress": None},
                    ],
                },
            },
        ],
    }
    result = parse_customer_account_relations(data)
    agreement = result.accounts[0].customer_account.business_agreements[0]
    assert agreement.consumption_address is None


def test_parse_customer_account_relations_populates_address_and_language() -> None:
    data = {
        "items": [
            {
                "id": "rel-1",
                "admin": True,
                "customerAccount": {
                    "customerAccountNumber": "CA1",
                    "language": "nl",
                    "businessAgreements": [
                        {
                            "businessAgreementNumber": "BA1",
                            "consumptionAddress": {
                                "street": "TESTSTRAAT",
                                "houseNumber": "1",
                                "boxNumber": "0101",
                                "floor": "3",
                                "roomNumber": "R2",
                                "supplement": "A",
                                "locationSupplement": "REAR",
                                "country": "Belgium",
                                "countryCode": "BE",
                            },
                        },
                    ],
                },
            },
        ],
    }
    result = parse_customer_account_relations(data)
    account = result.accounts[0].customer_account
    assert account.language == "nl"
    address = account.business_agreements[0].consumption_address
    assert address is not None
    assert address.box_number == "0101"
    assert address.floor == "3"
    assert address.room_number == "R2"
    assert address.supplement == "A"
    assert address.location_supplement == "REAR"
    assert address.country == "Belgium"


def test_parse_tou_schedules_null_schedule() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [{"dgoTgoSchedule": None}],
            }
        ]
    }
    result = parse_tou_schedules(data)
    assert len(result.items) == 1
    meter = result.items[0].grid_meter_schedules[0]
    assert meter.dgo_tgo is None
    assert meter.supplier is None


@pytest.mark.parametrize("meter", [None, 4, "bad", []])
def test_parse_tou_grid_meter_non_dict_is_dropped(meter: Any) -> None:
    assert _parse_tou_grid_meter(meter) is None


def test_parse_tou_schedules_canonicalises_optimal_timeslot_code() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "dgoTgoSchedule": {
                            "offtake": {"optimalTimeslotCode": "S_TOU1_OFFTAKE_OFFPEAK"},
                            "injection": {"optimalTimeslotCode": "BRAND_NEW"},
                        },
                    },
                ],
            },
        ],
    }
    result = parse_tou_schedules(data)
    schedule = result.items[0].grid_meter_schedules[0].dgo_tgo
    assert schedule is not None
    assert schedule.offtake is not None
    assert schedule.offtake.optimal_timeslot_code == "offpeak"
    assert schedule.injection is not None
    assert schedule.injection.optimal_timeslot_code == "brand_new"


def test_parse_tou_schedules_absent_supplier_and_optimal_code() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {"dgoTgoSchedule": {"offtake": {"monday": []}}},
                ],
            },
        ],
    }
    result = parse_tou_schedules(data)
    meter = result.items[0].grid_meter_schedules[0]
    assert meter.supplier is None
    assert meter.dgo_tgo is not None
    assert meter.dgo_tgo.offtake is not None
    assert meter.dgo_tgo.offtake.optimal_timeslot_code is None


def test_parse_tou_schedules_derives_optimal_from_cost_indicator() -> None:
    """When the wire omits ``optimalTimeslotCode``, derive it from ``costIndicator``."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "monday": [
                                    {
                                        "startTime": "00:00:00",
                                        "endTime": "06:00:00",
                                        "slotCode": "S_TOU1_OFFTAKE_OFFPEAK",
                                        "costIndicator": 2,
                                    },
                                    {
                                        "startTime": "06:00:00",
                                        "endTime": "22:00:00",
                                        "slotCode": "S_TOU1_OFFTAKE_PEAK",
                                        "costIndicator": 5,
                                    },
                                ]
                            },
                            "injection": {
                                "monday": [
                                    {
                                        "startTime": "00:00:00",
                                        "endTime": "06:00:00",
                                        "slotCode": "S_TOU1_INJECTION_OFFPEAK",
                                        "costIndicator": 2,
                                    },
                                    {
                                        "startTime": "06:00:00",
                                        "endTime": "22:00:00",
                                        "slotCode": "S_TOU1_INJECTION_PEAK",
                                        "costIndicator": 5,
                                    },
                                ]
                            },
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert supplier.offtake.optimal_timeslot_code == "offpeak"
    assert supplier.injection is not None
    assert supplier.injection.optimal_timeslot_code == "peak"


def test_parse_tou_schedules_accepts_hhmm_and_hhmmss_in_same_day() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "monday": [
                                    {
                                        "startTime": "00:00",
                                        "endTime": "06:00",
                                        "slotCode": "OFFPEAK",
                                    },
                                    {
                                        "startTime": "06:00:00",
                                        "endTime": "00:00:00",
                                        "slotCode": "PEAK",
                                    },
                                ]
                            }
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert [(s.start_time, s.slot_code) for s in supplier.offtake.monday] == [
        ("00:00", "offpeak"),
        ("06:00:00", "peak"),
    ]


def test_parse_tou_schedules_strips_bare_direction_prefix() -> None:
    """Bare OFFTAKE_/INJECTION_ prefixes also collapse, matching hass rfind semantics."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "monday": [
                                    {
                                        "startTime": "00:00",
                                        "endTime": "12:00",
                                        "slotCode": "OFFTAKE_PEAK",
                                    },
                                    {
                                        "startTime": "12:00",
                                        "endTime": "00:00",
                                        "slotCode": "S_TOU2_INJECTION_OFFPEAK",
                                    },
                                ]
                            }
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert [s.slot_code for s in supplier.offtake.monday] == ["peak", "offpeak"]


def test_parse_tou_schedules_captures_active_configuration_id() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "activeConfigurationId": "TOU001",
                            "offtake": {"monday": []},
                        },
                        "dgoTgoSchedule": {
                            "activeConfigurationId": "TOTAL_HOURS",
                            "offtake": {"monday": []},
                        },
                    }
                ],
            }
        ]
    }
    meter = parse_tou_schedules(data).items[0].grid_meter_schedules[0]
    assert meter.supplier is not None
    assert meter.supplier.active_configuration_id == "TOU001"
    assert meter.dgo_tgo is not None
    assert meter.dgo_tgo.active_configuration_id == "TOTAL_HOURS"


def test_parse_tou_schedules_primary_meter_selection_from_multi_meter_wire() -> None:
    """End-to-end: two meters, first is exclusive-night, primary_meter picks the day one."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "gridMeterNumber": "NIGHT",
                        "exclusiveNightMeter": True,
                        "supplierSchedule": {"offtake": {"monday": []}},
                    },
                    {
                        "gridMeterNumber": "DAY",
                        "exclusiveNightMeter": False,
                        "supplierSchedule": {"offtake": {"monday": []}},
                    },
                ],
            }
        ]
    }
    item = parse_tou_schedules(data).items[0]
    assert len(item.grid_meter_schedules) == 2
    primary = item.primary_meter()
    assert primary is not None
    assert primary.grid_meter_number == "DAY"


def test_parse_tou_schedules_canonicalises_direction_prefixed_optimal_code() -> None:
    """Wire `optimalTimeslotCode` also goes through the canonicaliser."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "optimalTimeslotCode": "S_TOU1_OFFTAKE_PEAK",
                                "monday": [],
                            }
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert supplier.offtake.optimal_timeslot_code == "peak"


def test_parse_tou_schedules_blank_optimal_code_falls_through_to_cost_derivation() -> None:
    """An empty-string `optimalTimeslotCode` should not override the derived value."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "optimalTimeslotCode": "",
                                "monday": [
                                    {
                                        "startTime": "00:00",
                                        "endTime": "06:00",
                                        "slotCode": "OFFPEAK",
                                        "costIndicator": 2,
                                    },
                                    {
                                        "startTime": "06:00",
                                        "endTime": "00:00",
                                        "slotCode": "PEAK",
                                        "costIndicator": 5,
                                    },
                                ],
                            }
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert supplier.offtake.optimal_timeslot_code == "offpeak"


def test_parse_tou_schedules_preserves_cost_indicator_zero() -> None:
    """`costIndicator: 0` is a legitimate integer and must round-trip untouched."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "monday": [
                                    {
                                        "startTime": "00:00",
                                        "endTime": "00:00",
                                        "slotCode": "OFFPEAK",
                                        "costIndicator": 0,
                                    }
                                ]
                            }
                        }
                    }
                ],
            }
        ]
    }
    supplier = parse_tou_schedules(data).items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert supplier.offtake.monday[0].cost_indicator == 0


def test_parse_tou_schedules_exposes_grid_meter_metadata() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "gridMeterNumber": "1SAG0000000000",
                        "exclusiveNightMeter": True,
                        "supplierSchedule": {"offtake": {"monday": []}},
                    }
                ],
            }
        ]
    }
    meter = parse_tou_schedules(data).items[0].grid_meter_schedules[0]
    assert meter.grid_meter_number == "1SAG0000000000"
    assert meter.exclusive_night_meter is True


def test_parse_tou_schedules_combined_schedule_fixture(load_fixture: LoadFixture) -> None:
    meter = (
        parse_tou_schedules(load_fixture("tou_schedules_combined.json"))
        .items[0]
        .grid_meter_schedules[0]
    )
    combined = meter.combined
    assert combined is not None
    assert combined.supplier_active_configuration_id == "TOTAL_HOURS"
    assert combined.dgo_tgo_active_configuration_id == "TOTAL_HOURS"
    assert combined.offtake is not None
    assert combined.offtake.monday == (
        TouCombinedSlot(
            start_time="00:00:00",
            end_time="00:00:00",
            supplier_slot_code="total_hours",
            dgo_tgo_slot_code="total_hours",
            cost_indicator=5,
        ),
    )
    assert combined.injection is not None
    assert combined.injection.sunday == ()


def test_parse_tou_schedules_combined_schedule_canonicalises_both_codes() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820000000001_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "combinedSchedule": {
                            "supplierActiveConfigurationId": "S_TOU1",
                            "dgoTgoActiveConfigurationId": "",
                            "offtake": {
                                "friday": [
                                    {
                                        "startTime": "07:00",
                                        "endTime": "22:00",
                                        "supplierSlotCode": "S_TOU1_OFFTAKE_PEAK",
                                        "dgoTgoSlotCode": "HIGH_LOAD_HOURS",
                                        "costIndicator": True,
                                    },
                                ],
                            },
                        },
                    }
                ],
            }
        ]
    }
    combined = parse_tou_schedules(data).items[0].grid_meter_schedules[0].combined
    assert combined is not None
    assert combined.supplier_active_configuration_id == "S_TOU1"
    assert combined.dgo_tgo_active_configuration_id is None
    assert combined.injection is None
    assert combined.offtake is not None
    (slot,) = combined.offtake.friday
    assert slot.supplier_slot_code == "peak"
    assert slot.dgo_tgo_slot_code == "peak"
    assert slot.cost_indicator is None


def test_parse_tou_schedules_parses_supplier_schedule() -> None:
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820070000000_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "supplierSchedule": {
                            "offtake": {
                                "optimalTimeslotCode": "PEAK",
                                "monday": [
                                    {
                                        "startTime": "00:00:00",
                                        "endTime": "22:00:00",
                                        "slotCode": "S_TOU1_OFFTAKE_PEAK",
                                        "costIndicator": 5,
                                    },
                                ],
                            },
                        },
                    },
                ],
            },
        ],
    }
    result = parse_tou_schedules(data)
    supplier = result.items[0].grid_meter_schedules[0].supplier
    assert supplier is not None
    assert supplier.offtake is not None
    assert supplier.offtake.optimal_timeslot_code == "peak"
    assert [s.slot_code for s in supplier.offtake.monday] == ["peak"]
    assert supplier.offtake.monday[0].cost_indicator == 5


def test_parse_epex_prices_derives_ends_from_observed_spacing() -> None:
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00+02:00", "value": 100.0},
            {"period": "2026-05-04T00:15:00+02:00", "value": 101.0},
            {"period": "2026-05-04T00:30:00+02:00", "value": 102.0},
            {"period": "2026-05-04T00:45:00+02:00", "value": 103.0},
        ],
    }
    result = parse_epex_prices(data, granularity_minutes=60)
    assert result.slot_duration == timedelta(minutes=15)
    for slot in result.slots:
        assert slot.end - slot.start == timedelta(minutes=15)
    assert result.slots[-1].end == datetime.fromisoformat("2026-05-04T01:00:00+02:00")


def test_parse_epex_prices_single_slot_falls_back_to_requested_granularity() -> None:
    data = {"timeSeries": [{"period": "2026-05-04T00:00:00+02:00", "value": 100.0}]}
    result = parse_epex_prices(data, granularity_minutes=15)
    assert result.slot_duration == timedelta(minutes=15)
    assert result.slots[0].end - result.slots[0].start == timedelta(minutes=15)


def test_parse_epex_prices_drops_duplicate_period() -> None:
    """A duplicated period is dropped so the modal spacing and last slot stay real."""
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00+02:00", "value": 100.0},
            {"period": "2026-05-04T00:00:00+02:00", "value": 100.0},
            {"period": "2026-05-04T01:00:00+02:00", "value": 101.0},
            {"period": "2026-05-04T02:00:00+02:00", "value": 102.0},
        ],
    }
    result = parse_epex_prices(data, granularity_minutes=60)
    assert len(result.slots) == 3
    assert result.slot_duration == timedelta(hours=1)
    assert all(slot.end > slot.start for slot in result.slots)
    assert result.slots[-1].end == datetime.fromisoformat("2026-05-04T03:00:00+02:00")


def test_parse_epex_prices_ignores_single_interior_gap() -> None:
    """One irregular gap does not unseat the regular modal spacing."""
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00+02:00", "value": 100.0},
            {"period": "2026-05-04T01:00:00+02:00", "value": 101.0},
            {"period": "2026-05-04T03:00:00+02:00", "value": 103.0},
            {"period": "2026-05-04T04:00:00+02:00", "value": 104.0},
        ],
    }
    result = parse_epex_prices(data, granularity_minutes=60)
    assert result.slot_duration == timedelta(hours=1)
    assert result.slots[1].end == datetime.fromisoformat("2026-05-04T02:00:00+02:00")
    assert result.slots[2].start == datetime.fromisoformat("2026-05-04T03:00:00+02:00")


def test_parse_epex_prices_trims_slot_before_skipped_entry() -> None:
    """The slot before a skipped entry keeps one step instead of stretching over the gap."""
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00+02:00", "value": 100.0},
            {"period": "2026-05-04T01:00:00+02:00", "value": 101.0},
            {"period": None, "value": 102.0},
            {"period": "2026-05-04T03:00:00+02:00", "value": 103.0},
        ],
    }
    result = parse_epex_prices(data, granularity_minutes=60)
    assert result.skipped_entries == 1
    assert len(result.slots) == 3
    assert result.slots[1].end - result.slots[1].start == timedelta(hours=1)
    assert result.slots[1].end < result.slots[2].start


def test_normalize_vocab_lowercases_and_passes_non_str_through() -> None:
    assert _normalize_vocab("PEAK") == "peak"
    assert _normalize_vocab("Off_Peak") == "off_peak"
    assert _normalize_vocab(None) is None
    assert _normalize_vocab(123) is None


_NULLED_PAYLOADS = [
    pytest.param(
        parse_customer_account_relations,
        {
            "items": [
                {
                    "id": None,
                    "admin": None,
                    "customerAccount": {
                        "customerAccountNumber": "CA1",
                        "name": None,
                        "segment": None,
                        "businessAgreements": [
                            {
                                "businessAgreementNumber": "BA1",
                                "active": None,
                                "consumptionAddress": {
                                    "street": None,
                                    "houseNumber": None,
                                    "postalCode": None,
                                    "city": None,
                                    "countryCode": None,
                                    "premisesNumber": None,
                                },
                                "electricityContract": {
                                    "hasSmartMeter": None,
                                    "active": None,
                                    "hasSolar": None,
                                },
                                "gasContract": None,
                            },
                        ],
                    },
                },
            ],
        },
        id="customer_account_relations",
    ),
    pytest.param(
        parse_prices,
        {
            "items": [
                {
                    "ean": None,
                    "prices": [
                        {
                            "from": None,
                            "to": None,
                            "vatTariff": None,
                            "proportionalPriceConfigurations": {
                                "offtake": [
                                    {
                                        "timeOfUseSlotCode": None,
                                        "priceValue": None,
                                        "priceValueExclVAT": None,
                                    },
                                ],
                                "injection": None,
                            },
                        },
                    ],
                },
            ],
        },
        id="prices",
    ),
    pytest.param(
        parse_energy_contracts,
        {
            "items": [
                {
                    "businessAgreementNumber": None,
                    "servicePointNumber": None,
                    "division": None,
                    "status": None,
                    "productConfiguration": {
                        "energyProduct": None,
                        "type": None,
                        "greenLevel": None,
                        "greenOrigin": None,
                    },
                },
            ],
        },
        id="energy_contracts",
    ),
    pytest.param(
        parse_monthly_peaks,
        {
            "year": None,
            "month": None,
            "peakOfTheMonth": {"peakKW": None, "peakKWh": None, "start": None, "end": None},
            "previousPeakOfTheMonth": None,
            "dailyPeaks": [
                {
                    "peakKW": None,
                    "peakKWh": None,
                    "start": "2026-04-01T00:00:00+02:00",
                    "end": "2026-04-02T00:00:00+02:00",
                },
            ],
        },
        id="monthly_peaks",
    ),
    pytest.param(
        parse_account_balance,
        {
            "status": None,
            "overview": {
                "totalAmount": None,
                "openAmount": None,
                "dueAmount": None,
                "pendingOnlinePaymentsAmount": None,
                "installmentPlanAmount": None,
            },
            "details": {
                "financialTransactions": [
                    {
                        "type": None,
                        "dueAmount": None,
                        "openAmount": None,
                        "dueDate": None,
                        "invoiceType": None,
                    },
                ],
                "invoiceStructuredCommunication": None,
            },
            "refundBlocked": None,
        },
        id="account_balance",
    ),
    pytest.param(
        parse_epex_prices,
        {
            "timeSeries": [{"period": None, "value": None}],
            "publicationTime": None,
            "marketDate": None,
        },
        id="epex_prices",
    ),
    pytest.param(
        parse_happy_hour_event,
        {"today": {"startTime": None, "endTime": None}, "tomorrow": None},
        id="happy_hour_event",
    ),
    pytest.param(
        parse_happy_hour_month_report,
        {
            "month": {
                "happyHour": {
                    "consumptionKWh": None,
                    "numberOfEligibleHappyHours": None,
                    "rewardEuros": None,
                    "isCalculationOngoing": None,
                    "comparisonToPreviousMonth": {
                        "consumptionKWhPercentageChange": None,
                        "numberOfEligibleHappyHoursPercentageChange": None,
                        "rewardEurosPercentageChange": None,
                    },
                },
                "energy": {"gas": {"kWh": None}},
                "cost": {"gas": None},
                "simulatedEnergy": {"gas": None},
                "simulatedCost": {"gas": {"amount": None}},
            },
            "history": [
                {"yearMonth": None, "happyHour": {"consumptionKWh": None}},
                {"yearMonth": "2024-09", "gas": {"kWh": None, "cost": None}},
            ],
        },
        id="happy_hour_month_report",
    ),
    pytest.param(parse_feature_flag, {"value": None, "reason": None}, id="feature_flag"),
    pytest.param(
        parse_solar_surplus_forecasts,
        {
            "forecasts": [
                {
                    "forecastDate": None,
                    "level": None,
                    "details": [
                        {
                            "startTime": "2026-05-04T10:00:00+02:00",
                            "value": None,
                            "level": None,
                        },
                        {"startTime": None, "value": None, "level": None},
                    ],
                    "forecastCreationDate": None,
                    "inferenceKey": None,
                },
            ],
        },
        id="solar_surplus_forecasts",
    ),
    pytest.param(
        parse_tou_schedules,
        {
            "items": [
                {
                    "eanWithSuffix": "541448820070000000_ID1",
                    "dgoTgoSchedule": {
                        "offtake": {
                            "monday": [
                                {"startTime": None, "endTime": None, "slotCode": None},
                            ],
                        },
                        "injection": None,
                    },
                    "gridMeterTimeOfUseSchedules": [
                        {
                            "combinedSchedule": {
                                "supplierActiveConfigurationId": None,
                                "dgoTgoActiveConfigurationId": None,
                                "offtake": {
                                    "monday": [
                                        {
                                            "startTime": None,
                                            "endTime": None,
                                            "supplierSlotCode": None,
                                            "dgoTgoSlotCode": None,
                                            "costIndicator": None,
                                        },
                                    ],
                                },
                                "injection": None,
                            },
                        },
                    ],
                },
            ],
        },
        id="tou_schedules",
    ),
    pytest.param(
        parse_usage_details,
        {
            "items": [
                {
                    "start": "2026-05-04T00:00:00+02:00",
                    "end": "2026-05-04T01:00:00+02:00",
                    "partialData": None,
                    "energy": {
                        "electricity": {
                            "offtake": {"kWhSum": None},
                            "injection": None,
                            "netto": None,
                        },
                        "gas": {"kWh": None},
                    },
                    "costs": {
                        "electricity": {"offtake": {"amountSum": None}, "netto": None},
                        "gas": None,
                        "gasAndElectricitySum": None,
                    },
                    "simulatedEnergy": {"gas": None},
                    "simulatedCosts": {"gas": None, "gasAndElectricitySum": None},
                },
                {"start": None, "end": None},
            ],
            "total": None,
        },
        id="usage_details",
    ),
    pytest.param(
        partial(parse_service_point, requested_ean="541448820000000001_ID1"),
        {"division": None, "ean": None, "eanBlocked": None, "premisesId": None},
        id="service_point",
    ),
    pytest.param(
        parse_service_points,
        {
            "items": [
                {
                    "ean": "541448820000000001",
                    "eanWithSuffix": None,
                    "division": None,
                    "hasSolar": None,
                    "dataAvailability": {"measured": {"quarterHourly": None, "daily": None}},
                    "dataSources": {
                        "p1": {"active": None, "applicable": None, "dongleStatus": None},
                        "p4": None,
                        "billing": {"type": None, "upgradableTo": None},
                    },
                },
                {"ean": None},
            ],
        },
        id="service_points",
    ),
    pytest.param(
        parse_meter_reads,
        {
            "items": [
                {
                    "ean": "541448820000000001",
                    "meterReadDate": "2026-10-01",
                    "origin": None,
                    "division": None,
                    "registers": [
                        {
                            "meterNumber": None,
                            "indexRead": 1.0,
                            "unit": None,
                            "active": None,
                            "minimumIndexReadRange": None,
                        },
                        {"indexRead": None},
                    ],
                },
                {"ean": "541448820000000001", "meterReadDate": None},
            ],
        },
        id="meter_reads",
    ),
    pytest.param(
        parse_monthly_billed_budget,
        {
            "from": None,
            "to": None,
            "alreadyUsedAmount": None,
            "alreadyUsedAmountRatio": None,
            "alreadyPaidAmount": None,
            "expectedCostAmount": None,
            "expectedMonthCostAmount": None,
            "currentMonthCostAmount": None,
            "lastInvoicedAmount": None,
            "payments": [{"date": "2024-01-01", "status": None}, {"date": None}],
        },
        id="monthly_billed_budget",
    ),
    pytest.param(
        parse_billing_period_usage,
        {
            "startDate": None,
            "endDate": None,
            "expectedYearInvoice": None,
            "usedAmount": None,
            "usedAmountRatio": None,
            "usedAmountFailureReason": None,
        },
        id="billing_period_usage",
    ),
    pytest.param(
        parse_budget_billing_plan_details,
        {
            "businessAgreementId": None,
            "startDate": None,
            "hasCHM": None,
            "budgetBillingPlanUpdatable": None,
            "budgetBillingPlan": {
                "currentAmount": None,
                "remainingSlices": None,
                "nextPartialInvoiceDate": None,
                "paymentSlices": None,
            },
            "bbpUpdateLimits": {"lowerLimit": None, "upperLimit": None},
            "bbpProposal": {
                "changeType": None,
                "proposedAmount": None,
                "significant": None,
                "evaluationContext": [{"event": None, "weight": None, "changeType": None}],
            },
            "periodDetailsPerContract": [
                {
                    "contractId": None,
                    "division": None,
                    "budgetBillingPlan": None,
                    "bbpProposal": None,
                    "isContractForCHM": None,
                },
            ],
        },
        id="budget_billing_plan",
    ),
    pytest.param(
        parse_happy_hour_eligibility,
        {"eligible": None, "reasons": None},
        id="happy_hour_eligibility",
    ),
    pytest.param(
        parse_happy_hour_service_status,
        {"status": None, "statusDate": None},
        id="happy_hour_service_status",
    ),
    pytest.param(
        parse_energy_score,
        {
            "businessAgreementNumber": None,
            "score": None,
            "lastUpdated": None,
            "scoring": {
                "consumptionAvailability": None,
                "energyQuestion": None,
                "hasCheckedMonthlyGraph": None,
                "sobrietyElectricity": None,
                "sobrietyGas": None,
            },
            "actions": {
                "activateAutomaticData": None,
                "enterMeterReads": None,
                "presentEnergyQuestion": None,
            },
            "details": {
                "contractConfiguration": None,
                "viewedEnergyScoreDetails": None,
                "hasCheckedMonthlyGraphDetails": None,
                "energyQuestionDetails": {
                    "id": None,
                    "answerScoreValue": None,
                    "answerBool": None,
                    "answerLabel": None,
                },
                "consumptionGranularityAvailabilityDetails": {
                    "electricity": {
                        "meterType": None,
                        "automaticDataFlow": None,
                        "hasMeterReadsInCurrentMonth": None,
                        "hasConsumptionDataEndOfMonth": None,
                    },
                    "gas": None,
                },
            },
        },
        id="energy_score",
    ),
    pytest.param(
        parse_ev_service_info,
        {
            "hasRewardableContract": None,
            "customerOnboarded": None,
            "services": [{"type": None, "status": None, "activation": None}],
        },
        id="ev_service_info",
    ),
    pytest.param(
        parse_electric_vehicles,
        {
            "items": [
                {
                    "id": 10001,
                    "vin": None,
                    "active": None,
                    "brandId": None,
                    "year": None,
                    "capabilities": {"chargeState": None, "location": {"isCapable": None}},
                    "chargeState": {
                        "status": None,
                        "chargePower": None,
                        "batteryLevel": None,
                        "range": None,
                        "policyState": None,
                    },
                    "updatedAt": None,
                }
            ]
        },
        id="electric_vehicles",
    ),
    pytest.param(
        parse_vehicle_charge_settings,
        {
            "departureTimes": {"enable": None, "currentValue": {"monday": None}},
            "smartChargingEnabled": None,
            "batteryReserve": {"enable": None, "currentValue": None, "maxValue": None},
            "targetBatteryLevel": None,
            "solarChargingEnabled": None,
            "maxAllowedTargetSoC": None,
        },
        id="vehicle_charge_settings",
    ),
    pytest.param(
        parse_charging_session_details,
        {
            "session": {
                "id": 200001,
                "vehicleName": None,
                "sessionType": None,
                "status": None,
                "start": None,
                "batteryLevelStart": None,
                "cost": None,
                "reward": None,
                "smartChargeOutcome": {"state": None, "offTarget": None},
            },
            "consumptions": [{"kwh": None, "start": None}],
        },
        id="charging_session_details",
    ),
    pytest.param(
        parse_charging_session_charge_settings,
        {"targetBatteryLevel": None, "departureTimeOverride": None, "direct": None},
        id="charging_session_charge_settings",
    ),
    pytest.param(
        parse_charging_sessions_page,
        {
            "page": {"size": None, "totalItems": None, "totalPages": None, "number": None},
            "items": [{"id": None}],
        },
        id="charging_sessions_page",
    ),
    pytest.param(
        parse_charging_sessions_summary,
        {
            "oldestSessionReached": None,
            "items": [
                {
                    "start": "2025-08-01T00:00:00+02:00",
                    "sessionCount": None,
                    "totalConsumptionKwh": None,
                    "managedConsumptionKwh": None,
                    "publicConsumptionKwh": None,
                    "cost": None,
                    "reward": None,
                }
            ],
        },
        id="charging_sessions_summary",
    ),
]


@pytest.mark.parametrize(("parser", "payload"), _NULLED_PAYLOADS)
def test_parsers_survive_explicit_nulls(
    parser: Callable[[dict[str, Any]], object],
    payload: dict[str, Any],
) -> None:
    """Explicit nulls in every numeric/str field parse into defaults or skips."""
    assert parser(payload) is not None


@pytest.mark.parametrize(
    ("ean", "expected"),
    [
        ("541448860000000001_ID1", "541448860000000001"),
        ("541448860000000001", "541448860000000001"),
    ],
)
def test_bare_ean(ean: str, expected: str) -> None:
    assert bare_ean(ean) == expected


def test_ean_with_delivery_point_suffix() -> None:
    assert ean_with_delivery_point_suffix("541448860000000001") == "541448860000000001_ID1"


_MALFORMED_CASES = [
    pytest.param(
        parse_customer_account_relations,
        {
            "items": [
                42,
                {"customerAccount": "not-a-dict"},
                {"customerAccount": {"customerAccountNumber": 5}},
                {"customerAccount": {"customerAccountNumber": ""}},
                {
                    "customerAccount": {
                        "customerAccountNumber": "CAN1",
                        "businessAgreements": [
                            7,
                            {"businessAgreementNumber": 9},
                            {"businessAgreementNumber": ""},
                            {"businessAgreementNumber": "BAN1"},
                        ],
                    }
                },
            ]
        },
        lambda r: (
            len(r.accounts) == 1 and len(r.accounts[0].customer_account.business_agreements) == 1
        ),
        id="relations",
    ),
    pytest.param(
        parse_prices,
        {"items": [5, {"ean": "541448820000000001", "prices": [3, {"from": "2026-01-01"}]}]},
        lambda r: len(r.items) == 1 and len(r.items[0].periods) == 1,
        id="prices",
    ),
    pytest.param(
        parse_energy_contracts,
        {
            "items": [
                None,
                {"businessAgreementNumber": "B1", "productConfiguration": "bad"},
                {
                    "businessAgreementNumber": "B1",
                    "productConfiguration": {"greenLevel": 3, "greenOrigin": ""},
                },
            ]
        },
        lambda r: (
            len(r.items) == 2
            and r.items[0].product_configuration is None
            and r.items[1].product_configuration.green_level is None
            and r.items[1].product_configuration.green_origin is None
        ),
        id="energy_contracts",
    ),
    pytest.param(
        parse_monthly_peaks,
        {
            "year": 2026,
            "month": 4,
            "peakOfTheMonth": "not-a-dict",
            "previousPeakOfTheMonth": {"start": "bad", "end": None},
            "dailyPeaks": [
                "x",
                {
                    "start": "2026-04-02T00:00:00+02:00",
                    "end": "2026-04-02T00:15:00+02:00",
                    "peakKW": 2.0,
                    "peakKWh": 0.5,
                },
            ],
        },
        lambda r: (
            len(r.daily_peaks) == 1
            and r.peak_of_the_month is None
            and r.previous_peak_of_the_month is None
        ),
        id="monthly_peaks",
    ),
    pytest.param(
        parse_account_balance,
        {
            "balance": 12.5,
            "details": {
                "financialTransactions": [
                    1,
                    {"type": "INVOICE", "dueAmount": 10.0, "openAmount": 0.0, "dueDate": 5},
                ]
            },
        },
        lambda r: (
            r.details is not None
            and len(r.details.financial_transactions) == 1
            and r.details.financial_transactions[0].due_date is None
        ),
        id="account_balance",
    ),
    pytest.param(
        parse_epex_prices,
        {
            "timeSeries": [
                {"period": "2026-05-04T00:00:00+02:00", "value": "not-a-number"},
                {"period": "2026-05-04T01:00:00+02:00", "value": 50.0},
            ]
        },
        lambda r: len(r.slots) == 1,
        id="epex_unparseable_value",
    ),
    pytest.param(
        parse_happy_hour_month_report,
        {
            "month": {"noHappyHour": True, "energy": {"gas": "bad"}, "cost": ["bad"]},
            "history": [
                3,
                {"happyHour": "no"},
                {"yearMonth": "not-a-month", "happyHour": {"savedAmount": 1.0}},
                {"yearMonth": "2026-05", "happyHour": {"savedAmount": 1.0}, "gas": "bad"},
            ],
        },
        lambda r: (
            r.current is None and len(r.history) == 1 and r.gas is None and r.history[0].gas is None
        ),
        id="happy_hour_month_report",
    ),
    pytest.param(
        parse_solar_surplus_forecasts,
        {
            "forecasts": [
                1,
                {
                    "date": "2026-05-04",
                    "details": [
                        2,
                        {"startTime": "2026-05-04T10:00:00"},
                        {"startTime": "2026-05-04T11:00:00+02:00", "value": "x", "level": 3},
                    ],
                },
            ]
        },
        lambda r: (
            len(r.forecasts) == 1
            and len(r.forecasts[0].details) == 1
            and r.forecasts[0].details[0].value is None
            and r.forecasts[0].details[0].level is None
        ),
        id="solar_surplus",
    ),
    pytest.param(
        parse_tou_schedules,
        {
            "items": [
                4,
                {"eanWithSuffix": 9},
                {
                    "eanWithSuffix": "541448820000000001_ID1",
                    "gridMeterTimeOfUseSchedules": [
                        {"dgoTgoSchedule": "bad", "combinedSchedule": "bad"},
                        {
                            "combinedSchedule": {
                                "offtake": {
                                    "monday": [
                                        3,
                                        {
                                            "startTime": "00:00",
                                            "endTime": "07:00",
                                            "supplierSlotCode": "OFFPEAK",
                                        },
                                        {
                                            "startTime": "07:00",
                                            "endTime": "22:00",
                                            "supplierSlotCode": "PEAK",
                                            "dgoTgoSlotCode": 4,
                                        },
                                        {
                                            "startTime": "22:00",
                                            "endTime": "00:00",
                                            "supplierSlotCode": "OFFPEAK",
                                            "dgoTgoSlotCode": "OFFPEAK",
                                        },
                                    ],
                                },
                                "injection": "bad",
                            },
                        },
                    ],
                },
            ]
        },
        lambda r: (
            len(r.items) == 1
            and r.items[0].grid_meter_schedules[0].dgo_tgo is None
            and r.items[0].grid_meter_schedules[0].combined is None
            and r.items[0].grid_meter_schedules[1].combined is not None
            and r.items[0].grid_meter_schedules[1].combined.injection is None
            and r.items[0].grid_meter_schedules[1].combined.offtake is not None
            and len(r.items[0].grid_meter_schedules[1].combined.offtake.monday) == 1
        ),
        id="tou_schedules",
    ),
    pytest.param(
        parse_usage_details,
        {
            "items": [
                {
                    "start": "2026-05-04T00:00:00+02:00",
                    "end": "2026-05-04T01:00:00+02:00",
                    "energy": "not-a-dict",
                },
                {
                    "start": "2026-05-04T01:00:00+02:00",
                    "end": "2026-05-04T02:00:00+02:00",
                    "energy": {"electricity": "x", "gas": 5},
                    "costs": "bad",
                    "simulatedEnergy": {"gas": "bad"},
                    "simulatedCosts": ["bad"],
                },
            ]
        },
        lambda r: (
            len(r.items) == 2
            and r.items[0].electricity is None
            and r.items[1].electricity is None
            and r.items[1].gas is None
            and r.items[1].gas_and_electricity_cost is None
            and r.items[1].simulated_gas is None
        ),
        id="usage_details",
    ),
    pytest.param(
        parse_service_points,
        {
            "items": [
                5,
                {"ean": 7},
                {
                    "ean": "541448820000000001",
                    "dataAvailability": {"measured": "bad"},
                    "dataSources": "bad",
                },
            ]
        },
        lambda r: (
            len(r.items) == 1
            and r.items[0].data_availability is None
            and r.items[0].data_sources is None
        ),
        id="service_points",
    ),
    pytest.param(
        parse_meter_reads,
        {
            "items": [
                6,
                {"ean": "541448820000000001", "meterReadDate": "not-a-date"},
                {"ean": "541448820000000001", "meterReadDate": "2026-10-01", "registers": "bad"},
                {
                    "ean": "541448820000000001",
                    "meterReadDate": "2026-10-01",
                    "registers": [8, {"indexRead": "12"}, {"indexRead": True}, {"indexRead": 3}],
                },
            ]
        },
        lambda r: (
            len(r.items) == 1
            and len(r.items[0].registers) == 1
            and r.items[0].registers[0].index_read == 3.0
        ),
        id="meter_reads",
    ),
    pytest.param(
        parse_monthly_billed_budget,
        {
            "from": "not-a-date",
            "alreadyUsedAmount": "bad",
            "payments": [9, {"date": "bad"}, {"status": "PAID"}, {"date": "2024-02-01"}],
        },
        lambda r: (
            r.start_date is None
            and r.already_used_amount == 0.0
            and len(r.payments) == 1
            and r.payments[0].status is None
            and r.skipped_entries == 3
        ),
        id="monthly_billed_budget",
    ),
    pytest.param(
        parse_billing_period_usage,
        {
            "startDate": "bad",
            "endDate": 5,
            "usedAmount": "bad",
            "usedAmountFailureReason": 7,
        },
        lambda r: (
            r.start_date is None
            and r.end_date is None
            and r.used_amount == 0.0
            and r.used_amount_failure_reason is None
        ),
        id="billing_period_usage",
    ),
    pytest.param(
        parse_budget_billing_plan_details,
        {
            "budgetBillingPlan": {
                "remainingSlices": "bad",
                "paymentSlices": [1, {"date": "bad"}, {"date": "2024-01-01", "status": "PAID"}],
            },
            "bbpUpdateLimits": "bad",
            "bbpProposal": {"evaluationContext": [2, {"event": "INDEX", "weight": "bad"}]},
            "periodDetailsPerContract": [
                3,
                {"budgetBillingPlan": {"slices": [{"status": "PAID"}]}, "bbpProposal": "bad"},
            ],
        },
        lambda r: (
            r.plan is not None
            and r.plan.remaining_slices == 0
            and len(r.plan.payment_slices) == 1
            and r.update_limits is None
            and r.proposal is not None
            and len(r.proposal.evaluation_context) == 1
            and r.proposal.evaluation_context[0].weight == 0.0
            and len(r.contract_periods) == 1
            and r.contract_periods[0].proposal is None
            and r.contract_periods[0].plan is not None
            and r.contract_periods[0].plan.payment_slices == ()
            and r.skipped_entries == 5
        ),
        id="budget_billing_plan",
    ),
    pytest.param(
        parse_happy_hour_eligibility,
        {"eligible": "true", "reasons": ["OTHER", 4, None, ""]},
        lambda r: r.eligible is None and r.reasons == ("OTHER",) and r.skipped_entries == 3,
        id="happy_hour_eligibility",
    ),
    pytest.param(
        parse_happy_hour_service_status,
        {"status": 5, "statusDate": "2024-05-01T09:15:00"},
        lambda r: r.status is None and r.status_date is None,
        id="happy_hour_service_status",
    ),
    pytest.param(
        parse_energy_score,
        {
            "score": 3,
            "lastUpdated": "not-a-date",
            "scoring": {"consumptionAvailability": "true", "sobrietyGas": 1},
            "actions": [],
            "details": {
                "contractConfiguration": "",
                "energyQuestionDetails": "Ja",
                "consumptionGranularityAvailabilityDetails": {
                    "electricity": ["DIGITAL"],
                    "gas": {"meterType": 7, "hasMeterReadsInCurrentMonth": "no"},
                },
            },
        },
        lambda r: (
            r.score is None
            and r.last_updated is None
            and r.criteria == EnergyScoreCriteria()
            and r.actions is None
            and r.details.contract_configuration is None
            and r.details.energy_question is None
            and r.details.electricity is None
            and r.details.gas == EnergyScoreDataAvailability()
        ),
        id="energy_score",
    ),
    pytest.param(
        parse_ev_service_info,
        {
            "hasRewardableContract": "yes",
            "services": [
                "SMART_CHARGE",
                {"status": "ACTIVE"},
                {"type": "SMART_CHARGE", "activation": "2025-06-12T13:33:06"},
            ],
        },
        lambda r: (
            r.has_rewardable_contract is None
            and r.services == (EvService(type="SMART_CHARGE"),)
            and r.skipped_entries == 2
        ),
        id="ev_service_info",
    ),
    pytest.param(
        parse_electric_vehicles,
        {
            "items": [
                {"id": "10001"},
                {"id": True},
                {
                    "id": 10002,
                    "capabilities": [],
                    "chargeState": "UNPLUGGED",
                    "createdAt": "2025-06-12T15:33:03",
                },
            ]
        },
        lambda r: r.items == (ElectricVehicle(id=10002),) and r.skipped_entries == 2,
        id="electric_vehicles",
    ),
    pytest.param(
        parse_vehicle_charge_settings,
        {
            "departureTimes": {
                "enable": 1,
                "currentValue": {"monday": "7h", "tuesday": "25:00", "wednesday": "07:30"},
            },
            "batteryReserve": "20",
            "targetBatteryLevel": {"currentValue": "eighty"},
            "smartChargingEnabled": "true",
        },
        lambda r: (
            r.departure_times == DepartureTimes(wednesday=time(7, 30))
            and r.battery_reserve is None
            and r.target_battery_level == ChargeSettingValue(current_value=0)
            and r.smart_charging_enabled is None
        ),
        id="vehicle_charge_settings",
    ),
    pytest.param(
        parse_charging_session_details,
        {
            "session": {
                "id": 200001,
                "start": "2025-06-14T11:43:32",
                "smartChargeOutcome": {"state": "OFF_TARGET", "offTarget": [21]},
            },
            "consumptions": [
                {"kwh": "2.86", "start": "2025-06-14T11:00:00+02:00"},
                {"kwh": True, "start": "2025-06-14T11:00:00+02:00"},
                {"kwh": 2.5, "start": "2025-06-14T12:00:00"},
                {"kwh": 1, "start": "2025-06-14T13:00:00+02:00"},
            ],
        },
        lambda r: (
            r.session
            == ChargingSession(
                id=200001, smart_charge_outcome=SmartChargeOutcome(state="off_target")
            )
            and r.consumptions
            == (
                ChargingSessionConsumption(
                    start=datetime(2025, 6, 14, 13, tzinfo=timezone(timedelta(hours=2))),
                    kwh=1.0,
                ),
            )
            and r.skipped_entries == 3
        ),
        id="charging_session_details",
    ),
    pytest.param(
        parse_charging_session_details,
        {"session": {"id": "200001"}, "consumptions": "none"},
        lambda r: r == ChargingSessionDetails(),
        id="charging_session_details_bad_session_id",
    ),
    pytest.param(
        parse_charging_session_charge_settings,
        {"targetBatteryLevel": "high", "departureTimeOverride": "2025-08-07T05:00:00", "direct": 0},
        lambda r: r == ChargingSessionChargeSettings(target_battery_level=0),
        id="charging_session_charge_settings",
    ),
    pytest.param(
        parse_charging_sessions_page,
        {"page": [0, 20], "items": [{"id": 200001}, "200002", {"id": None}]},
        lambda r: r == ChargingSessionsPage(items=(ChargingSession(id=200001),), skipped_entries=2),
        id="charging_sessions_page",
    ),
    pytest.param(
        parse_charging_sessions_summary,
        {
            "oldestSessionReached": "true",
            "items": [
                {"start": "2025-08-01", "sessionCount": 2},
                {"start": "2025-07-01T00:00:00+02:00", "sessionCount": "11", "cost": "free"},
            ],
        },
        lambda r: (
            r.oldest_session_reached is None
            and r.items
            == (
                ChargingSessionsSummaryEntry(
                    start=datetime(2025, 7, 1, tzinfo=timezone(timedelta(hours=2))),
                    session_count=11,
                    cost=0.0,
                ),
            )
            and r.skipped_entries == 1
        ),
        id="charging_sessions_summary",
    ),
]


@pytest.mark.parametrize(("parser", "payload", "check"), _MALFORMED_CASES)
def test_parsers_drop_malformed_entries(
    parser: Callable[[dict[str, Any]], Any],
    payload: dict[str, Any],
    check: Callable[[Any], bool],
) -> None:
    """Malformed entries are skipped; valid siblings survive; nothing raises."""
    assert check(parser(payload))


def test_parse_prices_counts_skipped_price_slots(caplog: pytest.LogCaptureFixture) -> None:
    """Non-dict proportional-price slots are dropped, counted, and debug-logged."""
    data = {
        "items": [
            {
                "ean": "541448820000000001",
                "prices": [
                    {
                        "from": "2026-01-01",
                        "to": "2026-02-01",
                        "proportionalPriceConfigurations": {
                            "offtake": [
                                "not-a-dict",
                                None,
                                {
                                    "timeOfUseSlotCode": "HIGH",
                                    "priceValue": 0.12,
                                    "priceValueExclVAT": 0.10,
                                },
                            ]
                        },
                    }
                ],
            }
        ]
    }
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium"):
        result = parse_prices(data)
    assert len(result.items[0].periods[0].offtake) == 1
    assert "skipped 2 malformed price slot entries" in caplog.text


def test_parse_tou_schedules_counts_skipped_tou_slots(caplog: pytest.LogCaptureFixture) -> None:
    """TOU slots with wrong-typed fields are dropped, counted, and debug-logged."""
    data = {
        "items": [
            {
                "eanWithSuffix": "541448820000000001_ID1",
                "gridMeterTimeOfUseSchedules": [
                    {
                        "dgoTgoSchedule": {
                            "offtake": {
                                "monday": [
                                    {"startTime": "00:00", "endTime": "07:00", "slotCode": 3},
                                    {"startTime": None, "endTime": "22:00", "slotCode": "high"},
                                    {"startTime": "07:00", "endTime": "22:00", "slotCode": "HIGH"},
                                ]
                            }
                        },
                    }
                ],
            }
        ]
    }
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium"):
        result = parse_tou_schedules(data)
    schedule = result.items[0].grid_meter_schedules[0].dgo_tgo
    assert schedule is not None
    offtake = schedule.offtake
    assert offtake is not None
    assert len(offtake.monday) == 1
    assert offtake.monday[0].slot_code == "high"
    assert "skipped 2 malformed TOU slot entries" in caplog.text


def test_parse_happy_hour_event_counts_skipped_windows(caplog: pytest.LogCaptureFixture) -> None:
    """A present-but-malformed window is dropped, counted, and debug-logged."""
    data = {
        "today": "not-a-window",
        "tomorrow": {
            "startTime": "2026-07-31T18:00:00+02:00",
            "endTime": "2026-07-31T19:00:00+02:00",
        },
    }
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium"):
        result = parse_happy_hour_event(data)
    assert len(result.windows) == 1
    assert "skipped 1 malformed happy hour window entries" in caplog.text


def test_parse_happy_hour_event_absent_window_is_not_a_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing or null today/tomorrow key is a no-event state, not a counted skip."""
    data = {
        "today": {
            "startTime": "2026-07-30T18:00:00+02:00",
            "endTime": "2026-07-30T19:00:00+02:00",
        },
        "tomorrow": None,
    }
    with caplog.at_level(logging.DEBUG, logger="aioengiebelgium"):
        result = parse_happy_hour_event(data)
    assert len(result.windows) == 1
    assert "skipped" not in caplog.text


def test_parse_epex_prices_reports_observed_spacing_over_requested() -> None:
    data = {
        "timeSeries": [
            {"period": "2026-05-04T00:00:00+02:00", "value": 40.0},
            {"period": "2026-05-04T00:30:00+02:00", "value": 50.0},
            {"period": "2026-05-04T01:00:00+02:00", "value": 60.0},
        ]
    }
    result = parse_epex_prices(data, granularity_minutes=60)
    assert result.slot_duration == timedelta(minutes=30)
    assert result.slots[-1].end == result.slots[-1].start + timedelta(minutes=30)


def _epex_day(base_utc: datetime, hours: int) -> dict[str, Any]:
    brussels = ZoneInfo("Europe/Brussels")
    return {
        "timeSeries": [
            {
                "period": (base_utc + timedelta(hours=i)).astimezone(brussels).isoformat(),
                "value": 50.0,
            }
            for i in range(hours)
        ]
    }


@pytest.mark.parametrize(
    ("base_utc", "hours"),
    [
        pytest.param(datetime(2026, 10, 24, 22, 0, tzinfo=UTC), 25, id="fallback_25h"),
        pytest.param(datetime(2026, 3, 28, 23, 0, tzinfo=UTC), 23, id="springforward_23h"),
    ],
)
def test_parse_epex_prices_dst_transition_days(base_utc: datetime, hours: int) -> None:
    """A 25h fall-back day and a 23h spring-forward day keep hourly slots contiguous."""
    result = parse_epex_prices(_epex_day(base_utc, hours))

    assert len(result.slots) == hours
    assert result.slot_duration == timedelta(hours=1)
    for current, nxt in pairwise(result.slots):
        assert current.end == nxt.start
    last = result.slots[-1]
    assert last.end - last.start == timedelta(hours=1)


def test_parse_prices_counts_skipped_entries() -> None:
    result = parse_prices({"items": [{"ean": "541448820000000001_ID1"}, "bogus"]})
    assert len(result.items) == 1
    assert result.skipped_entries == 1


def test_parse_energy_contracts_counts_skipped_entries() -> None:
    result = parse_energy_contracts({"items": [{"status": "ACTIVE"}, None]})
    assert len(result.items) == 1
    assert result.skipped_entries == 1


def test_parse_customer_account_relations_counts_skipped_entries() -> None:
    result = parse_customer_account_relations(
        {
            "items": [
                {"customerAccount": {"customerAccountNumber": "CA1"}},
                {"admin": True},
            ]
        }
    )
    assert len(result.accounts) == 1
    assert result.skipped_entries == 1


def test_parse_monthly_peaks_counts_skipped_entries() -> None:
    result = parse_monthly_peaks(
        {
            "year": 2026,
            "month": 4,
            "dailyPeaks": [
                {"start": "2026-04-01T00:00:00", "end": "2026-04-01T00:15:00"},
                {
                    "start": "2026-04-02T00:00:00+02:00",
                    "end": "2026-04-02T00:15:00+02:00",
                },
            ],
        }
    )
    assert len(result.daily_peaks) == 1
    assert result.skipped_entries == 1


def test_parse_epex_prices_counts_skipped_entries() -> None:
    result = parse_epex_prices(
        {
            "timeSeries": [
                {"period": "2026-05-04T00:00:00+02:00", "value": 50.0},
                {"period": "bogus", "value": 60.0},
            ]
        }
    )
    assert len(result.slots) == 1
    assert result.skipped_entries == 1


def test_parse_happy_hour_event_counts_skipped_entries() -> None:
    result = parse_happy_hour_event(
        {
            "today": {
                "startTime": "2026-07-30T18:00:00+02:00",
                "endTime": "2026-07-30T19:00:00+02:00",
            },
            "tomorrow": {"startTime": "bogus", "endTime": "also-bogus"},
        }
    )
    assert len(result.windows) == 1
    assert result.skipped_entries == 1


def test_parse_happy_hour_month_report_counts_skipped_entries() -> None:
    result = parse_happy_hour_month_report(
        {"history": [{"yearMonth": "2026-05"}, {"yearMonth": "bogus"}]}
    )
    assert len(result.history) == 1
    assert result.skipped_entries == 1


def test_parse_solar_surplus_forecasts_counts_skipped_entries() -> None:
    result = parse_solar_surplus_forecasts({"forecasts": [{"forecastDate": "2026-07-08"}, "bogus"]})
    assert len(result.forecasts) == 1
    assert result.skipped_entries == 1


def test_parse_tou_schedules_counts_skipped_entries() -> None:
    result = parse_tou_schedules(
        {"items": [{"eanWithSuffix": "541448820070000000_ID1"}, {"eanWithSuffix": 42}]}
    )
    assert len(result.items) == 1
    assert result.skipped_entries == 1


def test_parse_usage_details_counts_skipped_entries() -> None:
    result = parse_usage_details(
        {
            "items": [
                {"start": "2026-05-04T00:00:00+02:00", "end": "2026-05-04T01:00:00+02:00"},
                {"start": "2026-05-04T01:00:00", "end": "2026-05-04T02:00:00"},
            ]
        }
    )
    assert len(result.items) == 1
    assert result.skipped_entries == 1


@pytest.mark.parametrize(
    ("parser", "fixture_name"),
    [
        pytest.param(parse_prices, "prices_sample.json", id="prices"),
        pytest.param(
            parse_energy_contracts,
            "energy_contracts_dynamic_plus_fixed_gas.json",
            id="energy_contracts",
        ),
        pytest.param(
            parse_customer_account_relations,
            "customer_account_relations_sample.json",
            id="customer_account_relations",
        ),
        pytest.param(parse_monthly_peaks, "peaks_2026_04.json", id="monthly_peaks"),
        pytest.param(parse_happy_hour_event, "happy_hour_event.json", id="happy_hour_event"),
        pytest.param(
            parse_happy_hour_month_report,
            "happy_hour_month_report.json",
            id="happy_hour_month_report",
        ),
        pytest.param(parse_usage_details, "usage_details_hourly.json", id="usage_details"),
        pytest.param(
            parse_solar_surplus_forecasts,
            "solar_surplus_high.json",
            id="solar_surplus_forecasts",
        ),
        pytest.param(parse_tou_schedules, "tou_schedules_bihoraire.json", id="tou_schedules"),
        pytest.param(parse_epex_prices, "epex_24h.json", id="epex_prices"),
        pytest.param(parse_service_points, "service_points_dual_fuel.json", id="service_points"),
        pytest.param(parse_meter_reads, "meter_reads_history.json", id="meter_reads"),
        pytest.param(
            parse_monthly_billed_budget,
            "monthly_billed_budget.json",
            id="monthly_billed_budget",
        ),
        pytest.param(
            parse_budget_billing_plan_details,
            "budget_billing_plan_monthly.json",
            id="budget_billing_plan",
        ),
        pytest.param(
            parse_happy_hour_eligibility,
            "happy_hour_eligibility_not_eligible.json",
            id="happy_hour_eligibility",
        ),
        pytest.param(
            parse_ev_service_info,
            "ev_services_smart_charge_active.json",
            id="ev_service_info",
        ),
        pytest.param(parse_electric_vehicles, "electric_vehicles.json", id="electric_vehicles"),
        pytest.param(
            parse_charging_session_details,
            "latest_charging_session.json",
            id="latest_charging_session",
        ),
        pytest.param(
            parse_charging_session_details,
            "charging_session_smart_on_target.json",
            id="charging_session",
        ),
        pytest.param(
            parse_charging_sessions_page,
            "charging_sessions_last_page.json",
            id="charging_sessions_page",
        ),
        pytest.param(
            parse_charging_sessions_summary,
            "charging_sessions_summary.json",
            id="charging_sessions_summary",
        ),
    ],
)
def test_clean_payloads_have_zero_skipped_entries(
    parser: Callable[[dict[str, Any]], Any],
    fixture_name: str,
    load_fixture: LoadFixture,
) -> None:
    """Real captured payloads parse without dropping any entry."""
    assert parser(load_fixture(fixture_name)).skipped_entries == 0


def test_parse_service_points_counts_skipped_entries() -> None:
    result = parse_service_points({"items": [{"ean": "541448820000000001"}, {"division": "GAS"}]})
    assert len(result.items) == 1
    assert result.skipped_entries == 1


def test_parse_service_points_maps_source_specific_status_fields() -> None:
    result = parse_service_points(
        {
            "items": [
                {
                    "ean": "541448820000000001",
                    "dataSources": {
                        "p1": {"dongleStatus": "NOT_CONFIGURED"},
                        "p4": {"mandateStatus": "ACTIVE"},
                        "meterReads": {"status": "NOT_AVAILABLE"},
                        "billing": {"type": "SMR3", "upgradableTo": "SMR1"},
                        "imv": {"mandateStatus": "ACTIVE"},
                    },
                }
            ]
        }
    )
    sources = result.items[0].data_sources
    assert sources is not None
    assert sources.p1 is not None
    assert sources.p1.status == "NOT_CONFIGURED"
    assert sources.p4 is not None
    assert sources.p4.status == "ACTIVE"
    assert sources.meter_reads is not None
    assert sources.meter_reads.status == "NOT_AVAILABLE"
    assert sources.billing is not None
    assert (sources.billing.status, sources.billing.type, sources.billing.upgradable_to) == (
        None,
        "SMR3",
        "SMR1",
    )
    assert sources.imv is not None
    assert sources.imv.status is None


def test_parse_service_points_dual_fuel_fixture(load_fixture: LoadFixture) -> None:
    result = parse_service_points(load_fixture("service_points_dual_fuel.json"))
    assert {item.division for item in result.items} == {"ELECTRICITY", "GAS"}
    for item in result.items:
        assert item.data_availability is not None
        assert item.data_availability.daily is not None
        assert item.data_availability.daily.start is not None
        assert item.data_availability.daily.start.tzinfo is not None


def test_parse_meter_reads_counts_skipped_entries() -> None:
    result = parse_meter_reads(
        {"items": [{"ean": "541448820000000001", "meterReadDate": "2026-10-01"}, {"ean": "x"}]}
    )
    assert len(result.items) == 1
    assert result.skipped_entries == 1


def test_parse_meter_reads_drops_read_whose_registers_are_all_malformed() -> None:
    result = parse_meter_reads(
        {
            "items": [
                {
                    "ean": "541448820000000001",
                    "meterReadDate": "2026-10-01",
                    "registers": [{"indexRead": None}, 4],
                },
                {"ean": "541448820000000001", "meterReadDate": "2026-10-02", "registers": []},
            ]
        }
    )
    assert [read.read_date for read in result.items] == [date(2026, 10, 2)]
    assert result.skipped_entries == 1


def test_parse_meter_reads_history_fixture_keeps_both_origins(load_fixture: LoadFixture) -> None:
    result = parse_meter_reads(load_fixture("meter_reads_history.json"))
    assert {read.origin for read in result.items} == {"OFFICIAL", "INFORMATIVE"}
    assert {read.division for read in result.items} == {"ELECTRICITY", "GAS"}


def test_parse_meter_reads_latest_fixture_keeps_index_ranges(load_fixture: LoadFixture) -> None:
    result = parse_meter_reads(load_fixture("meter_reads_latest.json"))
    registers = [register for read in result.items for register in read.registers]
    assert registers
    assert all(register.minimum_index_read_range is not None for register in registers)
    assert all(register.maximum_index_read_range is not None for register in registers)
    assert {register.unit for register in registers} <= {"KWH", "M_3"}


def test_parse_monthly_billed_budget_fixture(load_fixture: LoadFixture) -> None:
    result = parse_monthly_billed_budget(load_fixture("monthly_billed_budget.json"))
    assert (result.start_date, result.end_date) == (date(2024, 1, 1), date(2024, 12, 31))
    assert len(result.payments) == 12
    assert {payment.status for payment in result.payments} == {"PAID", "INVOICED", "NOT_INVOICED"}
    assert result.already_used_amount is not None
    assert result.expected_cost_amount is not None
    assert result.already_used_amount_ratio == pytest.approx(
        result.already_used_amount / result.expected_cost_amount, abs=0.005
    )


def test_parse_monthly_billed_budget_empty_payload() -> None:
    result = parse_monthly_billed_budget({})
    assert result.payments == ()
    assert result.expected_cost_amount is None
    assert result.skipped_entries == 0


def test_parse_billing_period_usage_fixture(load_fixture: LoadFixture) -> None:
    result = parse_billing_period_usage(load_fixture("billing_period_usage.json"))
    assert (result.start_date, result.end_date) == (date(2023, 11, 9), date(2024, 11, 11))
    assert result.used_amount is not None
    assert result.expected_year_invoice is not None
    assert result.used_amount_ratio == pytest.approx(
        result.used_amount / result.expected_year_invoice, abs=0.005
    )
    assert result.used_amount_failure_reason is None


def test_parse_billing_period_usage_failure_reason_only(load_fixture: LoadFixture) -> None:
    result = parse_billing_period_usage(load_fixture("billing_period_usage_missing_data.json"))
    assert result == BillingPeriodUsage(used_amount_failure_reason="MISSING_DATA")


def test_parse_budget_billing_plan_monthly_fixture(load_fixture: LoadFixture) -> None:
    result = parse_budget_billing_plan_details(load_fixture("budget_billing_plan_monthly.json"))
    assert result.plan is not None
    assert result.plan.billing_cycle == "MONTHLY"
    assert {s.status for s in result.plan.payment_slices} == {"PAID", "NOT_INVOICED"}
    paid = [s for s in result.plan.payment_slices if s.status == "PAID"]
    assert result.plan.current_amount is not None
    assert result.plan.amount_paid == pytest.approx(len(paid) * result.plan.current_amount)
    assert result.proposal is not None
    assert [f.event for f in result.proposal.evaluation_context] == ["CONTRACT", "INDEX"]
    assert result.proposal.evaluation_context[0].weight == 0.0
    (period,) = result.contract_periods
    assert period.division == "ELECTRICITY"
    assert period.plan is not None
    assert len(period.plan.payment_slices) == len(result.plan.payment_slices)


def test_parse_budget_billing_plan_null_payment_slices_fall_back_to_slices() -> None:
    """A null paymentSlices key falls back to the per-contract slices key."""
    result = parse_budget_billing_plan_details(
        {"budgetBillingPlan": {"paymentSlices": None, "slices": [{"date": "2024-01-11"}]}}
    )
    assert result.plan is not None
    assert [s.payment_date for s in result.plan.payment_slices] == [date(2024, 1, 11)]


def test_parse_budget_billing_plan_flags_only_fixture(load_fixture: LoadFixture) -> None:
    result = parse_budget_billing_plan_details(load_fixture("budget_billing_plan_flags_only.json"))
    assert result.plan is None
    assert result.proposal is None
    assert result.update_limits is None
    assert result.plan_updatable is False
    assert result.contract_periods == ()
    assert result.skipped_entries == 0


def test_parse_happy_hour_eligibility_fixtures(load_fixture: LoadFixture) -> None:
    eligible = parse_happy_hour_eligibility(load_fixture("happy_hour_eligibility_eligible.json"))
    assert eligible == HappyHourEligibility(eligible=True)
    blocked = parse_happy_hour_eligibility(load_fixture("happy_hour_eligibility_not_eligible.json"))
    assert blocked.eligible is False
    assert blocked.reasons == ("OTHER", "WRONG_CONTRACT_TYPE")


def test_parse_happy_hour_service_status_fixtures(load_fixture: LoadFixture) -> None:
    active = parse_happy_hour_service_status(load_fixture("happy_hour_service_active.json"))
    assert active.status == "ACTIVE"
    assert active.status_date is not None
    assert active.status_date.utcoffset() == timedelta(hours=2)
    never = parse_happy_hour_service_status(load_fixture("happy_hour_service_not_activated.json"))
    assert never == HappyHourServiceStatus(status="NOT_ACTIVATED")


def test_parse_energy_score_single_fixture(load_fixture: LoadFixture) -> None:
    result = parse_energy_score(load_fixture("energy_score_single.json"))
    assert result == EnergyScore(
        business_agreement_number="000000000001",
        score="A",
        last_updated=date(2024, 10, 2),
        criteria=EnergyScoreCriteria(
            consumption_availability=True,
            energy_question=True,
            has_checked_monthly_graph=True,
            sobriety_electricity=True,
        ),
        actions=EnergyScoreActions(
            activate_automatic_data=False,
            enter_meter_reads=False,
            present_energy_question=False,
        ),
        details=EnergyScoreDetails(
            contract_configuration="SINGLE",
            viewed_energy_score_details=True,
            has_checked_monthly_graph_details=True,
            energy_question=EnergyScoreQuestionAnswer(
                question_id=11, answer_score_value=1, answer_bool=True, answer_label="Ja"
            ),
            electricity=EnergyScoreDataAvailability(
                meter_type="DIGITAL",
                automatic_data_flow="YES",
                has_meter_reads_in_current_month=True,
                has_consumption_data_end_of_month=True,
            ),
        ),
    )


def test_parse_energy_score_dual_fixture(load_fixture: LoadFixture) -> None:
    result = parse_energy_score(load_fixture("energy_score_dual.json"))
    assert result.score == "C"
    assert result.criteria is not None
    assert result.criteria.energy_question is False
    assert result.criteria.sobriety_gas is True
    assert result.actions is not None
    assert result.actions.present_energy_question is True
    assert result.details is not None
    assert result.details.contract_configuration == "DUAL"
    assert result.details.viewed_energy_score_details is False
    assert result.details.energy_question is None
    assert result.details.has_checked_monthly_graph_details is None
    assert result.details.gas is not None
    assert result.details.gas.has_consumption_data_end_of_month is False


@pytest.mark.parametrize(
    ("fixture_name", "absent"),
    [
        pytest.param("energy_score_single.json", "sobriety_gas", id="single_has_no_gas"),
        pytest.param("energy_score_dual.json", "has_checked_monthly_graph", id="dual_has_no_graph"),
    ],
)
def test_parse_energy_score_absent_criteria_are_none(
    fixture_name: str, absent: str, load_fixture: LoadFixture
) -> None:
    """A criterion missing from the payload does not count for the contract, so it is None."""
    criteria = parse_energy_score(load_fixture(fixture_name)).criteria
    assert criteria is not None
    assert getattr(criteria, absent) is None


def test_parse_energy_score_empty_payload() -> None:
    assert parse_energy_score({}) == EnergyScore()


@pytest.mark.parametrize("block", ["scoring", "actions", "details"])
@pytest.mark.parametrize("value", [None, "bad"], ids=["null", "not_a_dict"])
def test_parse_energy_score_absent_block_is_none(
    block: str, value: object, load_fixture: LoadFixture
) -> None:
    payload = load_fixture("energy_score_single.json") | {block: value}
    result = parse_energy_score(payload)
    field = {"scoring": "criteria", "actions": "actions", "details": "details"}[block]
    assert getattr(result, field) is None


def test_parse_ev_service_info_active_fixture(load_fixture: LoadFixture) -> None:
    result = parse_ev_service_info(load_fixture("ev_services_smart_charge_active.json"))
    assert result == EvServiceInfo(
        has_rewardable_contract=True,
        customer_onboarded=True,
        services=(
            EvService(
                type="SMART_CHARGE",
                status="ACTIVE",
                activation=datetime(2025, 6, 12, 13, 33, 6, 507231, tzinfo=UTC),
            ),
        ),
    )


def test_parse_ev_service_info_not_onboarded_fixture(load_fixture: LoadFixture) -> None:
    result = parse_ev_service_info(load_fixture("ev_services_not_onboarded.json"))
    assert result == EvServiceInfo(has_rewardable_contract=False, customer_onboarded=False)


def test_parse_ev_service_info_empty_payload() -> None:
    assert parse_ev_service_info({}) == EvServiceInfo()


def test_parse_electric_vehicles_fixture(load_fixture: LoadFixture) -> None:
    result = parse_electric_vehicles(load_fixture("electric_vehicles.json"))
    cest = timezone(timedelta(hours=2))
    assert result == ElectricVehiclesResponse(
        items=(
            ElectricVehicle(
                id=10001,
                vin="WVWZZZE1ZZP000001",
                active=True,
                reachable=True,
                model_name="ID.3",
                display_name="ID.3",
                brand_name="Volkswagen",
                brand_id=63,
                brand_logo_url="https://www.engie.be/dam/app/ev/vehicles-brands/volkswagen.png",
                year=2024,
                capabilities=VehicleCapabilities(
                    information=True,
                    charge_state=True,
                    location=True,
                    odometer=True,
                    set_max_current=False,
                    start_charging=True,
                    stop_charging=True,
                    smart_charging=True,
                ),
                charge_state=VehicleChargeState(
                    status="unplugged",
                    updated_at=datetime(2025, 8, 4, 16, 26, 52, tzinfo=UTC),
                    charge_power=0.0,
                    battery_level=83,
                    max_battery_level=100,
                    range=288,
                    policy_state="schedule",
                    session_has_error=False,
                    business_agreement_number="000000000001",
                ),
                updated_at=datetime(2025, 8, 6, 7, 29, 41, 711043, tzinfo=cest),
                created_at=datetime(2025, 6, 12, 15, 33, 3, 569782, tzinfo=cest),
            ),
        ),
    )


def test_parse_electric_vehicles_vocab_matches_enums(load_fixture: LoadFixture) -> None:
    (vehicle,) = parse_electric_vehicles(load_fixture("electric_vehicles.json")).items
    assert vehicle.charge_state is not None
    assert vehicle.charge_state.status == VehicleChargeStatus.UNPLUGGED
    assert vehicle.charge_state.policy_state == VehiclePolicyState.SCHEDULE


def test_parse_electric_vehicles_empty_fixture(load_fixture: LoadFixture) -> None:
    assert parse_electric_vehicles(load_fixture("electric_vehicles_empty.json")) == (
        ElectricVehiclesResponse()
    )


def test_parse_vehicle_charge_settings_fixture(load_fixture: LoadFixture) -> None:
    result = parse_vehicle_charge_settings(load_fixture("vehicle_charge_settings.json"))
    seven = time(7, 0)
    assert result == VehicleChargeSettings(
        departure_times=DepartureTimes(
            mode="native",
            monday=seven,
            tuesday=seven,
            wednesday=seven,
            thursday=seven,
            friday=seven,
            saturday=seven,
            sunday=seven,
        ),
        smart_charging_enabled=True,
        solar_charging_enabled=True,
        battery_reserve=ChargeSettingValue(
            mode="native", current_value=20, min_value=0, max_value=20
        ),
        target_battery_level=ChargeSettingValue(
            mode="native", current_value=80, min_value=0, max_value=100
        ),
        max_target_battery_level=100,
    )
    assert result.battery_reserve is not None
    assert result.battery_reserve.mode == ChargeSettingMode.NATIVE


def test_parse_vehicle_charge_settings_empty_payload() -> None:
    assert parse_vehicle_charge_settings({}) == VehicleChargeSettings()


def test_parse_latest_charging_session_unknown_status_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_session_details(load_fixture("latest_charging_session.json"))
    assert result == ChargingSessionDetails(
        session=ChargingSession(
            id=200004,
            vehicle_name="ID.3",
            session_type="smart_charging",
            status="unknown",
            source="enode",
            battery_level_start=0,
            total_consumption_kwh=0.0,
            cost=0.0,
            business_agreement_number="000000000001",
            updated_at=datetime(2025, 8, 6, 7, 4, 28, 121713, tzinfo=timezone(timedelta(hours=2))),
        ),
    )
    assert result.session is not None
    assert result.session.status == ChargingSessionStatus.UNKNOWN
    assert result.session.session_type == ChargingSessionType.SMART_CHARGING
    assert result.session.source == ChargingSessionSource.ENODE


def test_parse_charging_session_details_without_session_object() -> None:
    assert parse_charging_session_details({"session": None}) == ChargingSessionDetails()


def test_parse_latest_charging_session_charge_settings_fixture(
    load_fixture: LoadFixture,
) -> None:
    result = parse_charging_session_charge_settings(
        load_fixture("latest_charging_session_charge_settings.json")
    )
    assert result == ChargingSessionChargeSettings(
        target_battery_level=80,
        departure_time_override=datetime(2025, 8, 7, 5, 0, tzinfo=UTC),
        direct=False,
    )


_CEST = timezone(timedelta(hours=2))


def test_parse_charging_session_smart_off_target_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_session_details(load_fixture("charging_session_smart_off_target.json"))
    assert result == ChargingSessionDetails(
        session=ChargingSession(
            id=200001,
            vehicle_name="ID.3",
            session_type="smart_charging",
            status="ended",
            source="enode",
            start=datetime(2025, 6, 14, 11, 43, 32, 817000, tzinfo=_CEST),
            end=datetime(2025, 6, 14, 12, 20, 20, 923000, tzinfo=_CEST),
            battery_level_start=11,
            battery_level_end=21,
            total_consumption_kwh=5.36,
            cost=1.691833101287766,
            reward=0.08,
            business_agreement_number="000000000001",
            smart_charge_outcome=SmartChargeOutcome(
                state="off_target", battery_level_at_ready_by=21
            ),
            updated_at=datetime(2025, 6, 14, 12, 23, 3, 295990, tzinfo=_CEST),
        ),
        consumptions=(
            ChargingSessionConsumption(start=datetime(2025, 6, 14, 11, tzinfo=_CEST), kwh=2.86),
            ChargingSessionConsumption(start=datetime(2025, 6, 14, 12, tzinfo=_CEST), kwh=2.5),
        ),
    )


def test_parse_charging_session_on_target_has_empty_off_target(load_fixture: LoadFixture) -> None:
    result = parse_charging_session_details(load_fixture("charging_session_smart_on_target.json"))
    assert result.session is not None
    assert result.session.smart_charge_outcome == SmartChargeOutcome(state="on_target")
    assert result.session.smart_charge_outcome.state == SmartChargeOutcomeState.ON_TARGET
    assert len(result.consumptions) == 9
    assert {c.kwh for c in result.consumptions} == {0.0}


def test_parse_charging_session_public_has_no_smart_charge_fields(
    load_fixture: LoadFixture,
) -> None:
    result = parse_charging_session_details(load_fixture("charging_session_public.json"))
    assert result.session is not None
    assert result.session.session_type == ChargingSessionType.PUBLIC
    assert result.session.status == ChargingSessionStatus.ENDED
    assert result.session.smart_charge_outcome is None
    assert result.session.business_agreement_number is None
    assert result.session.reward is None


def test_parse_charging_sessions_last_page_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_sessions_page(load_fixture("charging_sessions_last_page.json"))
    assert (result.page_number, result.page_size, result.total_items, result.total_pages) == (
        1,
        20,
        22,
        2,
    )
    assert [s.id for s in result.items] == [200003, 200001]
    assert [s.session_type for s in result.items] == ["public", "smart_charging"]


def test_parse_charging_sessions_empty_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_sessions_page(load_fixture("charging_sessions_empty.json"))
    assert result == ChargingSessionsPage(page_number=0, page_size=20, total_items=0, total_pages=0)


def test_parse_charging_sessions_summary_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_sessions_summary(load_fixture("charging_sessions_summary.json"))
    assert result.oldest_session_reached is True
    assert [entry.start for entry in result.items] == [
        datetime(2025, 8, 1, tzinfo=_CEST),
        datetime(2025, 7, 1, tzinfo=_CEST),
        datetime(2025, 6, 1, tzinfo=_CEST),
    ]
    assert result.items[2] == ChargingSessionsSummaryEntry(
        start=datetime(2025, 6, 1, tzinfo=_CEST),
        session_count=9,
        total_consumption_kwh=123.24,
        managed_consumption_kwh=19.3,
        public_consumption_kwh=103.94,
        cost=6.090599164530949,
        reward=0.29,
    )
    assert result.items[0].reward is None


def test_parse_charging_sessions_summary_empty_fixture(load_fixture: LoadFixture) -> None:
    result = parse_charging_sessions_summary(load_fixture("charging_sessions_summary_empty.json"))
    assert result == ChargingSessionsSummary(oldest_session_reached=True)

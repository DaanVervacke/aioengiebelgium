"""Tests for aioengiebelgium.parsers."""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import partial
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from aioengiebelgium.models import (
    EnergyCostPair,
    SimulatedCost,
    SimulatedCostFlow,
    SimulatedEnergy,
    SimulatedEnergyFlow,
    bare_ean,
    ean_with_delivery_point_suffix,
)
from aioengiebelgium.parsers import (
    _normalize_vocab,
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
    assert first.year_month == "2026-05"
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
    assert first.year_month == "2025-08"
    assert first.happy_hour is None
    assert first.electricity_injection == EnergyCostPair(kwh=607.901, cost=26.1)
    assert first.electricity_offtake == EnergyCostPair(kwh=15.756, cost=31.29)

    last = result.history[-1]
    assert last.year_month == "2026-08"
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
    assert result.history == ()


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
                    "productConfiguration": {"energyProduct": None, "type": None},
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
            },
            "history": [{"yearMonth": None, "happyHour": {"consumptionKWh": None}}],
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
        {"items": [None, {"businessAgreementNumber": "B1", "productConfiguration": "bad"}]},
        lambda r: len(r.items) == 1 and r.items[0].product_configuration is None,
        id="energy_contracts",
    ),
    pytest.param(
        parse_monthly_peaks,
        {
            "year": 2026,
            "month": 4,
            "peakOfTheMonth": "not-a-dict",
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
        lambda r: len(r.daily_peaks) == 1 and r.peak_of_the_month is None,
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
            "month": {"noHappyHour": True},
            "history": [
                3,
                {"happyHour": "no"},
                {"yearMonth": "2026-05", "happyHour": {"savedAmount": 1.0}},
            ],
        },
        lambda r: r.current is None and len(r.history) == 1,
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
                    "gridMeterTimeOfUseSchedules": [{"dgoTgoSchedule": "bad"}],
                },
            ]
        },
        lambda r: len(r.items) == 1 and r.items[0].grid_meter_schedules[0].dgo_tgo is None,
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
                },
            ]
        },
        lambda r: (
            len(r.items) == 2
            and r.items[0].electricity is None
            and r.items[1].electricity is None
            and r.items[1].gas is None
        ),
        id="usage_details",
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

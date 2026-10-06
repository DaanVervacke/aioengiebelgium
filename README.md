# aioengiebelgium

[![Check](https://github.com/DaanVervacke/aioengiebelgium/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/aioengiebelgium/actions/workflows/check.yml)
[![PyPI version](https://img.shields.io/pypi/v/aioengiebelgium.svg)](https://pypi.org/project/aioengiebelgium/)
[![Python versions](https://img.shields.io/pypi/pyversions/aioengiebelgium.svg)](https://pypi.org/project/aioengiebelgium/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Async Python client for the ENGIE Belgium consumer API. Requires Python >= 3.14.

> Unofficial and reverse-engineered: not endorsed by ENGIE, and it may break
> without notice whenever ENGIE changes their API.

## Install

```bash
uv add aioengiebelgium
```

## Documentation

The documentation is hosted at
[aioengiebelgium.readthedocs.io](https://aioengiebelgium.readthedocs.io/).

## Usage

`tokens.json` in the example below is demo storage only. Restrict the file's
permissions or use your application's secure storage for the token pair.

```python
import asyncio
import json
from pathlib import Path

from aioengiebelgium import EngieBeClient, MfaMethod

_TOKEN_FILE = Path("tokens.json")


async def persist_tokens(access_token: str, refresh_token: str) -> None:
    # Save the token pair for the next refresh.
    payload = json.dumps({"access": access_token, "refresh": refresh_token})
    await asyncio.to_thread(_TOKEN_FILE.write_text, payload)


async def first_login() -> None:
    # First run: log in with MFA. on_token_refresh saves the tokens.
    async with EngieBeClient(on_token_refresh=persist_tokens) as client:
        flow = await client.async_start_authentication(
            "user@example.com",
            "password",
            mfa_method=MfaMethod.SMS,
        )
        # Once you receive your MFA code, then:
        await flow.async_submit_mfa("123456")

        relations = await client.async_get_customer_account_relations()
        print(relations)


async def next_run() -> None:
    # Later runs: reuse the saved tokens and skip the login entirely.
    raw = await asyncio.to_thread(_TOKEN_FILE.read_text)
    tokens = json.loads(raw)

    async with EngieBeClient(
        access_token=tokens["access"],
        refresh_token=tokens["refresh"],
        on_token_refresh=persist_tokens,
    ) as client:
        contracts = await client.async_get_energy_contracts("1234567890")
        print(contracts)


if _TOKEN_FILE.exists():
    asyncio.run(next_run())
else:
    asyncio.run(first_login())
```

## Token rotation

ENGIE rotates the refresh token on every refresh call, and the previous refresh
token becomes invalid immediately. If you pass an `on_token_refresh` callback, it
receives the new `(access_token, refresh_token)` pair whenever the tokens change
(manual refresh, an automatic refresh before expiry, or a refresh triggered by a
401). You must persist that pair durably. If you keep using the old refresh
token after a rotation, the next refresh fails and the user has to log in again.

## EPEX prices (no login required)

The EPEX day-ahead market endpoint is public. Fetch it from an unauthenticated
client, with no tokens and no login:

```python
import asyncio
from datetime import UTC, datetime, timedelta

from aioengiebelgium import EngieBeClient


async def main() -> None:
    async with EngieBeClient() as client:
        now = datetime.now(UTC)
        prices = await client.async_get_epex_prices(now, now + timedelta(days=1))
        print(prices)


asyncio.run(main())
```

## API reference

### Constructor

`EngieBeClient(...)`:

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `session` | `aiohttp.ClientSession \| None` | `None` | Caller-owned session. The client closes only a session it created itself. |
| `client_id` | `str` | `DEFAULT_CLIENT_ID` | OAuth client id used for the Auth0 flow. |
| `access_token` | `str \| None` | `None` | Previously stored access token. Skips the login flow. |
| `refresh_token` | `str \| None` | `None` | Previously stored refresh token. Rotated on every refresh. |
| `on_token_refresh` | `Callable[[str, str], Awaitable[None]] \| None` | `None` | Async callback receiving the new `(access_token, refresh_token)` pair on every rotation. |
| `request_timeout` | `float` | `30.0` | Per-request timeout in seconds. |

### Token state

| Member | Returns | Notes |
| --- | --- | --- |
| `access_token` | `str \| None` | Current access token, or `None` when unauthenticated. |
| `refresh_token` | `str \| None` | Current refresh token, or `None` when unauthenticated. |
| `access_token_expiry` | `datetime \| None` | Expiry from the access token's JWT `exp` claim, or `None` when unknown. |
| `subject` | `str \| None` | JWT `sub` claim of the access token, the stable account identifier. |
| `is_access_token_expired(now)` | `bool` | `True` when the expiry is known and `now` is at or past it. |

### Authentication

| Method | Returns | Notes |
| --- | --- | --- |
| `async_start_authentication(username, password, mfa_method=MfaMethod.SMS, *, auth_session=None)` | `AuthFlow` | Runs login steps 1-7 and returns an `AuthFlow` awaiting the MFA code. Finish with `await flow.async_submit_mfa("123456")`. |
| `async_refresh_token()` | `tuple[str, str]` | Refreshes the tokens and returns `(new_access_token, new_refresh_token)`. |
| `close()` | `None` | Closes the client. The session is closed only if this client created it. |

Persist every rotated pair via `on_token_refresh`. See [Token rotation](#token-rotation).

### Data getters

| Getter | Returns | Description |
| --- | --- | --- |
| `async_get_prices(business_agreement_number)` | `PricesResponse` | Supplier energy prices for a business agreement. |
| `async_get_energy_contracts(business_agreement_number, *, include_inactive=False)` | `EnergyContractsResponse` | Energy contracts for a business agreement. |
| `async_get_service_point(ean)` | `ServicePoint` | Service point details. Accepts a bare EAN or one with its delivery-point suffix (e.g. `_ID1`). |
| `async_get_customer_account_relations()` | `CustomerAccountRelations` | Customer account relations for the authenticated user. |
| `async_get_monthly_peaks(business_agreement_number, year, month, *, day=None)` | `MonthlyPeaks` | Capacity tariff peaks for a given month, with the peak of the month and the earlier, lower peak of the same month that it replaced. Pass `day` to get only that day's daily peak. |
| `async_get_happy_hour_event(business_agreement_number)` | `HappyHourEvent` | Today's and tomorrow's happy hour windows. |
| `async_get_happy_hour_month_report(business_agreement_number, year, month)` | `HappyHourMonthReport` | The happy hour month report. |
| `async_get_usage_details(business_agreement_number, start_date, end_date, granularity=UsageGranularity.HOURLY, *, include_simulation=False)` | `UsageDetailsResponse` | Energy usage and costs for a date range, per hour, day, month or year. Gas energy (kWh) and cost come back next to electricity when the business agreement has a gas contract. |
| `async_get_solar_surplus_forecasts(business_agreement_number, delivery_point_id)` | `SolarSurplusForecasts` | Solar surplus forecasts for a delivery point. |
| `async_get_feature_flag(business_agreement_number, flag)` | `FeatureFlag` | Query a boolean feature flag for a business agreement. |
| `async_get_tou_schedules(business_agreement_number)` | `TouSchedulesResponse` | Time-of-use tariff schedules. |
| `async_get_account_balance(business_agreement_number)` | `AccountBalance` | The billing account balance. |
| `async_get_service_points(business_agreement_number)` | `ServicePointsResponse` | Service points of a business agreement, with their metering data sources (P1, P4, billing, meter reads, IMV) and how far back measured data reaches. |
| `async_get_meter_reads(business_agreement_number, *, latest=False, start_date=None, end_date=None)` | `MeterReadsResponse` | Meter register indexes. Pass `latest=True` for the most recent read, a date range for the reads in it, or nothing for the full history. |
| `async_get_monthly_billed_budget(business_agreement_number)` | `MonthlyBilledBudget` | Costs so far, expected costs and the monthly payment status of the current billed budget period. ENGIE answers HTTP 500 for a contract without a monthly billed budget. |
| `async_get_billing_period_usage(business_agreement_number)` | `BillingPeriodUsage` | Cost used so far in the current billing period, the expected yearly invoice and their ratio. When ENGIE cannot compute the cost, only `used_amount_failure_reason` is set (for example `MISSING_DATA`). |
| `async_get_budget_billing_plan_details(business_agreement_number)` | `BudgetBillingPlanDetails` | The budget billing plan of the current billing period: amounts, payment slices, the amounts it can be set to, ENGIE's proposed new amount and the same details per energy contract. A business agreement without an adjustable plan returns only the flags. |
| `async_get_happy_hour_eligibility(business_agreement_number)` | `HappyHourEligibility` | Whether the business agreement can activate the happy hour service, with ENGIE's reason codes when it cannot. |
| `async_get_happy_hour_service_status(business_agreement_number)` | `HappyHourServiceStatus` | The happy hour service status (for example `ACTIVE` or `NOT_ACTIVATED`) and when it last changed. |
| `async_get_energy_score(business_agreement_number, year, month)` | `EnergyScore` | The app's energy score grade (A to E) for a month, the criteria behind it and the actions the app suggests. Some criteria track app use (monthly graph viewed, monthly question answered). A criterion that does not count for the contract is `None`. |
| `async_get_smart_charge_services(customer_account_number)` | `EvServiceInfo` | Whether the customer account is onboarded for Smart Charge and the status of its `SMART_CHARGE` service. The customer account number comes from `CustomerAccount.customer_account_number`. |
| `async_get_electric_vehicles(customer_account_number)` | `ElectricVehiclesResponse` | The vehicles of a customer account, with what ENGIE can read or control on each and the last charge state (battery level, range, plug status, charge power). Inactive vehicles are included with `active=False`. |
| `async_get_vehicle_charge_settings(vehicle_id)` | `VehicleChargeSettings` | The Smart Charge settings of a vehicle: departure time per weekday, target battery level, battery reserve and whether smart and solar charging are on. `vehicle_id` is `ElectricVehicle.id`. |
| `async_get_latest_charging_session(vehicle_id)` | `ChargingSessionDetails` | The latest charging session of a vehicle with the energy charged per interval. A session with status `unknown` has no start, end or end battery level yet. |
| `async_get_latest_charging_session_charge_settings(vehicle_id)` | `ChargingSessionChargeSettings` | The target battery level, the departure time override and the direct-charging flag of the latest charging session. |
| `async_get_epex_prices(from_dt, to_dt, *, granularity=EpexGranularity.HOURLY)` | `EpexPayload` | EPEX day-ahead market prices. Works without login. |

### Service actions

These calls change the customer's ENGIE service. They were built from the ENGIE Smart App's API contract and have not been run against a live account.

| Method | Returns | Description |
| --- | --- | --- |
| `async_activate_happy_hour_service(business_agreement_number)` | `HappyHourServiceStatus` | Activates the happy hour service and returns its new status. Check `async_get_happy_hour_eligibility` first. An `EngieBeInvalidResponseError` after activation can still mean the activation worked, so confirm with `async_get_happy_hour_service_status`. |
| `async_cancel_happy_hour_service(business_agreement_number)` | `None` | Cancels the happy hour service. ENGIE returns no body. |

### Exceptions

All exceptions derive from `EngieBeError`, which carries an optional HTTP
`status`:

| Exception | Meaning |
| --- | --- |
| `EngieBeError` | Base exception for all client errors. |
| `EngieBeClientClosedError` | The client was used after `close()`. |
| `EngieBeCommunicationError` | Communication errors: network failure, non-auth HTTP >= 400. |
| `EngieBeTimeoutError` | The request timed out. Safe to retry. |
| `EngieBeEpexNotPublishedError` | EPEX day-ahead prices are not yet published for the requested window (HTTP 404). |
| `EngieBeInvalidResponseError` | A 2xx response whose body is not the expected JSON object. |
| `EngieBeAuthenticationError` | Authentication errors: bad credentials, expired token. |
| `EngieBeMfaError` | MFA-related errors, such as an invalid code. |

EPEX day-ahead prices are published in the afternoon for the following day.
Requesting a window whose prices have not been published yet raises
`EngieBeEpexNotPublishedError`. Retry later.

## Development

This project uses [uv](https://docs.astral.sh/uv/) and targets Python 3.14+.

```bash
uv sync
uv run python -m scripts.check
```

## License

MIT, see [LICENSE](LICENSE).

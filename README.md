# aioengiebelgium

[![Check](https://github.com/DaanVervacke/aioengiebelgium/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/aioengiebelgium/actions/workflows/check.yml)
[![PyPI version](https://img.shields.io/pypi/v/aioengiebelgium.svg)](https://pypi.org/project/aioengiebelgium/)
[![Python versions](https://img.shields.io/pypi/pyversions/aioengiebelgium.svg)](https://pypi.org/project/aioengiebelgium/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Unofficial, reverse-engineered client for the ENGIE Belgium consumer API.
> It is not endorsed by ENGIE and may break without notice whenever ENGIE
> changes their API.

Unofficial asynchronous Python library to interact with
the ENGIE Belgium API.

Requires Python >= 3.14.

## Install

```bash
pip install aioengiebelgium
```

## Usage

`tokens.json` in the example below is demo storage only — restrict the file's
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
| `session` | `aiohttp.ClientSession \| None` | `None` | Caller-owned session; the client closes only a session it created itself. |
| `client_id` | `str` | `DEFAULT_CLIENT_ID` | OAuth client id used for the Auth0 flow. |
| `access_token` | `str \| None` | `None` | Previously stored access token; skips the login flow. |
| `refresh_token` | `str \| None` | `None` | Previously stored refresh token; rotated on every refresh. |
| `on_token_refresh` | `Callable[[str, str], Awaitable[None]] \| None` | `None` | Async callback receiving the new `(access_token, refresh_token)` pair on every rotation. |
| `request_timeout` | `float` | `30.0` | Per-request timeout in seconds. |

### Token state

| Member | Returns | Notes |
| --- | --- | --- |
| `access_token` | `str \| None` | Current access token, or `None` when unauthenticated. |
| `refresh_token` | `str \| None` | Current refresh token, or `None` when unauthenticated. |
| `access_token_expiry` | `datetime \| None` | Expiry from the access token's JWT `exp` claim, or `None` when unknown. |
| `subject` | `str \| None` | JWT `sub` claim of the access token; the stable account identifier. |
| `is_access_token_expired(now)` | `bool` | `True` when the expiry is known and `now` is at or past it. |

### Authentication

| Method | Returns | Notes |
| --- | --- | --- |
| `async_start_authentication(username, password, mfa_method=MfaMethod.SMS, *, auth_session=None)` | `AuthFlow` | Runs login steps 1-7 and returns an `AuthFlow` awaiting the MFA code; finish with `await flow.async_submit_mfa("123456")`. |
| `async_refresh_token()` | `tuple[str, str]` | Refreshes the tokens and returns `(new_access_token, new_refresh_token)`. |
| `close()` | `None` | Closes the client; the session is closed only if this client created it. |

ENGIE rotates the refresh token on every refresh and the previous one is
invalidated immediately: always persist the new pair via `on_token_refresh`.

### Data getters

| Getter | Returns | Description |
| --- | --- | --- |
| `async_get_prices(business_agreement_number)` | `PricesResponse` | Supplier energy prices for a business agreement. |
| `async_get_energy_contracts(business_agreement_number, *, include_inactive=False)` | `EnergyContractsResponse` | Energy contracts for a business agreement. |
| `async_get_service_point(ean)` | `ServicePoint` | Service point details; the EAN carries its delivery-point suffix (e.g. `_ID1`). |
| `async_get_customer_account_relations()` | `CustomerAccountRelations` | Customer account relations for the authenticated user. |
| `async_get_monthly_peaks(business_agreement_number, year, month)` | `MonthlyPeaks` | Capacity tariff peaks for a given month. |
| `async_get_happy_hour_event(business_agreement_number)` | `HappyHourEvent` | Today's and tomorrow's happy hour windows. |
| `async_get_happy_hour_month_report(business_agreement_number, year, month)` | `HappyHourMonthReport` | The happy hour month report. |
| `async_get_usage_details(business_agreement_number, start_date, end_date, granularity=UsageGranularity.HOURLY, *, include_simulation=False)` | `UsageDetailsResponse` | Energy usage details for a date range. |
| `async_get_solar_surplus_forecasts(business_agreement_number, delivery_point_id)` | `SolarSurplusForecasts` | Solar surplus forecasts for a delivery point. |
| `async_get_feature_flag(flag, business_agreement_number)` | `FeatureFlag` | Query a boolean feature flag for a business agreement. |
| `async_get_tou_schedules(business_agreement_number)` | `TouSchedulesResponse` | Time-of-use tariff schedules. |
| `async_get_account_balance(business_agreement_number)` | `AccountBalance` | The billing account balance. |
| `async_get_epex_prices(from_dt, to_dt, *, granularity=EpexGranularity.HOURLY)` | `EpexPayload` | EPEX day-ahead market prices; works without login. |

### Exceptions

All exceptions derive from `EngieBeError`, which carries an optional HTTP
`status`:

| Exception | Meaning |
| --- | --- |
| `EngieBeError` | Base exception for all client errors. |
| `EngieBeCommunicationError` | Communication errors: timeout, network failure, non-auth HTTP >= 400. |
| `EngieBeEpexNotPublishedError` | EPEX day-ahead prices are not yet published for the requested window (HTTP 404). |
| `EngieBeInvalidResponseError` | A 2xx response whose body is not the expected JSON object. |
| `EngieBeAuthenticationError` | Authentication errors: bad credentials, expired token. |
| `EngieBeMfaError` | MFA-related errors, such as an invalid code. |

EPEX day-ahead prices are published in the afternoon for the following day.
Requesting a window whose prices have not been published yet raises
`EngieBeEpexNotPublishedError`; retry later.

## Development

This project uses [uv](https://docs.astral.sh/uv/) and targets Python 3.14+.

```bash
uv sync
uv run python -m scripts.check
```

## License

MIT, see [LICENSE](LICENSE).

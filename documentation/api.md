# API reference

## Constructor

`EngieBeClient(...)`:

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `session` | `aiohttp.ClientSession \| None` | `None` | Caller-owned session. The client closes only a session it created itself. |
| `client_id` | `str` | `DEFAULT_CLIENT_ID` | OAuth client id used for the Auth0 flow. |
| `access_token` | `str \| None` | `None` | Previously stored access token. Skips the login flow. |
| `refresh_token` | `str \| None` | `None` | Previously stored refresh token. Rotated on every refresh. |
| `on_token_refresh` | `Callable[[str, str], Awaitable[None]] \| None` | `None` | Async callback receiving the new `(access_token, refresh_token)` pair on every rotation. |
| `request_timeout` | `float` | `30.0` | Per-request timeout in seconds. |

Arguments after `session` are keyword-only.

## Token state

| Member | Returns | Notes |
| --- | --- | --- |
| `access_token` | `str \| None` | Current access token, or `None` when unauthenticated. |
| `refresh_token` | `str \| None` | Current refresh token, or `None` when unauthenticated. |
| `access_token_expiry` | `datetime \| None` | Expiry from the access token's JWT `exp` claim, or `None` when unknown. |
| `subject` | `str \| None` | JWT `sub` claim of the access token, the stable account identifier. |
| `is_access_token_expired(now)` | `bool` | `True` when the expiry is known and `now` is at or past it. |

Tokens are read-only properties. They change only via the constructor,
auth-flow adoption, or refresh.

## Authentication

| Method | Returns | Notes |
| --- | --- | --- |
| `async_start_authentication(username, password, mfa_method=MfaMethod.SMS, *, auth_session=None)` | `AuthFlow` | Runs the credential steps and returns an `AuthFlow` awaiting the MFA code. Finish with `await flow.async_submit_mfa("123456")`. |
| `async_refresh_token()` | `tuple[str, str]` | Refreshes the tokens and returns `(new_access_token, new_refresh_token)`. |
| `close()` | `None` | Closes the client. The session is closed only if this client created it. |

Persist every rotated pair via `on_token_refresh`. See
[Authentication](authentication.md#token-rotation).

## Data getters

| Getter | Returns | Description |
| --- | --- | --- |
| `async_get_prices(business_agreement_number)` | `PricesResponse` | Supplier energy prices for a business agreement. |
| `async_get_energy_contracts(business_agreement_number, *, include_inactive=False)` | `EnergyContractsResponse` | Energy contracts for a business agreement. |
| `async_get_service_point(ean)` | `ServicePoint` | Service point details. Accepts a bare EAN or one with its delivery-point suffix (e.g. `_ID1`). |
| `async_get_customer_account_relations()` | `CustomerAccountRelations` | Customer account relations for the authenticated user. |
| `async_get_monthly_peaks(business_agreement_number, year, month)` | `MonthlyPeaks` | Capacity tariff peaks for a given month. |
| `async_get_happy_hour_event(business_agreement_number)` | `HappyHourEvent` | Today's and tomorrow's happy hour windows. |
| `async_get_happy_hour_month_report(business_agreement_number, year, month)` | `HappyHourMonthReport` | The happy hour month report. |
| `async_get_usage_details(business_agreement_number, start_date, end_date, granularity=UsageGranularity.HOURLY, *, include_simulation=False)` | `UsageDetailsResponse` | Energy usage details for a date range. |
| `async_get_solar_surplus_forecasts(business_agreement_number, delivery_point_id)` | `SolarSurplusForecasts` | Solar surplus forecasts for a delivery point. |
| `async_get_feature_flag(business_agreement_number, flag)` | `FeatureFlag` | Query a boolean feature flag for a business agreement. |
| `async_get_tou_schedules(business_agreement_number)` | `TouSchedulesResponse` | Time-of-use tariff schedules. |
| `async_get_account_balance(business_agreement_number)` | `AccountBalance` | The billing account balance. |
| `async_get_epex_prices(from_dt, to_dt, *, granularity=EpexGranularity.HOURLY)` | `EpexPayload` | EPEX day-ahead market prices. Works without login. |

A business agreement number may contain spaces in user-facing form. The
library strips them before the request.

## Exceptions

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

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0, breaking changes ship as minor bumps.

## [Unreleased]

### Maintenance

- Allow uv 0.13

## [0.8.0] - 2026-10-10

### Bug Fixes

- Read HH:MM:SS schedule times and check EANs before the suffix
- Correct login, token refresh and closed client error handling

### Documentation

- Match the docs, docstrings and contributor guides to the code

## [0.7.0] - 2026-10-10

### Bug Fixes

- Validate the BAN and date range of usage details requests
- Count entries dropped from nested lists in skipped_entries
- Close the login session when authentication is cancelled
- Validate the delivery point id of solar surplus requests
- Require the _ID suffix on solar surplus delivery point ids

### Documentation

- Correct and complete the README API reference
- Correct and complete the Sphinx documentation
- Document the nested skip count and the remaining argument checks
- List every argument check and match the contributor guides to CI

### Features

- Close an unfinished login flow on async with exit

### Maintenance

- Build the Sphinx documentation in CI

## [0.6.0] - 2026-10-06

### Features

- Add smart charge service getter
- Add electric vehicles getter
- Add vehicle charge settings getter
- Add latest charging session getters
- Add charging session history getters

### Maintenance

- Remove comments and stray punctuation from the repo

## [0.5.0] - 2026-10-05

### Features

- Add service points and meter reads getters
- Add gas costs, electricity netto and yearly granularity to usage details
- Add replaced peak and day filter to monthly peaks
- Add combined schedule to time-of-use schedules
- Add green level and gas month report fields
- Add monthly billed budget getter
- Add billing period usage getter
- Add budget billing plan details getter
- Add happy hour eligibility and service status getters
- Add happy hour service activation and cancellation
- Add energy score getter

### Maintenance

- Refresh the changelog version links
- Align the changelog tooling with the library family
- Bump the feature flag app version to 5.0.0.1168

## [0.4.5] - 2026-10-04

### Bug Fixes

- Trim EPEX slots to one observed step around gaps

## [0.4.4] - 2026-10-04

### Bug Fixes

- Round EPEX EUR/kWh prices to six decimals

## [0.4.3] - 2026-10-02

### Maintenance

- Complete the uv toolchain migration
- Migrate the release drafter config and label workflows
- Manage the changelog with git-cliff

## [0.4.2] - 2026-09-30

### Documentation

- Replace the MkDocs site with a Sphinx API reference generated from docstrings via autodoc. The guides move to reStructuredText, and the reference now covers every exported model, enum, exception, and helper.
- Link the hosted documentation from the README.

## [0.4.1] - 2026-09-30

### Documentation

- Add a MkDocs documentation site under `documentation/` with a Read the Docs build configuration in `.readthedocs.yaml`. The site covers the quickstart, the MFA login flow, the token-rotation contract, the tokenless EPEX endpoint, and the full client API.

## [0.4.0] - 2026-09-30

### Breaking changes

- `EngieBeClient` constructor arguments after `session` are now keyword-only.
- `async_get_feature_flag` now takes `(business_agreement_number, flag)`, ban-first like the other getters.
- `async_get_service_point` accepts both bare and suffixed EANs. A bare EAN is normalized with its delivery-point suffix before the request.
- `EpexPayload.market_date`, `SolarSurplusDay.forecast_date`, and `FinancialTransaction.due_date` are now `date` values instead of strings.
- `MonthReportHistoryEntry.year_month` is now the month's start `date` instead of a `YYYY-MM` string.
- `AccountBalance.earliest_due_date` consumes the typed `due_date` field and returns midnight in the given timezone.
- `version` and `PackageNotFoundError` are no longer leaked into the package namespace. Only `__version__` is exported.

### Added

- `EngieBeTimeoutError` (subclass of `EngieBeCommunicationError`), raised instead of the generic communication error when a request exceeds its timeout.
- `EngieBeClientClosedError` (subclass of `EngieBeError`), raised by the closed-client guard instead of the base error.
- `skipped_entries` on `PricesResponse`, `EnergyContractsResponse`, `CustomerAccountRelations`, `MonthlyPeaks`, `HappyHourEvent`, `HappyHourMonthReport`, `UsageDetailsResponse`, `SolarSurplusForecasts`, `TouSchedulesResponse`, and `EpexPayload`: the number of malformed entries that lenient parsing dropped. A non-zero count signals a truncated response.

### Documentation

- Add community files: `CONTRIBUTING.md`, `SECURITY.md`, issue templates, a pull request template, and the `dependencies` label for Dependabot pull requests.
- Document the full client API in the README: constructor, token state, authentication, all 13 data getters, and the exception taxonomy.
- Document the token-rotation contract and the tokenless EPEX day-ahead endpoint.
- Add CI, PyPI version, Python versions, and MIT license badges plus an unofficial-API disclaimer.

### Maintenance

- Pin the remaining unpinned auth and parser branches with tests: primary-form state extraction, the non-callback resume guard, and the defensive hidden-input, grid-meter, and token-error fallbacks. Add wire tests for a custom `client_id` and unmatched-request refusal.
- Release Drafter now resolves `breaking-change` labels as a minor version bump, matching pre-1.0 semver convention.
- The CI gate installs the built wheel into a clean virtual environment and imports `EngieBeClient` from outside the repository.
- The source distribution now includes the LICENSE file.
- The auth-flow form harvester html-unescapes hidden-input values and accepts single-quoted `value` attributes.
- Request arguments are validated at the endpoint-args layer: BANs must be digits after space-stripping, EANs must be digits with an optional `_ID<n>` delivery-point suffix, and months must be 1-12 with years 2000-2100.
- The auth-flow state fallback is scoped to the harvested form instead of any `?state=` occurrence in the page.

### Fixed

- The auth flow reads a redirect's continuation state from the `Location` header first, falling back to the body. Auth0 now serves anchor-less redirect stubs that body scraping alone cannot parse.

### Security

- The MFA resume guard requires the callback URI with a query separator instead of a bare prefix match.
- Removed a live OAuth token capture from the local, gitignored captures directory.

## [0.3.0] - 2026-09-19

### Breaking changes

- `PricePeriod.valid_from` and `valid_to` are now `date | None` values instead of strings. Use `PricePeriod.contains()` to test whether a date is covered by a period.

### Added

- `PricePeriod.contains()` helper to test whether a date falls within a period. Price period boundaries accept both ISO dates and datetimes.

## [0.2.0] - 2026-09-15

### Maintenance

- Switch release tooling to Release Drafter: add `.github/release-drafter.yml` config and `.github/workflows/release-drafter.yml` workflow. Update `release.yml` to trigger on `release: published` (with `workflow_dispatch` fallback for an existing tag).

## [0.1.4] - 2026-09-15

### Added

- `EngieBeClient.subject` property exposing the JWT `sub` claim of the access token, for use as a stable account identifier by integrations.

## [0.1.3] - 2026-08-25

### Changed

- Submit all hidden inputs from each Auth0 form, not just `state`. Required
  by HA ADR-0004.
- Report the `js-available`, `webauthn-available` and
  `webauthn-platform-available` flags as Auth0 renders them, instead of
  hard-coding `true`.

### Removed

- Passkey-enrollment abort path. Auth0 skips it now that we report WebAuthn
  support honestly.

## [0.1.2] - 2026-08-23

### Added

- Support for multiple grid meters per EAN.
- Helper methods on `TouScheduleItem` to pick the primary meter and check for time-of-use.
- Cost indicator (1 cheapest, 5 dearest) on every slot.
- Slot code for accounts without a network time-of-use split.
- Feature flag for the supplier time-of-use gate.
- Optimal slot is derived from cost when the API does not send one.

### Changed

- Time-of-use schedules come from the billing endpoint the ENGIE app uses.
- Direction-prefixed slot codes are recognised (`S_TOU1_OFFTAKE_PEAK` reads as `peak`).
- `HIGH_LOAD_HOURS` and `LOW_LOAD_HOURS` map to `peak` and `offpeak`.
- Slot times accept both `HH:MM` and `HH:MM:SS`.

### Removed

- Old time-of-use feature flag. The ENGIE app no longer uses it.

## [0.1.1] - 2026-08-12

### Added

- New `ServicePoint` fields, including market details and metering configuration.

### Fixed

- Service point parsing now matches the real API response.
- `async_get_service_point` expects the EAN with its delivery-point suffix (e.g. `_ID1`).

### Security

- Raised the aiohttp floor to 3.14.3.

## [0.1.0] - 2026-08-02

### Added

- Initial release.

[Unreleased]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.5...v0.5.0
[0.4.5]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DaanVervacke/aioengiebelgium/releases/tag/v0.1.0

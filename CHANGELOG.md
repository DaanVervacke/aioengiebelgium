# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DaanVervacke/aioengiebelgium/releases/tag/v0.1.0

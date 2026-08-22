# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `TouSlot.cost_indicator` carries the wire `costIndicator` (1 cheapest, 5 dearest).
- `TouGridMeterSchedule` model with `grid_meter_number`, `exclusive_night_meter`, `supplier`, `dgo_tgo`.
- `TouSchedule.active_configuration_id` carries the wire configuration id (e.g. `TOU001`, `TOTAL_HOURS`).
- `TouScheduleItem.primary_meter()` returns the first non-exclusive-night meter.
- `TouScheduleItem.has_tou()` returns True when the primary meter carries more than one distinct slot code in any direction.
- `TouSlotCode.TOTAL_HOURS` for accounts whose network side has no time-of-use split.
- `FeatureFlagKey.TOU_IS_ACTIVE` for the supplier-side TOU gating flag.
- `TouDirectionSchedule.optimal_timeslot_code` is derived from `costIndicator` when the wire omits it (cheapest for offtake, dearest for injection).

### Changed

- `async_get_tou_schedules` now targets the billing microservice.
- `TouScheduleItem` exposes `grid_meter_schedules`. `dgo_tgo` and `supplier` moved to `TouGridMeterSchedule`.
- Slot codes are canonicalised: supplier direction prefixes (`S_TOU1_OFFTAKE_`, `S_TOU1_INJECTION_`) are stripped, and `HIGH_LOAD_HOURS` / `LOW_LOAD_HOURS` collapse to `peak` / `offpeak`.
- `startTime` and `endTime` accept both `HH:MM` and `HH:MM:SS`.
- `TouSchedule` gained `active_configuration_id` as its first field. Construct with keyword arguments.

### Removed

- `FeatureFlagKey.DGO_TOU_IS_ACTIVE`. The Smart App no longer queries it.

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

[Unreleased]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DaanVervacke/aioengiebelgium/releases/tag/v0.1.0

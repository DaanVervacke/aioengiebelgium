# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-08-12

### Added

- `ServicePoint` now models the full captured service-point payload: `ean`
  (delivery-point suffixed echo), `division`, `type`, `charging_station`,
  `premises_id`, and nested `market_details` via the new
  `ServicePointMarketDetails`, `ServicePointInstallation`, and
  `MeteringConfiguration` models (dgo, grid, smart-meter regime, metering
  method, register configuration, billing frequency).

### Fixed

- `parse_service_point` now reads the real single-object response shape and
  extracts `division`, instead of scanning for 18-digit keys, which returned
  an empty mapping against live responses. `ServicePoint.ean_energy_types`
  maps the bare requested EAN to its division.
- `EngieBeClient.async_get_service_point` documents that the EAN argument must
  carry the delivery-point suffix (e.g. `_ID1`). The endpoint answers 404 for
  a bare EAN.

## [0.1.0] - 2026-08-02

### Added

- Initial release.

[Unreleased]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/DaanVervacke/aioengiebelgium/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/DaanVervacke/aioengiebelgium/releases/tag/v0.1.0

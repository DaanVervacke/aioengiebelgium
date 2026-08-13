# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

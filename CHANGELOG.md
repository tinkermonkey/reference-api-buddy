# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.2.0] - 2025-08-21

### Added
- Domain-level TTL configuration support for flexible cache management
- Enhanced cache engine with configurable TTL per domain mapping

### Fixed
- Fixed bug in handling `Transfer-Encoding: chunked` responses from upstream servers
- Fixed previous hard-coded cache entry TTL, now uses domain-specific configuration

## [0.1.0] - 2025-08-19

### Added
- Initial proof-of-concept implementation
- Core proxy functionality with caching and throttling
- Unit and integration test suite
- Documentation and design specifications

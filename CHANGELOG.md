# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.4.2] - 2025-09-16

### Added
- Complete administrative API with 6 endpoints for system monitoring and debugging:
  - `GET /admin/config` - Returns current runtime configuration with sensitive data sanitized
  - `GET /admin/status` - Provides comprehensive system health and operational metrics
  - `GET /admin/cache` - Returns detailed cache statistics and health information
  - `GET /admin/domains` - Shows all configured domain mappings and their status
  - `GET /admin/cache/{domain}` - Returns cache entries and statistics for specific domains
  - `POST /admin/validate-config` - Validates configuration without applying changes
- Security integration with secure key authentication for admin endpoints
- Configuration sanitization that automatically redacts sensitive fields (keys, secrets, passwords, tokens)
- Comprehensive system health monitoring with component status tracking
- Cache analytics including hit rates, TTL distribution, and entry details
- Domain-specific monitoring with error tracking and performance metrics
- Admin utilities module for shared functionality across admin endpoints
- Rate limiting and access logging for admin endpoints
- Full JSON response formatting with proper error handling
- Comprehensive test coverage with 20 unit tests and 14 integration tests

### Changed
- Updated datetime handling throughout codebase to use `datetime.now(timezone.utc)` instead of deprecated `datetime.utcnow()`
- Improved type annotations with proper `Dict[str, Any]` usage for better mypy compliance
- Enhanced handler architecture to support admin endpoint routing

### Fixed
- Eliminated all Python 3.13 datetime deprecation warnings
- Fixed inconsistent datetime import patterns across the codebase
- Resolved mypy type checking issues with mixed dictionary types
- Aligned CI flake8 configuration with pre-commit hooks to prevent configuration drift

### Security
- Admin endpoints respect existing security configuration requirements
- Sensitive configuration data is automatically sanitized in API responses
- Admin access attempts are logged for security auditing
- Secure key validation prevents unauthorized access to administrative functions

## [0.3.0] - 2025-08-22

### Added
- Monitoring interface (`MonitoringManager`) for programmatic access to proxy, cache, upstream, database, and throttling metrics
- Unit tests for monitoring interface

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

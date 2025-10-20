# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.5.0] - 2025-10-20

### Added
- **Fine-grained rate limiting**: Per-second and per-minute rate limits for domain-specific throttling
  - Configure `max_requests_per_second` and `max_requests_per_minute` in domain mappings
  - Automatic request throttling with configurable delay tolerance
  - Multi-window priority system (second → minute → hour)
  - Sliding window implementation for accurate rate limiting
  - Backward compatible with existing hour-level throttling
- **Request deduplication**: Automatic coalescing of concurrent requests to the same resource
  - `InFlightTracker` class for tracking in-flight upstream requests
  - Thread-safe coordination using threading events
  - Prevents duplicate upstream API calls during request bursts
  - Error propagation and timeout handling for waiting requests
  - Automatic cleanup of completed requests
  - Statistics reporting via `get_stats()`
- Comprehensive test coverage with 8 new tests for request deduplication and 9 tests for rate limiting
- Configuration validation for new rate limiting parameters

### Changed
- `ThrottleManager` now accepts `domain_mappings` parameter to extract per-minute/per-second limits
- `ThrottleManager` extends `ThrottleState` to track minute and second-level request windows
- Request handler flow modified to use `get_required_delay()` instead of `should_throttle()`
- Proxy now sleeps automatically to stay within rate limits rather than rejecting requests with 429
- Only returns 429 when required delay exceeds `progressive_max_delay` (default 300 seconds)
- Request handler wraps upstream forwarding with deduplication logic
- Updated existing tests to work with new `get_required_delay()` method

### Fixed
- Prevents burst requests to upstream APIs when multiple clients request the same resource simultaneously
- Eliminates race conditions during concurrent cache misses for identical resources

### Performance
- Significant reduction in duplicate upstream API calls during request bursts
- Faster response times for waiting requests (share result instead of making duplicate calls)
- Better upstream API utilization with automatic rate smoothing
- **Deduplicated requests do NOT count against rate limits** - only the first upstream request is rate-limited

## [0.4.3] - 2025-09-16

### Added
- Comprehensive Wikidata SPARQL smoke test for end-to-end validation
- Enhanced debug logging for gzip decompression and header management
- Magic number detection for reliable gzip content identification

### Changed
- Increased proxy timeout from 30 to 60 seconds for complex SPARQL queries
- Improved gzip decompression with robust error handling for chunked+gzipped responses
- Enhanced header management with case-insensitive handling for Content-Length conflicts

### Fixed
- **Critical**: Resolved InvalidChunkLength errors when processing chunked transfer encoding with gzipped responses
- **Critical**: Fixed Content-Length header conflicts by implementing case-insensitive header removal during decompression
- Proper cleanup of Transfer-Encoding and Content-Encoding headers after gzip decompression
- Timeout issues for complex queries requiring more than 30 seconds processing time

### Security
- Improved error handling prevents potential issues with malformed gzipped responses
- Enhanced header validation ensures proper HTTP compliance

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

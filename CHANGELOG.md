# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Fixed
- **A path-prefix key (`/<key>/<domain>/<path>`) works.** The proxy stripped the key but then matched the domain
  against the unstripped path, so every such request returned 404 "Domain not mapped". The key-free path is now used
  for domain matching, the cache key and the upstream request.
- **A query key (`?key=<key>`) works.** `parse_qs` returns lists, so the key reached validation as a list and every
  such request returned 500. The key parameter is also removed before the request is cached and forwarded, so
  other query parameters reach upstream unchanged and the cache entry is shared with the other placements.
- **The proxy key is no longer sent to the upstream API.** `X-API-Buddy-Key` is never forwarded, and
  `Authorization` is dropped only when it carries `Bearer <proxy key>`; an upstream API's own Bearer token still
  passes through. A path segment or `key=` parameter that is not the proxy key is left for upstream, so APIs that
  take their own `?key=` keep working when proxy security is off.
- **A valid key is no longer shadowed by a value that only looks like one.** Key extraction returned the first
  candidate it found (path prefix, then `?key=`, then headers), so with `require_secure_key` on, a request with a
  valid `X-API-Buddy-Key` or `Authorization: Bearer` key got a 401 when its path also had a 32-44 character first
  segment (such as a long domain key) or an upstream API's own `?key=`. Every candidate is now checked and the one
  that matches the proxy key wins; the others stay in the upstream request. A request with no matching key is still
  rejected.
- **Repeated or mixed `key=` parameters are handled.** Every `key` value is checked, so `?key=<upstream>&key=<proxy>`
  is accepted, and only the parameter holding the proxy key is removed: the upstream API's own `key=` reaches it, and
  a proxy key sent both as a path prefix or header and as `?key=` is not forwarded upstream.
- **The proxy key is no longer written to the access log.** The request line the HTTP server logs to stderr carried a
  path-prefix or `?key=` proxy key in full. The key, raw or percent-encoded (wholly or in part), is now replaced with
  `[REDACTED]` in every access and error log line. The proxy writes these lines itself in the standard plain format,
  so on Python 3.15 they are no longer coloured in a terminal.

### Tests
- Regression tests for all four key placements (header, Bearer, path prefix, query) through a running
  `CachingProxy` and a recording upstream, checking that the proxy key never appears in the upstream request.
- Regression tests for header and Bearer keys combined with an upstream `?key=` and with a 40-character domain key.
- Regression tests that the stderr access log never carries the proxy key: path prefix, `?key=`, a key repeated in
  the header and the query, and a percent-encoded key.

## [0.5.2] - 2026-11-24

### Removed
- **Runtime dependencies.** The package only uses the standard library, so `requests`, `urllib3`, `certifi`,
  `charset-normalizer` and `idna` are no longer installed with it. `requests` moves to the `dev` extra for the tests.
- **Python 3.8 and 3.9 support.** Both are end-of-life. `requires-python` is now `>=3.10`.

### Changed
- Tested on Python 3.10 through 3.15; classifiers updated to match.
- Dev tooling raised to current releases that still support Python 3.10: pytest 9, pytest-cov 7, black 26,
  isort 9, flake8 7.4+, mypy 2.4, pre-commit 4.6+, coverage 7.16+, twine 7, build 1.6, pip-audit 2.10.
  Docs extra raised to Sphinx 8.1, sphinx-rtd-theme 3.1, myst-parser 4.0.
- Pre-commit hooks updated (pre-commit-hooks 6.0.0, isort 9.0.2, flake8 7.5.0, mypy 2.4.1).
- GitHub Actions updated to checkout v7, setup-python v7, upload-artifact v7, download-artifact v8 and
  codecov-action v7 (`file` renamed to `files`). CI and release builds use Python 3.13.
- Packaging uses an SPDX license expression (`license = "MIT"`) with setuptools 77+, replacing the deprecated
  license table and license classifier.
- Tests that call live external services are marked `network` and deselected by default; run them with
  `pytest -m network` or `make test-performance`.
- Timing-dependent tests are now deterministic: the cache-first throttling test checks behaviour instead of
  wall-clock latency (and runs in CI again), the deduplication tests register threads in a fixed order instead of
  sleeping, and integration tests use free ports and no startup sleeps.
- Removed the `[tool.pytest.ini_options]` and `[tool.mypy]` sections from `pyproject.toml`. `pytest.ini` and
  `mypy.ini` take precedence, so those sections were never read.
- `make install` installs the package with its dev extra instead of reading a missing `requirements.txt`.

## [0.5.1] - 2026-11-24

### Fixed
- **Upstream errors are no longer cached.** Only 2xx responses are stored, so an outage or a 4xx no longer
  blanks a resource for the whole TTL. Throttled (429) responses are not cached either.
- **Upstream HTTP error statuses are passed through.** A 404 or 503 from upstream now reaches the caller with its
  real status, body and headers instead of a generic 502. Network errors and unmapped upstreams still return 502.
- **A request answered with a 429 no longer stays in-flight forever.** The request that owns an in-flight entry now
  releases it on every path, so later requests for the same resource get a prompt 429 instead of waiting 60s and
  failing with a 500.
- **PUT and DELETE requests no longer share an in-flight slot.** They have no cache key and previously all
  deduplicated onto the same entry, so concurrent requests could receive each other's responses.
- **`cache.max_cache_entries` is read from config.** The cache was capped at 1,000 entries whatever the config said.
  The default stays 1,000; the value must be a positive integer.
- `reference_api_buddy.__version__` now matches the package version.

### Tests
- Regression tests for all of the above against a local upstream server.
- Expiry tests no longer use a hard-coded "far future" timestamp that has since passed.

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

"""Request processing pipeline for ProxyHTTPRequestHandler."""

import datetime
import gzip
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from reference_api_buddy.utils.logger import get_logger


class RequestProcessingMixin:
    """Mixin to add request processing pipeline to ProxyHTTPRequestHandler."""

    @property
    def logger(self):
        # Use the proxy's logger if available, else get a default handler logger
        if hasattr(self, "proxy") and hasattr(self.proxy, "logger"):
            return self.proxy.logger
        return get_logger("core.handler")

    def _forward_request(self, method: str, target_url: str, body: bytes = None, headers: dict = None):
        """Forward request to upstream server and return response data,
        status, headers."""

        start_time = time.time()
        domain_key = None
        real_url = None

        try:
            # Map proxy requests to real ones
            domain_mappings = self.proxy.config.get("domain_mappings", {})

            # Parse the path to extract domain key
            path_parts = target_url.lstrip("/").split("/")
            if path_parts:
                domain_key = path_parts[0]
                if domain_key in domain_mappings:
                    upstream = domain_mappings[domain_key].get("upstream", "")
                    if upstream:
                        # Replace domain key with real upstream URL
                        real_path = "/" + "/".join(path_parts[1:]) if len(path_parts) > 1 else "/"
                        # Handle query parameters
                        if "?" in target_url:
                            path_part, query_part = target_url.split("?", 1)
                            real_path = "/" + "/".join(path_part.lstrip("/").split("/")[1:])
                            if not real_path or real_path == "/":
                                real_path = "/"
                            real_url = upstream.rstrip("/") + real_path + "?" + query_part
                        else:
                            real_url = upstream.rstrip("/") + real_path
                    else:
                        # No upstream configured, return 502 Bad Gateway
                        error_msg = f"No upstream configured for domain: {domain_key}"
                        self.logger.error(error_msg)
                        return error_msg.encode("utf-8"), 502, {"Content-Type": "text/plain"}
                else:
                    # Domain not mapped, return 404 Not Found
                    error_msg = f"Domain not mapped: {domain_key}"
                    self.logger.warning(error_msg)
                    return error_msg.encode("utf-8"), 404, {"Content-Type": "text/plain"}
            else:
                # Invalid path, return 400 Bad Request
                error_msg = "Invalid request path"
                self.logger.warning(f"Invalid path: {target_url}")
                return error_msg.encode("utf-8"), 400, {"Content-Type": "text/plain"}

            self.logger.debug(f"Forwarding {method} request from {target_url} to {real_url}")

            # Create request
            req = urllib.request.Request(real_url, method=method)

            # Add headers (filter out problematic ones)
            if headers:
                for key, value in headers.items():
                    if key.lower() not in ["host", "connection", "content-length"]:
                        req.add_header(key, value)

            # Ensure we accept gzip encoding
            req.add_header("Accept-Encoding", "gzip, deflate")

            # Add body for POST requests
            if body and method == "POST":
                req.data = body

            self.logger.debug(f"Making {method} request to {real_url} with timeout=60")
            self.logger.debug(f"Request headers: {req.headers}")

            # Make request with longer timeout for external services (especially SPARQL queries)
            with urllib.request.urlopen(req, timeout=60) as response:
                response_data = response.read()
                status_code = response.getcode()
                response_headers = dict(response.headers)

                # Calculate response time
                response_time_ms = int((time.time() - start_time) * 1000)

                self.logger.debug(f"Received response from {real_url}: {status_code}")
                self.logger.debug(f"Response headers: {response_headers}")

                # Handle compression - be more robust about gzip detection and decompression
                encoding = response_headers.get("Content-Encoding", "").lower()
                decompressed = False

                # Check if data is gzipped using magic number (more comprehensive check)
                if len(response_data) >= 2 and response_data[:2] == b"\x1f\x8b":
                    self.logger.debug(
                        f"Detected gzipped data by magic number for {real_url} "
                        f"(first 10 bytes: {response_data[:10].hex()})"
                    )
                    try:
                        decompressed_data = gzip.decompress(response_data)
                        response_data = decompressed_data
                        decompressed = True
                        self.logger.debug(f"Successfully decompressed gzip data for " f"{real_url}")
                    except (gzip.BadGzipFile, zlib.error, OSError) as e:
                        self.logger.warning(f"Failed to decompress gzipped data for " f"{real_url}: {e}")
                        # Keep original data if decompression fails
                elif encoding in ["gzip", "deflate"]:
                    self.logger.debug(f"Detected {encoding} encoding via header for " f"{real_url}")
                    try:
                        if encoding == "gzip":
                            decompressed_data = gzip.decompress(response_data)
                        elif encoding == "deflate":
                            decompressed_data = zlib.decompress(response_data)
                        response_data = decompressed_data
                        decompressed = True
                        self.logger.debug(f"Successfully decompressed {encoding} data for {real_url}")
                    except (gzip.BadGzipFile, zlib.error, OSError) as e:
                        self.logger.warning(f"Failed to decompress {encoding} data for {real_url}: {e}")
                        # Keep original data if decompression fails

                        # Fix headers after decompression
                if decompressed:
                    # Remove compression-related headers (case-insensitive)
                    headers_to_remove = []
                    for key in response_headers.keys():
                        if key.lower() in ["content-encoding", "transfer-encoding", "content-length"]:
                            headers_to_remove.append(key)

                    for key in headers_to_remove:
                        response_headers.pop(key, None)

                    # Set correct content length for decompressed data
                    response_headers["Content-Length"] = str(len(response_data))
                    self.logger.debug(f"Updated headers after decompression: " f"Content-Length={len(response_data)}")
                else:
                    # Even if not decompressed, ensure we have proper headers for the proxy response
                    # Remove chunked encoding as we'll send the full response at once
                    headers_to_remove = []
                    for key, value in response_headers.items():
                        if key.lower() == "transfer-encoding" and value.lower() == "chunked":
                            headers_to_remove.append(key)

                    for key in headers_to_remove:
                        response_headers.pop(key, None)

                    # Only set Content-Length if not already present (case-insensitive check)
                    has_content_length = any(key.lower() == "content-length" for key in response_headers.keys())
                    if not has_content_length:
                        response_headers["Content-Length"] = str(len(response_data))
                        self.logger.debug(f"Removed chunked encoding, set Content-Length={len(response_data)}")

                # Store upstream metrics for successful requests
                if domain_key and hasattr(self.proxy, "db_manager"):
                    try:
                        self.proxy.db_manager.store_upstream_metrics(
                            domain=domain_key,
                            method=method,
                            response_time_ms=response_time_ms,
                            response_size_bytes=len(response_data),
                            cache_hit=False,
                            status_code=status_code,
                        )
                    except Exception as e:
                        self.logger.debug(f"Failed to store upstream metrics: {e}")

                self.logger.debug(f"Final response: {response_data}")
                return response_data, status_code, response_headers

        except urllib.error.HTTPError as e:
            # Calculate response time for failed requests too
            response_time_ms = int((time.time() - start_time) * 1000)

            # Store metrics for HTTP errors
            if domain_key and hasattr(self.proxy, "db_manager"):
                try:
                    self.proxy.db_manager.store_upstream_metrics(
                        domain=domain_key,
                        method=method,
                        response_time_ms=response_time_ms,
                        response_size_bytes=0,
                        cache_hit=False,
                        status_code=e.code,
                    )
                except Exception as store_error:
                    self.logger.debug(f"Failed to store upstream error metrics: {store_error}")

            # Handle HTTP errors (4xx, 5xx responses from upstream)
            self.logger.error(f"HTTP error from upstream {real_url}: {e.code} {e.reason}")
            error_msg = f"Upstream HTTP error: {e.code} {e.reason}"
            return error_msg.encode("utf-8"), 502, {"Content-Type": "text/plain"}
        except urllib.error.URLError as e:
            # Calculate response time for network errors
            response_time_ms = int((time.time() - start_time) * 1000)

            # Store metrics for network errors
            if domain_key and hasattr(self.proxy, "db_manager"):
                try:
                    self.proxy.db_manager.store_upstream_metrics(
                        domain=domain_key,
                        method=method,
                        response_time_ms=response_time_ms,
                        response_size_bytes=0,
                        cache_hit=False,
                        status_code=502,  # Gateway error
                    )
                except Exception as store_error:
                    self.logger.debug(f"Failed to store upstream network error metrics: {store_error}")

            # Handle URL/network errors
            self.logger.error(f"Network error accessing upstream {real_url}: {e.reason}")
            error_msg = f"Upstream network error: {e.reason}"
            return error_msg.encode("utf-8"), 502, {"Content-Type": "text/plain"}
        except Exception as e:
            # Calculate response time for general errors
            response_time_ms = int((time.time() - start_time) * 1000)

            # Store metrics for general errors
            if domain_key and hasattr(self.proxy, "db_manager"):
                try:
                    self.proxy.db_manager.store_upstream_metrics(
                        domain=domain_key,
                        method=method,
                        response_time_ms=response_time_ms,
                        response_size_bytes=0,
                        cache_hit=False,
                        status_code=500,  # Internal server error
                    )
                except Exception as store_error:
                    self.logger.debug(f"Failed to store upstream general error metrics: {store_error}")

            self.logger.error(f"Failed to forward request to {real_url}: {e}")
            # Return 502 Bad Gateway on network/upstream errors
            error_msg = f"Upstream server error: {str(e)}"
            return error_msg.encode("utf-8"), 502, {"Content-Type": "text/plain"}

    def _handle_request(self, method: str):
        try:
            import time

            self.logger.debug(f"Handling {method} request for path: {self.path}")
            # 1. Extract and validate secure key
            sanitized_path = self.path
            if hasattr(self.proxy, "security_manager") and self.proxy.security_manager is not None:
                key, sanitized_path = self.proxy.security_manager.extract_secure_key(
                    self.path, self.headers, parse_qs(urlparse(self.path).query)
                )
                if self.proxy.config.get("security", {}).get("require_secure_key", False):
                    if not key or not self.proxy.security_manager.validate_request(key):
                        self.logger.warning("Unauthorized request: Invalid or missing secure key.")
                        self.send_response(401)
                        self.end_headers()
                        self.wfile.write(b"Unauthorized: Invalid or missing secure key\n")
                        return

            # 2. Check for admin endpoints
            if self._is_admin_path(sanitized_path):
                if not self._is_admin_enabled():
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not Found\n")
                    return

                self._handle_admin_request(method, sanitized_path)
                return

            # 3. Check admin endpoints (stub: /admin/health) - kept for backward compatibility
            if self.path.startswith("/admin/health"):
                self.logger.debug("Health check endpoint hit.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK\n")
                return
            # 4. Determine if this request matches a configured domain mapping
            domain_mappings = self.proxy.config.get("domain_mappings", {})
            matched = False
            matched_domain_key = None

            # Parse the request URL to handle both path-based and full URL requests
            parsed_url = urlparse(self.path)
            request_netloc = parsed_url.netloc

            for domain_key, mapping in domain_mappings.items():
                # Match by netloc (for full URLs like http://example.com/path)
                if request_netloc and request_netloc == domain_key:
                    matched = True
                    matched_domain_key = domain_key
                    break
                # Match by path prefix (for path-based requests like /example.com/path)
                elif self.path.startswith(f"/{domain_key}/") or self.path == f"/{domain_key}":
                    matched = True
                    matched_domain_key = domain_key
                    break
            # 5. If matched, apply cache-first architecture: check cache before any throttling
            # This ensures cache hits bypass throttling entirely for maximum performance
            if matched:
                target_url = self.path  # TODO: domain mapping logic

                # Read request body for POST requests
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if method == "POST" else None

                # Caching - check cache first before any throttling
                cache_key = None
                cached = None
                if (
                    method in ("GET", "POST")
                    and hasattr(self.proxy, "cache_engine")
                    and self.proxy.cache_engine is not None
                ):
                    content_type = self.headers.get("Content-Type")
                    cache_key = self.proxy.cache_engine.generate_cache_key(method, target_url, body, content_type)
                    cached = self.proxy.cache_engine.get(cache_key)
                    if cached:
                        self.logger.info(f"Cache hit for key: {cache_key} {target_url}")

                        # Store cache hit metrics
                        if matched_domain_key and hasattr(self.proxy, "db_manager"):
                            try:
                                self.proxy.db_manager.store_upstream_metrics(
                                    domain=matched_domain_key,
                                    method=method,
                                    response_time_ms=0,  # Cache hits are essentially instantaneous
                                    response_size_bytes=len(cached.data),
                                    cache_hit=True,
                                    status_code=cached.status_code,
                                )
                            except Exception as e:
                                self.logger.debug(f"Failed to store cache hit metrics: {e}")

                        self.send_response(cached.status_code)
                        # Send headers (data is already decompressed when cached)
                        for k, v in cached.headers.items():
                            self.send_header(k, v)
                        self.end_headers()
                        self.wfile.write(cached.data)
                        return
                    else:
                        self.logger.info(f"Cache miss for key: {cache_key}")

                # Throttling - only apply when forwarding to upstream (cache miss)
                if hasattr(self.proxy, "throttle_manager") and self.proxy.throttle_manager is not None:
                    # Use the matched domain key for throttling
                    domain = matched_domain_key
                    self.proxy.throttle_manager.record_request(domain)
                    if self.proxy.throttle_manager.should_throttle(domain):
                        delay = self.proxy.throttle_manager.get_throttle_delay(domain)
                        limit = getattr(self.proxy.throttle_manager, "domain_limits", {}).get(
                            domain, getattr(self.proxy.throttle_manager, "default_limit", 1000)
                        )
                        state = self.proxy.throttle_manager.get_state(domain)
                        remaining = max(0, limit - len(state.request_timestamps))
                        reset = 1
                        if state.request_timestamps:
                            reset = int(
                                self.proxy.throttle_manager.time_window - (time.time() - state.request_timestamps[0])
                            )
                        self.logger.info(
                            f"Throttling upstream request for domain {domain}: "
                            f"delay={delay}, limit={limit}, "
                            f"remaining={remaining}, reset={reset}"
                        )
                        self.send_response(429)
                        self.send_header("Retry-After", str(delay))
                        self.send_header("X-RateLimit-Limit", str(limit))
                        self.send_header("X-RateLimit-Remaining", str(remaining))
                        self.send_header("X-RateLimit-Reset", str(reset))
                        if hasattr(self.proxy, "metrics_collector") and self.proxy.metrics_collector:
                            self.proxy.metrics_collector.record_event(
                                "throttle",
                                {
                                    "domain": domain,
                                    "delay": delay,
                                    "limit": limit,
                                    "remaining": remaining,
                                    "reset": reset,
                                    "cache_miss": True,  # Mark this as a cache miss throttle
                                },
                            )
                        self.end_headers()
                        self.wfile.write(b"Too Many Requests\n")
                        return

                # Forward to upstream if cache miss
                response_data, status_code, headers = self._forward_request(method, target_url, body, self.headers)

                # Cache the response (data is already decompressed by _forward_request)
                if (
                    method in ("GET", "POST")
                    and hasattr(self.proxy, "cache_engine")
                    and self.proxy.cache_engine is not None
                ):
                    from reference_api_buddy.database.models import CachedResponse

                    # Create proper CachedResponse object with no explicit TTL (will be set by TTL manager)
                    resp_obj = CachedResponse(
                        data=response_data,
                        headers=headers,
                        status_code=status_code,
                        created_at=None,  # Will be set by cache engine
                        ttl_seconds=None,  # Will be determined by TTL manager based on domain
                        access_count=0,
                        last_accessed=None,
                    )
                    # Cache with domain information for TTL resolution
                    self.proxy.cache_engine.set(cache_key, resp_obj, domain_key=matched_domain_key)

                # Send response to client
                self.send_response(status_code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response_data)
                return
            # 5. If not matched, transparently proxy (no cache/throttle)
            # In a real implementation, this would forward the request to the mapped
            # upstream
            self.logger.debug(f"Proxying request for path: {self.path}")
            # Read request body for POST requests
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if method == "POST" else None
            response_data, status_code, headers = self._forward_request(method, self.path, body, self.headers)
            self.send_response(status_code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(response_data)
        except Exception as e:
            self.logger.error(f"Exception while handling request: {e}")
            self.send_response(500)
            self.end_headers()
            tb = traceback.format_exc()
            self.wfile.write(f"Internal Server Error\n{tb}".encode())

    # Admin endpoint methods
    def _is_admin_path(self, path: str) -> bool:
        """Check if path is an admin endpoint."""
        return path.startswith("/admin/")

    def _is_admin_enabled(self) -> bool:
        """Check if admin endpoints are enabled."""
        return self.proxy.config.get("admin", {}).get("enabled", True)

    def _check_admin_rate_limit(self) -> bool:
        """Check if request is within admin rate limits."""
        from reference_api_buddy.core.admin_utils import AdminRateLimiter

        # Use proxy-level rate limiter to share state across requests
        if not hasattr(self.proxy, "_admin_rate_limiter"):
            self.proxy._admin_rate_limiter = AdminRateLimiter()

        client_ip = self.client_address[0]
        limit = self.proxy.config.get("admin", {}).get("rate_limit_per_minute", 10)

        return self.proxy._admin_rate_limiter.is_allowed(client_ip, limit)

    def _handle_admin_request(self, method: str, path: str):
        """Handle admin endpoint requests with rate limiting and routing."""
        try:
            # Rate limiting check
            if not self._check_admin_rate_limit():
                self._send_admin_error(429, "RATE_LIMIT_EXCEEDED", "Too many requests")
                return

            # Log admin access
            self._log_admin_access(method, path)

            # Route to specific admin handler
            if method == "GET":
                self._route_admin_get(path)
            elif method == "POST":
                self._route_admin_post(path)
            else:
                self._send_admin_error(405, "METHOD_NOT_ALLOWED", f"Method {method} not allowed")

        except Exception as e:
            self.logger.error(f"Admin request error: {e}")
            self._send_admin_error(500, "INTERNAL_ERROR", "Internal server error")

    def _route_admin_get(self, path: str):
        """Route GET requests to appropriate admin handlers."""
        if path == "/admin/config":
            self._handle_admin_config()
        elif path == "/admin/status":
            self._handle_admin_status()
        elif path == "/admin/domains":
            self._handle_admin_domains()
        elif path == "/admin/cache":
            self._handle_admin_cache()
        elif path.startswith("/admin/cache/"):
            domain = path.split("/", 3)[3]  # Extract domain from /admin/cache/{domain}
            self._handle_admin_cache_domain(domain)
        elif path == "/admin/health":  # Keep existing health endpoint
            self._handle_admin_health()
        else:
            self._send_admin_error(404, "ENDPOINT_NOT_FOUND", f"Admin endpoint not found: {path}")

    def _route_admin_post(self, path: str):
        """Route POST requests to appropriate admin handlers."""
        if path == "/admin/validate-config":
            self._handle_admin_validate_config()
        else:
            self._send_admin_error(404, "ENDPOINT_NOT_FOUND", f"Admin endpoint not found: {path}")

    def _send_admin_response(self, status_code: int, data: dict):
        """Send standardized JSON response for admin endpoints."""
        import json

        response_data = json.dumps(data, indent=2).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_data)))
        self.end_headers()
        self.wfile.write(response_data)

    def _send_admin_error(self, status_code: int, error_code: str, message: str):
        """Send standardized error response for admin endpoints."""
        from datetime import datetime, timezone

        error_response = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "success": False,
            "error": message,
            "error_code": error_code,
        }
        self._send_admin_response(status_code, error_response)

    def _log_admin_access(self, method: str, path: str):
        """Log admin endpoint access for security auditing."""
        if self.proxy.config.get("admin", {}).get("log_access", True):
            client_ip = self.client_address[0]
            self.logger.info(f"Admin access: {client_ip} {method} {path}")

    def _handle_admin_health(self):
        """Handle GET /admin/health - simple health check."""
        self.logger.debug("Health check endpoint hit.")
        response = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z", "status": "healthy"}
        self._send_admin_response(200, response)

    def _handle_admin_config(self):
        """Handle GET /admin/config - return sanitized configuration."""
        try:
            config_data = self._get_sanitized_config()
            response = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                "proxy_version": "1.0.0",  # Could be dynamic from package metadata
                "security_enabled": self.proxy.config.get("security", {}).get("require_secure_key", False),
                "configuration": config_data["config"],
                "sanitized_fields": config_data["sanitized_fields"],
            }
            self._send_admin_response(200, response)
        except Exception as e:
            self.logger.error(f"Config endpoint error: {e}")
            self._send_admin_error(500, "CONFIG_ERROR", "Failed to retrieve configuration")

    def _get_sanitized_config(self) -> dict:
        """Return configuration with sensitive data redacted."""
        import copy

        config = copy.deepcopy(self.proxy.config)
        sanitized_fields = []

        def sanitize_dict(d, path=""):
            nonlocal sanitized_fields
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key

                # Check if field name suggests sensitive data
                if any(sensitive in key.lower() for sensitive in ["key", "secret", "password", "token"]):
                    d[key] = "[REDACTED]"
                    sanitized_fields.append(current_path)
                elif isinstance(value, dict):
                    sanitize_dict(value, current_path)

        sanitize_dict(config)

        return {"config": config, "sanitized_fields": sanitized_fields}

    def _handle_admin_status(self):
        """Handle GET /admin/status - return system health and metrics."""
        try:
            import time

            uptime_seconds = int(time.time() - getattr(self.proxy, "start_time", time.time()))

            components = self._get_component_status()
            metrics = self._get_system_metrics()

            overall_status = self._determine_overall_status(components)

            response = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                "status": overall_status,
                "uptime_seconds": uptime_seconds,
                "components": components,
                "metrics": metrics,
            }
            self._send_admin_response(200, response)
        except Exception as e:
            self.logger.error(f"Status endpoint error: {e}")
            self._send_admin_error(500, "STATUS_ERROR", "Failed to retrieve status")

    def _get_component_status(self) -> dict:
        """Get status of all proxy components."""
        components = {}

        # Cache Engine Status
        try:
            if hasattr(self.proxy, "cache_engine") and self.proxy.cache_engine:
                cache_stats = (
                    self.proxy.cache_engine.get_stats() if hasattr(self.proxy.cache_engine, "get_stats") else {}
                )
                total_entries = cache_stats.get("cache_size", 0)

                components["cache_engine"] = {
                    "status": "healthy",
                    "backend": (
                        "sqlite"
                        if self.proxy.config.get("cache", {}).get("database_path", ":memory:") != ":memory:"
                        else "memory"
                    ),
                    "total_entries": total_entries,
                    "database_size_bytes": self._get_database_size(),
                }
            else:
                components["cache_engine"] = {"status": "unavailable"}
        except Exception as e:
            components["cache_engine"] = {"status": "error", "error": str(e)}

        # Database Manager Status
        try:
            if hasattr(self.proxy, "db_manager") and self.proxy.db_manager:
                components["database_manager"] = {
                    "status": "healthy",
                    "connection_active": True,
                    "last_backup": None,  # Could be enhanced with actual backup tracking
                }
            else:
                components["database_manager"] = {"status": "unavailable"}
        except Exception as e:
            components["database_manager"] = {"status": "error", "error": str(e)}

        # Throttle Manager Status
        try:
            if hasattr(self.proxy, "throttle_manager") and self.proxy.throttle_manager:
                active_throttles = len([s for s in self.proxy.throttle_manager.states.values() if s.delay_seconds > 1])
                components["throttle_manager"] = {"status": "healthy", "active_throttles": active_throttles}
            else:
                components["throttle_manager"] = {"status": "unavailable"}
        except Exception as e:
            components["throttle_manager"] = {"status": "error", "error": str(e)}

        # Security Manager Status
        try:
            if hasattr(self.proxy, "security_manager") and self.proxy.security_manager:
                components["security_manager"] = {
                    "status": "healthy",
                    "security_enabled": self.proxy.security_manager.security_enabled,
                }
            else:
                components["security_manager"] = {"status": "unavailable"}
        except Exception as e:
            components["security_manager"] = {"status": "error", "error": str(e)}

        return components

    def _get_system_metrics(self) -> dict:
        """Collect system-wide metrics."""
        metrics = {}

        try:
            # Use existing monitoring manager if available
            if hasattr(self.proxy, "monitoring_manager") and self.proxy.monitoring_manager:
                cache_stats = self.proxy.monitoring_manager.get_cache_stats()
                upstream_stats = self.proxy.monitoring_manager.get_upstream_stats()

                metrics["total_requests"] = upstream_stats.get("total_requests", 0)
                metrics["cache_hit_rate"] = cache_stats.get("hit_rate", 0.0)
                metrics["average_response_time_ms"] = upstream_stats.get("average_response_time", 0)
                metrics["errors_last_hour"] = upstream_stats.get("error_count", 0)
            else:
                # Fallback metrics
                metrics = {
                    "total_requests": "unavailable",
                    "cache_hit_rate": "unavailable",
                    "average_response_time_ms": "unavailable",
                    "errors_last_hour": "unavailable",
                }
        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _determine_overall_status(self, components: dict) -> str:
        """Determine overall system status from component statuses."""
        statuses = [comp.get("status", "unavailable") for comp in components.values()]

        if "error" in statuses:
            return "error"
        elif "degraded" in statuses:
            return "degraded"
        elif "unavailable" in statuses:
            return "degraded"
        else:
            return "healthy"

    def _get_database_size(self) -> int:
        """Get database file size in bytes."""
        try:
            import os

            db_path = self.proxy.config.get("cache", {}).get("database_path", ":memory:")
            if db_path and db_path != ":memory:" and os.path.exists(db_path):
                return os.path.getsize(db_path)
            return 0
        except Exception:
            return 0

    def _handle_admin_cache(self):
        """Handle GET /admin/cache - return cache statistics."""
        try:
            cache_stats = self._get_cache_statistics()
            response = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z", **cache_stats}
            self._send_admin_response(200, response)
        except Exception as e:
            self.logger.error(f"Cache endpoint error: {e}")
            self._send_admin_error(500, "CACHE_ERROR", "Failed to retrieve cache statistics")

    def _handle_admin_cache_domain(self, domain: str):
        """Handle GET /admin/cache/{domain} - return domain-specific cache data."""
        try:
            domain_stats = self._get_domain_cache_statistics(domain)
            if domain_stats is None:
                self._send_admin_error(404, "DOMAIN_NOT_FOUND", f"Domain not found: {domain}")
                return

            response = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                "domain": domain,
                **domain_stats,
            }
            self._send_admin_response(200, response)
        except Exception as e:
            self.logger.error(f"Domain cache endpoint error: {e}")
            self._send_admin_error(500, "CACHE_ERROR", f"Failed to retrieve cache data for domain: {domain}")

    def _get_cache_statistics(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        stats: Dict[str, Any] = {}

        try:
            cache_backend = (
                "sqlite"
                if self.proxy.config.get("cache", {}).get("database_path", ":memory:") != ":memory:"
                else "memory"
            )
            db_path = self.proxy.config.get("cache", {}).get("database_path", ":memory:")

            stats["cache_backend"] = cache_backend
            stats["database_path"] = db_path if db_path != ":memory:" else "in-memory"
            stats["database_size_bytes"] = self._get_database_size()

            # Get cache statistics from cache engine
            if hasattr(self.proxy, "cache_engine") and self.proxy.cache_engine:
                cache_stats = (
                    self.proxy.cache_engine.get_stats() if hasattr(self.proxy.cache_engine, "get_stats") else {}
                )

                stats["total_entries"] = cache_stats.get("cache_size", 0)
                stats["expired_entries"] = cache_stats.get("expired_entries", 0)

                stats["statistics"] = {
                    "hit_rate": cache_stats.get("hit_rate", 0.0),
                    "total_hits": cache_stats.get("hits", 0),
                    "total_misses": cache_stats.get("misses", 0),
                    "total_sets": cache_stats.get("sets", 0),
                    "compressed_entries": cache_stats.get("compressed", 0),
                    "average_entry_size_bytes": cache_stats.get("average_size", 0),
                }

                # TTL distribution
                default_ttl_count = cache_stats.get("default_ttl_entries", 0)
                custom_ttl_count = cache_stats.get("custom_ttl_entries", 0)
                stats["ttl_distribution"] = {"default_ttl": default_ttl_count, "custom_ttl": custom_ttl_count}

                # Oldest and newest entries
                stats["oldest_entry"] = cache_stats.get("oldest_entry")
                stats["newest_entry"] = cache_stats.get("newest_entry")
            else:
                stats.update(
                    {
                        "total_entries": 0,
                        "expired_entries": 0,
                        "statistics": {
                            "hit_rate": 0.0,
                            "total_hits": 0,
                            "total_misses": 0,
                            "total_sets": 0,
                            "compressed_entries": 0,
                            "average_entry_size_bytes": 0,
                        },
                        "ttl_distribution": {"default_ttl": 0, "custom_ttl": 0},
                        "oldest_entry": None,
                        "newest_entry": None,
                    }
                )

        except Exception as e:
            stats["error"] = str(e)

        return stats

    def _get_domain_cache_statistics(self, domain: str) -> dict:
        """Get cache statistics for a specific domain."""
        try:
            # Check if domain exists in domain mappings
            domain_mappings = self.proxy.config.get("domain_mappings", {})
            if domain not in domain_mappings:
                return None

            # Get domain-specific cache statistics
            stats = {"cache_entries": 0, "total_size_bytes": 0, "hit_rate": 0.0, "entries": []}

            # Try to get domain-specific stats from cache engine
            if hasattr(self.proxy, "cache_engine") and self.proxy.cache_engine:
                if hasattr(self.proxy.cache_engine, "get_domain_stats"):
                    domain_stats = self.proxy.cache_engine.get_domain_stats(domain)
                    if domain_stats:
                        stats.update(domain_stats)

                # If the cache engine supports getting entries by domain
                if hasattr(self.proxy.cache_engine, "get_domain_entries"):
                    entries = self.proxy.cache_engine.get_domain_entries(domain)
                    stats["entries"] = entries[:10]  # Limit to 10 entries for response size

            return stats

        except Exception as e:
            self.logger.error(f"Error getting domain cache statistics: {e}")
            return None

    def _handle_admin_domains(self):
        """Handle GET /admin/domains - return domain mapping status."""
        try:
            domain_stats = self._get_domain_mapping_statistics()
            response = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                "domain_mappings": domain_stats,
            }
            self._send_admin_response(200, response)
        except Exception as e:
            self.logger.error(f"Domains endpoint error: {e}")
            self._send_admin_error(500, "DOMAINS_ERROR", "Failed to retrieve domain statistics")

    def _get_domain_mapping_statistics(self) -> dict:
        """Get statistics for all configured domain mappings."""
        domain_stats = {}
        domain_mappings = self.proxy.config.get("domain_mappings", {})

        for domain_key, mapping in domain_mappings.items():
            try:
                stats = {
                    "upstream": mapping.get("upstream", ""),
                    "ttl_seconds": mapping.get(
                        "ttl_seconds", self.proxy.config.get("cache", {}).get("default_ttl_seconds", 86400)
                    ),
                    "status": "healthy",  # Default status
                    "last_successful_request": None,
                    "total_requests": 0,
                    "cache_entries": 0,
                    "error_rate": 0.0,
                    "last_error": None,
                }

                # Try to get upstream metrics from monitoring manager
                if hasattr(self.proxy, "monitoring_manager") and self.proxy.monitoring_manager:
                    upstream_stats = self.proxy.monitoring_manager.get_upstream_stats()

                    # Look for domain-specific stats
                    domain_upstream_stats = upstream_stats.get("domains", {}).get(domain_key, {})
                    if domain_upstream_stats:
                        stats["total_requests"] = domain_upstream_stats.get("total_requests", 0)
                        stats["error_rate"] = domain_upstream_stats.get("error_rate", 0.0)
                        stats["last_successful_request"] = domain_upstream_stats.get("last_successful_request")
                        stats["last_error"] = domain_upstream_stats.get("last_error")

                        # Determine status based on error rate
                        if stats["error_rate"] > 0.5:
                            stats["status"] = "error"
                        elif stats["error_rate"] > 0.1:
                            stats["status"] = "degraded"

                # Try to get cache entry count for this domain
                if hasattr(self.proxy, "cache_engine") and self.proxy.cache_engine:
                    if hasattr(self.proxy.cache_engine, "get_domain_entry_count"):
                        stats["cache_entries"] = self.proxy.cache_engine.get_domain_entry_count(domain_key)

                domain_stats[domain_key] = stats

            except Exception as e:
                domain_stats[domain_key] = {"upstream": mapping.get("upstream", ""), "status": "error", "error": str(e)}

        return domain_stats

    def _handle_admin_validate_config(self):
        """Handle POST /admin/validate-config - validate configuration without applying."""
        try:
            import json
            from datetime import datetime, timezone

            # Read and parse request body
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_admin_error(400, "EMPTY_BODY", "Request body is required")
                return

            body = self.rfile.read(content_length)
            try:
                request_data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_admin_error(400, "INVALID_JSON", "Invalid JSON in request body")
                return

            config_to_validate = request_data.get("configuration", {})

            # Validate configuration
            from reference_api_buddy.core.config import ConfigurationValidator

            merged_config = ConfigurationValidator.merge_with_defaults(config_to_validate)
            is_valid, errors = ConfigurationValidator.validate_config(merged_config)

            # Generate warnings for missing optional fields
            warnings = self._generate_config_warnings(config_to_validate, merged_config)

            response = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "merged_config": merged_config,
            }

            status_code = 200 if is_valid else 400
            self._send_admin_response(status_code, response)

        except Exception as e:
            self.logger.error(f"Config validation endpoint error: {e}")
            self._send_admin_error(500, "VALIDATION_ERROR", "Failed to validate configuration")

    def _generate_config_warnings(self, user_config: dict, merged_config: dict) -> list:
        """Generate warnings for configuration differences."""
        warnings = []

        def check_defaults(user_dict, merged_dict, path=""):
            for key, value in merged_dict.items():
                current_path = f"{path}.{key}" if path else key

                if key not in user_dict:
                    if isinstance(value, (str, int, float, bool)):
                        warnings.append(f"{current_path} not specified, using default value: {value}")
                elif isinstance(value, dict) and isinstance(user_dict.get(key), dict):
                    check_defaults(user_dict[key], value, current_path)

        try:
            check_defaults(user_config, merged_config)
        except Exception as e:
            warnings.append(f"Warning generation error: {str(e)}")

        return warnings


class ProxyHTTPRequestHandler(RequestProcessingMixin, BaseHTTPRequestHandler):
    """HTTP request handler for the caching proxy."""

    server_version = "ReferenceAPIBuddy/1.0"

    def __init__(self, *args, proxy_instance=None, **kwargs):
        self.proxy = proxy_instance
        self.metrics_collector = getattr(proxy_instance, "metrics_collector", None)
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_PUT(self):
        self._handle_request("PUT")

    def do_DELETE(self):
        self._handle_request("DELETE")

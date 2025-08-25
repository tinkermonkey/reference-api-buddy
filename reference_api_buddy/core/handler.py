"""Request processing pipeline for ProxyHTTPRequestHandler."""

import gzip
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler
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

            self.logger.debug(f"Making {method} request to {real_url} with timeout=30")
            self.logger.debug(f"Request headers: {req.headers}")

            # Make request with longer timeout for external services
            with urllib.request.urlopen(req, timeout=30) as response:
                response_data = response.read()
                status_code = response.getcode()
                response_headers = dict(response.headers)

                # Calculate response time
                response_time_ms = int((time.time() - start_time) * 1000)

                self.logger.debug(f"Received response from {real_url}: {status_code}")
                self.logger.debug(f"Response headers: {response_headers}")

                # Handle compression
                encoding = response_headers.get("Content-Encoding", "").lower()
                decompressed = False

                # Check if data is gzipped using magic number (more comprehensive check)
                if len(response_data) >= 2 and response_data[:2] == b"\x1f\x8b":
                    self.logger.debug(
                        f"Detected gzipped data by magic number for {real_url} "
                        f"(first 10 bytes: {response_data[:10].hex()})"
                    )
                    try:
                        response_data = gzip.decompress(response_data)
                        decompressed = True
                        self.logger.debug(f"Successfully decompressed gzip data for " f"{real_url}")
                    except Exception as e:
                        self.logger.warning(f"Failed to decompress gzipped data for " f"{real_url}: {e}")
                elif encoding in ["gzip", "deflate"]:
                    self.logger.debug(f"Detected {encoding} encoding via header for " f"{real_url}")
                    try:
                        if encoding == "gzip":
                            response_data = gzip.decompress(response_data)
                        elif encoding == "deflate":
                            response_data = zlib.decompress(response_data)
                        decompressed = True
                        self.logger.debug(f"Successfully decompressed {encoding} data for {real_url}")
                    except Exception as e:
                        self.logger.warning(f"Failed to decompress {encoding} data for {real_url}: {e}")

                # Fix headers after decompression
                if decompressed:
                    # Remove compression-related headers
                    response_headers.pop("Content-Encoding", None)
                    # Remove chunked encoding
                    response_headers.pop("Transfer-Encoding", None)
                    # Set correct content length for decompressed data
                    response_headers["Content-Length"] = str(len(response_data))
                    self.logger.debug(f"Updated headers after decompression: " f"Content-Length={len(response_data)}")
                else:
                    # Even if not decompressed, ensure we have proper headers for the proxy response
                    # Remove chunked encoding as we'll send the full response at once
                    if "Transfer-Encoding" in response_headers and response_headers["Transfer-Encoding"] == "chunked":
                        response_headers.pop("Transfer-Encoding", None)
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
            if hasattr(self.proxy, "security_manager") and self.proxy.security_manager is not None:
                key, _ = self.proxy.security_manager.extract_secure_key(
                    self.path, self.headers, parse_qs(urlparse(self.path).query)
                )
                if self.proxy.config.get("security", {}).get("require_secure_key", False):
                    if not key or not self.proxy.security_manager.validate_request(key):
                        self.logger.warning("Unauthorized request: Invalid or missing secure key.")
                        self.send_response(401)
                        self.end_headers()
                        self.wfile.write(b"Unauthorized: Invalid or missing secure key\n")
                        return
            # 2. Check admin endpoints (stub: /admin/health)
            if self.path.startswith("/admin/health"):
                self.logger.debug("Health check endpoint hit.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK\n")
                return
            # 3. Determine if this request matches a configured domain mapping
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
            # 4. If matched, apply cache-first architecture: check cache before any throttling
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

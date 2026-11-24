"""End-to-end tests for the 0.5.1 fixes, run against a real proxy and a real local upstream.

- Upstream errors are passed through with their own status and are never cached.
- A request answered with a 429 does not stay in flight.
- ``cache.max_cache_entries`` is read from the configuration.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import socket
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from reference_api_buddy.core.config import DEFAULT_CONFIG, ConfigurationValidator, deep_merge
from reference_api_buddy.core.proxy import CachingProxy


class FakeUpstream:
    """A local HTTP server that answers with scripted statuses and records every request."""

    def __init__(self):
        self.requests = []
        self.statuses = []  # popped one per request; an empty list means 200
        self.lock = threading.Lock()
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with upstream.lock:
                    upstream.requests.append(self.path)
                    status = upstream.statuses.pop(0) if upstream.statuses else 200
                body = b'{"ok": true}' if status < 400 else f"upstream said {status}".encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if status < 400 else "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def upstream():
    fake = FakeUpstream()
    yield fake
    fake.close()


@pytest.fixture
def make_proxy(upstream):
    """Start a proxy for the fake upstream; the proxy is mapped as ``/api``."""
    started = []

    def _make(requests_per_hour=1000, **cache_overrides):
        port = _free_port()
        config = {
            "server": {"host": "127.0.0.1", "port": port},
            "security": {"require_secure_key": False, "log_security_events": False},
            "cache": {"database_path": ":memory:", **cache_overrides},
            "domain_mappings": {"api": {"upstream": upstream.url}},
            "throttling": {"progressive_max_delay": 1, "domain_limits": {"api": requests_per_hour}},
            "admin": {"enabled": False},
            "logging": {"level": "ERROR", "enable_console": False},
        }
        proxy = CachingProxy(config)
        proxy.start(blocking=False)
        started.append(proxy)
        return proxy, port

    yield _make
    for proxy in started:
        proxy.stop()


def _get(port: int, path: str, timeout: float = 5.0):
    connection = HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


class TestUpstreamErrors:
    def test_upstream_status_is_passed_through(self, make_proxy, upstream):
        _, port = make_proxy()
        upstream.statuses = [404]

        status, body, _ = _get(port, "/api/missing")

        assert status == 404
        assert b"upstream said 404" in body

    @pytest.mark.parametrize("error_status", [404, 429, 500, 503])
    def test_upstream_errors_are_not_cached(self, make_proxy, upstream, error_status):
        _, port = make_proxy()
        upstream.statuses = [error_status]

        first_status, _, _ = _get(port, "/api/term")
        second_status, _, _ = _get(port, "/api/term")
        third_status, _, _ = _get(port, "/api/term")

        assert first_status == error_status
        assert second_status == 200
        assert third_status == 200
        # The success is cached, the error was not
        assert len(upstream.requests) == 2

    def test_network_errors_are_not_cached(self, make_proxy, upstream):
        proxy, port = make_proxy()
        upstream.close()  # nothing listens at the upstream address any more

        first_status, _, _ = _get(port, "/api/term")
        assert first_status == 502

        revived = FakeUpstream()
        try:
            # Point the same domain at a live upstream: the 502 must not be served from the cache
            proxy.config["domain_mappings"]["api"]["upstream"] = revived.url
            second_status, _, _ = _get(port, "/api/term")
            assert second_status == 200
            assert len(revived.requests) == 1
        finally:
            revived.close()

    def test_successful_responses_are_still_cached(self, make_proxy, upstream):
        _, port = make_proxy()

        assert _get(port, "/api/term")[0] == 200
        assert _get(port, "/api/term")[0] == 200

        assert len(upstream.requests) == 1


class TestThrottledRequestsDoNotStayInFlight:
    def test_throttled_request_asked_again_is_answered_at_once(self, make_proxy, upstream):
        proxy, port = make_proxy(requests_per_hour=1)
        assert _get(port, "/api/a")[0] == 200

        for _ in range(3):
            started = time.monotonic()
            status, _, headers = _get(port, "/api/b", timeout=5)
            assert status == 429
            assert "Retry-After" in headers
            assert time.monotonic() - started < 2

        assert len(upstream.requests) == 1
        assert proxy.inflight_tracker.get_stats()["in_flight_count"] == 0

    def test_concurrent_requests_waiting_on_a_throttled_one_get_the_429(self, make_proxy, upstream):
        proxy, port = make_proxy(requests_per_hour=1)
        assert _get(port, "/api/a")[0] == 200

        statuses = []
        threads = [
            threading.Thread(target=lambda: statuses.append(_get(port, "/api/b", timeout=10)[0])) for _ in range(5)
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert statuses == [429] * 5
        assert time.monotonic() - started < 5
        assert proxy.inflight_tracker.get_stats()["in_flight_count"] == 0

    def test_in_flight_request_is_completed_when_the_miss_path_raises(self, make_proxy, upstream):
        proxy, port = make_proxy()

        def explode(*args, **kwargs):
            raise RuntimeError("throttle manager exploded")

        proxy.throttle_manager.get_required_delay = explode

        status, _, _ = _get(port, "/api/a")

        assert status == 500
        assert proxy.inflight_tracker.get_stats()["in_flight_count"] == 0


class TestMaxCacheEntries:
    def test_cache_cap_is_read_from_config(self, make_proxy):
        proxy, _ = make_proxy(max_cache_entries=5000)

        assert proxy.cache_engine.max_cache_entries == 5000

    def test_cache_cap_defaults_to_1000(self, make_proxy):
        proxy, _ = make_proxy()

        assert proxy.cache_engine.max_cache_entries == 1000

    def test_cache_cap_is_applied_after_reload_config(self, make_proxy):
        proxy, _ = make_proxy()

        proxy.reload_config({**proxy.config, "cache": {**proxy.config["cache"], "max_cache_entries": 7}})

        assert proxy.cache_engine.max_cache_entries == 7

    def test_entries_past_the_old_cap_are_kept(self, make_proxy, upstream):
        _, port = make_proxy(requests_per_hour=100_000, max_cache_entries=1100)
        for i in range(1050):
            assert _get(port, f"/api/term{i}")[0] == 200
        assert len(upstream.requests) == 1050

        # The first term would have been evicted by the fixed 1,000-entry cap
        assert _get(port, "/api/term0")[0] == 200
        assert len(upstream.requests) == 1050

    @pytest.mark.parametrize("bad_value", [0, -1, "100", 1.5, True])
    def test_invalid_cap_is_rejected_by_the_validator(self, bad_value):
        config = deep_merge(DEFAULT_CONFIG, {"cache": {"max_cache_entries": bad_value}})

        valid, errors = ConfigurationValidator.validate_config(config)

        assert not valid
        assert any("max_cache_entries" in error for error in errors)

    def test_valid_and_default_caps_pass_the_validator(self):
        assert ConfigurationValidator.validate_config(DEFAULT_CONFIG)[0]
        config = deep_merge(DEFAULT_CONFIG, {"cache": {"max_cache_entries": 100_000}})
        assert ConfigurationValidator.validate_config(config)[0]

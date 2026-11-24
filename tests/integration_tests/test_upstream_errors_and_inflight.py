"""Regression tests for upstream error handling and in-flight request cleanup.

Covers GitHub issue #4:
1. Upstream errors are passed through with their real status and are never cached.
2. A request answered with a 429 releases its in-flight entry.
3. cache.max_cache_entries is read from config.
Plus: PUT/DELETE requests never share an in-flight slot.
"""

import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy import CachingProxy  # noqa: E402
from reference_api_buddy.core.config import DEFAULT_CONFIG, ConfigurationValidator, deep_merge  # noqa: E402


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeUpstreamHandler(BaseHTTPRequestHandler):
    """Upstream whose behaviour is chosen by the request path."""

    hits = {}
    hits_lock = threading.Lock()

    def log_message(self, format, *args):
        pass

    def _count(self):
        with self.hits_lock:
            self.hits[self.path] = self.hits.get(self.path, 0) + 1
            return self.hits[self.path]

    def _reply(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        hit = self._count()
        if self.path.startswith("/flaky"):
            # Outage on the first request, healthy afterwards
            if hit == 1:
                self._reply(503, b"upstream down")
            else:
                self._reply(200, b"recovered")
        elif self.path.startswith("/missing"):
            self._reply(404, b"no such term")
        elif self.path.startswith("/slow"):
            time.sleep(0.5)
            self._reply(200, f"{self.command} {self.path}".encode())
        else:
            self._reply(200, f"ok {self.path}".encode())

    do_GET = _handle
    do_PUT = _handle
    do_DELETE = _handle


def _request(url, method="GET", timeout=10):
    """Return (status, body) without raising on HTTP error statuses."""
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def upstream():
    FakeUpstreamHandler.hits = {}
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), FakeUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def make_proxy(upstream):
    proxies = []
    temp_dir = tempfile.TemporaryDirectory()

    def _make(throttling=None):
        port = _free_port()
        config = {
            "domain_mappings": {"up": {"upstream": upstream}},
            "server": {"host": "127.0.0.1", "port": port},
            "cache": {"database_path": str(Path(temp_dir.name) / f"cache_{port}.db")},
            "logging": {"level": "WARNING"},
        }
        if throttling:
            config["throttling"] = throttling
        proxy = CachingProxy(config)
        proxy.start(blocking=False)
        time.sleep(0.1)
        proxies.append(proxy)
        return proxy, f"http://127.0.0.1:{port}/up"

    yield _make
    for proxy in proxies:
        proxy.stop()
    temp_dir.cleanup()


class TestUpstreamErrors:
    def test_upstream_error_status_is_passed_through(self, make_proxy):
        _, base = make_proxy()
        status, body = _request(f"{base}/missing/term")
        assert status == 404
        assert body == b"no such term"

    def test_upstream_error_is_not_cached(self, make_proxy):
        _, base = make_proxy()
        status, body = _request(f"{base}/flaky/term")
        assert status == 503
        assert body == b"upstream down"

        # The outage must not be served from cache: the next request reaches upstream
        status, body = _request(f"{base}/flaky/term")
        assert status == 200
        assert body == b"recovered"
        assert FakeUpstreamHandler.hits["/flaky/term"] == 2

        # And the healthy response is cached
        status, body = _request(f"{base}/flaky/term")
        assert status == 200
        assert FakeUpstreamHandler.hits["/flaky/term"] == 2

    def test_network_error_is_not_cached(self, make_proxy):
        proxy, base = make_proxy()
        # Point the mapping at a closed port to force a URLError
        proxy.config["domain_mappings"]["up"]["upstream"] = f"http://127.0.0.1:{_free_port()}"
        status, _ = _request(f"{base}/anything")
        assert status == 502
        assert proxy.cache_engine.get(proxy.cache_engine.generate_cache_key("GET", "/up/anything")) is None


class TestThrottledInflightCleanup:
    def test_repeated_429_returns_promptly(self, make_proxy):
        proxy, base = make_proxy(
            throttling={"default_requests_per_hour": 1, "progressive_max_delay": 1, "domain_limits": {"up": 1}}
        )
        status, _ = _request(f"{base}/a")
        assert status == 200

        status, _ = _request(f"{base}/b")
        assert status == 429

        # Before the fix this hung for 60s on a leaked in-flight entry, then returned 500
        start = time.time()
        status, _ = _request(f"{base}/b", timeout=10)
        assert status == 429
        assert time.time() - start < 5

        assert proxy.inflight_tracker.get_stats()["in_flight_count"] == 0
        assert proxy.cache_engine.get(proxy.cache_engine.generate_cache_key("GET", "/up/b")) is None


class TestNonCacheableMethods:
    def test_concurrent_put_and_delete_get_their_own_responses(self, make_proxy):
        _, base = make_proxy()
        results = {}

        def call(method, path):
            results[(method, path)] = _request(f"{base}{path}", method=method)

        threads = [
            threading.Thread(target=call, args=("PUT", "/slow/one")),
            threading.Thread(target=call, args=("DELETE", "/slow/two")),
        ]
        for t in threads:
            t.start()
            time.sleep(0.05)
        for t in threads:
            t.join(timeout=10)

        assert results[("PUT", "/slow/one")] == (200, b"PUT /slow/one")
        assert results[("DELETE", "/slow/two")] == (200, b"DELETE /slow/two")


class TestMaxCacheEntries:
    def test_default_is_1000(self):
        proxy = CachingProxy({"logging": {"level": "WARNING"}})
        assert proxy.cache_engine.max_cache_entries == 1000

    def test_read_from_config(self):
        proxy = CachingProxy({"cache": {"max_cache_entries": 50000}, "logging": {"level": "WARNING"}})
        assert proxy.cache_engine.max_cache_entries == 50000

    def test_survives_reload(self):
        proxy = CachingProxy({"logging": {"level": "WARNING"}})
        proxy.reload_config({"cache": {"max_cache_entries": 2500}, "logging": {"level": "WARNING"}})
        assert proxy.cache_engine.max_cache_entries == 2500

    @pytest.mark.parametrize("value", [0, -5, "many", True])
    def test_invalid_values_are_rejected(self, value):
        config = deep_merge(DEFAULT_CONFIG, {"cache": {"max_cache_entries": value}})
        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        assert "cache.max_cache_entries must be a positive integer." in errors

"""Integration tests for the request processing pipeline."""

import os
import sys

# Add the project root to the path to import modules
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import socket
import threading
import time
from http.client import HTTPConnection

import pytest

from reference_api_buddy.core.handler import ProxyHTTPRequestHandler
from reference_api_buddy.core.server import ThreadedHTTPServer


class DummySecurityManager:
    def extract_secure_key(self, path, headers, query):
        return headers.get("X-Secure-Key"), path

    def validate_request(self, key):
        return key == "valid-key"


class DummyThrottleManager:
    def __init__(self):
        self.calls = {}
        self.time_window = 60
        self.domain_limits = {"throttled.com": 1}

    def record_request(self, domain):
        now = time.time()
        if domain not in self.calls:
            self.calls[domain] = []
        self.calls[domain].append(now)
        # Remove old timestamps
        self.calls[domain] = [t for t in self.calls[domain] if now - t < self.time_window]

    def should_throttle(self, domain):
        limit = self.domain_limits.get(domain, 1000)
        self.record_request(domain)
        return len(self.calls.get(domain, [])) > limit

    def get_throttle_delay(self, domain):
        return 1

    def get_state(self, domain):
        class State:
            def __init__(self, timestamps):
                self.request_timestamps = timestamps

        return State(self.calls.get(domain, []))


class DummyCacheEngine:
    def __init__(self):
        self._cache = {}

    def generate_cache_key(self, method, url, body, content_type):
        return f"{method}:{url}"

    def get(self, cache_key):
        return self._cache.get(cache_key)

    def set(self, cache_key, resp_obj):
        # Store as a simple object with .status_code, .headers, .data
        class Resp:
            def __init__(self, data, headers, status_code):
                self.data = data
                self.headers = headers
                self.status_code = status_code

        self._cache[cache_key] = Resp(resp_obj.data, resp_obj.headers, resp_obj.status_code)


from reference_api_buddy.core.config import ConfigurationManager


class DummyProxy:
    def __init__(self, domain_mappings=None):
        class DummyLogger:
            def debug(self, msg):
                pass

            def info(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

            def critical(self, msg):
                pass

        self.logger = DummyLogger()
        self.metrics_collector = None
        config = {"security": {"require_secure_key": True}, "domain_mappings": domain_mappings or {}}
        self.config = ConfigurationManager(config).config
        self.security_manager = DummySecurityManager()
        self.throttle_manager = DummyThrottleManager()
        self.cache_engine = DummyCacheEngine()


@pytest.fixture(scope="module")
def server_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def http_server(server_port):
    # Only /resource and /throttled.com/resource are cacheable/throttled
    domain_mappings = {
        "resource": {},
        "throttled.com": {},
    }
    proxy = DummyProxy(domain_mappings=domain_mappings)
    server = ThreadedHTTPServer(("127.0.0.1", server_port), ProxyHTTPRequestHandler, proxy)
    thread = threading.Thread(target=server.start, kwargs={"blocking": False}, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield server, server_port, proxy
    server.stop()
    thread.join()


def test_unauthorized_request(http_server):
    server, port, _ = http_server
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/test")
    resp = conn.getresponse()
    assert resp.status == 401
    body = resp.read()
    assert b"Unauthorized" in body
    conn.close()


def test_admin_health(http_server):
    server, port, _ = http_server
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/admin/health", headers={"X-Secure-Key": "valid-key"})
    resp = conn.getresponse()
    assert resp.status == 200
    body = resp.read()
    assert b"OK" in body
    conn.close()


def test_throttled_request(http_server):
    server, port, _ = http_server
    conn = HTTPConnection("127.0.0.1", port)
    # Use a throttled domain
    conn.request("GET", "http://throttled.com/resource", headers={"X-Secure-Key": "valid-key"})
    resp = conn.getresponse()
    assert resp.status == 429
    body = resp.read()
    assert b"Too Many Requests" in body
    conn.close()


def test_cache_and_upstream(http_server):
    server, port, proxy = http_server
    conn = HTTPConnection("127.0.0.1", port)
    # First request: no upstream configured, should return 502 Bad Gateway
    conn.request("GET", "/resource", headers={"X-Secure-Key": "valid-key"})
    resp = conn.getresponse()
    assert resp.status == 502
    body = resp.read()
    assert b"No upstream configured" in body
    conn.close()
    # Second request: same result since no upstream is configured
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/resource", headers={"X-Secure-Key": "valid-key"})
    resp = conn.getresponse()
    assert resp.status == 502
    body = resp.read()
    assert b"No upstream configured" in body  # Still get error
    conn.close()


def test_configured_upstream_caching(server_port):
    """Test caching with a properly configured upstream"""
    # Configure a domain mapping with an actual upstream (using httpbin.org for testing)
    domain_mappings = {"httpbin": {"upstream": "https://httpbin.org"}}
    proxy = DummyProxy(domain_mappings=domain_mappings)
    server = ThreadedHTTPServer(("127.0.0.1", server_port + 1), ProxyHTTPRequestHandler, proxy)
    thread = threading.Thread(target=server.start, kwargs={"blocking": False}, daemon=True)
    thread.start()
    time.sleep(0.2)

    try:
        conn = HTTPConnection("127.0.0.1", server_port + 1)
        # First request: cache miss, should forward to httpbin and cache
        conn.request("GET", "/httpbin/get", headers={"X-Secure-Key": "valid-key"})
        resp = conn.getresponse()
        # Should get 200 from httpbin.org/get endpoint
        assert resp.status == 200
        body = resp.read()
        # httpbin.org/get returns JSON with request info
        assert b'"url"' in body  # httpbin response contains URL field
        conn.close()

        # Second request: should be served from cache
        conn = HTTPConnection("127.0.0.1", server_port + 1)
        conn.request("GET", "/httpbin/get", headers={"X-Secure-Key": "valid-key"})
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read()
        assert b'"url"' in body  # Same response from cache
        conn.close()
    finally:
        server.stop()
        thread.join()

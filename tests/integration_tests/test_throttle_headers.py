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
        self.calls = 0
        self.domain = "throttled.com"
        self.delay = 7
        self.limit = 5
        self.state = type(
            "State", (), {"request_timestamps": [time.time()] * 6, "violations": 2, "delay_seconds": self.delay}
        )()

    def record_request(self, domain):
        self.calls += 1

    def should_throttle(self, domain):
        return domain == self.domain

    def get_throttle_delay(self, domain):
        return self.delay

    def get_state(self, domain):
        return self.state

    @property
    def domain_limits(self):
        return {self.domain: self.limit}

    @property
    def default_limit(self):
        return 1000

    @property
    def time_window(self):
        return 3600


class DummyCacheEngine:
    def generate_cache_key(self, method, url, body, content_type):
        return f"{method}:{url}"

    def get(self, cache_key):
        return None

    def set(self, cache_key, resp_obj):
        pass


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
    domain_mappings = {"throttled.com": {}}
    proxy = DummyProxy(domain_mappings=domain_mappings)
    server = ThreadedHTTPServer(("127.0.0.1", server_port), ProxyHTTPRequestHandler, proxy)
    thread = threading.Thread(target=server.start, kwargs={"blocking": False}, daemon=True)
    thread.start()
    time.sleep(0.2)
    yield server, server_port, proxy
    server.stop()
    thread.join()


def test_throttle_headers(http_server):
    server, port, _ = http_server
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "http://throttled.com/resource", headers={"X-Secure-Key": "valid-key"})
    resp = conn.getresponse()
    assert resp.status == 429
    headers = dict(resp.getheaders())
    assert "Retry-After" in headers
    assert "X-RateLimit-Limit" in headers
    assert "X-RateLimit-Remaining" in headers
    assert "X-RateLimit-Reset" in headers
    assert int(headers["Retry-After"]) == 7
    assert int(headers["X-RateLimit-Limit"]) == 5
    assert int(headers["X-RateLimit-Remaining"]) == 0
    assert int(headers["X-RateLimit-Reset"]) > 0
    body = resp.read()
    assert b"Too Many Requests" in body
    conn.close()

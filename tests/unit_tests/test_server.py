"""Unit tests for HTTP server and handler."""

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

from reference_api_buddy.core.config import ConfigurationManager
from reference_api_buddy.core.handler import ProxyHTTPRequestHandler
from reference_api_buddy.core.server import ThreadedHTTPServer


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
        # Use config to control which URLs are cacheable/throttled
        config = {"domain_mappings": domain_mappings or {}}
        self.config = ConfigurationManager(config).config


@pytest.fixture(scope="module")
def server_port():
    # Find a free port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def http_server(server_port):
    proxy = DummyProxy()
    server = ThreadedHTTPServer(("127.0.0.1", server_port), ProxyHTTPRequestHandler, proxy)
    thread = threading.Thread(target=server.start, kwargs={"blocking": False}, daemon=True)
    thread.start()
    time.sleep(0.2)  # Give server time to start
    yield server, server_port
    server.stop()
    thread.join()


def test_server_responds_not_implemented(http_server):
    server, port = http_server
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/test")
    resp = conn.getresponse()
    assert resp.status == 404  # Domain not mapped should return 404
    body = resp.read()
    assert b"Domain not mapped" in body
    conn.close()


def test_server_handles_multiple_requests(http_server):
    server, port = http_server
    conn = HTTPConnection("127.0.0.1", port)
    for _ in range(3):
        conn.request("POST", "/test")
        resp = conn.getresponse()
        assert resp.status == 404  # Domain not mapped should return 404
        body = resp.read()
        assert b"Domain not mapped" in body
    conn.close()

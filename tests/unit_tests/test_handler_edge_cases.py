"""Edge case tests for HTTP handler to improve coverage."""

import gzip
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer

# Add the project root to the path to import modules
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.core.config import ConfigurationManager
from reference_api_buddy.core.handler import ProxyHTTPRequestHandler, RequestProcessingMixin
from reference_api_buddy.core.server import ThreadedHTTPServer
from reference_api_buddy.security.manager import SecurityManager
from reference_api_buddy.throttling.manager import ThrottleManager


class MockProxy:
    """Mock proxy for testing handler edge cases."""

    def __init__(self, config=None, cache_engine=None, security_manager=None, throttle_manager=None):
        class MockLogger:
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

        self.logger = MockLogger()
        self.metrics_collector = Mock()
        self.config = config or {}
        self.cache_engine = cache_engine
        self.security_manager = security_manager
        self.throttle_manager = throttle_manager


class MockHandler(RequestProcessingMixin):
    """Mock handler for testing mixin methods directly."""

    def __init__(self, proxy=None, path="", headers=None, body=None):
        self.proxy = proxy or MockProxy()
        self.path = path
        self.headers = headers or {}
        self.rfile = io.BytesIO(body or b"")
        self.wfile = io.BytesIO()
        self._response_status = None
        self._response_headers = {}
        self._response_written = False

    def send_response(self, status):
        self._response_status = status

    def send_header(self, key, value):
        self._response_headers[key] = value

    def end_headers(self):
        self._response_written = True

    def _handle_request_safe(self, method):
        """Wrapper around _handle_request that catches exceptions."""
        try:
            self._handle_request(method)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Internal Server Error: {str(e)}".encode())


class TestHandlerEdgeCases:
    """Test edge cases and error scenarios in the HTTP handler."""

    def test_forward_request_no_upstream(self):
        """Test _forward_request with domain that has no upstream configured."""
        config = {"domain_mappings": {"emptydomain": {}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        response_data, status, headers = handler._forward_request("GET", "/emptydomain/test")
        assert status == 502
        assert b"No upstream configured" in response_data

    def test_forward_request_unmapped_domain(self):
        """Test _forward_request with unmapped domain."""
        config = {"domain_mappings": {}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        response_data, status, headers = handler._forward_request("GET", "/unmappeddomain/test")
        assert status == 404
        assert b"Domain not mapped" in response_data

    def test_forward_request_invalid_path(self):
        """Test _forward_request with invalid path."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy)

        response_data, status, headers = handler._forward_request("GET", "/")
        assert status == 400
        assert b"Invalid request path" in response_data

    def test_forward_request_network_error(self):
        """Test _forward_request with network error."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://127.0.0.1:99999"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")
            assert status == 502
            assert b"Upstream server error" in response_data

    def test_gzip_decompression_success(self):
        """Test successful gzip decompression."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        original_data = b"Hello, World!"
        gzipped_data = gzip.compress(original_data)

        mock_response = Mock()
        mock_response.read.return_value = gzipped_data
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "gzip"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == original_data
            assert "Content-Encoding" not in headers

    def test_gzip_decompression_failure(self):
        """Test gzip decompression failure handling."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        mock_response = Mock()
        mock_response.read.return_value = b"\x1f\x8b\x08\x00invalid_gzip_data"
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "gzip"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            # Should return original data even if decompression fails
            assert response_data == b"\x1f\x8b\x08\x00invalid_gzip_data"

    def test_deflate_decompression_success(self):
        """Test successful deflate decompression."""
        import zlib

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        original_data = b"Hello, deflate!"
        deflated_data = zlib.compress(original_data)

        mock_response = Mock()
        mock_response.read.return_value = deflated_data
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "deflate"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == original_data
            assert "Content-Encoding" not in headers

    def test_deflate_decompression_failure(self):
        """Test deflate decompression failure handling."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        mock_response = Mock()
        mock_response.read.return_value = b"invalid_deflate_data"
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "deflate"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == b"invalid_deflate_data"

    def test_gzip_magic_number_detection(self):
        """Test gzip detection by magic number without header."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        original_data = b"Hello, magic gzip!"
        gzipped_data = gzip.compress(original_data)

        mock_response = Mock()
        mock_response.read.return_value = gzipped_data
        mock_response.getcode.return_value = 200
        mock_response.headers = {}  # No Content-Encoding header

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == original_data

    def test_admin_health_endpoint(self):
        """Test admin health endpoint handling."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy, path="/admin/health")

        handler._handle_request("GET")
        assert handler._response_status == 200

    def test_security_manager_unauthorized(self):
        """Test security manager rejecting unauthorized request."""
        security_manager = Mock()
        security_manager.extract_secure_key.return_value = ("invalid_key", None)
        security_manager.validate_request.return_value = False

        config = {
            "security": {"require_secure_key": True},
            "domain_mappings": {"testdomain": {"upstream": "http://example.com"}},
        }
        proxy = MockProxy(config=config, security_manager=security_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test")
        handler._handle_request("GET")

        assert handler._response_status == 401

    def test_security_manager_authorized(self):
        """Test security manager allowing authorized request."""
        security_manager = Mock()
        security_manager.extract_secure_key.return_value = ("valid_key", None)
        security_manager.validate_request.return_value = True

        config = {
            "security": {"require_secure_key": True},
            "domain_mappings": {"testdomain": {"upstream": "http://example.com"}},
        }
        proxy = MockProxy(config=config, security_manager=security_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test")

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b"Success", 200, {})
            handler._handle_request("GET")

            # Should proceed past security check
            assert handler._response_status != 401

    def test_throttling_rate_limit_exceeded(self):
        """Test throttling when rate limit is exceeded."""
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True
        throttle_manager.get_throttle_delay.return_value = 5
        throttle_manager.domain_limits = {}
        throttle_manager.default_limit = 1000
        throttle_manager.time_window = 3600

        mock_state = Mock()
        mock_state.request_timestamps = []
        throttle_manager.get_state.return_value = mock_state

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, throttle_manager=throttle_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test")
        handler._handle_request("GET")

        assert handler._response_status == 429
        assert "5" in handler._response_headers.get("Retry-After", "")

    def test_cache_hit(self):
        """Test cache hit scenario."""
        mock_cached = Mock()
        mock_cached.status_code = 200
        mock_cached.headers = {"Content-Type": "application/json"}
        mock_cached.data = b'{"cached": true}'

        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = mock_cached

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, cache_engine=cache_engine)

        handler = MockHandler(proxy=proxy, path="/testdomain/test")
        handler._handle_request("GET")

        assert handler._response_status == 200

    def test_cache_miss_and_set(self):
        """Test cache miss and subsequent cache set."""
        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = None  # Cache miss

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, cache_engine=cache_engine)

        handler = MockHandler(proxy=proxy, path="/testdomain/test")

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b'{"response": true}', 200, {"Content-Type": "application/json"})
            handler._handle_request("GET")

            cache_engine.set.assert_called_once()

    def test_post_request_with_body(self):
        """Test POST request with request body."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)

        request_body = b'{"data": "test"}'
        handler = MockHandler(
            proxy=proxy, path="/testdomain/test", headers={"Content-Length": str(len(request_body))}, body=request_body
        )

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b'{"success": true}', 200, {})
            handler._handle_request("POST")

            mock_forward.assert_called_once()
            args = mock_forward.call_args[0]
            assert args[2] == request_body

    def test_exception_handling(self):
        """Test exception handling in _handle_request."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy, path="/testdomain/test")

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.side_effect = Exception("Test exception")
            handler._handle_request("GET")

            assert handler._response_status == 500

    def test_transparent_proxy_for_unmatched_domain(self):
        """Test transparent proxying for domains not in mapping."""
        config = {"domain_mappings": {"knowndomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)

        handler = MockHandler(proxy=proxy, path="/unknowndomain/test")

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b"Transparent proxy response", 200, {})
            handler._handle_request("GET")

            mock_forward.assert_called_once()

    def test_query_parameters_handling(self):
        """Test URL with query parameters."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"Response with query params"
            mock_response.getcode.return_value = 200
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            response_data, status, headers = handler._forward_request("GET", "/testdomain/test?param=value")
            assert status == 200

    def test_root_path_handling(self):
        """Test handling of root path requests."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"Root response"
            mock_response.getcode.return_value = 200
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            response_data, status, headers = handler._forward_request("GET", "/testdomain/")
            assert status == 200

    def test_handler_logger_fallback(self):
        """Test handler logger fallback when no proxy logger available."""
        handler = MockHandler()
        handler.proxy = None

        # Should not raise exception when accessing logger
        logger = handler.logger
        assert logger is not None

    def test_metrics_collection_on_throttle(self):
        """Test metrics collection when throttling occurs."""
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True
        throttle_manager.get_throttle_delay.return_value = 5
        throttle_manager.domain_limits = {}
        throttle_manager.default_limit = 1000
        throttle_manager.time_window = 3600

        mock_state = Mock()
        mock_state.request_timestamps = []
        throttle_manager.get_state.return_value = mock_state

        metrics_collector = Mock()
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, throttle_manager=throttle_manager)
        proxy.metrics_collector = metrics_collector

        handler = MockHandler(proxy=proxy, path="/testdomain/test")
        handler._handle_request("GET")

        metrics_collector.record_event.assert_called_once()
        call_args = metrics_collector.record_event.call_args
        assert call_args[0][0] == "throttle"

    def test_handler_initialization(self):
        """Test ProxyHTTPRequestHandler initialization."""
        proxy = MockProxy()

        with patch("reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__"):
            handler = ProxyHTTPRequestHandler(None, None, None, proxy_instance=proxy)

            assert handler.proxy == proxy
            assert handler.metrics_collector == proxy.metrics_collector

    def test_handler_without_proxy_instance(self):
        """Test handler initialization without proxy instance."""
        with patch("reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__"):
            handler = ProxyHTTPRequestHandler(None, None, None)

            assert handler.proxy is None
            assert handler.metrics_collector is None

    def test_http_method_handlers_exist(self):
        """Test that all HTTP method handlers exist."""
        handler_class = ProxyHTTPRequestHandler

        assert hasattr(handler_class, "do_GET")
        assert hasattr(handler_class, "do_POST")
        assert hasattr(handler_class, "do_PUT")
        assert hasattr(handler_class, "do_DELETE")

    def test_header_filtering(self):
        """Test that problematic headers are filtered."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)
        handler = MockHandler(proxy=proxy)

        headers = {
            "Host": "old-host.com",
            "Connection": "keep-alive",
            "Content-Length": "100",
            "Accept": "application/json",
            "Authorization": "Bearer token",
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"Response"
            mock_response.getcode.return_value = 200
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            response_data, status, response_headers = handler._forward_request(
                "GET", "/testdomain/test", headers=headers
            )
            assert status == 200


class MockUpstreamServer:
    """Mock upstream server for testing forwarding scenarios."""

    def __init__(self, port):
        self.port = port
        self.server = None
        self.thread = None
        self.responses = {}
        self.request_count = 0

    def add_response(self, path, response_data, status=200, headers=None, compressed=False):
        """Add a response for a specific path."""
        if compressed and isinstance(response_data, str):
            response_data = gzip.compress(response_data.encode())
            headers = headers or {}
            headers["Content-Encoding"] = "gzip"
        self.responses[path] = {
            "data": response_data,
            "status": status,
            "headers": headers or {},
        }

    def start(self):
        """Start the mock server."""

        class MockRequestHandler(BaseHTTPRequestHandler):
            def __init__(self, mock_server):
                self.mock_server = mock_server

            def __call__(self, *args, **kwargs):
                self.mock_server_ref = self.mock_server
                return BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

            def do_GET(self):
                self.mock_server_ref.request_count += 1
                path = self.path
                if path in self.mock_server_ref.responses:
                    resp = self.mock_server_ref.responses[path]
                    self.send_response(resp["status"])
                    for key, value in resp["headers"].items():
                        self.send_header(key, value)
                    self.end_headers()
                    if isinstance(resp["data"], str):
                        self.wfile.write(resp["data"].encode())
                    else:
                        self.wfile.write(resp["data"])
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not Found")

            def do_POST(self):
                self.do_GET()

            def log_message(self, format, *args):
                pass  # Suppress logging

        handler_class = MockRequestHandler(self)
        self.server = HTTPServer(("127.0.0.1", self.port), handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.1)  # Give server time to start

    def stop(self):
        """Stop the mock server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join()


@pytest.fixture
def mock_upstream_port():
    """Get a free port for mock upstream server."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def mock_upstream_server(mock_upstream_port):
    """Create and start a mock upstream server."""
    server = MockUpstreamServer(mock_upstream_port)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def proxy_with_domain_mapping(mock_upstream_port):
    """Create a proxy with domain mapping."""
    config = {
        "domain_mappings": {
            "testdomain": {"upstream": f"http://127.0.0.1:{mock_upstream_port}"},
            "emptydomain": {},  # Domain with no upstream
        }
    }
    return MockProxy(config=config)


class TestHandlerEdgeCases:
    """Test edge cases and error scenarios in the HTTP handler."""

    def test_malformed_request_handling(self):
        """Test handling of malformed requests."""
        proxy = MockProxy()

        # Test empty path - this should go to transparent proxy and fail
        handler = MockHandler(proxy=proxy, path="", headers={})
        handler._handle_request_safe("GET")
        # Empty path goes to transparent proxy which will return 404 for unmapped domain
        assert handler._response_status in [404, 500, 502]

        # Test root path only
        handler = MockHandler(proxy=proxy, path="/", headers={})
        handler._handle_request_safe("GET")
        # Root path should result in error
        assert handler._response_status in [404, 500, 502]

    def test_domain_mapping_edge_cases(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test domain mapping error scenarios."""
        # Test domain with no upstream configured
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/emptydomain/test", headers={})

        response_data, status, headers = handler._forward_request("GET", "/emptydomain/test")
        assert status == 502
        assert b"No upstream configured" in response_data

    def test_domain_not_mapped(self):
        """Test request to unmapped domain."""
        proxy = MockProxy(config={"domain_mappings": {}})
        handler = MockHandler(proxy=proxy, path="/unmappeddomain/test", headers={})

        response_data, status, headers = handler._forward_request("GET", "/unmappeddomain/test")
        assert status == 404
        assert b"Domain not mapped" in response_data

    def test_invalid_path_handling(self):
        """Test handling of invalid request paths."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy, path="/", headers={})

        response_data, status, headers = handler._forward_request("GET", "/")
        assert status == 404
        assert b"Domain not mapped" in response_data

    @pytest.mark.skipif(os.environ.get("CI") == "true", reason="Skipping network timeout tests in CI environment")
    def test_timeout_scenarios(self, proxy_with_domain_mapping):
        """Test timeout handling."""
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Mock urllib.request.urlopen to raise timeout
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("timeout")
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")
            assert status == 502
            assert b"Upstream network error" in response_data  # Updated to match new error message

    def test_connection_error_recovery(self, proxy_with_domain_mapping):
        """Test connection error handling."""
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Mock urllib.request.urlopen to raise connection error
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = ConnectionError("Connection refused")
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")
            assert status == 502
            assert b"Upstream server error" in response_data

    def test_gzip_compression_handling(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test gzip compression and decompression edge cases."""
        # Add gzipped response
        mock_upstream_server.add_response(
            "/test", "Hello, World!", compressed=True, headers={"Content-Encoding": "gzip"}
        )

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})
        response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

        assert status == 200
        assert response_data == b"Hello, World!"
        assert "Content-Encoding" not in headers  # Should be removed after decompression
        assert headers.get("Content-Length") == str(len(response_data))

    def test_gzip_decompression_failure(self, proxy_with_domain_mapping):
        """Test gzip decompression failure handling."""
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Mock response with invalid gzip data
        mock_response = Mock()
        mock_response.read.return_value = b"\x1f\x8b\x08\x00invalid_gzip_data"  # Invalid gzip
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "gzip"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            # Should still return response even if decompression fails
            assert status == 200
            assert response_data == b"\x1f\x8b\x08\x00invalid_gzip_data"

    def test_deflate_compression_handling(self, proxy_with_domain_mapping):
        """Test deflate compression handling."""
        import zlib

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Mock response with deflate data
        original_data = b"Hello, deflate world!"
        deflate_data = zlib.compress(original_data)

        mock_response = Mock()
        mock_response.read.return_value = deflate_data
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "deflate"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == original_data
            assert "Content-Encoding" not in headers

    def test_deflate_decompression_failure(self, proxy_with_domain_mapping):
        """Test deflate decompression failure handling."""
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Mock response with invalid deflate data
        mock_response = Mock()
        mock_response.read.return_value = b"invalid_deflate_data"
        mock_response.getcode.return_value = 200
        mock_response.headers = {"Content-Encoding": "deflate"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            # Should still return response even if decompression fails
            assert status == 200
            assert response_data == b"invalid_deflate_data"

    def test_large_request_body_handling(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test handling of large request bodies."""
        # Use mocking instead of the real server for large body test
        handler = MockHandler(
            proxy=proxy_with_domain_mapping,
            path="/testdomain/test",
            headers={"Content-Type": "application/json", "Content-Length": "1000000"},
        )

        # Create large body
        large_body = b"x" * 1000000

        # Mock the urllib.request.urlopen to avoid connection issues
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"Response to large request"
            mock_response.getcode.return_value = 200
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            response_data, status, headers = handler._forward_request(
                "POST", "/testdomain/test", large_body, handler.headers
            )

            assert status == 200
            assert response_data == b"Response to large request"

    def test_invalid_headers_processing(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test processing of invalid headers."""
        mock_upstream_server.add_response("/test", "Response with filtered headers")

        # Headers that should be filtered out
        invalid_headers = {
            "Host": "old-host.com",
            "Connection": "keep-alive",
            "Content-Length": "100",
            "Accept": "application/json",  # This should be kept
            "Authorization": "Bearer token",  # This should be kept
        }

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers=invalid_headers)
        response_data, status, headers = handler._forward_request("GET", "/testdomain/test", headers=invalid_headers)

        assert status == 200

    def test_security_manager_integration(self):
        """Test security manager integration."""
        security_manager = Mock()
        security_manager.extract_secure_key.return_value = ("test_key", None)
        security_manager.validate_request.return_value = False

        config = {
            "security": {"require_secure_key": True},
            "domain_mappings": {"testdomain": {"upstream": "http://example.com"}},
        }
        proxy = MockProxy(config=config, security_manager=security_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})
        handler._handle_request("GET")

        assert handler._response_status == 401

    def test_security_manager_valid_key(self):
        """Test security manager with valid key."""
        security_manager = Mock()
        security_manager.extract_secure_key.return_value = ("valid_key", None)
        security_manager.validate_request.return_value = True

        config = {
            "security": {"require_secure_key": True},
            "domain_mappings": {"testdomain": {"upstream": "http://example.com"}},
        }
        proxy = MockProxy(config=config, security_manager=security_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})

        # Mock _forward_request to avoid actual network call
        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b"Success", 200, {})
            handler._handle_request("GET")

            # Should not return 401 since key is valid
            assert handler._response_status != 401

    def test_admin_health_endpoint(self):
        """Test admin health endpoint."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy, path="/admin/health", headers={})

        handler._handle_request("GET")
        assert handler._response_status == 200

    def test_throttling_integration(self):
        """Test throttling manager integration."""
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True
        throttle_manager.get_throttle_delay.return_value = 5
        throttle_manager.domain_limits = {"": 100}  # Empty domain for urlparse
        throttle_manager.default_limit = 1000
        throttle_manager.time_window = 3600

        # Mock throttle state
        mock_state = Mock()
        mock_state.request_timestamps = [time.time() - 1800]  # Half window ago
        throttle_manager.get_state.return_value = mock_state

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, throttle_manager=throttle_manager)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})
        handler._handle_request_safe("GET")

        assert handler._response_status == 429
        assert "5" in handler._response_headers.get("Retry-After", "")

    def test_cache_hit_scenario(self):
        """Test cache hit scenario."""
        # Mock cached response
        mock_cached = Mock()
        mock_cached.status_code = 200
        mock_cached.headers = {"Content-Type": "application/json"}
        mock_cached.data = b'{"cached": true}'

        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = mock_cached

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, cache_engine=cache_engine)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})
        handler._handle_request_safe("GET")

        assert handler._response_status == 200

    def test_cache_miss_scenario(self):
        """Test cache miss scenario."""
        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = None  # Cache miss

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, cache_engine=cache_engine)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})

        # Mock _forward_request to avoid actual network call
        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b'{"response": true}', 200, {"Content-Type": "application/json"})
            handler._handle_request_safe("GET")

            # Should call cache.set to store the response
            cache_engine.set.assert_called_once()

    def test_post_request_with_body(self):
        """Test POST request with body."""
        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = None

        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, cache_engine=cache_engine)

        # Mock rfile with request body
        request_body = b'{"data": "test"}'
        handler = MockHandler(
            proxy=proxy, path="/testdomain/test", headers={"Content-Length": str(len(request_body))}, body=request_body
        )

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b'{"success": true}', 200, {})
            handler._handle_request_safe("POST")

            # Verify body was passed to _forward_request
            mock_forward.assert_called_once()
            args = mock_forward.call_args[0]
            assert args[2] == request_body  # Body parameter    def test_exception_handling_in_handle_request(self):
        """Test exception handling in _handle_request."""
        proxy = MockProxy()
        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})

        # Mock _forward_request to raise an exception
        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.side_effect = Exception("Test exception")
            handler._handle_request("GET")

            assert handler._response_status == 500

    def test_no_proxy_attribute_logger(self):
        """Test handler without proxy attribute uses default logger."""
        handler = MockHandler()
        handler.proxy = None

        # Should not raise exception when accessing logger
        logger = handler.logger
        assert logger is not None

    def test_unmatched_domain_transparent_proxy(self):
        """Test transparent proxying for unmatched domains."""
        config = {"domain_mappings": {"knowndomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)

        handler = MockHandler(proxy=proxy, path="/unknowndomain/test", headers={})

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b"Transparent proxy response", 200, {})
            handler._handle_request("GET")

            # Should still call _forward_request for transparent proxying
            mock_forward.assert_called_once()

    def test_query_parameters_in_url(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test handling URLs with query parameters."""
        mock_upstream_server.add_response("/test?param=value", "Response with query params")

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test?param=value", headers={})
        response_data, status, headers = handler._forward_request("GET", "/testdomain/test?param=value")

        assert status == 200

    def test_empty_request_body_post(self):
        """Test POST request with empty body."""
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config)

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={"Content-Length": "0"})
        handler.rfile = io.BytesIO(b"")

        with patch.object(handler, "_forward_request") as mock_forward:
            mock_forward.return_value = (b"Success", 200, {})
            handler._handle_request("POST")

            # Should handle empty body gracefully
            mock_forward.assert_called_once()
            args = mock_forward.call_args[0]
            assert args[2] == b""  # Empty body

    def test_http_methods_coverage(self):
        """Test all HTTP methods are handled."""
        proxy = MockProxy()

        # Test that ProxyHTTPRequestHandler has all the method handlers
        handler_class = ProxyHTTPRequestHandler

        # Verify all HTTP methods are implemented
        assert hasattr(handler_class, "do_GET")
        assert hasattr(handler_class, "do_POST")
        assert hasattr(handler_class, "do_PUT")
        assert hasattr(handler_class, "do_DELETE")

    def test_handler_initialization(self):
        """Test ProxyHTTPRequestHandler initialization."""
        proxy = MockProxy()

        # Mock the BaseHTTPRequestHandler.__init__ to avoid actual server setup
        with patch("reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__"):
            handler = ProxyHTTPRequestHandler(None, None, None, proxy_instance=proxy)

            assert handler.proxy == proxy
            assert handler.metrics_collector == proxy.metrics_collector

    def test_handler_without_proxy_instance(self):
        """Test handler initialization without proxy instance."""
        with patch("reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__"):
            handler = ProxyHTTPRequestHandler(None, None, None)

            assert handler.proxy is None
            assert handler.metrics_collector is None

    def test_metrics_collection_on_throttle(self):
        """Test metrics collection when throttling occurs."""
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True
        throttle_manager.get_throttle_delay.return_value = 5
        throttle_manager.domain_limits = {}
        throttle_manager.default_limit = 1000
        throttle_manager.time_window = 3600

        mock_state = Mock()
        mock_state.request_timestamps = []
        throttle_manager.get_state.return_value = mock_state

        metrics_collector = Mock()
        config = {"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}}
        proxy = MockProxy(config=config, throttle_manager=throttle_manager)
        proxy.metrics_collector = metrics_collector

        handler = MockHandler(proxy=proxy, path="/testdomain/test", headers={})
        handler._handle_request("GET")

        # Verify metrics were recorded
        metrics_collector.record_event.assert_called_once()
        call_args = metrics_collector.record_event.call_args
        assert call_args[0][0] == "throttle"

    def test_gzip_magic_number_detection(self, proxy_with_domain_mapping):
        """Test gzip detection by magic number."""
        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/test", headers={})

        # Create gzipped data without Content-Encoding header
        original_data = b"Hello, gzip magic!"
        gzipped_data = gzip.compress(original_data)

        mock_response = Mock()
        mock_response.read.return_value = gzipped_data
        mock_response.getcode.return_value = 200
        mock_response.headers = {}  # No Content-Encoding header

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = mock_response
            response_data, status, headers = handler._forward_request("GET", "/testdomain/test")

            assert status == 200
            assert response_data == original_data

    def test_root_path_handling(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test handling of root path requests."""
        mock_upstream_server.add_response("/", "Root response")

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/", headers={})
        response_data, status, headers = handler._forward_request("GET", "/testdomain/")

        assert status == 200

    def test_root_path_with_query(self, proxy_with_domain_mapping, mock_upstream_server):
        """Test handling of root path with query parameters."""
        mock_upstream_server.add_response("/?param=value", "Root with query")

        handler = MockHandler(proxy=proxy_with_domain_mapping, path="/testdomain/?param=value", headers={})
        response_data, status, headers = handler._forward_request("GET", "/testdomain/?param=value")

        assert status == 200

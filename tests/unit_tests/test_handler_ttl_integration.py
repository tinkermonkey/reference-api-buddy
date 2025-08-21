"""Unit tests for request handler TTL integration."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from unittest.mock import MagicMock, Mock, patch

import pytest

from reference_api_buddy.core.handler import ProxyHTTPRequestHandler
from reference_api_buddy.database.models import CachedResponse


class TestHandlerTTLIntegration:
    """Test request handler TTL integration functionality."""

    @pytest.fixture
    def mock_proxy_with_ttl(self):
        """Create a mock proxy with TTL configuration."""
        proxy = Mock()
        proxy.config = {
            "cache": {"default_ttl_seconds": 3600},
            "domain_mappings": {
                "api1": {"upstream": "https://api1.example.com", "ttl_seconds": 300},
                "api2": {"upstream": "https://api2.example.com", "ttl_seconds": 7200},
            },
            "security": {"require_secure_key": False},
        }
        proxy.logger = Mock()
        proxy.security_manager = None
        proxy.throttle_manager = None
        proxy.metrics_collector = None

        # Mock cache engine with TTL manager
        cache_engine = Mock()
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.get.return_value = None  # Cache miss
        cache_engine.set = Mock()
        proxy.cache_engine = cache_engine

        return proxy

    @pytest.fixture
    def mock_handler(self, mock_proxy_with_ttl):
        """Create a mock handler with the proxy."""
        handler = Mock(spec=ProxyHTTPRequestHandler)
        handler.proxy = mock_proxy_with_ttl
        handler.path = "/api1/test/endpoint"
        handler.headers = {"Content-Type": "application/json"}
        handler.logger = Mock()

        # Mock the RequestProcessingMixin methods
        handler._forward_request = Mock(return_value=(b'{"result": "test"}', 200, {"Content-Type": "application/json"}))
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.rfile = Mock()
        handler.rfile.read.return_value = b""

        return handler

    def test_handler_creates_proper_cached_response_object(self, mock_handler):
        """Test that handler creates proper CachedResponse objects."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        # Create a real instance to test the mixin method
        mixin = RequestProcessingMixin()
        mixin.proxy = mock_handler.proxy
        mixin.path = mock_handler.path
        mixin.headers = mock_handler.headers
        mixin.send_response = mock_handler.send_response
        mixin.send_header = mock_handler.send_header
        mixin.end_headers = mock_handler.end_headers
        mixin.wfile = mock_handler.wfile
        mixin.rfile = mock_handler.rfile
        mixin._forward_request = mock_handler._forward_request

        # Execute the request handling
        mixin._handle_request("GET")

        # Verify cache engine set was called
        mock_handler.proxy.cache_engine.set.assert_called_once()

        # Get the call arguments
        call_args = mock_handler.proxy.cache_engine.set.call_args
        args, kwargs = call_args
        cache_key, response_obj = args
        domain_key = kwargs.get("domain_key")

        # Verify the cache key
        assert cache_key == "test_cache_key"

        # Verify the response object is a proper CachedResponse
        assert isinstance(response_obj, CachedResponse)
        assert response_obj.data == b'{"result": "test"}'
        assert response_obj.headers == {"Content-Type": "application/json"}
        assert response_obj.status_code == 200
        assert response_obj.created_at is None  # Should be None, set by cache engine
        assert response_obj.ttl_seconds is None  # Should be None, determined by TTL manager
        assert response_obj.access_count == 0
        assert response_obj.last_accessed is None

        # Verify domain key is passed correctly
        assert domain_key == "api1"

    def test_handler_passes_correct_domain_key_for_different_domains(self, mock_proxy_with_ttl):
        """Test that handler passes correct domain keys for different domain mappings."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        test_cases = [
            ("/api1/test", "api1"),
            ("/api2/endpoint", "api2"),
            ("/api1", "api1"),
            ("/api2", "api2"),
        ]

        for path, expected_domain in test_cases:
            # Create fresh mixin for each test
            mixin = RequestProcessingMixin()
            mixin.proxy = mock_proxy_with_ttl
            mixin.path = path
            mixin.headers = {"Content-Type": "application/json"}
            mixin.send_response = Mock()
            mixin.send_header = Mock()
            mixin.end_headers = Mock()
            mixin.wfile = Mock()
            mixin.rfile = Mock()
            mixin.rfile.read.return_value = b""
            mixin._forward_request = Mock(
                return_value=(b'{"result": "test"}', 200, {"Content-Type": "application/json"})
            )

            # Reset cache engine mock
            mock_proxy_with_ttl.cache_engine.set.reset_mock()

            # Execute the request handling
            mixin._handle_request("GET")

            # Verify correct domain key was passed
            call_args = mock_proxy_with_ttl.cache_engine.set.call_args
            args, kwargs = call_args
            domain_key = kwargs.get("domain_key")
            assert domain_key == expected_domain, f"Expected {expected_domain} for path {path}, got {domain_key}"

    def test_handler_no_hardcoded_ttl_in_response(self, mock_handler):
        """Test that handler no longer uses hardcoded TTL values."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        # Create a real instance to test the mixin method
        mixin = RequestProcessingMixin()
        mixin.proxy = mock_handler.proxy
        mixin.path = mock_handler.path
        mixin.headers = mock_handler.headers
        mixin.send_response = mock_handler.send_response
        mixin.send_header = mock_handler.send_header
        mixin.end_headers = mock_handler.end_headers
        mixin.wfile = mock_handler.wfile
        mixin.rfile = mock_handler.rfile
        mixin._forward_request = mock_handler._forward_request

        # Execute the request handling
        mixin._handle_request("GET")

        # Get the response object that was cached
        call_args = mock_handler.proxy.cache_engine.set.call_args
        args, kwargs = call_args
        _, response_obj = args

        # Verify TTL is None (not hardcoded)
        assert response_obj.ttl_seconds is None, "TTL should be None to let TTL manager determine it"

    def test_handler_post_request_with_body(self, mock_proxy_with_ttl):
        """Test that handler properly handles POST requests with body."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        mixin = RequestProcessingMixin()
        mixin.proxy = mock_proxy_with_ttl
        mixin.path = "/api1/post/endpoint"
        mixin.headers = {"Content-Type": "application/json", "Content-Length": "20"}
        mixin.send_response = Mock()
        mixin.send_header = Mock()
        mixin.end_headers = Mock()
        mixin.wfile = Mock()
        mixin.rfile = Mock()
        mixin.rfile.read.return_value = b'{"data": "test"}'
        mixin._forward_request = Mock(
            return_value=(b'{"result": "created"}', 201, {"Content-Type": "application/json"})
        )

        # Execute POST request handling
        mixin._handle_request("POST")

        # Verify cache engine set was called with correct parameters
        mock_proxy_with_ttl.cache_engine.set.assert_called_once()
        call_args = mock_proxy_with_ttl.cache_engine.set.call_args
        args, kwargs = call_args
        _, response_obj = args
        domain_key = kwargs.get("domain_key")

        # Verify response object properties
        assert isinstance(response_obj, CachedResponse)
        assert response_obj.data == b'{"result": "created"}'
        assert response_obj.status_code == 201
        assert response_obj.ttl_seconds is None
        assert domain_key == "api1"

    def test_handler_cache_hit_bypasses_caching_logic(self, mock_proxy_with_ttl):
        """Test that cache hits bypass the caching logic entirely."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        # Configure cache to return a hit
        cached_response = CachedResponse(
            data=b'{"cached": "response"}',
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at="2025-08-21 10:00:00",
            ttl_seconds=3600,
            access_count=1,
            last_accessed="2025-08-21 10:00:00",
        )
        mock_proxy_with_ttl.cache_engine.get.return_value = cached_response

        mixin = RequestProcessingMixin()
        mixin.proxy = mock_proxy_with_ttl
        mixin.path = "/api1/cached/endpoint"
        mixin.headers = {"Content-Type": "application/json"}
        mixin.send_response = Mock()
        mixin.send_header = Mock()
        mixin.end_headers = Mock()
        mixin.wfile = Mock()
        mixin.rfile = Mock()
        mixin.rfile.read.return_value = b""
        mixin._forward_request = Mock()  # Should not be called

        # Execute request handling
        mixin._handle_request("GET")

        # Verify forward request was not called (cache hit)
        mixin._forward_request.assert_not_called()

        # Verify cache engine set was not called (no new caching)
        mock_proxy_with_ttl.cache_engine.set.assert_not_called()

        # Verify response was sent from cache
        mixin.send_response.assert_called_once_with(200)
        mixin.wfile.write.assert_called_once_with(b'{"cached": "response"}')

    def test_handler_without_cache_engine(self, mock_proxy_with_ttl):
        """Test that handler works when cache engine is not available."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        # Remove cache engine
        mock_proxy_with_ttl.cache_engine = None

        mixin = RequestProcessingMixin()
        mixin.proxy = mock_proxy_with_ttl
        mixin.path = "/api1/no-cache"
        mixin.headers = {"Content-Type": "application/json"}
        mixin.send_response = Mock()
        mixin.send_header = Mock()
        mixin.end_headers = Mock()
        mixin.wfile = Mock()
        mixin.rfile = Mock()
        mixin.rfile.read.return_value = b""
        mixin._forward_request = Mock(
            return_value=(b'{"result": "no-cache"}', 200, {"Content-Type": "application/json"})
        )

        # Execute request handling
        mixin._handle_request("GET")

        # Verify forward request was called
        mixin._forward_request.assert_called_once()

        # Verify response was sent successfully
        mixin.send_response.assert_called_once_with(200)
        mixin.wfile.write.assert_called_once_with(b'{"result": "no-cache"}')

    def test_handler_unmapped_domain_fallback(self, mock_proxy_with_ttl):
        """Test that handler handles unmapped domains appropriately."""
        from reference_api_buddy.core.handler import RequestProcessingMixin

        mixin = RequestProcessingMixin()
        mixin.proxy = mock_proxy_with_ttl
        mixin.path = "/unmapped_domain/endpoint"  # Not in domain_mappings
        mixin.headers = {"Content-Type": "application/json"}
        mixin.send_response = Mock()
        mixin.send_header = Mock()
        mixin.end_headers = Mock()
        mixin.wfile = Mock()
        mixin.rfile = Mock()
        mixin.rfile.read.return_value = b""
        mixin._forward_request = Mock(
            return_value=(b"Domain not mapped: unmapped_domain", 404, {"Content-Type": "text/plain"})
        )

        # Execute request handling
        mixin._handle_request("GET")

        # Verify response
        mixin.send_response.assert_called_once_with(404)
        mixin.wfile.write.assert_called_once_with(b"Domain not mapped: unmapped_domain")

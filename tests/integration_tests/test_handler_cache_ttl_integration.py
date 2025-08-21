"""Integration tests for handler-cache TTL integration."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import json
import time
from unittest.mock import Mock, patch

import pytest

from reference_api_buddy.core.handler import RequestProcessingMixin
from reference_api_buddy.core.proxy import CachingProxy
from reference_api_buddy.database.models import CachedResponse


class TestHandlerCacheTTLIntegration:
    """Integration tests for handler-cache TTL functionality."""

    @pytest.fixture
    def ttl_proxy_config(self):
        """Configuration for testing TTL integration."""
        return {
            "server": {"host": "127.0.0.1", "port": 0},
            "cache": {"default_ttl_seconds": 1800, "database_path": ":memory:"},  # 30 minutes default
            "domain_mappings": {
                "fast_api": {"upstream": "https://fast.example.com", "ttl_seconds": 300},  # 5 minutes
                "slow_api": {"upstream": "https://slow.example.com", "ttl_seconds": 7200},  # 2 hours
            },
            "security": {"require_secure_key": False},
            "logging": {"level": "INFO"},
        }

    def test_end_to_end_ttl_resolution_fast_api(self, ttl_proxy_config):
        """Test complete TTL resolution flow for fast API domain."""
        proxy = CachingProxy(ttl_proxy_config)

        def mock_forward_request(handler_self, method, target_url, body=None, headers=None):
            return (b'{"message": "fast api response"}', 200, {"Content-Type": "application/json"})

        try:
            # Create a request processing mixin instance to test functionality
            mixin = RequestProcessingMixin()
            mixin.proxy = proxy
            mixin.path = "/fast_api/test/endpoint"
            mixin.headers = {"Content-Type": "application/json"}
            mixin.send_response = Mock()
            mixin.send_header = Mock()
            mixin.end_headers = Mock()
            mixin.wfile = Mock()
            mixin.rfile = Mock()
            mixin.rfile.read.return_value = b""
            mixin._forward_request = mock_forward_request

            # Execute the request handling
            mixin._handle_request("GET")

            # Verify cache entry was created with domain-specific TTL
            cache_performance = proxy.cache_engine.get_cache_performance()
            assert cache_performance["total_entries"] == 1

            # Check that the cached entry has the correct TTL
            cache_key = proxy.cache_engine.generate_cache_key("GET", "/fast_api/test/endpoint")
            cached_entry = proxy.cache_engine.get(cache_key)
            assert cached_entry is not None
            assert cached_entry.ttl_seconds == 300  # Should use fast_api TTL
            assert cached_entry.data == b'{"message": "fast api response"}'

        finally:
            proxy.stop()

    def test_end_to_end_ttl_resolution_slow_api(self, ttl_proxy_config):
        """Test complete TTL resolution flow for slow API domain."""
        proxy = CachingProxy(ttl_proxy_config)

        def mock_forward_request(handler_self, method, target_url, body=None, headers=None):
            return (b'{"message": "slow api response"}', 200, {"Content-Type": "application/json"})

        try:
            mixin = RequestProcessingMixin()
            mixin.proxy = proxy
            mixin.path = "/slow_api/data/endpoint"
            mixin.headers = {"Content-Type": "application/json"}
            mixin.send_response = Mock()
            mixin.send_header = Mock()
            mixin.end_headers = Mock()
            mixin.wfile = Mock()
            mixin.rfile = Mock()
            mixin.rfile.read.return_value = b""
            mixin._forward_request = mock_forward_request

            # Execute the request handling
            mixin._handle_request("GET")

            # Verify cache entry has slow API TTL
            cache_key = proxy.cache_engine.generate_cache_key("GET", "/slow_api/data/endpoint")
            cached_entry = proxy.cache_engine.get(cache_key)
            assert cached_entry is not None
            assert cached_entry.ttl_seconds == 7200  # Should use slow_api TTL
            assert cached_entry.data == b'{"message": "slow api response"}'

        finally:
            proxy.stop()

    def test_end_to_end_ttl_resolution_unmapped_domain(self, ttl_proxy_config):
        """Test TTL resolution for unmapped domains using default TTL."""
        proxy = CachingProxy(ttl_proxy_config)

        def mock_forward_request(handler_self, method, target_url, body=None, headers=None):
            # Simulate unmapped domain response
            return (b"Domain not mapped: unmapped_domain", 404, {"Content-Type": "text/plain"})

        try:
            mixin = RequestProcessingMixin()
            mixin.proxy = proxy
            mixin.path = "/unmapped_domain/endpoint"
            mixin.headers = {"Content-Type": "application/json"}
            mixin.send_response = Mock()
            mixin.send_header = Mock()
            mixin.end_headers = Mock()
            mixin.wfile = Mock()
            mixin.rfile = Mock()
            mixin.rfile.read.return_value = b""
            mixin._forward_request = mock_forward_request

            # Execute the request handling
            mixin._handle_request("GET")

            # For unmapped domains, the handler should still work but may not cache 404 responses
            # This tests the flow works without crashing
            mixin.send_response.assert_called_once_with(404)

        finally:
            proxy.stop()

    def test_post_request_with_domain_specific_ttl(self, ttl_proxy_config):
        """Test POST request caching with domain-specific TTL."""
        proxy = CachingProxy(ttl_proxy_config)

        def mock_forward_request(handler_self, method, target_url, body=None, headers=None):
            return (b'{"created": "success", "id": 123}', 201, {"Content-Type": "application/json"})

        try:
            mixin = RequestProcessingMixin()
            mixin.proxy = proxy
            mixin.path = "/fast_api/create"
            mixin.headers = {"Content-Type": "application/json", "Content-Length": "20"}
            mixin.send_response = Mock()
            mixin.send_header = Mock()
            mixin.end_headers = Mock()
            mixin.wfile = Mock()
            mixin.rfile = Mock()
            mixin.rfile.read.return_value = b'{"name": "test"}'
            mixin._forward_request = mock_forward_request

            # Execute POST request
            mixin._handle_request("POST")

            # Verify cache entry was created with domain-specific TTL
            cache_key = proxy.cache_engine.generate_cache_key(
                "POST", "/fast_api/create", b'{"name": "test"}', "application/json"
            )
            cached_entry = proxy.cache_engine.get(cache_key)
            assert cached_entry is not None
            assert cached_entry.ttl_seconds == 300  # fast_api TTL
            assert cached_entry.status_code == 201
            assert cached_entry.data == b'{"created": "success", "id": 123}'

        finally:
            proxy.stop()

    def test_cache_hit_preserves_original_ttl(self, ttl_proxy_config):
        """Test that cache hits preserve the original TTL set by domain configuration."""
        proxy = CachingProxy(ttl_proxy_config)

        def mock_forward_request(handler_self, method, target_url, body=None, headers=None):
            return (b'{"data": "cached response"}', 200, {"Content-Type": "application/json"})

        try:
            # First request - populate cache
            mixin1 = RequestProcessingMixin()
            mixin1.proxy = proxy
            mixin1.path = "/slow_api/cached/data"
            mixin1.headers = {"Content-Type": "application/json"}
            mixin1.send_response = Mock()
            mixin1.send_header = Mock()
            mixin1.end_headers = Mock()
            mixin1.wfile = Mock()
            mixin1.rfile = Mock()
            mixin1.rfile.read.return_value = b""
            mixin1._forward_request = mock_forward_request

            mixin1._handle_request("GET")

            # Verify cache was populated with correct TTL
            cache_key = proxy.cache_engine.generate_cache_key("GET", "/slow_api/cached/data")
            cached_entry = proxy.cache_engine.get(cache_key)
            assert cached_entry is not None
            assert cached_entry.ttl_seconds == 7200  # slow_api TTL

            # Second request - should hit cache
            mixin2 = RequestProcessingMixin()
            mixin2.proxy = proxy
            mixin2.path = "/slow_api/cached/data"
            mixin2.headers = {"Content-Type": "application/json"}
            mixin2.send_response = Mock()
            mixin2.send_header = Mock()
            mixin2.end_headers = Mock()
            mixin2.wfile = Mock()
            mixin2.rfile = Mock()
            mixin2.rfile.read.return_value = b""
            mixin2._forward_request = Mock()  # Should not be called

            mixin2._handle_request("GET")

            # Verify forward request was not called (cache hit)
            mixin2._forward_request.assert_not_called()

            # Verify cached response was served
            mixin2.send_response.assert_called_once_with(200)
            mixin2.wfile.write.assert_called_once_with(b'{"data": "cached response"}')

        finally:
            proxy.stop()

    def test_different_domains_get_different_ttls_in_same_proxy(self, ttl_proxy_config):
        """Test that different domains get different TTLs in the same proxy instance."""
        proxy = CachingProxy(ttl_proxy_config)

        responses = {"/fast_api/endpoint1": b'{"fast": "response1"}', "/slow_api/endpoint2": b'{"slow": "response2"}'}

        def mock_forward_request(method, target_url, body=None, headers=None):
            # Extract the path from target_url to match responses
            path = target_url.split("?")[0] if target_url else ""  # Remove query parameters if any
            return (responses.get(path, b'{"default": "response"}'), 200, {"Content-Type": "application/json"})

        try:
            # Request to fast_api
            mixin1 = RequestProcessingMixin()
            mixin1.proxy = proxy
            mixin1.path = "/fast_api/endpoint1"
            mixin1.headers = {"Content-Type": "application/json"}
            mixin1.send_response = Mock()
            mixin1.send_header = Mock()
            mixin1.end_headers = Mock()
            mixin1.wfile = Mock()
            mixin1.rfile = Mock()
            mixin1.rfile.read.return_value = b""
            mixin1._forward_request = mock_forward_request

            mixin1._handle_request("GET")

            # Request to slow_api
            mixin2 = RequestProcessingMixin()
            mixin2.proxy = proxy
            mixin2.path = "/slow_api/endpoint2"
            mixin2.headers = {"Content-Type": "application/json"}
            mixin2.send_response = Mock()
            mixin2.send_header = Mock()
            mixin2.end_headers = Mock()
            mixin2.wfile = Mock()
            mixin2.rfile = Mock()
            mixin2.rfile.read.return_value = b""
            mixin2._forward_request = mock_forward_request

            mixin2._handle_request("GET")

            # Verify both entries have different TTLs
            cache_key1 = proxy.cache_engine.generate_cache_key("GET", "/fast_api/endpoint1")
            cache_key2 = proxy.cache_engine.generate_cache_key("GET", "/slow_api/endpoint2")

            cached1 = proxy.cache_engine.get(cache_key1)
            cached2 = proxy.cache_engine.get(cache_key2)

            assert cached1 is not None
            assert cached2 is not None

            assert cached1.ttl_seconds == 300  # fast_api TTL
            assert cached2.ttl_seconds == 7200  # slow_api TTL

            assert cached1.data == b'{"fast": "response1"}'
            assert cached2.data == b'{"slow": "response2"}'

        finally:
            proxy.stop()

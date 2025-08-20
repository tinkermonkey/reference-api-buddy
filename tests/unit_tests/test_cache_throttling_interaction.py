"""Tests for cache and throttling interaction.

This module tests that:
- Cache hits bypass throttling entirely
- Throttling only applies to upstream requests (cache misses)
- Metrics correctly distinguish between cache hits and throttled requests
"""

import io
import os
import sys
import time

# Add the project root to the path to import modules
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.core.handler import RequestProcessingMixin


class MockProxy:
    """Minimal mock proxy for testing."""

    def __init__(self, config=None, throttle_manager=None, cache_engine=None):
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
        self.throttle_manager = throttle_manager
        self.cache_engine = cache_engine


class MockCachedResponse:
    """Mock cached response object."""

    def __init__(self, data=b"cached data", status_code=200, headers=None):
        self.data = data
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}


class TestCacheThrottlingInteraction:
    """Test cache and throttling interaction."""

    def test_cache_hit_bypasses_throttling(self):
        """Test that cache hits bypass throttling entirely."""
        # Setup throttle manager that would normally throttle
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True  # Would throttle if called
        throttle_manager.get_throttle_delay.return_value = 5

        # Setup cache engine with a cache hit
        cache_engine = Mock()
        cached_response = MockCachedResponse(data=b"cached content", status_code=200)
        cache_engine.get.return_value = cached_response
        cache_engine.generate_cache_key.return_value = "test_cache_key"

        proxy = MockProxy(
            config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}},
            throttle_manager=throttle_manager,
            cache_engine=cache_engine,
        )

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy
                self.path = "/testdomain/test"
                self.headers = {"Content-Type": "application/json"}
                self.wfile = io.BytesIO()
                self._response_status = None
                self._response_headers = {}

            def send_response(self, status):
                self._response_status = status

            def send_header(self, key, value):
                self._response_headers[key] = value

            def end_headers(self):
                pass

            def rfile(self):
                return io.BytesIO()

            def read(self, length):
                return b""

        handler = TestHandler()

        # Mock rfile for reading request body
        with patch.object(handler, "rfile", io.BytesIO()):
            handler._handle_request("GET")

        # Should return cache hit with 200 status, not throttled 429
        assert handler._response_status == 200

        # Cache should be checked
        cache_engine.get.assert_called_once()

        # Throttling should NOT be invoked since cache hit was returned
        throttle_manager.record_request.assert_not_called()
        throttle_manager.should_throttle.assert_not_called()

        # Response data should be from cache
        assert handler.wfile.getvalue() == b"cached content"

    def test_cache_miss_applies_throttling(self):
        """Test that cache misses apply throttling before upstream request."""
        # Setup throttle manager that will throttle
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = True
        throttle_manager.get_throttle_delay.return_value = 5
        throttle_manager.domain_limits = {"testdomain": 100}
        throttle_manager.default_limit = 1000
        throttle_manager.time_window = 3600

        mock_state = Mock()
        mock_state.request_timestamps = [time.time() - 100] * 95  # Close to limit
        throttle_manager.get_state.return_value = mock_state

        # Setup cache engine with a cache miss
        cache_engine = Mock()
        cache_engine.get.return_value = None  # Cache miss
        cache_engine.generate_cache_key.return_value = "test_cache_key"

        metrics_collector = Mock()

        proxy = MockProxy(
            config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}},
            throttle_manager=throttle_manager,
            cache_engine=cache_engine,
        )
        proxy.metrics_collector = metrics_collector

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy
                self.path = "/testdomain/test"
                self.headers = {"Content-Type": "application/json"}
                self.wfile = io.BytesIO()
                self.rfile = io.BytesIO()  # Add rfile attribute
                self._response_status = None
                self._response_headers = {}

            def send_response(self, status):
                self._response_status = status

            def send_header(self, key, value):
                self._response_headers[key] = value

            def end_headers(self):
                pass

        handler = TestHandler()

        # Mock rfile for reading request body
        handler._handle_request("GET")

        # Should be throttled with 429 status
        assert handler._response_status == 429

        # Cache should be checked first
        cache_engine.get.assert_called_once()

        # Throttling should be invoked only after cache miss
        throttle_manager.record_request.assert_called_once_with("testdomain")
        throttle_manager.should_throttle.assert_called_once_with("testdomain")

        # Metrics should record the throttle event with cache_miss flag
        metrics_collector.record_event.assert_called_once()
        call_args = metrics_collector.record_event.call_args
        assert call_args[0][0] == "throttle"
        assert call_args[0][1]["cache_miss"] == True

    def test_cache_miss_no_throttling_forwards_to_upstream(self):
        """Test that cache misses without throttling forward to upstream."""
        # Setup throttle manager that will NOT throttle
        throttle_manager = Mock()
        throttle_manager.record_request.return_value = None
        throttle_manager.should_throttle.return_value = False  # Won't throttle

        # Setup cache engine with a cache miss
        cache_engine = Mock()
        cache_engine.get.return_value = None  # Cache miss
        cache_engine.generate_cache_key.return_value = "test_cache_key"
        cache_engine.set.return_value = True

        proxy = MockProxy(
            config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}},
            throttle_manager=throttle_manager,
            cache_engine=cache_engine,
        )

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy
                self.path = "/testdomain/test"
                self.headers = {"Content-Type": "application/json"}
                self.wfile = io.BytesIO()
                self.rfile = io.BytesIO()  # Add rfile attribute
                self._response_status = None
                self._response_headers = {}

            def send_response(self, status):
                self._response_status = status

            def send_header(self, key, value):
                self._response_headers[key] = value

            def end_headers(self):
                pass

            def _forward_request(self, method, target_url, body, headers):
                # Mock successful upstream response
                return b"upstream response", 200, {"Content-Type": "application/json"}

        handler = TestHandler()

        # Run the handler
        handler._handle_request("GET")

        # Should get successful response from upstream
        assert handler._response_status == 200

        # Cache should be checked first
        cache_engine.get.assert_called_once()

        # Throttling should be invoked but not trigger throttling
        throttle_manager.record_request.assert_called_once_with("testdomain")
        throttle_manager.should_throttle.assert_called_once_with("testdomain")

        # Response should be cached
        cache_engine.set.assert_called_once()

        # Response data should be from upstream
        assert handler.wfile.getvalue() == b"upstream response"

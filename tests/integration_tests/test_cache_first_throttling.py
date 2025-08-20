"""Integration test demonstrating cache-first throttling behavior.

This test shows that:
1. Cache hits bypass throttling completely
2. Throttling only applies to upstream requests
3. Multiple cache hits remain fast even with aggressive throttling
"""

import json
import os
import sqlite3
import tempfile
import time
from unittest.mock import Mock, patch

import pytest
import requests

from reference_api_buddy import CachingProxy


class TestCacheFirstThrottling:
    """Integration test for cache-first throttling behavior."""

    def test_cache_hits_bypass_throttling_integration(self):
        """Test that cache hits bypass throttling in a real proxy scenario."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_db_path = os.path.join(temp_dir, "test_cache.db")

            # Very aggressive throttling config (1 request per hour)
            config = {
                "domain_mappings": {"httpbin": {"upstream": "https://httpbin.org"}},
                "server": {"host": "127.0.0.1", "port": 18080},  # Different port to avoid conflicts
                "cache": {"database_path": cache_db_path, "default_ttl_seconds": 300},  # 5 minutes
                "throttling": {
                    "default_requests_per_hour": 1,  # Very restrictive
                    "progressive_max_delay": 300,
                    "domain_limits": {"httpbin": 1},  # Only 1 request per hour
                },
                "security": {"require_secure_key": False},
            }

            # Start proxy
            proxy = CachingProxy(config)

            # Mock the _forward_request method to simulate upstream responses
            # without actually making HTTP requests
            original_forward = None
            call_count = 0

            def mock_forward_request(method, target_url, body=None, headers=None):
                nonlocal call_count
                call_count += 1

                # Simulate different responses based on URL
                if "get" in target_url.lower():
                    response_data = json.dumps(
                        {"url": target_url, "method": method, "call_count": call_count, "timestamp": time.time()}
                    ).encode("utf-8")
                    return response_data, 200, {"Content-Type": "application/json"}
                else:
                    return b"Not found", 404, {"Content-Type": "text/plain"}

            # Patch the _forward_request method for all handler instances
            with patch(
                "reference_api_buddy.core.handler.RequestProcessingMixin._forward_request",
                side_effect=mock_forward_request,
            ):
                try:
                    proxy.start(blocking=False)
                    time.sleep(0.1)  # Let server start

                    base_url = f"http://127.0.0.1:18080"
                    test_endpoint = f"{base_url}/httpbin/get"

                    # First request - should hit upstream and populate cache
                    start_time = time.time()
                    response1 = requests.get(test_endpoint, timeout=5)
                    first_request_time = time.time() - start_time

                    assert response1.status_code == 200
                    data1 = response1.json()
                    assert data1["call_count"] == 1
                    assert call_count == 1  # One upstream call

                    # Wait a moment to ensure timestamps would be different
                    time.sleep(0.1)

                    # Second request - should hit cache (no throttling)
                    start_time = time.time()
                    response2 = requests.get(test_endpoint, timeout=5)
                    second_request_time = time.time() - start_time

                    assert response2.status_code == 200
                    data2 = response2.json()
                    # Should be same data from cache (same call_count)
                    assert data2["call_count"] == 1
                    assert data2["timestamp"] == data1["timestamp"]
                    assert call_count == 1  # Still only one upstream call

                    # Cache hit should be much faster than upstream
                    assert second_request_time < first_request_time / 2

                    # Third request - should still hit cache
                    start_time = time.time()
                    response3 = requests.get(test_endpoint, timeout=5)
                    third_request_time = time.time() - start_time

                    assert response3.status_code == 200
                    data3 = response3.json()
                    assert data3["call_count"] == 1  # Same cached response
                    assert call_count == 1  # Still only one upstream call

                    # All cache hits should be fast
                    assert third_request_time < first_request_time / 2

                    # Now try a different endpoint that would trigger throttling
                    # if it had to go upstream
                    different_endpoint = f"{base_url}/httpbin/ip"

                    # This should be throttled since it's a cache miss and we've
                    # already used our 1 request per hour limit
                    response4 = requests.get(different_endpoint, timeout=5)

                    # Should be throttled
                    assert response4.status_code == 429
                    assert "Too Many Requests" in response4.text
                    assert call_count == 1  # No additional upstream calls due to throttling

                    print(f"✓ Cache hit #{1} bypassed throttling: {first_request_time:.4f}s")
                    print(f"✓ Cache hit #{2} bypassed throttling: {second_request_time:.4f}s")
                    print(f"✓ Cache hit #{3} bypassed throttling: {third_request_time:.4f}s")
                    print(f"✓ Cache miss was throttled (429 status)")
                    print(f"✓ Total upstream calls: {call_count} (should be 1)")

                finally:
                    proxy.stop()

    def test_throttling_metrics_include_cache_miss_flag(self):
        """Test that throttling metrics include cache_miss flag for debugging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_db_path = os.path.join(temp_dir, "test_cache.db")

            config = {
                "domain_mappings": {"httpbin": {"upstream": "https://httpbin.org"}},
                "server": {"host": "127.0.0.1", "port": 18081},
                "cache": {"database_path": cache_db_path},
                "throttling": {"default_requests_per_hour": 1, "domain_limits": {"httpbin": 1}},
                "security": {"require_secure_key": False},
            }

            proxy = CachingProxy(config)

            def mock_forward_request(method, target_url, body=None, headers=None):
                return b'{"test": "data"}', 200, {"Content-Type": "application/json"}

            with patch(
                "reference_api_buddy.core.handler.RequestProcessingMixin._forward_request",
                side_effect=mock_forward_request,
            ):
                try:
                    proxy.start(blocking=False)
                    time.sleep(0.1)

                    # First request to populate cache
                    requests.get("http://127.0.0.1:18081/httpbin/get", timeout=5)

                    # Second request should be throttled (different endpoint)
                    response = requests.get("http://127.0.0.1:18081/httpbin/post", timeout=5)
                    assert response.status_code == 429

                    # Check metrics for throttle events
                    metrics = proxy.get_metrics()
                    throttle_events = [
                        event for event in metrics.get("events", []) if event.get("event_type") == "throttle"
                    ]

                    # Should have at least one throttle event
                    assert len(throttle_events) >= 1

                    # The throttle event should have cache_miss flag
                    throttle_event = throttle_events[0]
                    assert throttle_event["details"]["cache_miss"] == True

                    print("✓ Throttling metrics correctly include cache_miss flag")

                finally:
                    proxy.stop()

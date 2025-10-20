import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
import time

import pytest

from reference_api_buddy.throttling.manager import ThrottleManager


def make_manager_with_rate_limits(domain_mappings=None, max_delay=300):
    """Create a ThrottleManager with rate limiting configuration."""
    throttling_config = {"default_requests_per_hour": 1000, "progressive_max_delay": max_delay, "domain_limits": {}}
    return ThrottleManager(throttling_config, domain_mappings=domain_mappings or {})


def test_per_second_rate_limiting():
    """Test that per-second rate limiting works correctly."""
    domain_mappings = {"test_api": {"upstream": "https://api.test.com", "max_requests_per_second": 2}}
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # First two requests should not require delay
    assert tm.get_required_delay(domain) == 0.0
    tm.record_request(domain)
    assert tm.get_required_delay(domain) == 0.0
    tm.record_request(domain)

    # Third request within the same second should require delay
    delay = tm.get_required_delay(domain)
    assert delay > 0.0
    assert delay <= 1.0  # Should be less than 1 second


def test_per_minute_rate_limiting():
    """Test that per-minute rate limiting works correctly."""
    domain_mappings = {"test_api": {"upstream": "https://api.test.com", "max_requests_per_minute": 3}}
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # First three requests should not require delay
    for i in range(3):
        assert tm.get_required_delay(domain) == 0.0
        tm.record_request(domain)
        time.sleep(0.01)  # Small delay to avoid timing issues

    # Fourth request within the same minute should require delay
    delay = tm.get_required_delay(domain)
    assert delay > 0.0
    assert delay <= 60.0  # Should be less than 60 seconds


def test_combined_rate_limiting():
    """Test that per-second and per-minute limits work together."""
    domain_mappings = {
        "test_api": {"upstream": "https://api.test.com", "max_requests_per_second": 2, "max_requests_per_minute": 10}
    }
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # Fill up the per-second limit
    tm.record_request(domain)
    tm.record_request(domain)

    # Next request should be limited by per-second
    delay = tm.get_required_delay(domain)
    assert delay > 0.0
    assert delay <= 1.0

    # Wait for the per-second window to clear
    time.sleep(1.1)

    # Should be able to make requests again (still under per-minute limit)
    assert tm.get_required_delay(domain) == 0.0


def test_multi_window_priority():
    """Test that the system returns the maximum delay across all windows."""
    domain_mappings = {
        "test_api": {"upstream": "https://api.test.com", "max_requests_per_second": 1, "max_requests_per_minute": 2}
    }
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # Make first request
    tm.record_request(domain)

    # Second request immediately - should be limited by per-second
    delay1 = tm.get_required_delay(domain)
    assert delay1 > 0.0

    # Record the second request
    time.sleep(delay1 + 0.01)
    tm.record_request(domain)

    # Third request should be limited by per-minute (2 requests already made)
    delay2 = tm.get_required_delay(domain)
    assert delay2 > 0.0
    # Should be close to 60 seconds since we need to wait for the first request to expire


def test_max_delay_exceeded():
    """Test that get_required_delay returns -1 when delay exceeds max_delay."""
    domain_mappings = {"test_api": {"upstream": "https://api.test.com", "max_requests_per_minute": 1}}
    throttling_config = {
        "default_requests_per_hour": 1000,
        "progressive_max_delay": 5,  # Very short max delay
        "domain_limits": {},
    }
    tm = ThrottleManager(throttling_config, domain_mappings=domain_mappings)
    domain = "test_api"

    # Make one request
    tm.record_request(domain)

    # Try to make another immediately - should require ~60s delay
    # Since max_delay is 5s, should return -1
    delay = tm.get_required_delay(domain)
    assert delay == -1.0


def test_no_rate_limiting_when_not_configured():
    """Test that domains without rate limits work normally."""
    domain_mappings = {
        "test_api": {
            "upstream": "https://api.test.com"
            # No max_requests_per_minute or max_requests_per_second
        }
    }
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # Should never require delay for per-minute/per-second
    # (still subject to per-hour limit)
    for _ in range(10):
        delay = tm.get_required_delay(domain)
        # Should only check hour-level, which has high default limit
        assert delay == 0.0
        tm.record_request(domain)


def test_different_domains_independent():
    """Test that rate limits for different domains are independent."""
    domain_mappings = {
        "api_a": {"upstream": "https://api.a.com", "max_requests_per_second": 2},
        "api_b": {"upstream": "https://api.b.com", "max_requests_per_second": 2},
    }
    tm = make_manager_with_rate_limits(domain_mappings)

    # Fill up api_a's limit
    tm.record_request("api_a")
    tm.record_request("api_a")

    # api_a should be rate limited
    assert tm.get_required_delay("api_a") > 0.0

    # api_b should still have no delay
    assert tm.get_required_delay("api_b") == 0.0


def test_cleanup_removes_old_timestamps():
    """Test that old timestamps are properly cleaned up."""
    domain_mappings = {"test_api": {"upstream": "https://api.test.com", "max_requests_per_second": 2}}
    tm = make_manager_with_rate_limits(domain_mappings)
    domain = "test_api"

    # Make requests and hit the limit
    tm.record_request(domain)
    tm.record_request(domain)
    assert tm.get_required_delay(domain) > 0.0

    # Wait for the window to clear
    time.sleep(1.1)

    # Should be able to make requests again
    assert tm.get_required_delay(domain) == 0.0

    # Verify old timestamps were cleaned up
    state = tm.get_state(domain)
    assert len(state.request_timestamps_second) <= 2


def test_hour_level_still_works_with_new_limits():
    """Test that existing hour-level throttling still functions."""
    domain_mappings = {"test_api": {"upstream": "https://api.test.com", "max_requests_per_second": 100}}
    throttling_config = {
        "default_requests_per_hour": 5,  # Very low limit
        "progressive_max_delay": 300,
        "domain_limits": {},
    }
    tm = ThrottleManager(throttling_config, domain_mappings=domain_mappings)
    domain = "test_api"

    # Make 5 requests (at the limit)
    for _ in range(5):
        tm.record_request(domain)
        time.sleep(0.01)

    # 6th request should hit hour limit
    # Since we have 5 requests in ~0.05s, the delay would be ~3600s
    # which exceeds max_delay (300s), so should return -1
    delay = tm.get_required_delay(domain)
    assert delay == -1.0  # Delay exceeds max_delay, so return -1

import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))
import time

import pytest

from reference_api_buddy.throttling.manager import ThrottleManager


def make_manager(config=None):
    return ThrottleManager(
        config or {"default_requests_per_hour": 5, "progressive_max_delay": 8, "domain_limits": {"api.test": 3}}
    )


def test_no_throttle_under_limit():
    tm = make_manager()
    domain = "api.test"
    for _ in range(3):
        tm.record_request(domain)
        assert not tm.should_throttle(domain)


def test_throttle_over_limit():
    tm = make_manager()
    domain = "api.test"
    for _ in range(3):
        tm.record_request(domain)
    tm.record_request(domain)
    assert tm.should_throttle(domain)
    assert tm.get_throttle_delay(domain) > 1


def test_progressive_throttling():
    tm = make_manager()
    domain = "api.test"
    for _ in range(3):
        tm.record_request(domain)
    for i in range(3):
        tm.record_request(domain)
        assert tm.should_throttle(domain)
        delay = tm.get_throttle_delay(domain)
        assert delay <= 8
        time.sleep(0.01)
    state = tm.get_state(domain)
    assert state.violations >= 3


def test_reset_throttle():
    tm = make_manager()
    domain = "api.test"
    for _ in range(4):
        tm.record_request(domain)
    assert tm.should_throttle(domain)
    tm.reset_throttle(domain)
    assert not tm.should_throttle(domain)
    state = tm.get_state(domain)
    assert state.violations == 0
    assert state.delay_seconds == 1


def test_domain_specific_limits():
    tm = make_manager({"default_requests_per_hour": 10, "domain_limits": {"api.foo": 2}})
    tm.record_request("api.foo")
    tm.record_request("api.foo")
    assert not tm.should_throttle("api.foo")
    tm.record_request("api.foo")
    assert tm.should_throttle("api.foo")
    tm.record_request("api.bar")
    for _ in range(9):
        tm.record_request("api.bar")
    # Should not throttle at limit
    assert not tm.should_throttle("api.bar")
    # Throttle after exceeding limit
    tm.record_request("api.bar")
    assert tm.should_throttle("api.bar")


def test_persist_and_load_state():
    tm = make_manager()
    domain = "api.test"
    for _ in range(4):
        tm.record_request(domain)
    # Trigger throttle event to increment violations
    tm.should_throttle(domain)
    snapshot = tm.persist_state()
    tm2 = make_manager()
    tm2.load_state(snapshot)
    # Compare violation count before calling should_throttle on tm2
    assert tm2.get_state(domain).violations == tm.get_state(domain).violations
    assert tm2.get_state(domain).delay_seconds == tm.get_state(domain).delay_seconds
    assert tm2.get_state(domain).total_requests == tm.get_state(domain).total_requests
    assert list(tm2.get_state(domain).request_timestamps) == list(tm.get_state(domain).request_timestamps)
    assert tm2.should_throttle(domain)

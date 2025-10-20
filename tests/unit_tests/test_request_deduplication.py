import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
import threading
import time

from reference_api_buddy.core.inflight_tracker import InFlightTracker


def test_first_request_proceeds_immediately():
    """Test that the first request for a cache key proceeds without waiting."""
    tracker = InFlightTracker()
    cache_key = "test_key_1"

    # First request should not wait
    inflight_request = tracker.should_wait(cache_key)
    assert inflight_request is None

    # Clean up
    tracker.complete_request(cache_key, result=(b"data", 200, {}))


def test_concurrent_requests_wait_for_first():
    """Test that concurrent requests for the same key wait for the first one."""
    tracker = InFlightTracker()
    cache_key = "test_key_2"
    results = []

    def first_request():
        """Simulates the first request that fetches from upstream."""
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is None  # First request doesn't wait

        # Simulate slow upstream request
        time.sleep(0.5)

        # Complete with result
        result = (b"fetched data", 200, {"Content-Type": "application/json"})
        tracker.complete_request(cache_key, result=result)
        results.append(("first", result))

    def waiting_request(request_id):
        """Simulates a request that arrives while another is in-flight."""
        # Small delay to ensure first request starts first
        time.sleep(0.1)

        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is not None  # Should wait

        # Wait for the first request to complete
        result, error = tracker.wait_for_result(cache_key, inflight_request, timeout=2.0)
        assert error is None
        assert result is not None
        results.append((f"waiting_{request_id}", result))

    # Start first request
    t1 = threading.Thread(target=first_request)
    t1.start()

    # Start multiple waiting requests
    t2 = threading.Thread(target=waiting_request, args=(2,))
    t3 = threading.Thread(target=waiting_request, args=(3,))
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()

    # All requests should have the same result
    assert len(results) == 3
    first_result = results[0][1]
    for _, result in results:
        assert result == first_result

    # Verify result content
    data, status, _headers = first_result
    assert data == b"fetched data"
    assert status == 200


def test_error_propagation():
    """Test that errors from the first request are propagated to waiters."""
    tracker = InFlightTracker()
    cache_key = "test_key_error"
    results = []

    def failing_request():
        """Simulates a request that fails."""
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is None

        # Simulate upstream failure
        time.sleep(0.2)
        error = RuntimeError("Upstream API error")
        tracker.complete_request(cache_key, error=error)
        results.append(("first", None, error))

    def waiting_request():
        """Simulates a waiting request."""
        time.sleep(0.05)
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is not None

        result, error = tracker.wait_for_result(cache_key, inflight_request, timeout=2.0)
        assert result is None
        assert error is not None
        assert isinstance(error, RuntimeError)
        results.append(("waiting", result, error))

    t1 = threading.Thread(target=failing_request)
    t2 = threading.Thread(target=waiting_request)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    # Both should have gotten the error
    for _, result, error in results:
        assert result is None
        assert isinstance(error, RuntimeError)


def test_timeout_waiting_for_inflight_request():
    """Test that waiters timeout if the first request takes too long."""
    tracker = InFlightTracker()
    cache_key = "test_key_timeout"
    waiter_result = []

    def slow_request():
        """Simulates a very slow request."""
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is None
        # Don't complete, let it timeout
        time.sleep(3.0)

    def waiting_request():
        """Simulates a waiting request with short timeout."""
        time.sleep(0.1)
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is not None

        result, error = tracker.wait_for_result(cache_key, inflight_request, timeout=0.5)
        waiter_result.append((result, error))

    t1 = threading.Thread(target=slow_request)
    t2 = threading.Thread(target=waiting_request)
    t1.start()
    t2.start()
    t2.join()  # Wait for the waiter to timeout

    # Waiter should have timed out
    assert len(waiter_result) == 1
    result, error = waiter_result[0]
    assert result is None
    assert isinstance(error, TimeoutError)

    # Clean up - let slow request finish
    t1.join()


def test_sequential_requests_dont_interfere():
    """Test that sequential requests for the same key work independently."""
    tracker = InFlightTracker()
    cache_key = "test_key_sequential"

    # First request
    inflight_request = tracker.should_wait(cache_key)
    assert inflight_request is None
    tracker.complete_request(cache_key, result=(b"first result", 200, {}))

    # Wait a bit to ensure cleanup
    time.sleep(0.1)

    # Second request (after first completed) - should NOT wait
    inflight_request = tracker.should_wait(cache_key)
    assert inflight_request is None
    tracker.complete_request(cache_key, result=(b"second result", 200, {}))


def test_different_cache_keys_independent():
    """Test that requests for different cache keys don't interfere."""
    tracker = InFlightTracker()
    cache_key1 = "key1"
    cache_key2 = "key2"

    # Start request for key1
    inflight1 = tracker.should_wait(cache_key1)
    assert inflight1 is None

    # Request for key2 should also proceed immediately
    inflight2 = tracker.should_wait(cache_key2)
    assert inflight2 is None

    # Clean up
    tracker.complete_request(cache_key1, result=(b"data1", 200, {}))
    tracker.complete_request(cache_key2, result=(b"data2", 200, {}))


def test_waiter_count_tracking():
    """Test that waiter counts are tracked correctly."""
    tracker = InFlightTracker()
    cache_key = "test_waiter_count"
    waiter_results = []

    def first_request():
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is None
        time.sleep(0.5)
        tracker.complete_request(cache_key, result=(b"data", 200, {}))

    def waiting_request(request_id):
        time.sleep(0.1)
        inflight_request = tracker.should_wait(cache_key)
        assert inflight_request is not None

        # Check stats before waiting completes
        stats = tracker.get_stats()
        assert cache_key in stats["cache_keys"]

        result, error = tracker.wait_for_result(cache_key, inflight_request, timeout=2.0)
        waiter_results.append((request_id, result, error))

    # Start threads
    threads = [threading.Thread(target=first_request)]
    threads.extend([threading.Thread(target=waiting_request, args=(i,)) for i in range(3)])

    for t in threads:
        t.start()

    time.sleep(0.2)
    # Check stats while requests are in-flight
    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 1
    assert stats["total_waiters"] >= 1  # At least the first requester

    for t in threads:
        t.join()

    # After completion, in-flight should be cleared
    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 0
    assert stats["total_waiters"] == 0


def test_stats_reporting():
    """Test that stats are reported correctly."""
    tracker = InFlightTracker()

    # Empty tracker
    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 0
    assert stats["total_waiters"] == 0
    assert len(stats["cache_keys"]) == 0

    # Add in-flight request
    cache_key = "test_stats"
    inflight_request = tracker.should_wait(cache_key)
    assert inflight_request is None

    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 1
    assert stats["total_waiters"] == 1
    assert cache_key in stats["cache_keys"]

    # Complete request
    tracker.complete_request(cache_key, result=(b"data", 200, {}))

    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 0

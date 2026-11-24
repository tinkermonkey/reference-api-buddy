import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
import threading

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


def _wait_in_threads(tracker, cache_key, waiters, timeout=5.0):
    """Call wait_for_result for each waiter in its own thread; return the threads and a results list.

    Waiters are registered by the caller, so the leader/waiter order is fixed and no sleeps are needed.
    """
    results = []

    def wait(request):
        results.append(tracker.wait_for_result(cache_key, request, timeout=timeout))

    threads = [threading.Thread(target=wait, args=(request,)) for request in waiters]
    for t in threads:
        t.start()
    return threads, results


def test_concurrent_requests_wait_for_first():
    """Test that concurrent requests for the same key wait for the first one."""
    tracker = InFlightTracker()
    cache_key = "test_key_2"

    assert tracker.should_wait(cache_key) is None  # The first request proceeds
    waiters = [tracker.should_wait(cache_key) for _ in range(2)]
    assert all(w is not None for w in waiters)  # Later requests wait

    threads, results = _wait_in_threads(tracker, cache_key, waiters)
    result = (b"fetched data", 200, {"Content-Type": "application/json"})
    tracker.complete_request(cache_key, result=result)
    for t in threads:
        t.join(timeout=5)

    # Every waiter receives the first request's result
    assert results == [(result, None), (result, None)]


def test_error_propagation():
    """Test that errors from the first request are propagated to waiters."""
    tracker = InFlightTracker()
    cache_key = "test_key_error"

    assert tracker.should_wait(cache_key) is None
    waiter = tracker.should_wait(cache_key)
    assert waiter is not None

    threads, results = _wait_in_threads(tracker, cache_key, [waiter])
    error = RuntimeError("Upstream API error")
    tracker.complete_request(cache_key, error=error)
    for t in threads:
        t.join(timeout=5)

    assert results == [(None, error)]


def test_timeout_waiting_for_inflight_request():
    """Test that waiters timeout if the first request takes too long."""
    tracker = InFlightTracker()
    cache_key = "test_key_timeout"

    assert tracker.should_wait(cache_key) is None
    waiter = tracker.should_wait(cache_key)
    assert waiter is not None

    # The first request never completes within the waiter's timeout
    result, error = tracker.wait_for_result(cache_key, waiter, timeout=0.2)
    assert result is None
    assert isinstance(error, TimeoutError)

    # The first request still owns the entry and can complete normally
    tracker.complete_request(cache_key, result=(b"late", 200, {}))
    assert tracker.get_stats()["in_flight_count"] == 0


def test_sequential_requests_dont_interfere():
    """Test that sequential requests for the same key work independently."""
    tracker = InFlightTracker()
    cache_key = "test_key_sequential"

    # First request
    inflight_request = tracker.should_wait(cache_key)
    assert inflight_request is None
    tracker.complete_request(cache_key, result=(b"first result", 200, {}))

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

    assert tracker.should_wait(cache_key) is None
    waiters = [tracker.should_wait(cache_key) for _ in range(3)]

    # The first requester plus three waiters
    stats = tracker.get_stats()
    assert stats["in_flight_count"] == 1
    assert stats["total_waiters"] == 4
    assert cache_key in stats["cache_keys"]

    threads, results = _wait_in_threads(tracker, cache_key, waiters)
    tracker.complete_request(cache_key, result=(b"data", 200, {}))
    for t in threads:
        t.join(timeout=5)

    assert results == [((b"data", 200, {}), None)] * 3

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

"""
InFlightTracker: Deduplicates concurrent requests to the same resource.

When multiple clients request the same resource simultaneously and the cache
misses, this tracker ensures only ONE request is made to the upstream API.
Other requests wait for the first one to complete and share its result.
"""

import threading
import time
from typing import Any, Optional, Tuple


class InFlightRequest:
    """Represents a request currently in-flight to upstream."""

    def __init__(self):
        self.event = threading.Event()
        self.result: Optional[Tuple[bytes, int, dict]] = None
        self.error: Optional[Exception] = None
        self.waiters = 1  # Number of threads waiting for this request


class InFlightTracker:
    """Tracks and deduplicates in-flight upstream requests."""

    def __init__(self):
        self.lock = threading.Lock()
        self.in_flight: dict[str, InFlightRequest] = {}

    def should_wait(self, cache_key: str) -> Optional[InFlightRequest]:
        """
        Check if a request for this cache_key is already in-flight.

        Returns:
            InFlightRequest if should wait for existing request, None if should proceed
        """
        with self.lock:
            if cache_key in self.in_flight:
                # Another thread is already fetching this resource
                request = self.in_flight[cache_key]
                request.waiters += 1
                return request
            else:
                # No in-flight request, create one and proceed
                request = InFlightRequest()
                self.in_flight[cache_key] = request
                return None

    def wait_for_result(
        self, cache_key: str, request: InFlightRequest, timeout: float = 60.0
    ) -> Tuple[Optional[Tuple[bytes, int, dict]], Optional[Exception]]:
        """
        Wait for an in-flight request to complete.

        Args:
            cache_key: The cache key being waited on
            request: The in-flight request object
            timeout: Maximum time to wait in seconds

        Returns:
            Tuple of (result, error). One will be None.
        """
        # Wait for the request to complete
        completed = request.event.wait(timeout=timeout)

        with self.lock:
            # Decrement waiter count
            request.waiters -= 1

            # Clean up if this was the last waiter
            if request.waiters == 0 and cache_key in self.in_flight:
                del self.in_flight[cache_key]

        if not completed:
            # Timeout occurred
            return None, TimeoutError(f"Timed out waiting for in-flight request: {cache_key}")

        return request.result, request.error

    def complete_request(
        self,
        cache_key: str,
        result: Optional[Tuple[bytes, int, dict]] = None,
        error: Optional[Exception] = None,
    ):
        """
        Mark an in-flight request as complete and notify all waiters.

        Args:
            cache_key: The cache key that was fetched
            result: The successful result (data, status_code, headers)
            error: The error that occurred (if any)
        """
        with self.lock:
            if cache_key not in self.in_flight:
                # Request was already cleaned up or never tracked
                return

            request = self.in_flight[cache_key]
            request.result = result
            request.error = error

            # Decrement the original requester's count
            request.waiters -= 1

            # Clean up if no one is waiting
            if request.waiters == 0:
                del self.in_flight[cache_key]

            # Notify all waiting threads
            request.event.set()

    def get_stats(self) -> dict:
        """Get statistics about in-flight requests."""
        with self.lock:
            return {
                "in_flight_count": len(self.in_flight),
                "total_waiters": sum(req.waiters for req in self.in_flight.values()),
                "cache_keys": list(self.in_flight.keys()),
            }

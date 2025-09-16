"""Admin utilities for the caching proxy module."""

import threading
import time
from typing import Dict, List


class AdminRateLimiter:
    """Simple rate limiter for admin endpoints."""

    def __init__(self):
        """Initialize the rate limiter with empty request tracking."""
        self.requests: Dict[str, List[float]] = {}  # IP -> list of timestamps
        self.lock = threading.Lock()

    def is_allowed(self, client_ip: str, limit_per_minute: int = 10) -> bool:
        """Check if client is within rate limit.

        Args:
            client_ip: IP address of the client
            limit_per_minute: Maximum requests allowed per minute

        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        now = time.time()
        minute_ago = now - 60

        with self.lock:
            if client_ip not in self.requests:
                self.requests[client_ip] = []

            # Remove old requests
            self.requests[client_ip] = [t for t in self.requests[client_ip] if t > minute_ago]

            # Check limit
            if len(self.requests[client_ip]) >= limit_per_minute:
                return False

            # Add current request
            self.requests[client_ip].append(now)
            return True

    def get_request_count(self, client_ip: str) -> int:
        """Get current request count for a client IP.

        Args:
            client_ip: IP address of the client

        Returns:
            Number of requests in the current minute window
        """
        now = time.time()
        minute_ago = now - 60

        with self.lock:
            if client_ip not in self.requests:
                return 0

            # Count recent requests
            recent_requests = [t for t in self.requests[client_ip] if t > minute_ago]
            return len(recent_requests)

    def clear_client(self, client_ip: str) -> None:
        """Clear rate limit data for a specific client.

        Args:
            client_ip: IP address of the client to clear
        """
        with self.lock:
            if client_ip in self.requests:
                del self.requests[client_ip]

    def clear_all(self) -> None:
        """Clear all rate limit data."""
        with self.lock:
            self.requests.clear()

"""
ThrottleManager: Domain-specific rate limiting and progressive throttling.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Dict


class ThrottleState:
    """Tracks throttling state for a domain."""

    def __init__(self, violations=0, delay_seconds=1, last_violation=0.0, total_requests=0):
        self.violations = violations
        self.delay_seconds = delay_seconds
        self.last_violation = last_violation
        self.total_requests = total_requests
        self.request_timestamps: deque = deque()


class ThrottleManager:
    """Manages rate limiting and progressive throttling per domain."""

    def __init__(self, throttling_config: dict):
        """
        throttling_config example:
        {
            "default_requests_per_hour": 1000,
            "progressive_max_delay": 300,
            "domain_limits": {"api.openai": 500}
        }
        """
        self.config = throttling_config or {}
        self.default_limit = self.config.get("default_requests_per_hour", 1000)
        self.max_delay = self.config.get("progressive_max_delay", 300)
        self.domain_limits = self.config.get("domain_limits", {})
        self.lock = threading.Lock()
        self.states: Dict[str, ThrottleState] = defaultdict(ThrottleState)
        self.time_window = 3600  # 1 hour in seconds

    def should_throttle(self, domain: str) -> bool:
        """Check if requests to domain should be throttled."""
        with self.lock:
            state = self.states[domain]
            now = time.time()
            self._cleanup_old_requests(domain, now)
            limit = self.domain_limits.get(domain, self.default_limit)
            # Only throttle if requests > limit
            if len(state.request_timestamps) > limit:
                self._apply_progressive_throttling(domain, now)
                return True
            if state.delay_seconds > 1 and (now - state.last_violation) < state.delay_seconds:
                return True
            return False

    def record_request(self, domain: str):
        """Record a request for throttling purposes."""
        with self.lock:
            now = time.time()
            state = self.states[domain]
            state.request_timestamps.append(now)
            state.total_requests += 1
            self._cleanup_old_requests(domain, now)

    def get_throttle_delay(self, domain: str) -> int:
        """Get the current throttle delay for a domain."""
        with self.lock:
            return self.states[domain].delay_seconds

    def _cleanup_old_requests(self, domain: str, current_time: float):
        """Remove request timestamps older than 1 hour."""
        state = self.states[domain]
        while state.request_timestamps and (current_time - state.request_timestamps[0]) > self.time_window:
            state.request_timestamps.popleft()

    def _apply_progressive_throttling(self, domain: str, now: float):
        """Apply progressive throttling based on consecutive violations."""
        state = self.states[domain]
        state.violations += 1
        state.last_violation = now
        # Exponential backoff: double delay up to max_delay
        state.delay_seconds = min(self.max_delay, state.delay_seconds * 2 if state.delay_seconds > 1 else 2)

    def reset_throttle(self, domain: str):
        """Reset throttle state for a domain (for testing/admin)."""
        with self.lock:
            self.states[domain] = ThrottleState()

    def get_state(self, domain: str) -> ThrottleState:
        """Get the current throttle state for a domain."""
        with self.lock:
            return self.states[domain]

    def persist_state(self) -> dict:
        """Return a serializable snapshot of throttle state (for persistence)."""
        with self.lock:
            return {
                domain: {
                    "violations": state.violations,
                    "delay_seconds": state.delay_seconds,
                    "last_violation": state.last_violation,
                    "total_requests": state.total_requests,
                    "request_timestamps": list(state.request_timestamps),
                }
                for domain, state in self.states.items()
            }

    def load_state(self, snapshot: dict):
        """Restore throttle state from a snapshot (for persistence)."""
        with self.lock:
            for domain, data in snapshot.items():
                state = ThrottleState(
                    violations=data.get("violations", 0),
                    delay_seconds=data.get("delay_seconds", 1),
                    last_violation=data.get("last_violation", 0.0),
                    total_requests=data.get("total_requests", 0),
                )
                state.request_timestamps = deque(data.get("request_timestamps", []))
                self.states[domain] = state

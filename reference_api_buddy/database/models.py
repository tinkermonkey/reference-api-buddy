"""Database models for Reference API Buddy."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


@dataclass
class CachedResponse:
    """Represents a cached HTTP response."""

    data: bytes
    headers: Dict[str, str]
    status_code: int
    created_at: str
    ttl_seconds: int
    access_count: int = 0
    last_accessed: Optional[str] = None


@dataclass
class ThrottleState:
    """Tracks throttling state for a domain."""

    violations: int = 0
    delay_seconds: int = 1
    last_violation: float = 0.0
    total_requests: int = 0


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    domain: str
    method: str
    cache_hit: bool
    response_time_ms: int
    response_size_bytes: int
    timestamp: datetime


@dataclass
class ProxyMetrics:
    """Overall proxy performance metrics."""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_response_time_ms: int = 0
    domains_served: int = 0
    uptime_seconds: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total) if total > 0 else 0.0

    @property
    def average_response_time(self) -> float:
        return (self.total_response_time_ms / self.total_requests) if self.total_requests > 0 else 0.0

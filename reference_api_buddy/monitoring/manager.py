"""
MonitoringManager: Provides programmatic access to operational metrics
and health information for the caching proxy module.

Implements the design in 3.2.2 of the monitoring interface design document.
"""


import os
import threading
import time
from typing import Any, Dict


class MonitoringManager:
    def __init__(self, proxy, cache_engine, db_manager, throttle_manager):
        """Initialize with references to core components."""
        self.proxy = proxy
        self.cache_engine = cache_engine
        self.db_manager = db_manager
        self.throttle_manager = throttle_manager
        self.start_time = getattr(proxy, "start_time", time.time())

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return cache entry counts, sizes, hit/miss rates, TTLs, and evictions."""
        stats = {}
        try:
            if self.cache_engine and hasattr(self.cache_engine, "get_cache_performance"):
                # Use existing cache performance method
                perf_stats = self.cache_engine.get_cache_performance()
                stats.update(perf_stats)

                # Get raw stats for additional info
                if hasattr(self.cache_engine, "get_stats"):
                    raw_stats = self.cache_engine.get_stats()
                    stats["hit_count"] = raw_stats.get("hits", "unavailable")
                    stats["miss_count"] = raw_stats.get("misses", "unavailable")
                    stats["miss_rate"] = 1.0 - stats.get("hit_rate", 0) if "hit_rate" in stats else "unavailable"
                    stats["sets"] = raw_stats.get("sets", "unavailable")
                    stats["compressed"] = raw_stats.get("compressed", "unavailable")
                    stats["decompressed"] = raw_stats.get("decompressed", "unavailable")
            else:
                # Fallback to unavailable if cache_engine is None or missing methods
                stats = {
                    "total_entries": {"unavailable": {}},
                    "entries_per_domain": {"unavailable": {}},
                    "cache_size_bytes": {"unavailable": {}},
                    "cache_size_per_domain": {"unavailable": {}},
                    "hit_count": {"unavailable": {}},
                    "miss_count": {"unavailable": {}},
                    "hit_rate": {"unavailable": {}},
                    "miss_rate": {"unavailable": {}},
                    "ttl_distribution": {"unavailable": {}},
                    "expired_entries": {"unavailable": {}},
                    "evicted_entries": {"unavailable": {}},
                }
        except Exception as e:
            stats["error"] = str(e)
        return stats

    def get_upstream_stats(self) -> Dict[str, Any]:
        """Return upstream response times, error rates, and request volumes."""
        stats = {}
        try:
            if self.db_manager and hasattr(self.db_manager, "get_upstream_metrics"):
                # Get metrics from database for all domains - this now returns overall + per-domain breakdown
                upstream_metrics = self.db_manager.get_upstream_metrics()

                # Return the complete structure with overall and by_domain breakdowns
                stats = upstream_metrics
            else:
                # Fallback to unavailable if no database or metrics method
                stats = {
                    "overall": {
                        "response_times": "unavailable",
                        "error_rates": "unavailable",
                        "request_volumes": "unavailable",
                    }
                }
        except Exception as e:
            stats["error"] = str(e)
            stats = {
                "overall": {
                    "response_times": "unavailable",
                    "error_rates": "unavailable",
                    "request_volumes": "unavailable",
                }
            }
        return stats

    def get_database_stats(self) -> Dict[str, Any]:
        """Return database file path, size, memory usage, and health."""
        stats = {}
        try:
            if self.db_manager:
                # Get database file path from database_path attribute
                db_path = getattr(self.db_manager, "database_path", None)
                if db_path and ":memory:" not in db_path and "file::memory:" not in db_path:
                    stats["db_file_path"] = db_path
                    if os.path.exists(db_path):
                        stats["db_file_size_bytes"] = os.path.getsize(db_path)
                    else:
                        stats["db_file_size_bytes"] = "file_not_found"
                else:
                    stats["db_file_path"] = "in_memory"
                    stats["db_file_size_bytes"] = "in_memory"

                # Check database health by trying a simple query
                try:
                    if hasattr(self.db_manager, "execute_query"):
                        self.db_manager.execute_query("SELECT 1")
                        stats["db_health"] = "healthy"
                    else:
                        stats["db_health"] = "unknown"
                except Exception:
                    stats["db_health"] = "error"

                # Memory usage estimation (approximate)
                stats["in_memory_cache_size"] = "unavailable"  # Would need specific implementation
            else:
                stats = {
                    "db_file_path": "unavailable",
                    "db_file_size_bytes": "unavailable",
                    "in_memory_cache_size": "unavailable",
                    "db_health": "unavailable",
                }
        except Exception as e:
            stats["error"] = str(e)
        return stats

    def get_proxy_health(self) -> Dict[str, Any]:
        """Return uptime, active threads, and recent errors."""
        stats = {}
        try:
            stats["uptime_seconds"] = time.time() - self.start_time
            stats["active_threads"] = threading.active_count()
            stats["recent_errors"] = getattr(self.proxy, "get_recent_errors", lambda: [])()
        except Exception as e:
            stats["error"] = str(e)
        return stats

    def get_throttling_stats(self) -> Dict[str, Any]:
        """Return current throttle state and per-domain request counts."""
        stats = {}
        try:
            if self.throttle_manager:
                # Get per-domain request counts from current window
                requests_per_domain = {}
                throttle_states = {}

                # Get all tracked domains and their stats
                if hasattr(self.throttle_manager, "states"):
                    for domain, state in self.throttle_manager.states.items():
                        requests_per_domain[domain] = {
                            "current_hour_requests": len(state.request_timestamps),
                            "total_requests": state.total_requests,
                            "violations": state.violations,
                            "current_delay_seconds": state.delay_seconds,
                        }
                        throttle_states[domain] = {
                            "is_throttled": state.delay_seconds > 1,
                            "violations": state.violations,
                            "delay_seconds": state.delay_seconds,
                            "last_violation": state.last_violation,
                        }

                stats["requests_per_domain"] = requests_per_domain if requests_per_domain else {}
                stats["throttle_state"] = throttle_states if throttle_states else {}

                # Get configuration info
                stats["default_requests_per_hour"] = self.throttle_manager.default_limit
                stats["progressive_max_delay"] = self.throttle_manager.max_delay
                stats["progressive_enabled"] = True  # Progressive throttling is always enabled

                # Get domain-specific limits
                stats["domain_limits"] = self.throttle_manager.domain_limits

            else:
                stats = {
                    "requests_per_domain": {},
                    "throttle_state": {},
                    "default_requests_per_hour": None,
                    "progressive_enabled": None,
                }
        except Exception as e:
            stats["error"] = str(e)
        return stats

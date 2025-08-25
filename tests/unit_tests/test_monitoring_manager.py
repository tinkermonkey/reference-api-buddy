"""
Unit tests for MonitoringManager (section 3.2.3/3.2.7 of monitoring design).
"""
import pytest

from reference_api_buddy.monitoring.manager import MonitoringManager


class DummyCacheEngine:
    def get_cache_performance(self):
        return {
            "total_entries": 42,
            "entries_per_domain": {"example.com": 10, "api.com": 32},
            "cache_size_bytes": 2048,
            "cache_size_per_domain": {"example.com": 512, "api.com": 1536},
            "hit_rate": 0.83,
            "miss_rate": 0.17,
            "ttl_distribution": {"min": 10, "max": 300, "avg": 120},
            "expired_entries": 5,
            "evicted_entries": 2,
        }

    def get_stats(self):
        return {"hits": 100, "misses": 20, "sets": 42, "compressed": 0, "decompressed": 0}


class DummyProxy:
    start_time = 1000

    def get_upstream_response_times(self):
        return {"api.com": {"avg": 120, "min": 100, "max": 150, "recent": [110, 120, 130]}}

    def get_upstream_error_rates(self):
        return {"api.com": {"count": 2, "rate": 0.01}}

    def get_upstream_request_volumes(self):
        return {"api.com": 200}

    def get_recent_errors(self):
        return ["TimeoutError"]


class DummyDBManager:
    database_path = "/tmp/test.db"

    def execute_query(self, q):
        return 1


class DummyState:
    def __init__(self):
        self.request_timestamps = [1] * 50
        self.total_requests = 50
        self.violations = 0
        self.delay_seconds = 0
        self.last_violation = 0.0


class DummyThrottleManager:
    default_limit = 1000
    max_delay = 300
    domain_limits = {"api.com": 100}
    states = {"api.com": DummyState()}


def test_monitoring_manager_initialization():
    monitor = MonitoringManager(DummyProxy(), DummyCacheEngine(), DummyDBManager(), DummyThrottleManager())
    assert monitor is not None


def test_get_cache_stats_returns_expected_keys():
    monitor = MonitoringManager(None, DummyCacheEngine(), None, None)
    stats = monitor.get_cache_stats()
    assert "total_entries" in stats
    assert "cache_size_bytes" in stats
    assert stats["total_entries"] == 42
    assert stats["cache_size_bytes"] == 2048


def test_get_upstream_stats_returns_expected_keys():
    monitor = MonitoringManager(DummyProxy(), None, None, None)
    stats = monitor.get_upstream_stats()
    # The fallback returns {'overall': {...}}
    assert "overall" in stats
    assert "response_times" in stats["overall"]
    assert "error_rates" in stats["overall"]
    assert "request_volumes" in stats["overall"]


def test_get_database_stats_returns_expected_keys(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db_path.write_text("dummy")

    class DBMgr:
        database_path = str(db_path)

        def execute_query(self, q):
            return 1

    monitor = MonitoringManager(None, None, DBMgr(), None)
    stats = monitor.get_database_stats()
    assert "db_file_path" in stats
    assert "db_file_size_bytes" in stats
    assert stats["db_file_size_bytes"] == db_path.stat().st_size
    assert stats["db_health"] == "healthy"


def test_get_proxy_health_returns_expected_keys(monkeypatch):
    monitor = MonitoringManager(DummyProxy(), None, None, None)
    stats = monitor.get_proxy_health()
    assert "uptime_seconds" in stats
    assert "active_threads" in stats
    assert "recent_errors" in stats
    assert stats["recent_errors"] == ["TimeoutError"]


def test_get_throttling_stats_returns_expected_keys():
    monitor = MonitoringManager(None, None, None, DummyThrottleManager())
    stats = monitor.get_throttling_stats()
    assert "throttle_state" in stats
    assert "requests_per_domain" in stats
    assert "api.com" in stats["throttle_state"]
    assert "api.com" in stats["requests_per_domain"]


def test_error_handling_for_missing_methods():
    class Empty:
        pass

    monitor = MonitoringManager(Empty(), Empty(), Empty(), Empty())
    assert monitor.get_cache_stats()["total_entries"] == "unavailable"
    # Upstream stats fallback is nested under 'overall'
    assert monitor.get_upstream_stats()["overall"]["response_times"] == "unavailable"
    assert monitor.get_database_stats()["db_file_path"] == "in_memory"
    assert monitor.get_throttling_stats()["throttle_state"] == {}
    assert monitor.get_throttling_stats()["requests_per_domain"] == {}

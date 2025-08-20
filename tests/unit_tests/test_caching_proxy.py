import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest

from reference_api_buddy.core.proxy import CachingProxy
from reference_api_buddy.security.manager import SecurityManager


class DummyCacheEngine:
    def __init__(self):
        self.set_calls = 0
        self.get_calls = 0

    def set(self, *a, **kw):
        self.set_calls += 1

    def get(self, *a, **kw):
        self.get_calls += 1
        return None


class DummyThrottleManager:
    def __init__(self):
        self.recorded = []

    def record_request(self, domain):
        self.recorded.append(domain)

    def should_throttle(self, domain):
        return False

    def get_throttle_delay(self, domain):
        return 1

    def get_state(self, domain):
        return {}


# --- DummyServer for monkeypatching ---
class DummyServer:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    def start(self, blocking=False):
        self.started = True

    def stop(self):
        self.stopped = True


def test_context_manager_lifecycle(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    config = {}
    with CachingProxy(config) as proxy:
        assert proxy.is_running()
    assert not proxy.is_running()


def test_start_stop(monkeypatch):
    server = DummyServer()
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: server)
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    proxy = CachingProxy({})
    proxy.start()
    assert proxy.is_running()
    proxy.stop()
    assert not proxy.is_running()
    assert server.started
    assert server.stopped


def test_get_secure_key(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    config = {"security": {"require_secure_key": True}}
    proxy = CachingProxy(config)
    key = proxy.get_secure_key()
    assert key is None or isinstance(key, str)


def test_update_and_reload_config(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    config = {"cache": {"max_cache_response_size": 1234}}
    proxy = CachingProxy(config)
    proxy.update_config("cache.max_cache_response_size", 5678)
    assert proxy.config["cache"]["max_cache_response_size"] == 5678
    proxy.reload_config({"cache": {"max_cache_response_size": 9999}})
    assert proxy.config["cache"]["max_cache_response_size"] == 9999


def test_clear_cache(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    proxy = CachingProxy({})
    # Should call cache_engine.clear_cache
    proxy.cache_engine.clear_cache = lambda domain=None: 42
    assert proxy.clear_cache() == 42


def test_metrics_collection(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    proxy = CachingProxy({})
    proxy.metrics_collector.record_event("cache_hit")
    proxy.metrics_collector.record_event("cache_miss")
    proxy.metrics_collector.record_event("throttle")
    proxy.metrics_collector.record_event("error")
    metrics = proxy.get_metrics()
    assert metrics["cache_hits"] == 1
    assert metrics["cache_misses"] == 1
    assert metrics["throttled"] == 1
    assert metrics["errors"] == 1
    assert metrics["total_requests"] == 4
    assert metrics["uptime_seconds"] >= 0


def test_callbacks_and_graceful_shutdown(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    called = {}

    def on_shutdown(proxy):
        called["shutdown"] = True

    config = {"callbacks": {"on_shutdown": on_shutdown}}
    proxy = CachingProxy(config)
    proxy.start()
    proxy.stop()
    assert called.get("shutdown")


def test_component_integration(monkeypatch):
    monkeypatch.setattr("reference_api_buddy.core.server.ThreadedHTTPServer", lambda *a, **k: DummyServer())
    monkeypatch.setattr("reference_api_buddy.core.handler.ProxyHTTPRequestHandler", object)
    config = {
        "security": {"require_secure_key": True},
        "cache": {"database_path": ":memory:"},
        "throttling": {"default_requests_per_hour": 100},
    }
    proxy = CachingProxy(config)
    # All components should be initialized
    assert hasattr(proxy, "security_manager")
    assert hasattr(proxy, "cache_engine")
    assert hasattr(proxy, "throttle_manager")
    assert hasattr(proxy, "metrics_collector")
    # Inter-component communication: metrics_collector should be usable
    proxy.metrics_collector.record_event("cache_hit")
    assert proxy.get_metrics()["cache_hits"] == 1

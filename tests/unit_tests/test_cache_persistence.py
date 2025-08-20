import os
import sys

# Add the project root to the path to import modules
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import time

# NOTE: Requires pytest-timeout plugin for @pytest.mark.timeout to work
import zlib

import pytest

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.database.models import CachedResponse


@pytest.fixture(scope="function")
def db_manager():
    return DatabaseManager(":memory:")


@pytest.fixture(scope="function")
def cache_engine(db_manager):
    # Use small max_cache_entries for eviction tests
    return CacheEngine(db_manager, max_response_size=10240, compression_threshold=32, max_cache_entries=3)


@pytest.fixture
def sample_response():
    return CachedResponse(
        data=b"response-data",
        headers={"Content-Type": "application/json"},
        status_code=200,
        created_at="2025-08-15 12:00:00",
        ttl_seconds=60,
        access_count=0,
        last_accessed=None,
    )


@pytest.mark.timeout(5)
def test_compression_and_decompression(cache_engine, sample_response):
    # Large enough to trigger compression
    sample_response.data = b"x" * 100
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    assert cache_engine.set(key, sample_response)
    cached = cache_engine.get(key)
    assert cached is not None
    assert cached.data == sample_response.data
    perf = cache_engine.get_cache_performance()
    assert perf["compressed"] >= 1
    assert perf["decompressed"] >= 1


@pytest.mark.timeout(5)
def test_lru_eviction(cache_engine, sample_response):
    # Fill cache to max_cache_entries
    keys = []
    for i in range(4):
        sample_response.data = f"data-{i}".encode()
        key = cache_engine.generate_cache_key("GET", f"http://example.com/api/{i}")
        cache_engine.set(key, sample_response)
        keys.append(key)
    # Only 3 entries should remain
    perf = cache_engine.get_cache_performance()
    assert perf["total_entries"] == 3
    # The first inserted key should be evicted
    assert cache_engine.get(keys[0]) is None
    # The last inserted key should be present
    assert cache_engine.get(keys[-1]) is not None
    assert perf["evictions"] >= 1


@pytest.mark.timeout(5)
def test_cleanup_expired_entries(cache_engine, sample_response, monkeypatch):
    # Insert expired entry
    sample_response.ttl_seconds = 1
    sample_response.created_at = "2025-08-15 12:00:00"
    key = cache_engine.generate_cache_key("GET", "http://example.com/api/expire")
    cache_engine.set(key, sample_response)
    # Patch time to simulate expiry
    monkeypatch.setattr("time.time", lambda: 1765867200)  # Far future
    cache_engine._cleanup_expired_entries()
    assert cache_engine.get(key) is None
    perf = cache_engine.get_cache_performance()
    assert perf["expired_entries"] >= 1


@pytest.mark.timeout(5)
def test_cache_performance_metrics(cache_engine, sample_response):
    key = cache_engine.generate_cache_key("GET", "http://example.com/api/perf")
    cache_engine.set(key, sample_response)
    cache_engine.get(key)
    perf = cache_engine.get_cache_performance()
    assert perf["total_entries"] >= 1
    assert perf["total_size_bytes"] > 0
    assert 0.0 <= perf["hit_rate"] <= 1.0

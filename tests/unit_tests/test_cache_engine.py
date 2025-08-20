import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import json

import pytest

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.database.models import CachedResponse


@pytest.fixture(scope="function")
def db_manager():
    # Use in-memory DB for tests
    return DatabaseManager(":memory:")


@pytest.fixture(scope="function")
def cache_engine(db_manager):
    return CacheEngine(db_manager)


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


def test_generate_cache_key_get(cache_engine):
    key1 = cache_engine.generate_cache_key("GET", "http://EXAMPLE.com/api/v1/resource?b=2&a=1")
    key2 = cache_engine.generate_cache_key("GET", "http://example.com/api/v1/resource/?a=1&b=2")
    assert key1 == key2  # Normalization should match


def test_generate_cache_key_post_json(cache_engine):
    body1 = b'{"b":2,"a":1}'
    body2 = b'{"a":1,"b":2}'
    key1 = cache_engine.generate_cache_key("POST", "http://example.com/api", body1, "application/json")
    key2 = cache_engine.generate_cache_key("POST", "http://example.com/api", body2, "application/json")
    assert key1 == key2  # JSON body normalization


def test_set_and_get_cache_entry(cache_engine, sample_response):
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    assert cache_engine.set(key, sample_response)
    cached = cache_engine.get(key)
    assert cached is not None
    assert cached.data == sample_response.data
    assert cached.headers == sample_response.headers
    assert cached.status_code == sample_response.status_code
    assert cached.ttl_seconds == sample_response.ttl_seconds
    assert cached.access_count == 1  # Access count incremented


def test_cache_expiry(cache_engine, sample_response, monkeypatch):
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    sample_response.ttl_seconds = 1
    sample_response.created_at = "2025-08-15 12:00:00"
    assert cache_engine.set(key, sample_response)
    # Patch time to simulate expiry
    monkeypatch.setattr("time.time", lambda: 1765867200)  # Far future
    cached = cache_engine.get(key)
    assert cached is None
    stats = cache_engine.get_stats()
    assert stats["expired"] >= 1


def test_set_too_large_response(cache_engine, sample_response):
    sample_response.data = b"x" * (cache_engine.max_response_size + 1)
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    assert not cache_engine.set(key, sample_response)


def test_delete_and_clear(cache_engine, sample_response):
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    cache_engine.set(key, sample_response)
    assert cache_engine.get(key) is not None
    cache_engine.delete(key)
    assert cache_engine.get(key) is None
    # Test clear
    cache_engine.set(key, sample_response)
    assert cache_engine.clear() >= 1
    assert cache_engine.get(key) is None


def test_stats_tracking(cache_engine, sample_response):
    key = cache_engine.generate_cache_key("GET", "http://example.com/api")
    cache_engine.set(key, sample_response)
    cache_engine.get(key)
    cache_engine.get("nonexistent")
    stats = cache_engine.get_stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["sets"] >= 1


def test_url_normalization_edge_cases(cache_engine):
    """Test URL normalization edge cases - empty path after strip."""
    # Test URL that becomes empty path after stripping
    url_with_only_slash = "http://example.com//"
    key = cache_engine.generate_cache_key("GET", url_with_only_slash)
    assert isinstance(key, str)

    # Test URL with no path that needs normalization
    url_no_path = "http://example.com"
    normalized_url = cache_engine._normalize_url(url_no_path)
    assert normalized_url.endswith("/")  # Should add trailing slash


def test_empty_normalized_path_handling(cache_engine):
    """Test handling when normalized path is empty."""
    # This tests the case where path.rstrip("/") results in empty string
    test_url = "http://example.com/"
    key = cache_engine.generate_cache_key("GET", test_url)
    assert isinstance(key, str)

    # Verify the URL normalization handles the empty path correctly
    normalized = cache_engine._normalize_url(test_url)
    assert "/" in normalized


def test_request_body_normalization_exception_handling(cache_engine):
    """Test exception handling in request body normalization."""
    # Test with malformed JSON that will cause an exception
    malformed_json = b'{"unclosed": "json"'  # Missing closing brace

    # This should fall back to hash when JSON parsing fails
    key = cache_engine.generate_cache_key("POST", "http://example.com/api", malformed_json, "application/json")
    assert isinstance(key, str)
    assert len(key) == 64  # SHA256 hex length

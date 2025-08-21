"""Unit tests for cache engine TTL functionality."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import time
from unittest.mock import Mock, patch

import pytest

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.database.models import CachedResponse


class TestCacheEngineTTL:
    """Test cache engine TTL functionality."""

    @pytest.fixture
    def config_with_ttl(self):
        return {
            "cache": {"default_ttl_seconds": 3600},
            "domain_mappings": {
                "short_ttl": {"upstream": "https://short.api.com", "ttl_seconds": 300},
                "long_ttl": {"upstream": "https://long.api.com", "ttl_seconds": 7200},
            },
        }

    @pytest.fixture
    def cache_engine_with_config(self, config_with_ttl):
        db_manager = DatabaseManager(":memory:")
        return CacheEngine(db_manager, config=config_with_ttl)

    @pytest.fixture
    def sample_response_no_ttl(self):
        return CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

    def test_cache_engine_uses_domain_ttl(self, cache_engine_with_config, sample_response_no_ttl):
        """Test cache engine uses domain-specific TTL when provided."""
        cache_key = "test_key"

        # Create fresh response objects for each test
        short_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

        long_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

        # Test short TTL domain
        assert cache_engine_with_config.set(cache_key + "_short", short_response, domain_key="short_ttl")
        cached_short = cache_engine_with_config.get(cache_key + "_short")
        assert cached_short.ttl_seconds == 300

        # Test long TTL domain
        assert cache_engine_with_config.set(cache_key + "_long", long_response, domain_key="long_ttl")
        cached_long = cache_engine_with_config.get(cache_key + "_long")
        assert cached_long.ttl_seconds == 7200

    def test_cache_engine_uses_default_ttl(self, cache_engine_with_config, sample_response_no_ttl):
        """Test cache engine uses default TTL when no domain specified."""
        cache_key = "test_key_default"

        # Create fresh response object
        default_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

        assert cache_engine_with_config.set(cache_key, default_response)
        cached = cache_engine_with_config.get(cache_key)
        assert cached.ttl_seconds == 3600  # Default from config

    def test_cache_engine_respects_explicit_ttl(self, cache_engine_with_config):
        """Test cache engine respects explicitly set TTL in response object."""
        explicit_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=1234,  # Explicit TTL
            access_count=0,
            last_accessed=None,
        )
        cache_key = "test_key_explicit"

        assert cache_engine_with_config.set(cache_key, explicit_response, domain_key="short_ttl")
        cached = cache_engine_with_config.get(cache_key)
        assert cached.ttl_seconds == 1234  # Should keep explicit TTL, not use domain config

    def test_cache_engine_without_config(self):
        """Test cache engine works without TTL configuration."""
        db_manager = DatabaseManager(":memory:")
        cache_engine = CacheEngine(db_manager)  # No config provided

        response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=60,  # Must provide explicit TTL when no config
            access_count=0,
            last_accessed=None,
        )

        # Should not crash, but TTL won't be set automatically
        cache_key = "test_key"
        # This test verifies the code doesn't crash when no config is provided
        try:
            cache_engine.set(cache_key, response, domain_key="any_domain")
        except AttributeError:
            pytest.fail("Cache engine should handle missing config gracefully")

    def test_fallback_to_default_for_unmapped_domain(self, cache_engine_with_config, sample_response_no_ttl):
        """Test fallback to default TTL for domains without specific configuration."""
        cache_key = "unmapped_test"

        # Create fresh response object
        unmapped_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

        assert cache_engine_with_config.set(cache_key, unmapped_response, domain_key="unmapped_domain")
        cached = cache_engine_with_config.get(cache_key)
        assert cached.ttl_seconds == 3600  # Should use default TTL

    def test_cache_engine_with_none_domain_key(self, cache_engine_with_config, sample_response_no_ttl):
        """Test cache engine handles None domain_key gracefully."""
        cache_key = "none_domain_test"

        # Create fresh response object
        none_domain_response = CachedResponse(
            data=b"response-data",
            headers={"Content-Type": "application/json"},
            status_code=200,
            created_at=None,
            ttl_seconds=None,
            access_count=0,
            last_accessed=None,
        )

        assert cache_engine_with_config.set(cache_key, none_domain_response, domain_key=None)
        cached = cache_engine_with_config.get(cache_key)
        assert cached.ttl_seconds == 3600  # Should use default TTL

"""Tests for TTL Manager functionality."""

import sys
from pathlib import Path

import pytest

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.ttl_manager import TTLManager


class TestTTLManager:
    """Test TTL Manager functionality."""

    def test_default_ttl_resolution(self):
        """Test default TTL is used when no domain-specific TTL is configured."""
        config = {
            "cache": {"default_ttl_seconds": 7200},
            "domain_mappings": {"example": {"upstream": "https://api.example.com"}},
        }
        ttl_manager = TTLManager(config)

        assert ttl_manager.get_ttl_for_domain("example") == 7200
        assert ttl_manager.get_default_ttl() == 7200

    def test_domain_specific_ttl_resolution(self):
        """Test domain-specific TTL overrides default."""
        config = {
            "cache": {"default_ttl_seconds": 86400},
            "domain_mappings": {
                "fast_api": {"upstream": "https://fast.api.com", "ttl_seconds": 300},
                "slow_api": {"upstream": "https://slow.api.com", "ttl_seconds": 7200},
            },
        }
        ttl_manager = TTLManager(config)

        assert ttl_manager.get_ttl_for_domain("fast_api") == 300
        assert ttl_manager.get_ttl_for_domain("slow_api") == 7200
        assert ttl_manager.get_default_ttl() == 86400

    def test_fallback_to_default_for_unmapped_domain(self):
        """Test fallback to default TTL for domains without specific configuration."""
        config = {"cache": {"default_ttl_seconds": 3600}, "domain_mappings": {}}
        ttl_manager = TTLManager(config)

        assert ttl_manager.get_ttl_for_domain("unmapped_domain") == 3600
        assert ttl_manager.get_ttl_for_domain("another_unmapped") == 3600

    def test_missing_cache_config_uses_default(self):
        """Test TTL manager works with missing cache configuration."""
        config = {"domain_mappings": {}}
        ttl_manager = TTLManager(config)

        assert ttl_manager.get_default_ttl() == 86400  # Default 1 day
        assert ttl_manager.get_ttl_for_domain("any_domain") == 86400

    def test_invalid_domain_mapping_format(self):
        """Test TTL manager handles invalid domain mapping formats gracefully."""
        config = {
            "cache": {"default_ttl_seconds": 1800},
            "domain_mappings": {
                "string_mapping": "https://api.example.com",  # Invalid: should be dict
                "valid_mapping": {"upstream": "https://valid.api.com", "ttl_seconds": 900},
            },
        }
        ttl_manager = TTLManager(config)

        assert ttl_manager.get_ttl_for_domain("string_mapping") == 1800  # Falls back to default
        assert ttl_manager.get_ttl_for_domain("valid_mapping") == 900

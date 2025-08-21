"""Unit tests for proxy TTL integration."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from reference_api_buddy.core.proxy import CachingProxy


class TestProxyTTLIntegration:
    """Test proxy TTL integration functionality."""

    @pytest.fixture
    def proxy_config_with_ttl(self):
        return {
            "server": {"host": "127.0.0.1", "port": 0},  # Random port
            "cache": {"default_ttl_seconds": 7200, "database_path": ":memory:"},
            "domain_mappings": {
                "test_domain": {"upstream": "https://test.api.com", "ttl_seconds": 1800},
                "fast_domain": {"upstream": "https://fast.api.com", "ttl_seconds": 300},
            },
            "logging": {"level": "INFO"},
        }

    def test_proxy_initializes_cache_engine_with_config(self, proxy_config_with_ttl):
        """Test that proxy passes configuration to cache engine during initialization."""
        proxy = CachingProxy(proxy_config_with_ttl)

        # Verify cache engine was created
        assert proxy.cache_engine is not None

        # Verify cache engine has TTL manager
        assert hasattr(proxy.cache_engine, "_ttl_manager")
        assert proxy.cache_engine._ttl_manager is not None

        # Verify TTL manager works correctly
        ttl_manager = proxy.cache_engine._ttl_manager
        assert ttl_manager.get_default_ttl() == 7200
        assert ttl_manager.get_ttl_for_domain("test_domain") == 1800
        assert ttl_manager.get_ttl_for_domain("fast_domain") == 300
        assert ttl_manager.get_ttl_for_domain("unmapped") == 7200  # Falls back to default

        proxy.stop()

    def test_proxy_config_reload_updates_cache_engine(self, proxy_config_with_ttl):
        """Test that proxy config reload properly updates cache engine TTL configuration."""
        proxy = CachingProxy(proxy_config_with_ttl)

        # Verify initial TTL configuration
        initial_ttl_manager = proxy.cache_engine._ttl_manager
        assert initial_ttl_manager.get_default_ttl() == 7200
        assert initial_ttl_manager.get_ttl_for_domain("test_domain") == 1800

        # Update configuration
        new_config = {
            "server": {"host": "127.0.0.1", "port": 0},
            "cache": {"default_ttl_seconds": 3600, "database_path": ":memory:"},
            "domain_mappings": {
                "test_domain": {"upstream": "https://test.api.com", "ttl_seconds": 900},  # Changed TTL
                "new_domain": {"upstream": "https://new.api.com", "ttl_seconds": 1200},
            },
            "logging": {"level": "INFO"},
        }

        proxy.reload_config(new_config)

        # Verify cache engine was re-initialized with new config
        updated_ttl_manager = proxy.cache_engine._ttl_manager
        assert updated_ttl_manager.get_default_ttl() == 3600
        assert updated_ttl_manager.get_ttl_for_domain("test_domain") == 900
        assert updated_ttl_manager.get_ttl_for_domain("new_domain") == 1200
        assert updated_ttl_manager.get_ttl_for_domain("fast_domain") == 3600  # No longer mapped, uses default

        proxy.stop()

    def test_proxy_without_ttl_config(self):
        """Test proxy initialization without TTL configuration."""
        minimal_config = {
            "server": {"host": "127.0.0.1", "port": 0},
            "cache": {"database_path": ":memory:"},
            "logging": {"level": "INFO"},
        }

        proxy = CachingProxy(minimal_config)

        # Verify cache engine was created
        assert proxy.cache_engine is not None

        # Verify cache engine has TTL manager with defaults
        assert hasattr(proxy.cache_engine, "_ttl_manager")
        assert proxy.cache_engine._ttl_manager is not None

        # Verify TTL manager uses default values
        ttl_manager = proxy.cache_engine._ttl_manager
        assert ttl_manager.get_default_ttl() == 86400  # Default 1 day

        proxy.stop()

    def test_proxy_cache_engine_without_config(self):
        """Test cache engine creation when no config is provided."""
        # This tests backward compatibility
        minimal_config = {}

        proxy = CachingProxy(minimal_config)

        # Verify cache engine was created (should still work)
        assert proxy.cache_engine is not None

        # May or may not have TTL manager depending on implementation
        # but should not crash

        proxy.stop()

    def test_proxy_context_manager_with_ttl_config(self, proxy_config_with_ttl):
        """Test proxy context manager functionality with TTL configuration."""
        with CachingProxy(proxy_config_with_ttl) as proxy:
            # Verify cache engine TTL configuration is available
            assert proxy.cache_engine is not None
            assert hasattr(proxy.cache_engine, "_ttl_manager")
            assert proxy.cache_engine._ttl_manager is not None

            ttl_manager = proxy.cache_engine._ttl_manager
            assert ttl_manager.get_default_ttl() == 7200
            assert ttl_manager.get_ttl_for_domain("test_domain") == 1800

        # Context manager should have cleaned up properly
        assert not proxy.is_running()

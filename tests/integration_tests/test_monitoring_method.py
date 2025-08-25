#!/usr/bin/env python3
"""Test script to verify the new get_monitoring_manager() convenience method."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.proxy import CachingProxy


def test_monitoring_manager_method():
    """Test that the get_monitoring_manager() method works correctly."""

    config = {
        "server": {
            "host": "127.0.0.1",
            "port": 18081,  # Different port to avoid conflicts
        },
        "domain_mappings": {"test": {"upstream": "https://httpbin.org"}},
        "cache": {"database_path": ":memory:"},  # In-memory for testing
        "security": {},
        "throttling": {},
    }

    print("Creating CachingProxy...")
    proxy = CachingProxy(config)

    print("Testing get_monitoring_manager() method...")
    try:
        # Test the new convenience method
        monitor = proxy.get_monitoring_manager()
        print("✓ get_monitoring_manager() method works!")

        # Test that we can call monitoring methods
        cache_stats = monitor.get_cache_stats()
        print(f"✓ Cache stats: {type(cache_stats).__name__} with {len(cache_stats)} keys")

        upstream_stats = monitor.get_upstream_stats()
        print(f"✓ Upstream stats: {type(upstream_stats).__name__} with {len(upstream_stats)} keys")

        db_stats = monitor.get_database_stats()
        print(f"✓ Database stats: {type(db_stats).__name__} with {len(db_stats)} keys")

        health_stats = monitor.get_proxy_health()
        print(f"✓ Proxy health: {type(health_stats).__name__} with {len(health_stats)} keys")

        throttle_stats = monitor.get_throttling_stats()
        print(f"✓ Throttling stats: {type(throttle_stats).__name__} with {len(throttle_stats)} keys")

        print("\n--- Sample Monitoring Output ---")
        print(f"Cache Stats: {cache_stats}")
        print(f"Upstream Stats: {upstream_stats}")
        print(f"Database Stats: {db_stats}")
        print(f"Proxy Health: {health_stats}")
        print(f"Throttling Stats: {throttle_stats}")

        print("\n✅ All monitoring methods work correctly!")

    except Exception as e:
        print(f"❌ Error testing monitoring manager: {e}")
        raise

    finally:
        # Clean up
        try:
            proxy.stop()
        except Exception:
            pass


if __name__ == "__main__":
    test_monitoring_manager_method()

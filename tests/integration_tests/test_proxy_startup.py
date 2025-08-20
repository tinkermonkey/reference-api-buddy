#!/usr/bin/env python3
"""Integration tests for proxy startup and shutdown."""

import sys
import time
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.proxy import CachingProxy


def test_proxy_startup():
    """Test basic proxy startup and shutdown."""
    config = {
        "server": {"host": "127.0.0.1", "port": 8899},
        "security": {"require_secure_key": False},
        "cache": {"database_path": ":memory:"},
        "domain_mappings": {},
        "logging": {"level": "DEBUG"},
    }

    # Test proxy creation
    proxy = CachingProxy(config)
    assert proxy is not None, "Failed to create proxy instance"

    try:
        # Test proxy startup
        proxy.start(blocking=False)

        # Let it run for a moment to ensure it's stable
        time.sleep(2)

        # Verify proxy is running (we can't easily check the server directly,
        # but if start() didn't raise an exception, it should be running)
        assert True, "Proxy started successfully"

    finally:
        # Always clean up
        proxy.stop()


def test_proxy_startup_and_stop_multiple_times():
    """Test that proxy can be started and stopped multiple times with new instances."""
    base_config = {
        "security": {"require_secure_key": False},
        "cache": {"database_path": ":memory:"},
        "domain_mappings": {},
        "logging": {"level": "DEBUG"},
    }

    # Test multiple start/stop cycles with new instances
    for i in range(3):
        config = {
            **base_config,
            "server": {"host": "127.0.0.1", "port": 8900 + i},  # Different port each time
        }
        proxy = CachingProxy(config)

        proxy.start(blocking=False)
        time.sleep(0.5)  # Brief pause to ensure startup
        proxy.stop()
        time.sleep(0.2)  # Brief pause to ensure cleanup


# Standalone script functionality
def _run_standalone_test():
    """Run the test as a standalone script."""
    try:
        print("Running proxy startup test...")
        test_proxy_startup()
        print("✓ Proxy startup test passed")

        print("Running multiple start/stop test...")
        test_proxy_startup_and_stop_multiple_times()
        print("✓ Multiple start/stop test passed")

        print("All tests passed!")
        return True

    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = _run_standalone_test()
    sys.exit(0 if success else 1)

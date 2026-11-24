#!/usr/bin/env python3
"""Integration tests for proxy startup and shutdown."""

import sys
import urllib.request
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.proxy import CachingProxy
from tests.helpers import free_port


def _assert_healthy(port):
    """The proxy answers its health endpoint."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/admin/health", timeout=5) as resp:
        assert resp.status == 200


def test_proxy_startup():
    """Test basic proxy startup and shutdown."""
    config = {
        "server": {"host": "127.0.0.1", "port": free_port()},
        "security": {"require_secure_key": False},
        "cache": {"database_path": ":memory:"},
        "domain_mappings": {},
        "logging": {"level": "DEBUG"},
    }

    # Test proxy creation
    proxy = CachingProxy(config)
    assert proxy is not None, "Failed to create proxy instance"

    try:
        # Test proxy startup; start() binds before returning
        proxy.start(blocking=False)
        _assert_healthy(config["server"]["port"])

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
            "server": {"host": "127.0.0.1", "port": free_port()},
        }
        proxy = CachingProxy(config)

        proxy.start(blocking=False)
        try:
            _assert_healthy(config["server"]["port"])
        finally:
            proxy.stop()


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

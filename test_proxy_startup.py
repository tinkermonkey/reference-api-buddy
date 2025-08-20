#!/usr/bin/env python3
"""Test script to verify proxy startup works locally."""

import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.proxy import CachingProxy


def test_proxy_startup():
    """Test basic proxy startup and shutdown."""
    try:
        config = {
            "server": {"host": "127.0.0.1", "port": 8899},
            "security": {"require_secure_key": False},
            "cache": {"database_path": ":memory:"},
            "domain_mappings": {},
            "logging": {"level": "DEBUG"},
        }

        print("Creating proxy...")
        proxy = CachingProxy(config)
        print("Proxy created successfully")

        print("Starting proxy...")
        proxy.start(blocking=False)
        print("Proxy started successfully")

        # Let it run for a moment
        time.sleep(2)

        print("Stopping proxy...")
        proxy.stop()
        print("Proxy stopped successfully")

        return True

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_proxy_startup()
    sys.exit(0 if success else 1)

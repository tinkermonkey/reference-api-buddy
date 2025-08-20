#!/usr/bin/env python3
"""Test script to verify CLI startup with timeout."""

import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()


def test_cli_startup():
    """Test CLI startup with proper process management."""
    try:
        # Set up environment
        env = {
            **sys.modules["os"].environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "API_BUDDY_DB_PATH": ":memory:",
            "API_BUDDY_LOG_LEVEL": "DEBUG",
        }

        print("Starting CLI process...")
        process = subprocess.Popen(
            [sys.executable, "-m", "reference_api_buddy.cli", "--host", "127.0.0.1", "--port", "8899"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        # Wait for a few seconds to let it start
        print("Waiting for startup...")
        time.sleep(3)

        # Check if it's still running
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            print(f"Process terminated early with code: {process.returncode}")
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            return False

        # Terminate it
        print("Terminating process...")
        process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            print("Process didn't terminate, killing...")
            process.kill()
            stdout, stderr = process.communicate()

        print(f"Process finished with code: {process.returncode}")
        print(f"STDOUT: {stdout}")
        print(f"STDERR: {stderr}")

        # Check if we got the expected startup message
        expected_msg = "Starting Reference API Buddy on 127.0.0.1:8899"
        if expected_msg in stdout or expected_msg in stderr:
            print("SUCCESS: Found expected startup message")
            return True
        else:
            print("WARNING: Expected startup message not found")
            return False

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    import os

    success = test_cli_startup()
    sys.exit(0 if success else 1)

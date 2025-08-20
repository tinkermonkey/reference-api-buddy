#!/usr/bin/env python3
"""Integration tests for CLI startup and termination."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))


def test_cli_startup():
    """Test CLI startup with proper process management."""
    # Set up environment
    env = {
        **sys.modules["os"].environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "API_BUDDY_DB_PATH": ":memory:",
        "API_BUDDY_LOG_LEVEL": "DEBUG",
    }

    # Start CLI process
    process = subprocess.Popen(
        [sys.executable, "-m", "reference_api_buddy.cli", "--host", "127.0.0.1", "--port", "8899"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )

    try:
        # Wait for a few seconds to let it start
        time.sleep(3)

        # Check if it's still running (shouldn't have terminated early)
        assert process.poll() is None, f"Process terminated early with code: {process.returncode}"

        # Terminate it
        process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

        # Check if we got the expected startup message
        expected_msg = "Starting Reference API Buddy on 127.0.0.1:8899"
        combined_output = stdout + stderr

        assert expected_msg in combined_output, (
            f"Expected startup message not found. " f"STDOUT: {stdout}, STDERR: {stderr}"
        )

    finally:
        # Ensure process is cleaned up
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def test_cli_startup_with_different_port():
    """Test CLI startup on a different port."""
    env = {
        **sys.modules["os"].environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "API_BUDDY_DB_PATH": ":memory:",
        "API_BUDDY_LOG_LEVEL": "INFO",
    }

    process = subprocess.Popen(
        [sys.executable, "-m", "reference_api_buddy.cli", "--host", "127.0.0.1", "--port", "8901"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )

    try:
        time.sleep(2)
        assert process.poll() is None, "Process should still be running"

        process.terminate()
        stdout, stderr = process.communicate(timeout=10)

        expected_msg = "Starting Reference API Buddy on 127.0.0.1:8901"
        combined_output = stdout + stderr
        assert expected_msg in combined_output, f"Expected message not found in: {combined_output}"

    finally:
        if process.poll() is None:
            process.kill()


# Standalone script functionality
def _run_standalone_test():
    """Run the test as a standalone script."""
    try:
        print("Running CLI startup test...")
        test_cli_startup()
        print("✓ CLI startup test passed")

        print("Running CLI startup with different port...")
        test_cli_startup_with_different_port()
        print("✓ CLI different port test passed")

        print("All tests passed!")
        return True

    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    import os

    success = _run_standalone_test()
    sys.exit(0 if success else 1)

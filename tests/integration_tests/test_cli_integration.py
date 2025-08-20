"""Integration tests for CLI functionality."""

import json
import os
import signal
import subprocess

# Add the project root to the path to import modules
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Get the project root directory dynamically
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))


def run_cli_process_with_retry(args, max_retries=3):
    """Run CLI process with retry logic for CI reliability."""
    for attempt in range(max_retries):
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            )

            # Let it start up for a moment (longer timeout for CI)
            time.sleep(2.0)

            # Terminate the process
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()

            return process, stdout, stderr

        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(1.0)  # Wait before retry


class TestCLIIntegration:
    """Integration tests for CLI module."""

    def test_cli_help_integration(self):
        """Test CLI help command integration."""
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--help"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0
        assert "Reference API Buddy - HTTP Caching Proxy" in result.stdout
        assert "Examples:" in result.stdout
        assert "--config" in result.stdout
        assert "--port" in result.stdout
        assert "--host" in result.stdout

    def test_cli_version_integration(self):
        """Test CLI version command integration."""
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--version"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_cli_generate_config_integration(self):
        """Test CLI config generation integration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Change to temp directory to avoid creating files in project root
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                result = subprocess.run(
                    [sys.executable, "-m", "reference_api_buddy.cli", "--generate-config"],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
                )

                assert result.returncode == 0
                assert "Generated default configuration:" in result.stdout

                # Verify config file was created in current directory (temp_dir)
                config_file = Path("api_buddy_config.json")
                assert config_file.exists()

                # Verify config file content
                with open(config_file, "r") as f:
                    config = json.load(f)

                assert "server" in config
                assert "security" in config
                assert "cache" in config
                assert "throttling" in config
                assert "domain_mappings" in config
                assert config["server"]["host"] == "127.0.0.1"
                assert config["server"]["port"] == 8080

            finally:
                os.chdir(original_cwd)

    def test_cli_security_key_integration(self):
        """Test CLI security key generation integration."""
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--security-key-only"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )

        assert result.returncode == 0
        assert "Generated security key:" in result.stdout

        # Extract the key from the output
        output_lines = result.stdout.strip().split("\n")
        key_line = [line for line in output_lines if "Generated security key:" in line][0]
        key = key_line.split("Generated security key: ")[1]

        # Verify key format (should be a reasonable length string)
        assert len(key) > 10
        assert key.isalnum() or "-" in key or "_" in key

    def test_cli_with_config_file_integration(self):
        """Test CLI with custom configuration file integration."""
        # Use in-memory database for CI environments to avoid file permission issues
        is_ci = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'
        
        if is_ci:
            database_path = ":memory:"
        else:
            # Use test_data directory for database
            test_db_path = PROJECT_ROOT / "test_data" / "test_cli_integration.db"
            database_path = str(test_db_path)
            
        config_data = {
            "server": {"host": "127.0.0.1", "port": 8081},
            "security": {"require_secure_key": False},
            "cache": {"database_path": database_path, "default_ttl_days": 3},
            "throttling": {"default_requests_per_hour": 500},
            "domain_mappings": {"test": {"upstream": "https://api.test.com"}},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            # Ensure test_data directory exists for non-CI environments
            if not is_ci:
                test_data_dir = PROJECT_ROOT / "test_data"
                test_data_dir.mkdir(exist_ok=True)

            # Test that CLI accepts the config file without error
            # We'll use a timeout to prevent the server from running indefinitely
            process, stdout, stderr = run_cli_process_with_retry(
                [sys.executable, "-m", "reference_api_buddy.cli", "--config", config_path]
            )

            # Debug output for CI
            if "Starting Reference API Buddy on 127.0.0.1:8081" not in stdout and "Starting Reference API Buddy on 127.0.0.1:8081" not in stderr:
                print(f"STDOUT: {stdout}")
                print(f"STDERR: {stderr}")
                print(f"Return code: {process.returncode}")
                print(f"Config path: {config_path}")
                print(f"Working directory: {PROJECT_ROOT}")
                print(f"Database path: {database_path}")
                if not is_ci:
                    print(f"Test DB exists: {Path(database_path).exists()}")

            # Check that it started successfully (no immediate errors)
            # The process should have printed startup information
            assert (
                "Starting Reference API Buddy on 127.0.0.1:8081" in stdout
                or "Starting Reference API Buddy on 127.0.0.1:8081" in stderr
            ), f"Expected startup message not found. STDOUT: {stdout}, STDERR: {stderr}"

        finally:
            Path(config_path).unlink()

    def test_cli_invalid_arguments_integration(self):
        """Test CLI with invalid arguments integration."""
        # Test invalid port
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--port", "invalid"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 2  # argparse error code
        assert "invalid int value" in result.stderr

    def test_cli_invalid_log_level_integration(self):
        """Test CLI with invalid log level integration."""
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--log-level", "INVALID"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 2  # argparse error code
        assert "invalid choice" in result.stderr

    def test_cli_nonexistent_config_file_integration(self):
        """Test CLI with non-existent configuration file integration."""
        result = subprocess.run(
            [sys.executable, "-m", "reference_api_buddy.cli", "--config", "/non/existent/config.json"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )

        assert result.returncode == 1
        assert "Configuration file not found" in result.stdout

    def test_cli_malformed_config_file_integration(self):
        """Test CLI with malformed configuration file integration."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json content")
            config_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", "reference_api_buddy.cli", "--config", config_path],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            )

            assert result.returncode == 1
            assert "Invalid JSON in configuration file" in result.stdout

        finally:
            Path(config_path).unlink()

    def test_cli_custom_host_port_integration(self):
        """Test CLI with custom host and port integration."""
        # Test that CLI accepts custom host and port without immediate error
        process, stdout, stderr = run_cli_process_with_retry(
            [sys.executable, "-m", "reference_api_buddy.cli", "--host", "0.0.0.0", "--port", "9090"]
        )

        # Debug output for CI
        if "Starting Reference API Buddy on 0.0.0.0:9090" not in stdout and "Starting Reference API Buddy on 0.0.0.0:9090" not in stderr:
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            print(f"Return code: {process.returncode}")
            print(f"Working directory: {PROJECT_ROOT}")

        # Check that it started with custom host and port
        assert (
            "Starting Reference API Buddy on 0.0.0.0:9090" in stdout
            or "Starting Reference API Buddy on 0.0.0.0:9090" in stderr
        ), f"Expected startup message not found. STDOUT: {stdout}, STDERR: {stderr}"

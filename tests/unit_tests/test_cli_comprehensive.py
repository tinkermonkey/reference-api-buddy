"""Comprehensive tests for the CLI module."""

import argparse
import json
import os

# Add the project root to the path to import modules
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from reference_api_buddy.cli import create_default_config, load_config, main


class TestLoadConfig:
    """Test configuration loading functionality."""

    def test_load_valid_config(self):
        """Test loading a valid JSON configuration file."""
        config_data = {"server": {"host": "0.0.0.0", "port": 9090}, "cache": {"database_path": "test.db"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            result = load_config(config_path)
            assert result == config_data
        finally:
            config_path.unlink()

    def test_load_config_file_not_found(self):
        """Test loading a non-existent configuration file."""
        non_existent_path = Path("/non/existent/config.json")

        with pytest.raises(SystemExit) as exc_info:
            load_config(non_existent_path)

        assert exc_info.value.code == 1

    def test_load_config_invalid_json(self):
        """Test loading a configuration file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json content")
            config_path = Path(f.name)

        try:
            with pytest.raises(SystemExit) as exc_info:
                load_config(config_path)

            assert exc_info.value.code == 1
        finally:
            config_path.unlink()

    def test_load_config_empty_file(self):
        """Test loading an empty configuration file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("")
            config_path = Path(f.name)

        try:
            with pytest.raises(SystemExit) as exc_info:
                load_config(config_path)

            assert exc_info.value.code == 1
        finally:
            config_path.unlink()


class TestCreateDefaultConfig:
    """Test default configuration creation."""

    def test_create_default_config_structure(self):
        """Test that default config contains all required sections."""
        config = create_default_config()

        assert isinstance(config, dict)
        assert "server" in config
        assert "security" in config
        assert "cache" in config
        assert "throttling" in config
        assert "domain_mappings" in config

    def test_create_default_config_server_settings(self):
        """Test default server configuration values."""
        config = create_default_config()

        assert config["server"]["host"] == "127.0.0.1"
        assert config["server"]["port"] == 8080

    def test_create_default_config_security_settings(self):
        """Test default security configuration values."""
        config = create_default_config()

        assert config["security"]["require_secure_key"] is True

    def test_create_default_config_cache_settings(self):
        """Test default cache configuration values."""
        config = create_default_config()

        assert config["cache"]["database_path"] == "api_buddy_cache.db"
        assert config["cache"]["default_ttl_days"] == 7

    def test_create_default_config_throttling_settings(self):
        """Test default throttling configuration values."""
        config = create_default_config()

        assert config["throttling"]["default_requests_per_hour"] == 1000

    def test_create_default_config_domain_mappings(self):
        """Test default domain mappings configuration."""
        config = create_default_config()

        assert "example" in config["domain_mappings"]
        assert config["domain_mappings"]["example"]["upstream"] == "https://api.example.com"


class TestCLIArgumentParsing:
    """Test CLI argument parsing functionality."""

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("sys.argv", ["api-buddy", "--help"])
    def test_cli_help_output(self, mock_logging, mock_proxy):
        """Test CLI help output functionality."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        # Help should exit with code 0
        assert exc_info.value.code == 0

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("sys.argv", ["api-buddy", "--version"])
    def test_cli_version_output(self, mock_logging, mock_proxy):
        """Test CLI version output functionality."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        # Version should exit with code 0
        assert exc_info.value.code == 0

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--generate-config"])
    def test_cli_generate_config(self, mock_print, mock_logging, mock_proxy):
        """Test CLI configuration generation functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "api_buddy_config.json"

            with patch("reference_api_buddy.cli.Path") as mock_path:
                mock_path.return_value = config_path

                # Mock the open function to capture what would be written
                with patch("builtins.open", mock_open()) as mock_file:
                    main()

                # Verify that a file was opened for writing
                mock_file.assert_called_once()
                # Verify print was called with expected message
                mock_print.assert_called_with(f"Generated default configuration: {config_path}")

    @patch("reference_api_buddy.security.manager.SecurityManager")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--security-key-only"])
    def test_cli_security_key_only(self, mock_print, mock_security_manager):
        """Test CLI security key generation functionality."""
        # Setup mock security manager
        mock_manager_instance = Mock()
        mock_manager_instance.generate_secure_key.return_value = "test-key-123"
        mock_security_manager.return_value = mock_manager_instance

        main()

        # Verify security manager was created and key was generated
        mock_security_manager.assert_called_once_with({})
        mock_manager_instance.generate_secure_key.assert_called_once()
        mock_print.assert_called_with("Generated security key: test-key-123")

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--port", "9090"])
    def test_cli_custom_port(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with custom port parameter."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify proxy was created with custom port
        args, kwargs = mock_proxy.call_args
        config = args[0]
        assert config["server"]["port"] == 9090

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--host", "0.0.0.0"])
    def test_cli_custom_host(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with custom host parameter."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify proxy was created with custom host
        args, kwargs = mock_proxy.call_args
        config = args[0]
        assert config["server"]["host"] == "0.0.0.0"

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--log-level", "DEBUG"])
    def test_cli_custom_log_level(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with custom log level parameter."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify configure_logging was called with DEBUG level
        args, kwargs = mock_logging.call_args
        config = args[0]
        assert config["level"] == "DEBUG"


class TestCLIConfigurationHandling:
    """Test CLI configuration file handling."""

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    def test_cli_with_config_file(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with configuration file."""
        config_data = {"server": {"host": "192.168.1.1", "port": 3000}, "cache": {"database_path": "custom.db"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            # Setup mock proxy
            mock_proxy_instance = Mock()
            mock_proxy_instance.start = Mock()
            mock_proxy_instance.get_secure_key = Mock(return_value=None)
            mock_proxy.return_value = mock_proxy_instance

            # Mock start method to avoid blocking
            def mock_start(blocking=False):
                if blocking:
                    raise KeyboardInterrupt()

            mock_proxy_instance.start.side_effect = mock_start

            with patch("sys.argv", ["api-buddy", "--config", config_path]):
                main()

            # Verify proxy was created with config file data
            args, kwargs = mock_proxy.call_args
            config = args[0]
            assert config["server"]["host"] == "192.168.1.1"
            assert config["server"]["port"] == 3000
            assert config["cache"]["database_path"] == "custom.db"

        finally:
            Path(config_path).unlink()

    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--config", "/non/existent/config.json"])
    def test_cli_with_invalid_config_file(self, mock_print):
        """Test CLI with non-existent configuration file."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


class TestCLIServerStartup:
    """Test CLI server startup functionality."""

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_server_startup_success(self, mock_print, mock_logging, mock_proxy):
        """Test successful server startup."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value="test-key-456")
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify proxy was created and started
        mock_proxy.assert_called_once()
        mock_proxy_instance.start.assert_called_once_with(blocking=True)

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_server_startup_with_security_key(self, mock_print, mock_logging, mock_proxy):
        """Test server startup with security key display."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value="test-secure-key-789")
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify security key was retrieved and displayed
        mock_proxy_instance.get_secure_key.assert_called_once()

        # Check that security key information was printed
        print_calls = [call.args[0] for call in mock_print.call_args_list]
        assert any("Security key: test-secure-key-789" in call for call in print_calls)
        assert any("Include this key in your requests:" in call for call in print_calls)

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_server_startup_error_handling(self, mock_print, mock_logging, mock_proxy):
        """Test server startup error handling."""
        # Setup mock proxy to raise an exception
        mock_proxy.side_effect = Exception("Test startup error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

        # Verify error message was printed
        print_calls = [call.args[0] for call in mock_print.call_args_list]
        assert any("Error starting proxy: Test startup error" in call for call in print_calls)

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_keyboard_interrupt_handling(self, mock_print, mock_logging, mock_proxy):
        """Test graceful shutdown on keyboard interrupt."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.stop = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to raise KeyboardInterrupt immediately
        mock_proxy_instance.start.side_effect = KeyboardInterrupt()

        main()

        # Verify stop was called
        mock_proxy_instance.stop.assert_called_once()

        # Verify shutdown message was printed
        print_calls = [call.args[0] for call in mock_print.call_args_list]
        assert any("Shutting down..." in call for call in print_calls)


class TestCLIArgumentValidation:
    """Test CLI argument validation."""

    @patch("sys.argv", ["api-buddy", "--port", "invalid"])
    def test_cli_invalid_port_argument(self):
        """Test CLI with invalid port argument."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        # argparse should exit with code 2 for invalid arguments
        assert exc_info.value.code == 2

    @patch("sys.argv", ["api-buddy", "--log-level", "INVALID"])
    def test_cli_invalid_log_level_argument(self):
        """Test CLI with invalid log level argument."""
        with pytest.raises(SystemExit) as exc_info:
            main()

        # argparse should exit with code 2 for invalid arguments
        assert exc_info.value.code == 2

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--port", "0"])
    def test_cli_edge_case_port_zero(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with port 0 (edge case)."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify proxy was created with port 0
        args, kwargs = mock_proxy.call_args
        config = args[0]
        assert config["server"]["port"] == 0

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy", "--port", "65535"])
    def test_cli_edge_case_port_max(self, mock_print, mock_logging, mock_proxy):
        """Test CLI with maximum port number (edge case)."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify proxy was created with port 65535
        args, kwargs = mock_proxy.call_args
        config = args[0]
        assert config["server"]["port"] == 65535


class TestCLIDefaultBehavior:
    """Test CLI default behavior."""

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_default_configuration_message(self, mock_print, mock_logging, mock_proxy):
        """Test that default configuration message is displayed."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify default configuration message was printed
        print_calls = [call.args[0] for call in mock_print.call_args_list]
        expected_message = "Using default configuration. Use --generate-config to create a config file."
        assert any(expected_message in call for call in print_calls)

    @patch("reference_api_buddy.cli.CachingProxy")
    @patch("reference_api_buddy.cli.configure_logging")
    @patch("builtins.print")
    @patch("sys.argv", ["api-buddy"])
    def test_cli_startup_information_display(self, mock_print, mock_logging, mock_proxy):
        """Test that startup information is properly displayed."""
        # Setup mock proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.start = Mock()
        mock_proxy_instance.get_secure_key = Mock(return_value=None)
        mock_proxy.return_value = mock_proxy_instance

        # Mock start method to avoid blocking
        def mock_start(blocking=False):
            if blocking:
                raise KeyboardInterrupt()

        mock_proxy_instance.start.side_effect = mock_start

        main()

        # Verify startup information was printed
        print_calls = [call.args[0] for call in mock_print.call_args_list]
        assert any("Starting Reference API Buddy on 127.0.0.1:8080" in call for call in print_calls)
        assert any("Press Ctrl+C to stop" in call for call in print_calls)

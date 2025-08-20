"""Comprehensive unit tests for configuration validation edge cases and error handling."""

import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.core.config import DEFAULT_CONFIG, ConfigurationManager, ConfigurationValidator, deep_merge


class TestConfigurationValidation:
    """Test configuration validation edge cases and error scenarios."""

    def test_invalid_config_not_dictionary(self):
        """Test validation when config is not a dictionary."""
        invalid_configs = [None, "string", 123, [], True]

        for invalid_config in invalid_configs:
            valid, errors = ConfigurationValidator.validate_config(invalid_config)
            assert not valid
            assert "Config must be a dictionary." in errors

    def test_valid_boolean_values_for_booleans(self):
        """Test that actual boolean values are valid for boolean fields."""
        # Test True/False values for all boolean fields
        bool_configs = [
            {"security": {"require_secure_key": True}},
            {"security": {"require_secure_key": False}},
            {"security": {"log_security_events": True}},
            {"security": {"log_security_events": False}},
            {"logging": {"enable_console": True}},
            {"logging": {"enable_console": False}},
            {"logging": {"enable_file": True}},
            {"logging": {"enable_file": False}},
        ]

        for config in bool_configs:
            merged_config = ConfigurationValidator.merge_with_defaults(config)
            valid, errors = ConfigurationValidator.validate_config(merged_config)
            assert valid, f"Config should be valid: {config}, errors: {errors}"

    def test_valid_integer_values_for_integers(self):
        """Test that actual integer values (including 0 and negative) are valid."""
        int_configs = [
            {"server": {"request_timeout": 0}},
            {"server": {"request_timeout": -1}},
            {"server": {"request_timeout": 30}},
            {"cache": {"max_cache_response_size": 0}},
            {"cache": {"max_cache_response_size": 1024}},
            {"throttling": {"default_requests_per_hour": 0}},
            {"throttling": {"default_requests_per_hour": 5000}},
            {"throttling": {"progressive_max_delay": 0}},
            {"throttling": {"progressive_max_delay": 600}},
            {"logging": {"max_file_size": 0}},
            {"logging": {"max_file_size": 50000000}},
            {"logging": {"backup_count": 0}},
            {"logging": {"backup_count": 10}},
        ]

        for config in int_configs:
            merged_config = ConfigurationValidator.merge_with_defaults(config)
            valid, errors = ConfigurationValidator.validate_config(merged_config)
            assert valid, f"Config should be valid: {config}, errors: {errors}"

    def test_invalid_server_host_type(self):
        """Test validation when server.host is not a string."""
        invalid_hosts = [123, None, [], {}]

        for invalid_host in invalid_hosts:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"server": {"host": invalid_host}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "server.host must be a string." in errors

    def test_invalid_server_request_timeout_type(self):
        """Test validation when server.request_timeout is not an integer."""
        invalid_timeouts = ["30", None, [], {}, 30.5]

        for invalid_timeout in invalid_timeouts:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"server": {"request_timeout": invalid_timeout}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "server.request_timeout must be an integer." in errors

    def test_invalid_security_require_secure_key_type(self):
        """Test validation when security.require_secure_key is not a boolean."""
        invalid_values = ["true", 1, 0, None, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"security": {"require_secure_key": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "security.require_secure_key must be a boolean." in errors

    def test_invalid_security_log_security_events_type(self):
        """Test validation when security.log_security_events is not a boolean."""
        invalid_values = ["false", 1, 0, None, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"security": {"log_security_events": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "security.log_security_events must be a boolean." in errors

    def test_invalid_cache_database_path_type(self):
        """Test validation when cache.database_path is not a string."""
        invalid_paths = [123, None, [], {}]

        for invalid_path in invalid_paths:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"cache": {"database_path": invalid_path}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "cache.database_path must be a string." in errors

    def test_invalid_cache_max_cache_response_size_type(self):
        """Test validation when cache.max_cache_response_size is not an integer."""
        invalid_sizes = ["10MB", None, [], {}, 10.5]

        for invalid_size in invalid_sizes:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"cache": {"max_cache_response_size": invalid_size}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "cache.max_cache_response_size must be an integer." in errors

    def test_invalid_throttling_default_requests_per_hour_type(self):
        """Test validation when throttling.default_requests_per_hour is not an integer."""
        invalid_values = ["1000", None, [], {}, 1000.5]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults(
                {"throttling": {"default_requests_per_hour": invalid_value}}
            )
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "throttling.default_requests_per_hour must be an integer." in errors

    def test_invalid_throttling_progressive_max_delay_type(self):
        """Test validation when throttling.progressive_max_delay is not an integer."""
        invalid_values = ["300", None, [], {}, 300.5]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults(
                {"throttling": {"progressive_max_delay": invalid_value}}
            )
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "throttling.progressive_max_delay must be an integer." in errors

    def test_invalid_logging_level_type(self):
        """Test validation when logging.level is not a string."""
        invalid_levels = [123, None, [], {}]

        for invalid_level in invalid_levels:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"level": invalid_level}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.level must be a string." in errors

    def test_invalid_logging_parent_logger_type(self):
        """Test validation when logging.parent_logger is not a string or None."""
        invalid_values = [123, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"parent_logger": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.parent_logger must be a string or None." in errors

    def test_valid_logging_parent_logger_none(self):
        """Test validation when logging.parent_logger is None (should be valid)."""
        config = {"logging": {"parent_logger": None}}
        # Merge with defaults to get complete config
        merged_config = ConfigurationValidator.merge_with_defaults(config)
        valid, errors = ConfigurationValidator.validate_config(merged_config)
        assert valid
        assert errors == []

    def test_valid_logging_parent_logger_string(self):
        """Test validation when logging.parent_logger is a string (should be valid)."""
        config = {"logging": {"parent_logger": "my_logger"}}
        # Merge with defaults to get complete config
        merged_config = ConfigurationValidator.merge_with_defaults(config)
        valid, errors = ConfigurationValidator.validate_config(merged_config)
        assert valid
        assert errors == []

    def test_invalid_logging_format_type(self):
        """Test validation when logging.format is not a string."""
        invalid_formats = [123, None, [], {}]

        for invalid_format in invalid_formats:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"format": invalid_format}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.format must be a string." in errors

    def test_invalid_logging_date_format_type(self):
        """Test validation when logging.date_format is not a string."""
        invalid_formats = [123, None, [], {}]

        for invalid_format in invalid_formats:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"date_format": invalid_format}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.date_format must be a string." in errors

    def test_invalid_logging_enable_console_type(self):
        """Test validation when logging.enable_console is not a boolean."""
        invalid_values = ["true", 1, 0, None, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"enable_console": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.enable_console must be a boolean." in errors

    def test_invalid_logging_enable_file_type(self):
        """Test validation when logging.enable_file is not a boolean."""
        invalid_values = ["false", 1, 0, None, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"enable_file": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.enable_file must be a boolean." in errors

    def test_invalid_logging_file_path_type(self):
        """Test validation when logging.file_path is not a string or None."""
        invalid_values = [123, [], {}]

        for invalid_value in invalid_values:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"file_path": invalid_value}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.file_path must be a string or None." in errors

    def test_valid_logging_file_path_none(self):
        """Test validation when logging.file_path is None (should be valid)."""
        config = {"logging": {"file_path": None}}
        # Merge with defaults to get complete config
        merged_config = ConfigurationValidator.merge_with_defaults(config)
        valid, errors = ConfigurationValidator.validate_config(merged_config)
        assert valid
        assert errors == []

    def test_valid_logging_file_path_string(self):
        """Test validation when logging.file_path is a string (should be valid)."""
        config = {"logging": {"file_path": "/var/log/api_buddy.log"}}
        # Merge with defaults to get complete config
        merged_config = ConfigurationValidator.merge_with_defaults(config)
        valid, errors = ConfigurationValidator.validate_config(merged_config)
        assert valid
        assert errors == []

    def test_invalid_logging_max_file_size_type(self):
        """Test validation when logging.max_file_size is not an integer."""
        invalid_sizes = ["10MB", None, [], {}, 10.5]

        for invalid_size in invalid_sizes:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"max_file_size": invalid_size}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.max_file_size must be an integer." in errors

    def test_invalid_logging_backup_count_type(self):
        """Test validation when logging.backup_count is not an integer."""
        invalid_counts = ["5", None, [], {}, 5.5]

        for invalid_count in invalid_counts:
            # Create a full config with just this field invalid
            config = ConfigurationValidator.merge_with_defaults({"logging": {"backup_count": invalid_count}})
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert "logging.backup_count must be an integer." in errors

    def test_multiple_validation_errors(self):
        """Test that multiple validation errors are collected and reported."""
        # Start with valid defaults and only make specific fields invalid
        config = ConfigurationValidator.merge_with_defaults(
            {
                "server": {"host": 123, "request_timeout": "30"},  # Should be string  # Should be int
                "security": {
                    "require_secure_key": "true",  # Should be bool
                    "log_security_events": 1,  # Should be bool
                },
            }
        )

        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        assert len(errors) == 4
        assert "server.host must be a string." in errors
        assert "server.request_timeout must be an integer." in errors
        assert "security.require_secure_key must be a boolean." in errors
        assert "security.log_security_events must be a boolean." in errors

    def test_missing_required_config_fields(self):
        """Test validation when required config fields are missing."""
        # Empty config should be invalid due to missing required fields
        config = {}
        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        # Should fail because required fields are missing

    def test_partial_config_sections(self):
        """Test validation with partial config sections."""
        configs = [
            {"server": {}},  # Missing host and request_timeout
            {"security": {}},  # Missing require_secure_key and log_security_events
            {"cache": {}},  # Missing database_path and max_cache_response_size
            {"throttling": {}},  # Missing default_requests_per_hour and progressive_max_delay
            {"logging": {}},  # Missing all logging fields
        ]

        for config in configs:
            valid, errors = ConfigurationValidator.validate_config(config)
            assert not valid
            assert len(errors) > 0


class TestConfigurationManagerEdgeCases:
    """Test ConfigurationManager edge cases and error scenarios."""

    def test_configuration_manager_with_invalid_config(self):
        """Test ConfigurationManager initialization with invalid config."""
        invalid_config = {"server": {"host": 123}}

        with pytest.raises(ValueError) as exc_info:
            ConfigurationManager(invalid_config)

        assert "Invalid configuration:" in str(exc_info.value)

    def test_configuration_manager_update_invalid_config(self):
        """Test ConfigurationManager update with invalid value."""
        cm = ConfigurationManager()

        with pytest.raises(ValueError) as exc_info:
            cm.update("server.host", 123)

        assert "Invalid configuration after update:" in str(exc_info.value)

    def test_configuration_manager_update_creates_nested_keys(self):
        """Test ConfigurationManager update creates nested keys if they don't exist."""
        cm = ConfigurationManager()

        # Update a nested key that doesn't exist yet
        cm.update("new_section.new_key", "test_value")

        assert cm.config["new_section"]["new_key"] == "test_value"

    def test_configuration_manager_update_deep_nesting(self):
        """Test ConfigurationManager update with deep nesting."""
        cm = ConfigurationManager()

        # Update a deeply nested key
        cm.update("level1.level2.level3.key", "deep_value")

        assert cm.config["level1"]["level2"]["level3"]["key"] == "deep_value"

    def test_configuration_manager_reload_invalid_config(self):
        """Test ConfigurationManager reload with invalid config."""
        cm = ConfigurationManager()

        invalid_config = {"server": {"host": 123}}

        with pytest.raises(ValueError) as exc_info:
            cm.reload(invalid_config)

        assert "Invalid configuration:" in str(exc_info.value)

    def test_configuration_manager_reload_preserves_state_on_error(self):
        """Test ConfigurationManager preserves state when reload fails."""
        original_config = {"server": {"host": "original_host"}}
        cm = ConfigurationManager(original_config)

        original_host = cm.config["server"]["host"]

        # Try to reload with invalid config
        invalid_config = {"server": {"host": 123}}

        with pytest.raises(ValueError):
            cm.reload(invalid_config)

        # Original configuration should be preserved
        assert cm.config["server"]["host"] == original_host


class TestDeepMergeEdgeCases:
    """Test deep_merge function edge cases."""

    def test_deep_merge_with_none_values(self):
        """Test deep_merge handles None values correctly."""
        base = {"key": "value", "nested": {"subkey": "subvalue"}}
        override = {"key": None, "nested": {"subkey": None}}

        result = deep_merge(base, override)

        assert result["key"] is None
        assert result["nested"]["subkey"] is None

    def test_deep_merge_with_different_types(self):
        """Test deep_merge when override changes data types."""
        base = {"key": "string_value", "nested": {"subkey": 123}}
        override = {"key": 456, "nested": {"subkey": "new_string"}}

        result = deep_merge(base, override)

        assert result["key"] == 456
        assert result["nested"]["subkey"] == "new_string"

    def test_deep_merge_with_new_keys(self):
        """Test deep_merge adds new keys from override."""
        base = {"existing": "value"}
        override = {"new_key": "new_value", "nested": {"new_nested": "nested_value"}}

        result = deep_merge(base, override)

        assert result["existing"] == "value"
        assert result["new_key"] == "new_value"
        assert result["nested"]["new_nested"] == "nested_value"

    def test_deep_merge_preserves_original_objects(self):
        """Test deep_merge doesn't modify original dictionaries."""
        base = {"key": "original", "nested": {"subkey": "original_sub"}}
        override = {"key": "modified", "nested": {"subkey": "modified_sub"}}

        original_base = base.copy()
        original_override = override.copy()

        result = deep_merge(base, override)

        # Original dictionaries should be unchanged
        assert base == original_base
        assert override == original_override
        assert result["key"] == "modified"
        assert result["nested"]["subkey"] == "modified_sub"

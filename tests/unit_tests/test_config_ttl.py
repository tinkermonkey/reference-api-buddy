"""Tests for TTL configuration validation."""

import sys
from pathlib import Path

import pytest

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.config import ConfigurationValidator


class TestTTLConfiguration:
    """Test TTL configuration validation."""

    def test_valid_ttl_configuration(self):
        """Test validation of valid TTL configuration."""
        config = {
            "server": {"host": "127.0.0.1", "request_timeout": 30},
            "security": {"require_secure_key": False, "log_security_events": True},
            "cache": {"database_path": ":memory:", "max_cache_response_size": 10485760, "default_ttl_seconds": 3600},
            "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
            "logging": {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            },
            "admin": {
                "enabled": True,
                "rate_limit_per_minute": 10,
                "include_sensitive_config": False,
                "log_access": True,
            },
            "domain_mappings": {"api1": {"upstream": "https://api1.com", "ttl_seconds": 1800}},
            "callbacks": {},
        }

        valid, errors = ConfigurationValidator.validate_config(config)
        assert valid, f"Configuration should be valid, but got errors: {errors}"
        assert len(errors) == 0

    def test_invalid_default_ttl_configuration(self):
        """Test validation of invalid default TTL configuration."""
        config = {
            "server": {"host": "127.0.0.1", "request_timeout": 30},
            "security": {"require_secure_key": False, "log_security_events": True},
            "cache": {
                "database_path": ":memory:",
                "max_cache_response_size": 10485760,
                "default_ttl_seconds": -100,  # Invalid: negative
            },
            "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
            "logging": {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            },
            "domain_mappings": {},
            "callbacks": {},
        }

        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        assert any("default_ttl_seconds must be a positive integer" in error for error in errors)

    def test_invalid_domain_ttl_configuration(self):
        """Test validation of invalid domain-specific TTL configuration."""
        config = {
            "server": {"host": "127.0.0.1", "request_timeout": 30},
            "security": {"require_secure_key": False, "log_security_events": True},
            "cache": {"database_path": ":memory:", "max_cache_response_size": 10485760, "default_ttl_seconds": 3600},
            "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
            "logging": {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            },
            "domain_mappings": {
                "api1": {"upstream": "https://api1.com", "ttl_seconds": "not_a_number"}  # Invalid: not integer
            },
            "callbacks": {},
        }

        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        assert any("ttl_seconds must be a positive integer" in error for error in errors)

    def test_zero_ttl_validation(self):
        """Test validation of zero TTL (should be invalid)."""
        config = {
            "server": {"host": "127.0.0.1", "request_timeout": 30},
            "security": {"require_secure_key": False, "log_security_events": True},
            "cache": {
                "database_path": ":memory:",
                "max_cache_response_size": 10485760,
                "default_ttl_seconds": 0,  # Invalid: zero
            },
            "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
            "logging": {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            },
            "domain_mappings": {},
            "callbacks": {},
        }

        valid, errors = ConfigurationValidator.validate_config(config)
        assert not valid
        assert any("default_ttl_seconds must be a positive integer" in error for error in errors)

    def test_missing_ttl_configuration_uses_default(self):
        """Test that missing TTL configuration is handled (should use default from merge)."""
        config = {
            "server": {"host": "127.0.0.1", "request_timeout": 30},
            "security": {"require_secure_key": False, "log_security_events": True},
            "cache": {
                "database_path": ":memory:",
                "max_cache_response_size": 10485760,
                # default_ttl_seconds is missing, should use default from merge
            },
            "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
            "logging": {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            },
            "admin": {
                "enabled": True,
                "rate_limit_per_minute": 10,
                "include_sensitive_config": False,
                "log_access": True,
            },
            "domain_mappings": {},
            "callbacks": {},
        }

        valid, errors = ConfigurationValidator.validate_config(config)
        assert valid, f"Configuration should be valid, but got errors: {errors}"
        assert len(errors) == 0

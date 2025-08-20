"""Configuration management for Reference API Buddy."""

import copy
from typing import Any, List, Tuple

# Default configuration schema
DEFAULT_CONFIG = {
    "server": {"host": "127.0.0.1", "request_timeout": 30},
    "security": {"require_secure_key": False, "log_security_events": True},
    "cache": {"database_path": ":memory:", "max_cache_response_size": 10485760},  # 10MB
    "throttling": {"default_requests_per_hour": 1000, "progressive_max_delay": 300},
    "logging": {
        "level": "INFO",
        "parent_logger": None,
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "enable_console": True,
        "enable_file": False,
        "file_path": None,
        "max_file_size": 10485760,  # 10MB
        "backup_count": 5,
    },
    "domain_mappings": {},
    "callbacks": {},
}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dictionaries."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


class ConfigurationValidator:
    """Validates configuration and provides error reporting."""

    @staticmethod
    def validate_config(config: dict) -> Tuple[bool, List[str]]:
        errors = []
        # Basic validation for required keys and types
        if not isinstance(config, dict):
            errors.append("Config must be a dictionary.")
            return False, errors
        # Validate server
        server = config.get("server", {})
        if not isinstance(server.get("host", None), str):
            errors.append("server.host must be a string.")
        if not isinstance(server.get("request_timeout", None), int):
            errors.append("server.request_timeout must be an integer.")
        # Validate security
        security = config.get("security", {})
        if not isinstance(security.get("require_secure_key", None), bool):
            errors.append("security.require_secure_key must be a boolean.")
        if not isinstance(security.get("log_security_events", None), bool):
            errors.append("security.log_security_events must be a boolean.")
        # Validate cache
        cache = config.get("cache", {})
        if not isinstance(cache.get("database_path", None), str):
            errors.append("cache.database_path must be a string.")
        if not isinstance(cache.get("max_cache_response_size", None), int):
            errors.append("cache.max_cache_response_size must be an integer.")
        # Validate throttling
        throttling = config.get("throttling", {})
        if not isinstance(throttling.get("default_requests_per_hour", None), int):
            errors.append("throttling.default_requests_per_hour must be an integer.")
        if not isinstance(throttling.get("progressive_max_delay", None), int):
            errors.append("throttling.progressive_max_delay must be an integer.")
        # Validate logging
        logging_cfg = config.get("logging", {})
        if not isinstance(logging_cfg.get("level", None), str):
            errors.append("logging.level must be a string.")
        if logging_cfg.get("parent_logger") is not None and not isinstance(logging_cfg.get("parent_logger"), str):
            errors.append("logging.parent_logger must be a string or None.")
        if not isinstance(logging_cfg.get("format", None), str):
            errors.append("logging.format must be a string.")
        if not isinstance(logging_cfg.get("date_format", None), str):
            errors.append("logging.date_format must be a string.")
        if not isinstance(logging_cfg.get("enable_console", None), bool):
            errors.append("logging.enable_console must be a boolean.")
        if not isinstance(logging_cfg.get("enable_file", None), bool):
            errors.append("logging.enable_file must be a boolean.")
        if logging_cfg.get("file_path") is not None and not isinstance(logging_cfg.get("file_path"), str):
            errors.append("logging.file_path must be a string or None.")
        if not isinstance(logging_cfg.get("max_file_size", None), int):
            errors.append("logging.max_file_size must be an integer.")
        if not isinstance(logging_cfg.get("backup_count", None), int):
            errors.append("logging.backup_count must be an integer.")
        # domain_mappings and callbacks can be empty dicts
        return len(errors) == 0, errors

    @staticmethod
    def merge_with_defaults(user_config: dict) -> dict:
        return deep_merge(DEFAULT_CONFIG, user_config)


class ConfigurationManager:
    """Manages configuration, validation, merging, and runtime updates."""

    def __init__(self, user_config: dict = None):
        if user_config is None:
            user_config = {}
        self._config = self.load_config(user_config)

    def load_config(self, user_config: dict) -> dict:
        merged = ConfigurationValidator.merge_with_defaults(user_config)
        valid, errors = ConfigurationValidator.validate_config(merged)
        if not valid:
            raise ValueError(f"Invalid configuration: {errors}")
        return merged

    @property
    def config(self) -> dict:
        return self._config

    def update(self, key_path: str, value: Any) -> None:
        """Update a config value at a dotted key path (e.g., 'server.host')."""
        keys = key_path.split(".")
        d = self._config
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        # Re-validate after update
        valid, errors = ConfigurationValidator.validate_config(self._config)
        if not valid:
            raise ValueError(f"Invalid configuration after update: {errors}")

    def reload(self, new_config: dict) -> None:
        self._config = self.load_config(new_config)

"""Logger utility for Reference API Buddy.

This module provides a configurable logging system that integrates with the
configuration manager to allow users to customize logging behavior.
"""

import logging
import logging.handlers
import sys
from typing import Any, Dict, Optional


class ColorFormatter(logging.Formatter):
    """Custom formatter to add colors to log levels in console output, only if output is a TTY."""

    COLORS = {
        "DEBUG": "\033[94m",  # Blue
        "INFO": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        msg = super().format(record)
        return f"{color}{msg}{self.RESET}"


class LoggerManager:
    """Manages logger configuration and provides logger instances."""

    def __init__(self):
        self._loggers: Dict[str, logging.Logger] = {}
        self._configured = False
        self._config = None

    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the logger with the provided configuration.

        Args:
            config: Logging configuration dictionary from ConfigurationManager
        """
        self._config = config
        self._configured = True

        # Configure root logger for the package
        self._configure_root_logger()

    def _configure_root_logger(self) -> None:
        """Configure the root logger based on the configuration."""
        if not self._config:
            return

        # Get or create the parent logger
        parent_logger_name = self._config.get("parent_logger")
        if parent_logger_name:
            parent_logger = logging.getLogger(parent_logger_name)
        else:
            parent_logger = logging.getLogger("api_buddy")

        # Clear existing handlers to avoid duplicates
        parent_logger.handlers.clear()

        # Set logging level
        level_str = self._config.get("level", "INFO")
        level = getattr(logging, level_str.upper(), logging.INFO)
        parent_logger.setLevel(level)

        # Create formatter
        log_format = self._config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        date_format = self._config.get("date_format", "%Y-%m-%d %H:%M:%S")
        formatter = logging.Formatter(log_format, date_format)
        color_formatter = ColorFormatter(log_format, date_format)

        # Add console handler if enabled
        if self._config.get("enable_console", True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(color_formatter)
            parent_logger.addHandler(console_handler)

        # Add file handler if enabled
        if self._config.get("enable_file", False):
            file_path = self._config.get("file_path")
            if file_path:
                max_size = self._config.get("max_file_size", 10485760)  # 10MB
                backup_count = self._config.get("backup_count", 5)

                file_handler = logging.handlers.RotatingFileHandler(
                    file_path, maxBytes=max_size, backupCount=backup_count
                )
                file_handler.setFormatter(formatter)
                parent_logger.addHandler(file_handler)

        # Prevent propagation to avoid duplicate logs
        parent_logger.propagate = False

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger with the specified name.

        Args:
            name: Name of the logger (will be prefixed with package name)

        Returns:
            Configured logger instance
        """
        if not self._configured:
            # Use default configuration if not configured
            self._config = {
                "level": "INFO",
                "parent_logger": None,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "enable_console": True,
                "enable_file": False,
                "file_path": None,
                "max_file_size": 10485760,
                "backup_count": 5,
            }
            self._configure_root_logger()
            self._configured = True

        # Determine the full logger name
        parent_logger_name = (self._config or {}).get("parent_logger")
        if parent_logger_name:
            full_name = f"{parent_logger_name}.{name}"
        else:
            full_name = f"api_buddy.{name}"

        # Return cached logger or create new one
        if full_name not in self._loggers:
            logger = logging.getLogger(full_name)
            self._loggers[full_name] = logger

        return self._loggers[full_name]

    def reconfigure(self, config: Dict[str, Any]) -> None:
        """Reconfigure all loggers with new configuration.

        Args:
            config: New logging configuration dictionary
        """
        self.configure(config)

        # Update all existing loggers
        for logger_name, logger in self._loggers.items():
            # The parent logger configuration will be inherited
            pass

    def set_level(self, level: str) -> None:
        """Change the logging level for all loggers.

        Args:
            level: New logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        if self._config:
            self._config["level"] = level
            self._configure_root_logger()


# Global logger manager instance
_logger_manager = LoggerManager()


def configure_logging(config: Dict[str, Any]) -> None:
    """Configure the logging system with the provided configuration.

    This function should be called once during application initialization
    with the logging configuration from ConfigurationManager.

    Args:
        config: Logging configuration dictionary
    """
    _logger_manager.configure(config)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the specified module/component.

    Args:
        name: Name of the module or component requesting the logger

    Returns:
        Configured logger instance

    Example:
        logger = get_logger(__name__)
        logger.info("This is an info message")
    """
    return _logger_manager.get_logger(name)


def reconfigure_logging(config: Dict[str, Any]) -> None:
    """Reconfigure the logging system with new settings.

    Args:
        config: New logging configuration dictionary
    """
    _logger_manager.reconfigure(config)


def set_log_level(level: str) -> None:
    """Change the logging level for the entire package.

    Args:
        level: New logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    _logger_manager.set_level(level)


# Convenience function for backward compatibility
def setup_logger(name: str, config: Optional[Dict[str, Any]] = None) -> logging.Logger:
    """Setup and return a logger with optional configuration.

    Args:
        name: Name of the logger
        config: Optional logging configuration

    Returns:
        Configured logger instance
    """
    if config:
        configure_logging(config)
    return get_logger(name)

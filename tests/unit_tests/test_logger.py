"""Unit tests for logger utility."""

import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import logging
import tempfile
import unittest
from io import StringIO

from reference_api_buddy.utils.logger import (
    LoggerManager,
    configure_logging,
    get_logger,
    reconfigure_logging,
    set_log_level,
)


class TestLoggerManager(unittest.TestCase):
    """Test cases for LoggerManager class."""

    def setUp(self):
        """Set up test environment."""
        self.logger_manager = LoggerManager()

    def test_configure_basic(self):
        """Test basic logger configuration."""
        config = {
            "level": "DEBUG",
            "parent_logger": None,
            "format": "%(name)s - %(levelname)s - %(message)s",
            "date_format": "%Y-%m-%d %H:%M:%S",
            "enable_console": True,
            "enable_file": False,
            "file_path": None,
            "max_file_size": 10485760,
            "backup_count": 5,
        }

        self.logger_manager.configure(config)
        self.assertTrue(self.logger_manager._configured)
        self.assertEqual(self.logger_manager._config, config)

    def test_get_logger(self):
        """Test getting logger instances."""
        config = {
            "level": "INFO",
            "parent_logger": None,
            "format": "%(name)s - %(levelname)s - %(message)s",
            "enable_console": True,
            "enable_file": False,
        }

        self.logger_manager.configure(config)
        logger = self.logger_manager.get_logger("test_module")

        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "api_buddy.test_module")

    def test_get_logger_with_parent(self):
        """Test getting logger with custom parent."""
        config = {
            "level": "INFO",
            "parent_logger": "my_app",
            "format": "%(name)s - %(levelname)s - %(message)s",
            "enable_console": True,
            "enable_file": False,
        }

        self.logger_manager.configure(config)
        logger = self.logger_manager.get_logger("test_module")

        self.assertEqual(logger.name, "my_app.test_module")

    def test_get_logger_without_configuration(self):
        """Test getting logger without prior configuration uses defaults."""
        logger = self.logger_manager.get_logger("test_module")

        self.assertIsInstance(logger, logging.Logger)
        self.assertTrue(self.logger_manager._configured)

    def test_set_level(self):
        """Test setting log level."""
        config = {"level": "INFO", "enable_console": True, "enable_file": False}

        self.logger_manager.configure(config)
        self.logger_manager.set_level("DEBUG")

        self.assertEqual(self.logger_manager._config["level"], "DEBUG")


class TestLoggerIntegration(unittest.TestCase):
    """Test cases for logger integration functions."""

    def test_configure_logging(self):
        """Test configure_logging function."""
        config = {"level": "WARNING", "enable_console": True, "enable_file": False, "format": "Test: %(message)s"}

        configure_logging(config)
        logger = get_logger("integration_test")

        # Capture log output
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger.parent.handlers = [handler]

        logger.info("This should not appear")  # Below WARNING level
        logger.warning("This should appear")

        output = stream.getvalue()
        self.assertNotIn("This should not appear", output)
        self.assertIn("This should appear", output)

    def test_get_logger_function(self):
        """Test get_logger convenience function."""
        logger = get_logger("function_test")
        self.assertIsInstance(logger, logging.Logger)

    def test_reconfigure_logging(self):
        """Test reconfiguring logging."""
        initial_config = {"level": "INFO", "enable_console": True, "enable_file": False}

        new_config = {"level": "ERROR", "enable_console": True, "enable_file": False}

        configure_logging(initial_config)
        reconfigure_logging(new_config)

        # The new configuration should be applied
        # This is a basic test - in practice, you'd verify the actual level change
        logger = get_logger("reconfig_test")
        self.assertIsInstance(logger, logging.Logger)

    def test_set_log_level_function(self):
        """Test set_log_level convenience function."""
        configure_logging({"level": "INFO", "enable_console": True, "enable_file": False})
        set_log_level("DEBUG")

        # Basic test that the function executes without error
        logger = get_logger("level_test")
        self.assertIsInstance(logger, logging.Logger)


class TestLoggerFileOutput(unittest.TestCase):
    """Test cases for file logging functionality."""

    def test_file_logging(self):
        """Test logging to file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as temp_file:
            temp_path = temp_file.name

        try:
            config = {
                "level": "INFO",
                "enable_console": False,
                "enable_file": True,
                "file_path": temp_path,
                "format": "%(levelname)s: %(message)s",
            }

            configure_logging(config)
            logger = get_logger("file_test")

            test_message = "Test file logging message"
            logger.info(test_message)

            # Force flush by removing handlers
            for handler in logger.parent.handlers:
                handler.flush()
                # Close file handlers to release locks on Windows
                if hasattr(handler, "close"):
                    handler.close()

            # Read the file and check content
            with open(temp_path, "r") as f:
                content = f.read()
                self.assertIn(test_message, content)
                self.assertIn("INFO:", content)

        finally:
            # Clean up - with Windows file lock handling
            import platform
            import time

            if platform.system() == "Windows":
                time.sleep(0.1)
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except (PermissionError, OSError):
                # On Windows, file might still be locked - ignore
                pass


if __name__ == "__main__":
    unittest.main()

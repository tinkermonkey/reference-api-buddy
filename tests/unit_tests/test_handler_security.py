"""Tests for HTTP handler security functionality.

This module tests security-related handler functionality including:
- Security validation
- Authentication handling
- Authorization checks
"""

import io
import os
import sys

# Add the project root to the path to import modules
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.core.handler import RequestProcessingMixin


class MockProxy:
    """Minimal mock proxy for testing."""

    def __init__(self, config=None, security_manager=None):
        class MockLogger:
            def debug(self, msg):
                pass

            def info(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

            def critical(self, msg):
                pass

        self.logger = MockLogger()
        self.config = config or {}
        self.security_manager = security_manager


class TestSecurityValidation:
    """Test security validation functionality."""

    def test_security_validation_failure(self):
        """Test security validation failure handling."""
        security_manager = Mock()
        security_manager.extract_secure_key.return_value = ("invalid_key", None)
        security_manager.validate_request.return_value = False

        proxy = MockProxy(
            config={
                "security": {"require_secure_key": True},
                "domain_mappings": {"testdomain": {"upstream": "http://example.com"}},
            },
            security_manager=security_manager,
        )

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy
                self.path = "/testdomain/test"
                self.headers = {}
                self.wfile = io.BytesIO()
                self._response_status = None

            def send_response(self, status):
                self._response_status = status

            def end_headers(self):
                pass

        handler = TestHandler()

        # This should trigger security validation failure
        handler._handle_request("GET")
        assert handler._response_status == 401

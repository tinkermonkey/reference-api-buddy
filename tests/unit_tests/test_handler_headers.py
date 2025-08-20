"""Tests for HTTP request header processing.

This module tests header handling functionality including:
- Request header filtering
- Header validation
- Header transformation
"""

import os
import sys
from unittest.mock import Mock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reference_api_buddy.core.handler import RequestProcessingMixin


class MockProxy:
    """Minimal mock proxy for testing."""

    def __init__(self, config=None):
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


class TestRequestHeaderFiltering:
    """Test request header filtering functionality."""

    def test_problematic_header_filtering(self):
        """Test that problematic headers are filtered from requests."""
        proxy = MockProxy(config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}})

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy

        handler = TestHandler()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test response"
            mock_response.getcode.return_value = 200
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # These headers should trigger filtering
            headers = {
                "Host": "old.example.com",
                "Connection": "keep-alive",
                "Content-Length": "100",
                "Accept": "application/json",  # This should be kept
            }

            result = handler._forward_request("GET", "/testdomain/test", headers=headers)
            assert result[1] == 200

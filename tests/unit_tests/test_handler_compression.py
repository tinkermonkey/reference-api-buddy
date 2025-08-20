"""Tests for HTTP request/response compression handling.

This module tests compression and decompression functionality including:
- Gzip compression/decompression
- Deflate compression/decompression
- Compression error handling
- Header updates after decompression
"""

import gzip
import os
import sys
import zlib
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


class TestGzipHandling:
    """Test gzip compression handling."""

    def test_gzip_decompression_error(self):
        """Test gzip decompression error handling."""
        proxy = MockProxy(config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}})

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy

        handler = TestHandler()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            # Invalid gzip data that should trigger decompression error
            mock_response.read.return_value = b"\x1f\x8binvalid_gzip"
            mock_response.getcode.return_value = 200
            mock_response.headers = {"Content-Encoding": "gzip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = handler._forward_request("GET", "/testdomain/test")
            # Should still return data even with decompression error
            assert result[1] == 200


class TestDeflateHandling:
    """Test deflate compression handling."""

    def test_deflate_decompression_error(self):
        """Test deflate decompression error handling."""
        proxy = MockProxy(config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}})

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy

        handler = TestHandler()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            # Invalid deflate data
            mock_response.read.return_value = b"invalid_deflate_data"
            mock_response.getcode.return_value = 200
            mock_response.headers = {"Content-Encoding": "deflate"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = handler._forward_request("GET", "/testdomain/test")
            assert result[1] == 200


class TestCompressionHeaderHandling:
    """Test compression-related header handling."""

    def test_header_updates_after_decompression(self):
        """Test header updates after successful decompression."""
        proxy = MockProxy(config={"domain_mappings": {"testdomain": {"upstream": "http://example.com"}}})

        class TestHandler(RequestProcessingMixin):
            def __init__(self):
                self.proxy = proxy

        handler = TestHandler()

        with patch("urllib.request.urlopen") as mock_urlopen:
            # Create valid gzipped data
            original_data = b"Hello, World!"
            gzipped_data = gzip.compress(original_data)

            mock_response = Mock()
            mock_response.read.return_value = gzipped_data
            mock_response.getcode.return_value = 200
            mock_response.headers = {"Content-Encoding": "gzip", "Transfer-Encoding": "chunked"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = handler._forward_request("GET", "/testdomain/test")
            data, status, headers = result

            # Headers should be updated after decompression
            assert status == 200
            assert data == original_data
            assert "Content-Encoding" not in headers
            assert "Transfer-Encoding" not in headers
            assert headers.get("Content-Length") == str(len(original_data))

"""Tests for ProxyHTTPRequestHandler class functionality.

This module tests the main handler class including:
- Handler initialization
- HTTP method routing
- Request delegation
"""

import os
import sys
from unittest.mock import Mock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reference_api_buddy.core.handler import ProxyHTTPRequestHandler


class MockProxy:
    """Minimal mock proxy for testing."""

    def __init__(self):
        class MockLogger:
            def debug(self, msg): pass
            def info(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): pass
            def critical(self, msg): pass

        self.logger = MockLogger()
        self.metrics_collector = Mock()


class TestProxyHTTPRequestHandlerClass:
    """Test the ProxyHTTPRequestHandler class functionality."""

    def test_handler_initialization_with_proxy(self):
        """Test handler initialization with proxy instance."""
        proxy = MockProxy()
        
        with patch('reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__'):
            handler = ProxyHTTPRequestHandler(None, None, None, proxy_instance=proxy)
            assert handler.proxy == proxy
            assert handler.metrics_collector == proxy.metrics_collector

    def test_handler_initialization_without_proxy(self):
        """Test handler initialization without proxy instance."""
        with patch('reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__'):
            handler = ProxyHTTPRequestHandler(None, None, None)
            assert handler.proxy is None
            assert handler.metrics_collector is None

    def test_http_method_routing(self):
        """Test that HTTP method handlers call _handle_request correctly."""
        proxy = MockProxy()
        
        with patch('reference_api_buddy.core.handler.BaseHTTPRequestHandler.__init__'):
            handler = ProxyHTTPRequestHandler(None, None, None, proxy_instance=proxy)
            
            with patch.object(handler, '_handle_request') as mock_handle:
                # Test GET method
                handler.do_GET()
                mock_handle.assert_called_with("GET")
                
                # Test POST method
                handler.do_POST()
                mock_handle.assert_called_with("POST")
                
                # Test PUT method
                handler.do_PUT()
                mock_handle.assert_called_with("PUT")
                
                # Test DELETE method
                handler.do_DELETE()
                mock_handle.assert_called_with("DELETE")

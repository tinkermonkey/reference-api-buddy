"""Unit tests for admin endpoints functionality."""

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy.core.admin_utils import AdminRateLimiter
from reference_api_buddy.core.handler import RequestProcessingMixin


class TestAdminRateLimiter(unittest.TestCase):
    """Test the AdminRateLimiter class."""

    def setUp(self):
        """Set up test fixtures."""
        self.rate_limiter = AdminRateLimiter()

    def test_initial_state(self):
        """Test initial state of rate limiter."""
        self.assertEqual(self.rate_limiter.get_request_count("192.168.1.1"), 0)
        self.assertTrue(self.rate_limiter.is_allowed("192.168.1.1", 10))

    def test_rate_limiting(self):
        """Test basic rate limiting functionality."""
        client_ip = "192.168.1.1"
        limit = 3

        # First 3 requests should be allowed
        for i in range(limit):
            self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))
            self.assertEqual(self.rate_limiter.get_request_count(client_ip), i + 1)

        # Next request should be denied
        self.assertFalse(self.rate_limiter.is_allowed(client_ip, limit))
        self.assertEqual(self.rate_limiter.get_request_count(client_ip), limit)

    def test_time_window_expiry(self):
        """Test that rate limits expire after time window."""
        client_ip = "192.168.1.1"
        limit = 2

        # Fill up the limit
        self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))
        self.assertFalse(self.rate_limiter.is_allowed(client_ip, limit))

        # Mock time to simulate 61 seconds later
        original_time = time.time()
        with patch("time.time") as mock_time:
            mock_time.return_value = original_time + 61
            self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))

    def test_multiple_clients(self):
        """Test rate limiting with multiple clients."""
        client1 = "192.168.1.1"
        client2 = "192.168.1.2"
        limit = 2

        # Each client should have independent limits
        self.assertTrue(self.rate_limiter.is_allowed(client1, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client2, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client1, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client2, limit))

        # Both should be rate limited independently
        self.assertFalse(self.rate_limiter.is_allowed(client1, limit))
        self.assertFalse(self.rate_limiter.is_allowed(client2, limit))

    def test_clear_client(self):
        """Test clearing rate limit data for specific client."""
        client_ip = "192.168.1.1"
        limit = 2

        # Fill up the limit
        self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))
        self.assertFalse(self.rate_limiter.is_allowed(client_ip, limit))

        # Clear and verify
        self.rate_limiter.clear_client(client_ip)
        self.assertEqual(self.rate_limiter.get_request_count(client_ip), 0)
        self.assertTrue(self.rate_limiter.is_allowed(client_ip, limit))

    def test_clear_all(self):
        """Test clearing all rate limit data."""
        client1 = "192.168.1.1"
        client2 = "192.168.1.2"
        limit = 1

        # Add requests for multiple clients
        self.assertTrue(self.rate_limiter.is_allowed(client1, limit))
        self.assertTrue(self.rate_limiter.is_allowed(client2, limit))

        # Clear all and verify
        self.rate_limiter.clear_all()
        self.assertEqual(self.rate_limiter.get_request_count(client1), 0)
        self.assertEqual(self.rate_limiter.get_request_count(client2), 0)

    def test_thread_safety(self):
        """Test thread safety of rate limiter."""
        client_ip = "192.168.1.1"
        limit = 100
        allowed_count = 0
        denied_count = 0

        def make_requests():
            nonlocal allowed_count, denied_count
            for _ in range(50):
                if self.rate_limiter.is_allowed(client_ip, limit):
                    allowed_count += 1
                else:
                    denied_count += 1

        # Start multiple threads
        threads = []
        for _ in range(4):
            thread = threading.Thread(target=make_requests)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify total requests don't exceed limit
        self.assertLessEqual(allowed_count, limit)
        self.assertEqual(allowed_count + denied_count, 200)  # 4 threads * 50 requests


class TestAdminEndpointMethods(unittest.TestCase):
    """Test admin endpoint methods in RequestProcessingMixin."""

    def setUp(self):
        """Set up test fixtures."""
        self.handler = RequestProcessingMixin()

        # Mock proxy and configuration
        self.handler.proxy = Mock()
        self.handler.proxy.config = {
            "admin": {"enabled": True, "rate_limit_per_minute": 10, "log_access": True},
            "security": {"require_secure_key": False},
            "cache": {"database_path": ":memory:", "default_ttl_seconds": 86400},
            "domain_mappings": {"example": {"upstream": "https://api.example.com", "ttl_seconds": 3600}},
        }

        # Mock proxy logger for the handler property
        mock_logger = Mock()
        self.handler.proxy.logger = mock_logger

        # Mock client address
        self.handler.client_address = ("192.168.1.1", 12345)

    def test_is_admin_path(self):
        """Test admin path detection."""
        self.assertTrue(self.handler._is_admin_path("/admin/config"))
        self.assertTrue(self.handler._is_admin_path("/admin/status"))
        self.assertTrue(self.handler._is_admin_path("/admin/cache/example"))
        self.assertFalse(self.handler._is_admin_path("/api/test"))
        self.assertFalse(self.handler._is_admin_path("/health"))

    def test_is_admin_enabled(self):
        """Test admin enabled check."""
        self.assertTrue(self.handler._is_admin_enabled())

        self.handler.proxy.config["admin"]["enabled"] = False
        self.assertFalse(self.handler._is_admin_enabled())

    def test_config_sanitization(self):
        """Test configuration sanitization."""
        # Add sensitive data to config
        self.handler.proxy.config["test_api"] = {
            "api_key": "secret123",
            "secret_token": "token456",
            "base_url": "https://api.test.com",
            "nested": {"password": "pass789", "username": "user"},
        }

        result = self.handler._get_sanitized_config()

        # Verify sensitive fields are redacted
        self.assertEqual(result["config"]["test_api"]["api_key"], "[REDACTED]")
        self.assertEqual(result["config"]["test_api"]["secret_token"], "[REDACTED]")
        self.assertEqual(result["config"]["test_api"]["nested"]["password"], "[REDACTED]")

        # Verify non-sensitive fields are preserved
        self.assertEqual(result["config"]["test_api"]["base_url"], "https://api.test.com")
        self.assertEqual(result["config"]["test_api"]["nested"]["username"], "user")

        # Verify sanitized fields list
        expected_fields = ["test_api.api_key", "test_api.secret_token", "test_api.nested.password"]
        for field in expected_fields:
            self.assertIn(field, result["sanitized_fields"])

    def test_component_status_healthy(self):
        """Test component status when all components are healthy."""
        # Mock healthy components
        self.handler.proxy.cache_engine = Mock()
        self.handler.proxy.cache_engine.get_stats.return_value = {"cache_size": 100}

        self.handler.proxy.db_manager = Mock()
        self.handler.proxy.throttle_manager = Mock()
        self.handler.proxy.throttle_manager.states = {"example": Mock(delay_seconds=0)}

        self.handler.proxy.security_manager = Mock()
        self.handler.proxy.security_manager.security_enabled = False

        status = self.handler._get_component_status()

        self.assertEqual(status["cache_engine"]["status"], "healthy")
        self.assertEqual(status["database_manager"]["status"], "healthy")
        self.assertEqual(status["throttle_manager"]["status"], "healthy")
        self.assertEqual(status["security_manager"]["status"], "healthy")

    def test_component_status_unavailable(self):
        """Test component status when components are unavailable."""
        # Set components to None to trigger unavailable status
        self.handler.proxy.cache_engine = None
        self.handler.proxy.db_manager = None
        self.handler.proxy.throttle_manager = None
        self.handler.proxy.security_manager = None

        status = self.handler._get_component_status()

        self.assertEqual(status["cache_engine"]["status"], "unavailable")
        self.assertEqual(status["database_manager"]["status"], "unavailable")
        self.assertEqual(status["throttle_manager"]["status"], "unavailable")
        self.assertEqual(status["security_manager"]["status"], "unavailable")

    def test_component_status_error(self):
        """Test component status when components have errors."""
        # Mock components that raise exceptions
        self.handler.proxy.cache_engine = Mock()
        self.handler.proxy.cache_engine.get_stats.side_effect = Exception("Cache error")

        status = self.handler._get_component_status()

        self.assertEqual(status["cache_engine"]["status"], "error")
        self.assertIn("Cache error", status["cache_engine"]["error"])

    def test_overall_status_determination(self):
        """Test overall status determination logic."""
        # All healthy
        components = {"comp1": {"status": "healthy"}, "comp2": {"status": "healthy"}}
        self.assertEqual(self.handler._determine_overall_status(components), "healthy")

        # One degraded
        components["comp1"]["status"] = "degraded"
        self.assertEqual(self.handler._determine_overall_status(components), "degraded")

        # One error
        components["comp1"]["status"] = "error"
        self.assertEqual(self.handler._determine_overall_status(components), "error")

        # One unavailable
        components = {"comp1": {"status": "healthy"}, "comp2": {"status": "unavailable"}}
        self.assertEqual(self.handler._determine_overall_status(components), "degraded")

    def test_cache_statistics_with_cache_engine(self):
        """Test cache statistics collection with cache engine."""
        # Mock cache engine with stats
        self.handler.proxy.cache_engine = Mock()
        self.handler.proxy.cache_engine.get_stats.return_value = {
            "cache_size": 150,
            "hits": 1000,
            "misses": 200,
            "sets": 300,
            "hit_rate": 0.83,
            "compressed": 75,
        }

        stats = self.handler._get_cache_statistics()

        self.assertEqual(stats["cache_backend"], "memory")
        self.assertEqual(stats["total_entries"], 150)
        self.assertEqual(stats["statistics"]["total_hits"], 1000)
        self.assertEqual(stats["statistics"]["hit_rate"], 0.83)

    def test_cache_statistics_without_cache_engine(self):
        """Test cache statistics collection without cache engine."""
        # No cache engine
        self.handler.proxy.cache_engine = None
        stats = self.handler._get_cache_statistics()

        self.assertEqual(stats["total_entries"], 0)
        self.assertEqual(stats["statistics"]["hit_rate"], 0.0)

    def test_domain_mapping_statistics(self):
        """Test domain mapping statistics collection."""
        # Mock monitoring manager
        self.handler.proxy.monitoring_manager = Mock()
        self.handler.proxy.monitoring_manager.get_upstream_stats.return_value = {
            "domains": {
                "example": {
                    "total_requests": 100,
                    "error_rate": 0.05,
                    "last_successful_request": "2025-09-16T14:25:00.000Z",
                }
            }
        }

        stats = self.handler._get_domain_mapping_statistics()

        self.assertIn("example", stats)
        self.assertEqual(stats["example"]["upstream"], "https://api.example.com")
        self.assertEqual(stats["example"]["ttl_seconds"], 3600)
        self.assertEqual(stats["example"]["status"], "healthy")
        self.assertEqual(stats["example"]["total_requests"], 100)

    @patch("json.loads")
    def test_config_validation_valid(self, mock_json_loads):
        """Test configuration validation with valid config."""
        # Mock request parsing
        mock_json_loads.return_value = {"configuration": {"cache": {"default_ttl_seconds": 7200}}}

        # Mock request body reading
        self.handler.rfile = Mock()
        self.handler.rfile.read.return_value = b'{"configuration": {}}'
        self.handler.headers = {"Content-Length": "20"}

        # Mock response sending
        self.handler._send_admin_response = Mock()

        self.handler._handle_admin_validate_config()

        # Verify response was sent
        self.handler._send_admin_response.assert_called_once()
        args = self.handler._send_admin_response.call_args[0]
        self.assertEqual(args[0], 200)  # Status code
        self.assertTrue(args[1]["valid"])  # Response should indicate valid

    def test_config_validation_empty_body(self):
        """Test configuration validation with empty body."""
        self.handler.headers = {"Content-Length": "0"}
        self.handler._send_admin_error = Mock()

        self.handler._handle_admin_validate_config()

        self.handler._send_admin_error.assert_called_once_with(400, "EMPTY_BODY", "Request body is required")

    def test_config_warnings_generation(self):
        """Test configuration warnings generation."""
        user_config = {"cache": {"default_ttl_seconds": 3600}}
        merged_config = {
            "cache": {"default_ttl_seconds": 3600, "database_path": ":memory:", "max_cache_response_size": 10485760},
            "server": {"host": "127.0.0.1", "request_timeout": 30},
        }

        warnings = self.handler._generate_config_warnings(user_config, merged_config)

        # Should warn about missing fields in existing sections
        warning_texts = " ".join(warnings)
        self.assertIn("cache.database_path", warning_texts)
        self.assertIn("cache.max_cache_response_size", warning_texts)
        self.assertIn("default value", warning_texts)
        # Note: server section warnings are not generated because the entire section is missing


if __name__ == "__main__":
    unittest.main()

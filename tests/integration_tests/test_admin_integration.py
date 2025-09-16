"""Integration tests for admin endpoints."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from reference_api_buddy.core.proxy import CachingProxy


class TestAdminEndpointsIntegration(unittest.TestCase):
    """Integration tests for admin endpoints with actual proxy server."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for the class."""
        cls.test_port = 18082
        cls.base_url = f"http://127.0.0.1:{cls.test_port}"

        # Create temporary database file
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.temp_db.close()

        cls.config = {
            "server": {"host": "127.0.0.1", "port": cls.test_port},
            "security": {"require_secure_key": False},
            "admin": {"enabled": True, "rate_limit_per_minute": 60, "log_access": True},  # High limit for testing
            "cache": {"database_path": cls.temp_db.name, "default_ttl_seconds": 3600},
            "domain_mappings": {
                "example": {"upstream": "https://api.example.com", "ttl_seconds": 1800},
                "test": {"upstream": "https://api.test.com"},
            },
        }

    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        if hasattr(cls, "proxy") and cls.proxy:
            cls.proxy.stop()

        # Clean up temporary database
        try:
            os.unlink(cls.temp_db.name)
        except OSError:
            pass

    def setUp(self):
        """Set up each test."""
        # Create and start proxy
        self.proxy = CachingProxy(self.config)

        # Start proxy in background thread
        self.proxy_thread = threading.Thread(target=self.proxy.start, kwargs={"blocking": True})
        self.proxy_thread.daemon = True
        self.proxy_thread.start()

        # Wait for server to start
        time.sleep(0.5)

        # Store reference for cleanup
        self.__class__.proxy = self.proxy

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, "proxy") and self.proxy:
            self.proxy.stop()
            time.sleep(0.1)

    def test_admin_config_endpoint(self):
        """Test GET /admin/config endpoint."""
        response = requests.get(f"{self.base_url}/admin/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("proxy_version", data)
        self.assertIn("security_enabled", data)
        self.assertIn("configuration", data)

        # Verify configuration content
        config = data["configuration"]
        self.assertEqual(config["admin"]["enabled"], True)
        self.assertEqual(config["cache"]["default_ttl_seconds"], 3600)
        self.assertIn("example", config["domain_mappings"])

    def test_admin_status_endpoint(self):
        """Test GET /admin/status endpoint."""
        response = requests.get(f"{self.base_url}/admin/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("status", data)
        self.assertIn("uptime_seconds", data)
        self.assertIn("components", data)
        self.assertIn("metrics", data)

        # Verify components
        components = data["components"]
        self.assertIn("cache_engine", components)
        self.assertIn("database_manager", components)
        self.assertIn("throttle_manager", components)
        self.assertIn("security_manager", components)

        # Status should be healthy or degraded (not error)
        self.assertIn(data["status"], ["healthy", "degraded"])

    def test_admin_domains_endpoint(self):
        """Test GET /admin/domains endpoint."""
        response = requests.get(f"{self.base_url}/admin/domains")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("domain_mappings", data)

        # Verify domain mappings
        domains = data["domain_mappings"]
        self.assertIn("example", domains)
        self.assertIn("test", domains)

        # Verify domain structure
        example_domain = domains["example"]
        self.assertEqual(example_domain["upstream"], "https://api.example.com")
        self.assertEqual(example_domain["ttl_seconds"], 1800)
        self.assertIn("status", example_domain)

    def test_admin_cache_endpoint(self):
        """Test GET /admin/cache endpoint."""
        response = requests.get(f"{self.base_url}/admin/cache")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("cache_backend", data)
        self.assertIn("database_path", data)
        self.assertIn("total_entries", data)
        self.assertIn("statistics", data)

        # Verify cache backend
        self.assertEqual(data["cache_backend"], "sqlite")

        # Verify statistics structure
        stats = data["statistics"]
        self.assertIn("hit_rate", stats)
        self.assertIn("total_hits", stats)
        self.assertIn("total_misses", stats)

    def test_admin_cache_domain_endpoint(self):
        """Test GET /admin/cache/{domain} endpoint."""
        response = requests.get(f"{self.base_url}/admin/cache/example")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("domain", data)
        self.assertIn("cache_entries", data)
        self.assertIn("total_size_bytes", data)
        self.assertIn("hit_rate", data)
        self.assertIn("entries", data)

        self.assertEqual(data["domain"], "example")

    def test_admin_cache_domain_not_found(self):
        """Test GET /admin/cache/{domain} with non-existent domain."""
        response = requests.get(f"{self.base_url}/admin/cache/nonexistent")

        self.assertEqual(response.status_code, 404)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "DOMAIN_NOT_FOUND")

    def test_admin_validate_config_endpoint(self):
        """Test POST /admin/validate-config endpoint."""
        test_config = {"configuration": {"cache": {"default_ttl_seconds": 7200}, "server": {"host": "192.168.1.1"}}}

        response = requests.post(
            f"{self.base_url}/admin/validate-config", json=test_config, headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify response structure
        self.assertIn("timestamp", data)
        self.assertIn("valid", data)
        self.assertIn("errors", data)
        self.assertIn("warnings", data)
        self.assertIn("merged_config", data)

        # Should be valid
        self.assertTrue(data["valid"])
        self.assertEqual(len(data["errors"]), 0)

        # Should have warnings for missing fields
        self.assertGreater(len(data["warnings"]), 0)

    def test_admin_validate_config_invalid(self):
        """Test POST /admin/validate-config with invalid config."""
        test_config = {
            "configuration": {
                "cache": {"default_ttl_seconds": -1},  # Invalid negative value
                "admin": {"enabled": "not_a_boolean"},  # Invalid type
            }
        }

        response = requests.post(
            f"{self.base_url}/admin/validate-config", json=test_config, headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()

        # Should be invalid with errors
        self.assertFalse(data["valid"])
        self.assertGreater(len(data["errors"]), 0)

    def test_admin_validate_config_empty_body(self):
        """Test POST /admin/validate-config with empty body."""
        response = requests.post(f"{self.base_url}/admin/validate-config")

        self.assertEqual(response.status_code, 400)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "EMPTY_BODY")

    def test_admin_validate_config_invalid_json(self):
        """Test POST /admin/validate-config with invalid JSON."""
        response = requests.post(
            f"{self.base_url}/admin/validate-config", data="invalid json{", headers={"Content-Type": "application/json"}
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "INVALID_JSON")

    def test_admin_health_endpoint(self):
        """Test GET /admin/health endpoint."""
        response = requests.get(f"{self.base_url}/admin/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("timestamp", data)
        self.assertEqual(data["status"], "healthy")

    def test_admin_endpoint_not_found(self):
        """Test accessing non-existent admin endpoint."""
        response = requests.get(f"{self.base_url}/admin/nonexistent")

        self.assertEqual(response.status_code, 404)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "ENDPOINT_NOT_FOUND")

    def test_admin_method_not_allowed(self):
        """Test using unsupported HTTP method on admin endpoint."""
        response = requests.put(f"{self.base_url}/admin/config")

        self.assertEqual(response.status_code, 405)
        data = response.json()

        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "METHOD_NOT_ALLOWED")

    def test_non_admin_request(self):
        """Test that non-admin requests still work normally."""
        # This should return a 404 or proxy response, not admin error
        response = requests.get(f"{self.base_url}/test/endpoint")

        # Should not be an admin error response
        if response.status_code == 404:
            # Normal 404, not admin JSON error
            self.assertNotEqual(response.headers.get("Content-Type"), "application/json")
        else:
            # Proxy response (might be error but not admin error)
            pass


class TestAdminEndpointsWithSecurity(unittest.TestCase):
    """Integration tests for admin endpoints with security enabled."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for the class."""
        cls.test_port = 18083
        cls.base_url = f"http://127.0.0.1:{cls.test_port}"

        cls.config = {
            "server": {"host": "127.0.0.1", "port": cls.test_port},
            "security": {"require_secure_key": True},
            "admin": {"enabled": True, "rate_limit_per_minute": 60, "log_access": True},
            "cache": {"database_path": ":memory:"},
            "domain_mappings": {"example": {"upstream": "https://api.example.com"}},
        }

    def setUp(self):
        """Set up each test."""
        # Create and start proxy
        self.proxy = CachingProxy(self.config)
        self.secure_key = self.proxy.get_secure_key()

        # Start proxy in background thread
        self.proxy_thread = threading.Thread(target=self.proxy.start, kwargs={"blocking": True})
        self.proxy_thread.daemon = True
        self.proxy_thread.start()

        # Wait for server to start
        time.sleep(0.5)

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, "proxy") and self.proxy:
            self.proxy.stop()
            time.sleep(0.1)

    def test_admin_endpoint_with_valid_key(self):
        """Test admin endpoint access with valid secure key."""
        response = requests.get(f"{self.base_url}/{self.secure_key}/admin/config")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("configuration", data)
        self.assertTrue(data["security_enabled"])

    def test_admin_endpoint_without_key(self):
        """Test admin endpoint access without secure key."""
        response = requests.get(f"{self.base_url}/admin/config")

        # Should be unauthorized
        self.assertEqual(response.status_code, 401)

    def test_admin_endpoint_with_invalid_key(self):
        """Test admin endpoint access with invalid secure key."""
        response = requests.get(f"{self.base_url}/invalid_key/admin/config")

        # Should be unauthorized
        self.assertEqual(response.status_code, 401)

    def test_admin_validate_config_with_security(self):
        """Test POST endpoint with security enabled."""
        test_config = {"configuration": {"cache": {"default_ttl_seconds": 3600}}}

        response = requests.post(
            f"{self.base_url}/{self.secure_key}/admin/validate-config",
            json=test_config,
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["valid"])


class TestAdminRateLimiting(unittest.TestCase):
    """Integration tests for admin endpoint rate limiting."""

    def setUp(self):
        """Set up each test."""
        self.test_port = 18084
        self.base_url = f"http://127.0.0.1:{self.test_port}"

        self.config = {
            "server": {"host": "127.0.0.1", "port": self.test_port},
            "security": {"require_secure_key": False},
            "admin": {"enabled": True, "rate_limit_per_minute": 3, "log_access": True},  # Low limit for testing
            "cache": {"database_path": ":memory:"},
            "domain_mappings": {},
        }

        # Create and start proxy
        self.proxy = CachingProxy(self.config)

        # Start proxy in background thread
        self.proxy_thread = threading.Thread(target=self.proxy.start, kwargs={"blocking": True})
        self.proxy_thread.daemon = True
        self.proxy_thread.start()

        # Wait for server to start
        time.sleep(0.5)

    def tearDown(self):
        """Clean up after each test."""
        if hasattr(self, "proxy") and self.proxy:
            self.proxy.stop()
            time.sleep(0.1)

    def test_rate_limiting_enforcement(self):
        """Test that rate limiting is enforced on admin endpoints."""
        # Make requests up to the limit
        for i in range(3):
            response = requests.get(f"{self.base_url}/admin/status")
            self.assertEqual(response.status_code, 200)

        # Next request should be rate limited
        response = requests.get(f"{self.base_url}/admin/status")
        self.assertEqual(response.status_code, 429)

        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "RATE_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()

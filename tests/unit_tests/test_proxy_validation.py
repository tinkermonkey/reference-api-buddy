import os
import sys

# Add the project root to the path to import modules
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import base64
import secrets

import pytest

from reference_api_buddy.core.proxy import CachingProxy, SecurityError
from reference_api_buddy.security.manager import SecurityManager


def make_key():
    key_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key_bytes).decode("ascii").rstrip("=")


def test_validate_request_success_path():
    key = make_key()
    config = {"security": {"require_secure_key": True, "secure_key": key}}
    proxy = CachingProxy(config)
    path = f"/{key}/domain.com/api"
    headers = {}
    query_params = {}
    out_key, sanitized = proxy.validate_request(path, headers, query_params)
    assert out_key == key
    assert sanitized == "/domain.com/api"


def test_validate_request_success_query():
    key = make_key()
    config = {"security": {"require_secure_key": True, "secure_key": key}}
    proxy = CachingProxy(config)
    path = "/domain.com/api"
    headers = {}
    query_params = {"key": key}
    out_key, sanitized = proxy.validate_request(path, headers, query_params)
    assert out_key == key
    assert sanitized == "/domain.com/api"


def test_validate_request_success_header():
    key = make_key()
    config = {"security": {"require_secure_key": True, "secure_key": key}}
    proxy = CachingProxy(config)
    path = "/domain.com/api"
    headers = {"X-API-Buddy-Key": key}
    query_params = {}
    out_key, sanitized = proxy.validate_request(path, headers, query_params)
    assert out_key == key
    assert sanitized == "/domain.com/api"


def test_validate_request_invalid_key():
    key = make_key()
    config = {"security": {"require_secure_key": True, "secure_key": key}}
    proxy = CachingProxy(config)
    path = "/domain.com/api"
    headers = {"X-API-Buddy-Key": "wrong"}
    query_params = {}
    with pytest.raises(SecurityError):
        proxy.validate_request(path, headers, query_params)


def test_validate_request_missing_key():
    key = make_key()
    config = {"security": {"require_secure_key": True, "secure_key": key}}
    proxy = CachingProxy(config)
    path = "/domain.com/api"
    headers = {}
    query_params = {}
    with pytest.raises(SecurityError):
        proxy.validate_request(path, headers, query_params)


def test_validate_request_no_key_required():
    config = {"security": {"require_secure_key": False}}
    proxy = CachingProxy(config)
    path = "/domain.com/api"
    headers = {}
    query_params = {}
    out_key, sanitized = proxy.validate_request(path, headers, query_params)
    assert out_key is None
    assert sanitized == "/domain.com/api"


def test_sanitize_path_removes_null_and_nonascii():
    config = {"security": {"require_secure_key": False}}
    proxy = CachingProxy(config)
    dirty = "/api/\x00\x01\x02test//path"
    clean = proxy._sanitize_path(dirty)
    assert clean == "/api/test/path"


def test_log_security_event_prints(monkeypatch):
    config = {"security": {"log_security_events": True}}
    proxy = CachingProxy(config)
    events = []

    def fake_info(msg):
        events.append(msg)

    monkeypatch.setattr(proxy.logger, "info", fake_info)
    proxy._log_security_event("test", {"foo": "bar"})
    assert events and "[SECURITY]" in events[0]

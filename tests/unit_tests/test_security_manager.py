import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import secrets

import pytest

from reference_api_buddy.security.manager import SecurityManager


def test_generate_secure_key_length_and_format():
    sm = SecurityManager({})
    key = sm.generate_secure_key()
    # Should be base64-url, 43-44 chars for 32 bytes
    assert 43 <= len(key) <= 44
    # Should decode to 32 bytes
    key_bytes = base64.urlsafe_b64decode(key + "==")
    assert len(key_bytes) == 32


def test_validate_secure_key_success_and_failure():
    sm = SecurityManager({})
    key = sm.secure_key
    assert sm.validate_secure_key(key)
    assert not sm.validate_secure_key("wrongkey")
    assert not sm.validate_secure_key("")
    assert not sm.validate_secure_key(None)


def test_extract_from_path():
    sm = SecurityManager({})
    key = sm.secure_key
    path = f"/{key}/domain.com/api"
    extracted, sanitized = sm._extract_from_path(path)
    assert extracted == key
    assert sanitized == "/domain.com/api"

    # Should not extract if not enough segments
    extracted, sanitized = sm._extract_from_path("/notakey")
    assert extracted is None
    assert sanitized == "/notakey"


def test_extract_from_query():
    sm = SecurityManager({})
    key = sm.secure_key
    query_params = {"key": key}
    extracted, _ = sm._extract_from_query("/api", query_params)
    assert extracted == key
    # No key present
    extracted, _ = sm._extract_from_query("/api", {})
    assert extracted is None


def test_extract_from_header():
    sm = SecurityManager({})
    key = sm.secure_key
    headers = {"X-API-Buddy-Key": key}
    extracted, _ = sm._extract_from_header("/api", headers)
    assert extracted == key
    # Authorization Bearer
    headers = {"Authorization": f"Bearer {key}"}
    extracted, _ = sm._extract_from_header("/api", headers)
    assert extracted == key
    # No key present
    headers = {}
    extracted, _ = sm._extract_from_header("/api", headers)
    assert extracted is None


def test_extract_secure_key_priority():
    sm = SecurityManager({})
    key = sm.secure_key
    # Path takes priority
    path = f"/{key}/domain.com/api"
    headers = {"X-API-Buddy-Key": "wrong"}
    query_params = {"key": "wrong"}
    extracted, sanitized = sm.extract_secure_key(path, headers, query_params)
    assert extracted == key
    assert sanitized == "/domain.com/api"
    # Query param if not in path
    path = "/domain.com/api"
    headers = {}
    query_params = {"key": key}
    extracted, sanitized = sm.extract_secure_key(path, headers, query_params)
    assert extracted == key
    assert sanitized == "/domain.com/api"
    # Header if not in path or query
    headers = {"X-API-Buddy-Key": key}
    query_params = {}
    extracted, sanitized = sm.extract_secure_key(path, headers, query_params)
    assert extracted == key
    assert sanitized == "/domain.com/api"
    # None if not found
    headers = {}
    query_params = {}
    extracted, sanitized = sm.extract_secure_key(path, headers, query_params)
    assert extracted is None
    assert sanitized == "/domain.com/api"

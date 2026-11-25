import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

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


def test_extract_secure_key_prefers_the_proxy_key():
    sm = SecurityManager({})
    key = sm.secure_key
    domain = "d" * 40  # a first path segment that looks like a path-prefix key
    upstream_key = "AIza" + "u" * 35  # an upstream API's own ?key=
    path = f"/{domain}/api?key={upstream_key}"
    query_params = {"key": [upstream_key]}
    # A valid header or Bearer key wins over non-matching path and query candidates
    for headers in ({"X-API-Buddy-Key": key}, {"Authorization": f"Bearer {key}"}):
        extracted, sanitized = sm.extract_secure_key(path, headers, query_params)
        assert extracted == key
        assert sanitized == path
    # A valid query key wins over a non-matching path candidate and keeps the path segment
    extracted, sanitized = sm.extract_secure_key(f"/{domain}/api?key={key}", {}, {"key": [key]})
    assert extracted == key
    assert sanitized == f"/{domain}/api"
    # A valid Bearer key wins over a wrong X-API-Buddy-Key
    headers = {"X-API-Buddy-Key": "wrong", "Authorization": f"Bearer {key}"}
    extracted, sanitized = sm.extract_secure_key("/domain.com/api", headers, {})
    assert extracted == key


def test_extract_secure_key_falls_back_to_first_candidate():
    sm = SecurityManager({})
    domain = "d" * 40
    headers = {"X-API-Buddy-Key": "wrong-header"}
    extracted, sanitized = sm.extract_secure_key(f"/{domain}/api?key=wrong-query", headers, {"key": ["wrong-query"]})
    assert extracted == domain
    assert sanitized == "/api?key=wrong-query"
    extracted, sanitized = sm.extract_secure_key("/domain.com/api?key=wrong-query", headers, {"key": ["wrong-query"]})
    assert extracted == "wrong-query"
    assert sanitized == "/domain.com/api"


def test_extract_from_query_accepts_parse_qs_lists():
    sm = SecurityManager({})
    key = sm.secure_key
    path = f"/domain.com/api?a=1&key={key}&b=2"
    extracted, sanitized = sm._extract_from_query(path, {"key": [key], "a": ["1"], "b": ["2"]})
    assert extracted == key
    assert sanitized == "/domain.com/api?a=1&b=2"
    extracted, sanitized = sm._extract_from_query("/api", {"key": []})
    assert extracted is None
    assert sanitized == "/api"


def test_extract_secure_key_strips_query_key():
    sm = SecurityManager({})
    key = sm.secure_key
    extracted, sanitized = sm.extract_secure_key(f"/domain.com/api?key={key}", {}, {"key": [key]})
    assert extracted == key
    assert sanitized == "/domain.com/api"


def test_remove_query_param_keeps_other_parameters_verbatim():
    remove = SecurityManager._remove_query_param
    assert remove("/api?key=abc", "key") == "/api"
    assert remove("/api?q=a%20b&key=abc&key=def&r=", "key") == "/api?q=a%20b&r="
    assert remove("/api?keys=1&monkey=2", "key") == "/api?keys=1&monkey=2"
    assert remove("/api", "key") == "/api"
    assert remove("/api?key=up&key=mine&q=1", "key", "mine") == "/api?key=up&q=1"
    assert remove("/api?key=a%2Bb", "key", "a+b") == "/api"


def test_extract_from_query_prefers_the_proxy_key_among_several():
    sm = SecurityManager({})
    key = sm.secure_key
    for path in (f"/api?key=upstream&key={key}", f"/api?key={key}&key=upstream"):
        extracted, sanitized = sm._extract_from_query(path, {"key": ["upstream", key]})
        assert extracted == key
        assert sanitized == "/api?key=upstream"


def test_is_proxy_authorization():
    sm = SecurityManager({})
    key = sm.secure_key
    assert sm.is_proxy_authorization(f"Bearer {key}")
    assert sm.is_proxy_authorization(f"bearer {key}")
    assert not sm.is_proxy_authorization("Bearer upstream-token")
    assert not sm.is_proxy_authorization(f"Basic {key}")
    assert not sm.is_proxy_authorization(None)

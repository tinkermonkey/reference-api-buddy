"""Regression tests for secure-key placement, run through a live CachingProxy.

With `security.require_secure_key` on, a client may send the proxy key in four places:
the X-API-Buddy-Key header, an `Authorization: Bearer` header, a path prefix
(`/<key>/<domain>/<path>`) or a `key=` query parameter. Every placement must reach the
upstream API, and the proxy key must never appear in the upstream request.
"""

import base64
import secrets
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from reference_api_buddy import CachingProxy  # noqa: E402

# A 40-character domain key, the length of a path-prefix proxy key
LONG_DOMAIN = "a" * 40
UPSTREAM_API_KEY = "AIzaSyUpstreamOwnApiKey-0123456789abcdef"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


class RecordingUpstreamHandler(BaseHTTPRequestHandler):
    """Upstream that records every request it receives and echoes the path."""

    requests = []
    lock = threading.Lock()

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        with self.lock:
            self.requests.append({"path": self.path, "headers": dict(self.headers.items())})
        body = f"ok {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _get(url, headers=None):
    """Return (status, body) without raising on HTTP error statuses."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def upstream():
    RecordingUpstreamHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), RecordingUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def make_proxy(upstream):
    proxies = []
    temp_dir = tempfile.TemporaryDirectory()

    def _make(require_secure_key=True):
        key = _make_key()
        port = _free_port()
        config = {
            "domain_mappings": {"up": {"upstream": upstream}, LONG_DOMAIN: {"upstream": upstream}},
            "server": {"host": "127.0.0.1", "port": port},
            "cache": {"database_path": str(Path(temp_dir.name) / f"cache_{port}.db")},
            "security": {"require_secure_key": require_secure_key, "secure_key": key},
            "logging": {"level": "WARNING"},
        }
        proxy = CachingProxy(config)
        proxy.start(blocking=False)
        proxies.append(proxy)
        return key, f"http://127.0.0.1:{port}"

    yield _make
    for proxy in proxies:
        proxy.stop()
    temp_dir.cleanup()


def _upstream_requests():
    with RecordingUpstreamHandler.lock:
        return list(RecordingUpstreamHandler.requests)


def _assert_key_not_forwarded(key):
    seen = _upstream_requests()
    assert seen, "the upstream received no request"
    for request in seen:
        assert key not in request["path"]
        for name, value in request["headers"].items():
            assert key not in value, f"proxy key forwarded upstream in header {name}"
        assert "x-api-buddy-key" not in {name.lower() for name in request["headers"]}


class TestSecureKeyPlacements:
    def test_header_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x", headers={"X-API-Buddy-Key": key})
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    def test_bearer_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x", headers={"Authorization": f"Bearer {key}"})
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)
        assert "authorization" not in {name.lower() for name in _upstream_requests()[0]["headers"]}

    def test_path_prefix_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/{key}/up/x")
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    def test_query_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x?key={key}")
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    def test_query_key_keeps_other_parameters(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x?a=1&key={key}&b=two%20words")
        assert (status, body) == (200, b"ok /x?a=1&b=two%20words")
        _assert_key_not_forwarded(key)

    def test_missing_key_is_rejected(self, make_proxy):
        _, base = make_proxy()
        status, _ = _get(f"{base}/up/x")
        assert status == 401
        assert _upstream_requests() == []

    def test_wrong_key_is_rejected(self, make_proxy):
        _, base = make_proxy()
        for url, headers in [
            (f"{base}/up/x", {"X-API-Buddy-Key": _make_key()}),
            (f"{base}/up/x", {"Authorization": f"Bearer {_make_key()}"}),
            (f"{base}/{_make_key()}/up/x", {}),
            (f"{base}/up/x?key={_make_key()}", {}),
        ]:
            status, _ = _get(url, headers=headers)
            assert status == 401, url
        assert _upstream_requests() == []


class TestSecureKeyNotInCacheKey:
    def test_every_placement_shares_one_cache_entry(self, make_proxy):
        key, base = make_proxy()
        placements = [
            (f"{base}/up/x?q=1", {"X-API-Buddy-Key": key}),
            (f"{base}/up/x?q=1", {"Authorization": f"Bearer {key}"}),
            (f"{base}/{key}/up/x?q=1", {}),
            (f"{base}/up/x?q=1&key={key}", {}),
        ]
        for url, headers in placements:
            status, body = _get(url, headers=headers)
            assert (status, body) == (200, b"ok /x?q=1"), url
        # The first request fills the cache; the rest are served from it
        assert len(_upstream_requests()) == 1


class TestUpstreamCredentialsPassThrough:
    def test_upstream_bearer_token_is_forwarded(self, make_proxy):
        key, base = make_proxy()
        status, _ = _get(
            f"{base}/up/x",
            headers={"X-API-Buddy-Key": key, "Authorization": "Bearer upstream-token"},
        )
        assert status == 200
        assert _upstream_requests()[0]["headers"].get("Authorization") == "Bearer upstream-token"
        _assert_key_not_forwarded(key)

    def test_upstream_key_parameter_is_forwarded_when_security_is_off(self, make_proxy):
        _, base = make_proxy(require_secure_key=False)
        status, body = _get(f"{base}/up/x?key=upstream-api-key")
        assert (status, body) == (200, b"ok /x?key=upstream-api-key")

    def test_proxy_key_is_still_stripped_when_security_is_off(self, make_proxy):
        key, base = make_proxy(require_secure_key=False)
        for url, headers in [
            (f"{base}/up/a", {"X-API-Buddy-Key": key}),
            (f"{base}/up/b", {"Authorization": f"Bearer {key}"}),
            (f"{base}/{key}/up/c", {}),
            (f"{base}/up/d?key={key}", {}),
        ]:
            status, _ = _get(url, headers=headers)
            assert status == 200, url
        assert [r["path"] for r in _upstream_requests()] == ["/a", "/b", "/c", "/d"]
        _assert_key_not_forwarded(key)


class TestProxyKeyWinsOverOtherCandidates:
    """A valid header or Bearer key must not be shadowed by a path or query value that is not the proxy key."""

    @pytest.mark.parametrize("auth", ["header", "bearer"])
    def test_header_key_with_upstream_query_key(self, make_proxy, auth):
        key, base = make_proxy()
        headers = {"X-API-Buddy-Key": key} if auth == "header" else {"Authorization": f"Bearer {key}"}
        status, body = _get(f"{base}/up/x?key={UPSTREAM_API_KEY}&q=1", headers=headers)
        assert (status, body) == (200, f"ok /x?key={UPSTREAM_API_KEY}&q=1".encode())
        _assert_key_not_forwarded(key)

    @pytest.mark.parametrize("auth", ["header", "bearer"])
    def test_header_key_with_long_domain(self, make_proxy, auth):
        key, base = make_proxy()
        headers = {"X-API-Buddy-Key": key} if auth == "header" else {"Authorization": f"Bearer {key}"}
        status, body = _get(f"{base}/{LONG_DOMAIN}/x", headers=headers)
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    @pytest.mark.parametrize("auth", ["header", "bearer"])
    def test_header_key_with_long_domain_and_upstream_query_key(self, make_proxy, auth):
        key, base = make_proxy()
        headers = {"X-API-Buddy-Key": key} if auth == "header" else {"Authorization": f"Bearer {key}"}
        status, body = _get(f"{base}/{LONG_DOMAIN}/x?key={UPSTREAM_API_KEY}", headers=headers)
        assert (status, body) == (200, f"ok /x?key={UPSTREAM_API_KEY}".encode())
        _assert_key_not_forwarded(key)

    def test_query_key_with_long_domain(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/{LONG_DOMAIN}/x?key={key}")
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    def test_proxy_query_key_after_upstream_query_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x?key={UPSTREAM_API_KEY}&key={key}")
        assert (status, body) == (200, f"ok /x?key={UPSTREAM_API_KEY}".encode())
        _assert_key_not_forwarded(key)

    def test_proxy_query_key_before_upstream_query_key(self, make_proxy):
        key, base = make_proxy()
        status, body = _get(f"{base}/up/x?key={key}&key={UPSTREAM_API_KEY}")
        assert (status, body) == (200, f"ok /x?key={UPSTREAM_API_KEY}".encode())
        _assert_key_not_forwarded(key)

    @pytest.mark.parametrize("auth", ["path", "header", "bearer"])
    def test_key_repeated_in_query_is_not_forwarded(self, make_proxy, auth):
        key, base = make_proxy()
        url = f"{base}/{key}/up/x?key={key}" if auth == "path" else f"{base}/up/x?key={key}"
        headers = {"path": {}, "header": {"X-API-Buddy-Key": key}, "bearer": {"Authorization": f"Bearer {key}"}}[auth]
        status, body = _get(url, headers=headers)
        assert (status, body) == (200, b"ok /x")
        _assert_key_not_forwarded(key)

    def test_wrong_header_key_with_upstream_candidates_is_rejected(self, make_proxy):
        _, base = make_proxy()
        for url in [f"{base}/up/x?key={UPSTREAM_API_KEY}", f"{base}/{LONG_DOMAIN}/x"]:
            status, _ = _get(url, headers={"X-API-Buddy-Key": _make_key()})
            assert status == 401, url
        assert _upstream_requests() == []

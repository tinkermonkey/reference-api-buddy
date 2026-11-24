"""Security manager implementation for cryptographic operations."""

import base64
import hmac
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote_plus

# Where a client may put the proxy's own key. None of these may reach the upstream API.
PROXY_KEY_HEADER = "X-API-Buddy-Key"
PROXY_KEY_QUERY_PARAM = "key"


class SecurityManager:
    """Handles cryptographic key generation, extraction, and validation.

    Provides secure key generation, constant-time validation, and key extraction
    from various request locations (path, query parameters, headers).

    Example:
        >>> manager = SecurityManager({"require_secure_key": True})
        >>> key = manager.generate_secure_key()
        >>> is_valid = manager.validate_request(key)
        >>> print(f"Key valid: {is_valid}")
    """

    def __init__(self, security_config: Dict[str, Any]) -> None:
        """Initialize SecurityManager with security configuration.

        Args:
            security_config: Configuration dictionary with security settings
        """
        self.config = security_config or {}
        self.security_enabled = self.config.get("require_secure_key", False)
        self.secure_key = self.config.get("secure_key") or self.generate_secure_key()

    def generate_secure_key(self) -> str:
        """Generate a cryptographically secure key.

        Returns:
            A URL-safe base64-encoded 256-bit random key

        Example:
            >>> manager = SecurityManager({})
            >>> key = manager.generate_secure_key()
            >>> print(f"Generated key: {key}")
        """
        key_bytes = secrets.token_bytes(32)
        return base64.urlsafe_b64encode(key_bytes).decode("ascii").rstrip("=")

    def validate_request(self, provided_key: Optional[str]) -> bool:
        """Validate the provided key with constant-time comparison.

        Args:
            provided_key: The key provided in the request, may be None

        Returns:
            True if key is valid or security is disabled, False otherwise

        Note:
            Uses constant-time comparison to prevent timing attacks.
        """
        if not self.security_enabled:
            return True
        if not self.secure_key or not provided_key:
            return False

        return hmac.compare_digest(self.secure_key.encode("utf-8"), provided_key.encode("utf-8"))

    def validate_secure_key(self, provided_key: Optional[str]) -> bool:
        """Validate the provided key using constant-time comparison.

        Args:
            provided_key: The key to validate

        Returns:
            True if the key matches the secure key, False otherwise

        Note:
            This is an alias for validate_request but with stricter checking -
            it doesn't return True when security is disabled.
        """
        if not provided_key or not self.secure_key:
            return False
        return hmac.compare_digest(self.secure_key.encode("utf-8"), provided_key.encode("utf-8"))

    def extract_secure_key(
        self, request_path: str, headers: Dict[str, str], query_params: Dict[str, str]
    ) -> Tuple[Optional[str], str]:
        """Extract secure key from path, query, or headers.

        Every place a key may appear is checked: the path prefix, the ``key`` query
        parameter, the X-API-Buddy-Key header and an ``Authorization: Bearer`` header.
        A candidate in the path or query is not always the proxy key (a long first path
        segment may be a domain, and ``key=`` may be the upstream API's own key), so the
        first candidate that matches the proxy key wins. If none matches, the first
        candidate found is returned so the caller can reject it.

        Args:
            request_path: The HTTP request path
            headers: Dictionary of HTTP headers
            query_params: Dictionary of query parameters

        Returns:
            Tuple of (extracted_key, sanitized_path) where extracted_key is None
            if no key found, and sanitized_path is the request path with that key removed

        Example:
            >>> manager = SecurityManager({})
            >>> key, path = manager.extract_secure_key("/abc123/api/test", {}, {})
            >>> print(f"Key: {key}, Path: {path}")
        """
        candidates = [
            self._extract_from_path(request_path),
            self._extract_from_query(request_path, query_params),
            (headers.get(PROXY_KEY_HEADER), request_path),
            (self._bearer_token(headers.get("Authorization")), request_path),
        ]
        candidates = [(key, path) for key, path in candidates if key]
        for key, path in candidates:
            if self.validate_secure_key(key):
                return key, path
        if candidates:
            return candidates[0]
        return None, request_path

    def _extract_from_path(self, request_path: str) -> Tuple[Optional[str], str]:
        """Extract key from path prefix: /{key}/domain.com/path.

        Args:
            request_path: The request path to extract key from

        Returns:
            Tuple of (key, sanitized_path) where key is None if not found
        """
        if not request_path or not request_path.startswith("/"):
            return None, request_path
        parts = request_path.lstrip("/").split("/", 1)
        if len(parts) < 2:
            return None, request_path
        key_candidate, rest = parts[0], "/" + parts[1]
        # Heuristic: base64url keys are usually 43-44 chars (32 bytes)
        if 32 <= len(key_candidate) <= 44:
            return key_candidate, rest
        return None, request_path

    def _extract_from_query(self, request_path: str, query_params: Dict[str, Any]) -> Tuple[Optional[str], str]:
        """Extract key from query string (?key=...).

        Args:
            request_path: The request path, including its query string
            query_params: Query parameters, either single values or the lists
                that ``urllib.parse.parse_qs`` returns

        Returns:
            Tuple of (key, sanitized_path) where key is None if not found and
            sanitized_path is the request path without the ``key`` parameter
        """
        key = query_params.get(PROXY_KEY_QUERY_PARAM)
        if isinstance(key, (list, tuple)):
            key = key[0] if key else None
        if not key:
            return None, request_path
        return key, self._remove_query_param(request_path, PROXY_KEY_QUERY_PARAM)

    @staticmethod
    def _remove_query_param(request_path: str, name: str) -> str:
        """Remove every occurrence of one query parameter, leaving the rest byte-for-byte.

        Args:
            request_path: The request path, including its query string
            name: The parameter name to remove

        Returns:
            The request path without that parameter (and without a trailing ``?``)
        """
        path, _, query = request_path.partition("?")
        if not query:
            return request_path
        kept = [part for part in query.split("&") if part and unquote_plus(part.split("=", 1)[0]) != name]
        return f"{path}?{'&'.join(kept)}" if kept else path

    def _extract_from_header(self, request_path: str, headers: Dict[str, str]) -> Tuple[Optional[str], str]:
        """Extract key from headers (X-API-Buddy-Key or Authorization: Bearer ...).

        Args:
            request_path: The request path (returned unchanged)
            headers: Dictionary of HTTP headers

        Returns:
            Tuple of (key, request_path) where key is None if not found
        """
        key = headers.get(PROXY_KEY_HEADER) or self._bearer_token(headers.get("Authorization"))
        return key, request_path

    @staticmethod
    def _bearer_token(authorization: Optional[str]) -> Optional[str]:
        """Return the token from an ``Authorization: Bearer <token>`` value, or None."""
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip() or None
        return None

    def is_proxy_authorization(self, authorization: Optional[str]) -> bool:
        """Tell whether an Authorization header carries this proxy's key as a Bearer token.

        Args:
            authorization: The Authorization header value, may be None

        Returns:
            True only for ``Bearer <proxy key>``; any other credential belongs to the upstream API
        """
        return self.validate_secure_key(self._bearer_token(authorization))

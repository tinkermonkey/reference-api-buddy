"""Security manager implementation for cryptographic operations."""

import base64
import hmac
import secrets
from typing import Any, Dict, Optional, Tuple


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

        Args:
            request_path: The HTTP request path
            headers: Dictionary of HTTP headers
            query_params: Dictionary of query parameters

        Returns:
            Tuple of (extracted_key, sanitized_path) where extracted_key is None
            if no key found, and sanitized_path is the request path with key removed

        Example:
            >>> manager = SecurityManager({})
            >>> key, path = manager.extract_secure_key("/abc123/api/test", {}, {})
            >>> print(f"Key: {key}, Path: {path}")
        """
        key, new_path = self._extract_from_path(request_path)
        if key:
            return key, new_path
        key, _ = self._extract_from_query(request_path, query_params)
        if key:
            return key, request_path
        key, _ = self._extract_from_header(request_path, headers)
        if key:
            return key, request_path
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

    def _extract_from_query(self, request_path: str, query_params: Dict[str, str]) -> Tuple[Optional[str], str]:
        """Extract key from query string (?key=...).

        Args:
            request_path: The request path (returned unchanged)
            query_params: Dictionary of query parameters

        Returns:
            Tuple of (key, request_path) where key is None if not found
        """
        key = query_params.get("key")
        return (key, request_path) if key else (None, request_path)

    def _extract_from_header(self, request_path: str, headers: Dict[str, str]) -> Tuple[Optional[str], str]:
        """Extract key from headers (X-API-Buddy-Key or Authorization: Bearer ...).

        Args:
            request_path: The request path (returned unchanged)
            headers: Dictionary of HTTP headers

        Returns:
            Tuple of (key, request_path) where key is None if not found
        """
        key = headers.get("X-API-Buddy-Key")
        if key:
            return key, request_path
        auth = headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth[7:].strip(), request_path
        return None, request_path

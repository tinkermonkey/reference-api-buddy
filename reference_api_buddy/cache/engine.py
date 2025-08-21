"""Cache engine implementation for Reference API Buddy."""

import hashlib
import json
import threading
import time
import zlib
from typing import Any, Dict, Optional

from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.database.models import CachedResponse


class CacheEngine:
    """Core caching logic with key generation, method-specific caching, TTL,
    and statistics.

    Provides thread-safe caching operations with automatic compression, TTL management,
    and cache size limits. Supports both GET and POST request caching with
    content-aware key generation.

    Example:
        >>> db_manager = DatabaseManager(":memory:")
        >>> cache = CacheEngine(db_manager, max_response_size=1024*1024)
        >>> cache.set("test_key", response_object)
        >>> cached = cache.get("test_key")
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        config: dict = None,
        max_response_size: int = 10485760,
        compression_threshold: int = 1024,
        max_cache_entries: int = 1000,
    ) -> None:
        """Initialize cache engine with database manager and configuration.

        Args:
            db_manager: Database manager for persistent storage
            config: Full configuration dictionary for TTL management
            max_response_size: Maximum response size to cache (bytes)
            compression_threshold: Minimum size for compression (bytes)
            max_cache_entries: Maximum number of cache entries
        """
        self.db_manager = db_manager
        self.max_response_size = max_response_size
        self.compression_threshold = compression_threshold
        self.max_cache_entries = max_cache_entries
        self._lock = threading.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "sets": 0,
            "expired": 0,
            "compressed": 0,
            "decompressed": 0,
        }

        # Initialize TTL manager if config is provided
        if config:
            from reference_api_buddy.core.ttl_manager import TTLManager

            self._ttl_manager = TTLManager(config)
        else:
            self._ttl_manager = None

        self._cleanup_expired_entries()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent cache keys.

        Args:
            url: The URL to normalize

        Returns:
            Normalized URL with sorted query parameters and consistent path handling
        """
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        query = urlencode(sorted(parse_qsl(parsed.query)))
        # Treat all trailing slashes as insignificant except for root
        path = parsed.path
        if path != "/":
            path = path.rstrip("/")
            if not path:
                path = "/"
        normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path, query=query)
        # If the normalized path is empty, set to '/'
        if not normalized.path:
            normalized = normalized._replace(path="/")
        return urlunparse(normalized)

    def _normalize_request_body(self, body: bytes, content_type: Optional[str]) -> str:
        """Normalize request body for consistent cache key generation.

        Args:
            body: Request body bytes
            content_type: Content-Type header value

        Returns:
            Normalized string representation of the body
        """
        if not body:
            return ""
        if content_type and "application/json" in content_type:
            try:
                obj = json.loads(body.decode("utf-8"))
                return json.dumps(obj, sort_keys=True, separators=(",", ":"))
            except Exception:
                pass
        # Fallback: hash the body
        return hashlib.sha256(body).hexdigest()

    def generate_cache_key(
        self, method: str, url: str, body: Optional[bytes] = None, content_type: Optional[str] = None
    ) -> str:
        """Generate a cache key based on method, URL, and body.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            body: Request body (for POST requests)
            content_type: Content-Type header value

        Returns:
            SHA256 hash as hexadecimal string for use as cache key

        Example:
            >>> cache = CacheEngine(db_manager)
            >>> key = cache.generate_cache_key("GET", "https://api.example.com/data")
            >>> print(f"Cache key: {key}")
        """
        normalized_url = self._normalize_url(url)
        key_components = [method.upper(), normalized_url]
        if method.upper() == "POST" and body:
            normalized_body = self._normalize_request_body(body, content_type)
            key_components.append(normalized_body)
        key_string = ":".join(key_components)
        return hashlib.sha256(key_string.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> Optional[CachedResponse]:
        """Retrieve a cached response if not expired and decompress if needed.

        Args:
            cache_key: The cache key to retrieve

        Returns:
            CachedResponse object if found and not expired, None otherwise

        Example:
            >>> cached = cache.get("some_cache_key")
            >>> if cached:
            ...     print(f"Cache hit! Status: {cached.status_code}")
        """
        with self._lock:  # Protect database operations from concurrent access
            rows = self.db_manager.execute_query(
                "SELECT response_data, headers, status_code, created_at, "
                "ttl_seconds, access_count, last_accessed "
                "FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            )
            if not rows:
                self._stats["misses"] += 1
                return None
            (
                data,
                headers,
                status_code,
                created_at,
                ttl_seconds,
                access_count,
                last_accessed,
            ) = rows[0]
            now = int(time.time())
            # created_at may be a string or a datetime.datetime
            if hasattr(created_at, "timestamp"):
                created_ts = int(created_at.timestamp())
            elif isinstance(created_at, str):
                try:
                    created_ts = int(time.mktime(time.strptime(created_at, "%Y-%m-%d %H:%M:%S")))
                except Exception:
                    from datetime import datetime

                    created_ts = int(datetime.fromisoformat(created_at).timestamp())
            else:
                created_ts = int(created_at)
            if now > created_ts + ttl_seconds:
                self.delete(cache_key)
                self._stats["expired"] += 1
                return None
            # Decompress if needed
            if data and data[:2] == b"\x78\x9c":  # zlib magic header
                try:
                    data = zlib.decompress(data)
                    self._stats["decompressed"] += 1
                except Exception:
                    pass
            # Update access count and last_accessed
            self.db_manager.execute_update(
                "UPDATE cache_entries SET access_count = access_count + 1, "
                "last_accessed = CURRENT_TIMESTAMP WHERE cache_key = ?",
                (cache_key,),
            )
            self._stats["hits"] += 1
            return CachedResponse(
                data=data,
                headers=json.loads(headers),
                status_code=status_code,
                created_at=created_at,
                ttl_seconds=ttl_seconds,
                access_count=access_count + 1,
                last_accessed=last_accessed,
            )

    def set(self, cache_key: str, response: CachedResponse, domain_key: Optional[str] = None) -> bool:
        """Store a response in the cache with appropriate TTL.

        Args:
            cache_key: The cache key
            response: Response object to cache
            domain_key: Optional domain key for domain-specific TTL

        Returns:
            True if cached successfully, False otherwise
        """
        data = response.data
        # Always check original size before compression
        if len(data) > self.max_response_size:
            return False

        # If no TTL is set in response, determine it based on domain/default
        if hasattr(self, "_ttl_manager") and self._ttl_manager and response.ttl_seconds is None:
            if domain_key:
                response.ttl_seconds = self._ttl_manager.get_ttl_for_domain(domain_key)
            else:
                response.ttl_seconds = self._ttl_manager.get_default_ttl()

        compressed = False
        if len(data) > self.compression_threshold:
            try:
                data = zlib.compress(data)
                compressed = True
            except Exception:
                pass

        # Protect database operations from concurrent access
        with self._lock:
            self.db_manager.execute_update(
                "REPLACE INTO cache_entries (cache_key, response_data, "
                "headers, status_code, created_at, ttl_seconds, "
                "access_count, last_accessed) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, 0, CURRENT_TIMESTAMP)",
                (
                    cache_key,
                    data,
                    json.dumps(response.headers, separators=(",", ":")),
                    response.status_code,
                    response.ttl_seconds,
                ),
            )
            self._evict_if_needed()
            self._stats["sets"] += 1
            if compressed:
                self._stats["compressed"] += 1
        return True

    def _evict_if_needed(self):
        """Evict least recently used entries if over max_cache_entries."""
        while True:
            count = self.db_manager.execute_query("SELECT COUNT(*) FROM cache_entries")[0][0]
            if count <= self.max_cache_entries:
                break
            to_evict = count - self.max_cache_entries
            rows = self.db_manager.execute_query(
                "SELECT cache_key FROM cache_entries ORDER BY " "last_accessed ASC LIMIT ?", (to_evict,)
            )
            for (cache_key,) in rows:
                self.delete(cache_key)
                self._stats["evictions"] += 1

    def _cleanup_expired_entries(self):
        """Remove expired cache entries."""
        now = int(time.time())
        rows = self.db_manager.execute_query("SELECT cache_key, created_at, ttl_seconds FROM cache_entries")
        expired_count = 0
        for cache_key, created_at, ttl_seconds in rows:
            # created_at may be a string or datetime
            if hasattr(created_at, "timestamp"):
                created_ts = int(created_at.timestamp())
            elif isinstance(created_at, str):
                try:
                    created_ts = int(time.mktime(time.strptime(created_at, "%Y-%m-%d %H:%M:%S")))
                except Exception:
                    from datetime import datetime

                    created_ts = int(datetime.fromisoformat(created_at).timestamp())
            else:
                created_ts = int(created_at)
            if now > created_ts + ttl_seconds:
                self.delete(cache_key)
                expired_count += 1

        # Update stats in a thread-safe way
        if expired_count > 0:
            with self._lock:
                self._stats["expired"] += expired_count

    def get_cache_performance(self) -> Dict[str, Any]:
        """Return cache performance metrics."""
        total_entries = self.db_manager.execute_query("SELECT COUNT(*) FROM cache_entries")[0][0]
        total_size = self.db_manager.execute_query("SELECT SUM(LENGTH(response_data)) FROM cache_entries")[0][0] or 0
        stats = self.get_stats()
        return {
            "total_entries": total_entries,
            "total_size_bytes": total_size,
            "expired_entries": stats["expired"],
            "hit_rate": (
                stats["hits"] / (stats["hits"] + stats["misses"]) if (stats["hits"] + stats["misses"]) > 0 else 0.0
            ),
            "evictions": stats["evictions"],
            "compressed": stats["compressed"],
            "decompressed": stats["decompressed"],
        }

    def delete(self, cache_key: str) -> int:
        """Delete a cache entry."""
        return self.db_manager.execute_update("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))

    def clear(self) -> int:
        """Clear all cache entries."""
        return self.db_manager.execute_update("DELETE FROM cache_entries")

    def clear_cache(self, domain: Optional[str] = None) -> int:
        """Clear cache entries for a specific domain or all entries.

        Args:
            domain: Domain to clear cache for. If None, clears all entries.

        Returns:
            Number of entries cleared.
        """
        if domain is None:
            return self.clear()
        # Clear entries for specific domain by matching cache keys
        # that contain the domain
        return self.db_manager.execute_update("DELETE FROM cache_entries WHERE cache_key LIKE ?", (f"%{domain}%",))

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)

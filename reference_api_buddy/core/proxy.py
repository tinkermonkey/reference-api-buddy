import time
from typing import Any, Dict, List, Optional, Tuple

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.database.manager import DatabaseManager
from reference_api_buddy.security.manager import SecurityManager
from reference_api_buddy.throttling.manager import ThrottleManager
from reference_api_buddy.utils.logger import configure_logging, get_logger


class SecurityError(Exception):
    """Security-related errors raised during request validation.

    This exception is raised when:
    - Required secure key is missing
    - Provided secure key is invalid
    - Request fails security validation
    """

    pass


class CachingProxy:
    @staticmethod
    def get_logger(name: str):
        """Expose the get_logger utility function for external use.

        Args:
            name: Name of the logger (usually __name__ of the module)

        Returns:
            Configured logger instance
        """
        from reference_api_buddy.utils.logger import get_logger as _get_logger

        return _get_logger(name)

    """Main entry point for the caching proxy module.

    A thread-safe HTTP caching proxy that provides intelligent caching,
    progressive throttling, and detailed metrics for development environments.

    Example:
        Basic usage with security enabled:

        >>> config = {
        ...     "security": {"require_secure_key": True},
        ...     "domain_mappings": {
        ...         "example": {"upstream": "https://api.example.com"}
        ...     }
        ... }
        >>> proxy = CachingProxy(config)
        >>> proxy.start(blocking=False)
        >>> print(f"Secure key: {proxy.get_secure_key()}")
        >>> proxy.stop()

        Using as context manager:

        >>> with CachingProxy(config) as proxy:
        ...     # proxy is automatically started and stopped
        ...     pass
    """

    def validate_request(
        self, path: str, headers: Dict[str, str], query_params: Dict[str, str]
    ) -> Tuple[Optional[str], str]:
        """Extract and validate secure key from request.

        Args:
            path: The request path that may contain a secure key
            headers: HTTP headers dictionary that may contain authentication
            query_params: Query parameters dictionary that may contain the key

        Returns:
            A tuple of (extracted_key, sanitized_path) where extracted_key
            is None if no key found or security is disabled

        Raises:
            SecurityError: If security is enabled but key is invalid or missing

        Example:
            >>> proxy = CachingProxy({"security": {"require_secure_key": True}})
            >>> key, path = proxy.validate_request("/abc123/example.com/api", {}, {})
            >>> print(f"Key: {key}, Path: {path}")
        """
        key, sanitized = self.security_manager.extract_secure_key(path, headers, query_params)
        if not self.security_manager.validate_request(key):
            self.logger.warning("Invalid or missing secure key for path: %s", path)
            raise SecurityError("Invalid or missing secure key")
        return key, sanitized

    def _sanitize_path(self, path: str) -> str:
        """Remove null bytes, non-ASCII chars, and collapse multiple slashes.

        Args:
            path: The input path that may contain problematic characters

        Returns:
            A cleaned path with only printable ASCII characters and
            normalized slashes

        Example:
            >>> proxy = CachingProxy({})
            >>> clean = proxy._sanitize_path("/api/\\x00test//path")
            >>> print(clean)  # "/api/test/path"
        """
        import re

        cleaned = "".join([c for c in path if 32 <= ord(c) <= 126])
        # Collapse multiple slashes
        cleaned = re.sub(r"/+", "/", cleaned)
        return cleaned

    def _log_security_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Log security event if enabled in configuration.

        Args:
            event_type: Type of security event (e.g., "invalid_key", "rate_limit")
            details: Additional details about the event
        """
        if self.config.get("security", {}).get("log_security_events", True):
            self.logger.info(f"[SECURITY] {event_type}: {details}")

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the proxy with configuration and all components.

        Args:
            config: Configuration dictionary containing server, security, cache,
                   throttling, and domain mapping settings

        Raises:
            ValueError: If configuration is invalid

        Example:
            >>> config = {
            ...     "server": {"host": "127.0.0.1", "port": 8080},
            ...     "security": {"require_secure_key": True},
            ...     "cache": {"database_path": "cache.db"},
            ...     "domain_mappings": {
            ...         "example": {"upstream": "https://api.example.com"}
            ...     }
            ... }
            >>> proxy = CachingProxy(config)
        """
        self.config = config or {}
        self._validate_and_merge_config()
        # Configure logging system
        configure_logging(self.config.get("logging", {}))
        self.logger = get_logger("core.proxy")
        self.security_manager = SecurityManager(self.config.get("security", {}))
        self.db_manager = DatabaseManager(self.config.get("cache", {}).get("database_path", ":memory:"))
        self.cache_engine = CacheEngine(
            self.db_manager, max_response_size=self.config.get("cache", {}).get("max_cache_response_size", 10485760)
        )
        self.throttle_manager = ThrottleManager(self.config.get("throttling", {}))
        self.metrics_collector = MetricsCollector()
        self.callbacks = self.config.get("callbacks", {})
        self.server: Optional[Any] = None
        self.running = False
        self.start_time: Optional[float] = None
        self._metrics: Dict[str, Any] = {}

    def start(self, blocking: bool = False) -> None:
        """Start the proxy server.

        Args:
            blocking: If True, blocks until server stops. If False,
                     starts server in background thread.

        Raises:
            RuntimeError: If server is already running
            OSError: If unable to bind to specified host/port

        Example:
            >>> proxy = CachingProxy(config)
            >>> proxy.start(blocking=False)  # Start in background
            >>> # Do other work...
            >>> proxy.stop()
        """
        from reference_api_buddy.core.handler import ProxyHTTPRequestHandler
        from reference_api_buddy.core.server import ThreadedHTTPServer

        if self.running:
            raise RuntimeError("Server is already running")

        if self.server is None:
            host = self.config.get("server", {}).get("host", "127.0.0.1")
            port = self.config.get("server", {}).get("port", 8080)
            self.server = ThreadedHTTPServer((host, port), ProxyHTTPRequestHandler, self)
        self.running = True
        self.start_time = time.time()
        self.logger.info(f"Proxy server starting on {host}:{port} (blocking={blocking})")
        self.server.start(blocking=blocking)

    def stop(self) -> None:
        """Stop the proxy server and cleanup resources.

        This method is safe to call multiple times. If the server is not
        running, this method does nothing.

        Example:
            >>> proxy.stop()  # Gracefully stops the server
        """
        if self.server:
            self.server.stop()
        self.running = False

        # Close database connections to release file locks (important for Windows)
        if hasattr(self, "db_manager") and self.db_manager:
            try:
                self.db_manager.close()
            except Exception as e:
                self.logger.error(f"Error closing database manager: {e}")

        self.logger.info("Proxy server stopped.")
        # Graceful shutdown: flush metrics, call shutdown callbacks
        if "on_shutdown" in self.callbacks:
            try:
                self.callbacks["on_shutdown"](self)
            except Exception as e:
                self.logger.error(f"Error in shutdown callback: {e}")

    def get_secure_key(self) -> Optional[str]:
        """Return the secure key if security is enabled.

        Returns:
            The secure key string if security is enabled, None otherwise

        Example:
            >>> proxy = CachingProxy({"security": {"require_secure_key": True}})
            >>> key = proxy.get_secure_key()
            >>> print(f"Use this key in requests: {key}")
        """
        self.logger.debug("Retrieving secure key from security manager.")
        if hasattr(self.security_manager, "secure_key"):
            return getattr(self.security_manager, "secure_key", None)
        return None

    def is_running(self) -> bool:
        """Check if the proxy server is running.

        Returns:
            True if the server is currently running, False otherwise
        """
        return self.running

    def get_metrics(self) -> Dict[str, Any]:
        """Return current metrics and statistics.

        Returns:
            Dictionary containing cache hits, misses, throttling stats,
            and performance metrics

        Example:
            >>> metrics = proxy.get_metrics()
            >>> print(f"Cache hit rate: {metrics.get('hit_rate', 0):.2%}")
        """
        return self.metrics_collector.get_metrics()

    def clear_cache(self, domain: Optional[str] = None) -> int:
        """Clear cache entries for a domain or all domains.

        Args:
            domain: Specific domain to clear cache for. If None, clears all
                cache entries

        Returns:
            Number of cache entries that were cleared

        Example:
            >>> cleared = proxy.clear_cache("example.com")
            >>> print(f"Cleared {cleared} cache entries for example.com")
            >>> total_cleared = proxy.clear_cache()  # Clear all
        """
        self.logger.info(f"Clearing cache for domain: {domain}")
        return self.cache_engine.clear_cache(domain)

    def update_config(self, key_path: str, value: Any) -> None:
        """Update configuration at runtime using dot notation.

        Args:
            key_path: Dot-separated path to the configuration key (e.g., "server.port")
            value: New value to set

        Example:
            >>> proxy.update_config("server.port", 9090)
            >>> proxy.update_config("throttling.default_requests_per_hour", 500)
        """
        self.logger.info(f"Updating config '{key_path}' to {value}")
        keys = key_path.split(".")
        cfg = self.config
        for k in keys[:-1]:
            cfg = cfg.setdefault(k, {})
        cfg[keys[-1]] = value

    def reload_config(self, new_config: Dict[str, Any]) -> None:
        """Reload configuration completely.

        Args:
            new_config: New configuration dictionary to replace current config

        Note:
            This will reinitialize all components with the new configuration.
            The server must be restarted for server configuration changes
            to take effect.
        """
        self.logger.info("Reloading configuration...")
        self.config = new_config or {}
        self._validate_and_merge_config()
        # Re-configure logging system
        configure_logging(self.config.get("logging", {}))
        self.logger = get_logger("core.proxy")
        # Re-initialize components
        self.security_manager = SecurityManager(self.config.get("security", {}))
        self.db_manager = DatabaseManager(self.config.get("cache", {}).get("database_path", ":memory:"))
        self.cache_engine = CacheEngine(
            self.db_manager, max_response_size=self.config.get("cache", {}).get("max_cache_response_size", 10485760)
        )
        self.throttle_manager = ThrottleManager(self.config.get("throttling", {}))
        self.metrics_collector = MetricsCollector()
        self.callbacks = self.config.get("callbacks", {})

    def _validate_and_merge_config(self) -> None:
        """Validate and merge configuration with defaults."""
        # For now, just ensure required keys exist; could add schema validation
        defaults = {
            "server": {"host": "127.0.0.1", "port": 8080},
            "security": {},
            "cache": {"database_path": ":memory:", "max_cache_response_size": 10485760},
            "throttling": {},
            "callbacks": {},
        }
        for k, v in defaults.items():
            self.config.setdefault(k, v)

    def __enter__(self) -> "CachingProxy":
        """Enter context manager and start the proxy server."""
        self.start(blocking=False)
        return self

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[Any]) -> None:
        """Exit context manager and stop the proxy server."""
        self.stop()


class MetricsCollector:
    """Collects and reports proxy metrics, supports event callbacks.

    Tracks request counts, cache performance, throttling events, and errors.
    Thread-safe for concurrent request handling.
    """

    def __init__(self) -> None:
        """Initialize metrics collector with default counters."""
        self._metrics = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "throttled": 0,
            "errors": 0,
            "start_time": time.time(),
        }
        self._events: List[Tuple[str, Dict[str, Any]]] = []

    def record_event(self, event_type: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Record a proxy event for metrics tracking.

        Args:
            event_type: Type of event ("cache_hit", "cache_miss", "throttle", "error")
            details: Additional event details dictionary
        """
        self._metrics["total_requests"] += 1
        if event_type == "cache_hit":
            self._metrics["cache_hits"] += 1
        elif event_type == "cache_miss":
            self._metrics["cache_misses"] += 1
        elif event_type == "throttle":
            self._metrics["throttled"] += 1
        elif event_type == "error":
            self._metrics["errors"] += 1
        self._events.append((event_type, details or {}))

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics summary.

        Returns:
            Dictionary with request counts, cache performance, uptime, and recent events
        """
        m = dict(self._metrics)
        m["uptime_seconds"] = time.time() - self._metrics["start_time"]

        # Include recent events for debugging (convert tuples to dicts)
        m["events"] = [{"event_type": event_type, "details": details} for event_type, details in self._events]

        return m

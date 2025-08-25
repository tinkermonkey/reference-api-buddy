"""Database manager: connection pooling, schema, thread safety."""

import sqlite3
import threading
from datetime import datetime
from typing import Any, List

from reference_api_buddy.utils.logger import get_logger


def adapt_datetime_iso(val):
    """Adapt datetime to ISO 8601 date."""
    return val.isoformat()


def convert_datetime(val):
    """Convert ISO 8601 datetime to datetime object."""
    from datetime import datetime

    return datetime.fromisoformat(val.decode())


def convert_timestamp(val):
    """Convert timestamp to datetime object."""
    from datetime import datetime

    return datetime.fromisoformat(val.decode())


# Register adapters and converters to replace deprecated default ones
sqlite3.register_adapter(datetime, adapt_datetime_iso)
sqlite3.register_converter("datetime", convert_datetime)
sqlite3.register_converter("timestamp", convert_timestamp)

SCHEMA = [
    # Cache entries table
    """CREATE TABLE IF NOT EXISTS cache_entries (
        cache_key TEXT PRIMARY KEY,
        response_data BLOB NOT NULL,
        headers TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ttl_seconds INTEGER NOT NULL,
        access_count INTEGER DEFAULT 0,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    # Metrics table
    """CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        method TEXT NOT NULL,
        cache_hit BOOLEAN NOT NULL,
        response_time_ms INTEGER,
        response_size_bytes INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    # Config history
    """CREATE TABLE IF NOT EXISTS config_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_data TEXT NOT NULL,
        changed_by TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_cache_created_ttl " "ON cache_entries(created_at, ttl_seconds);",
    "CREATE INDEX IF NOT EXISTS idx_metrics_domain_timestamp " "ON metrics(domain, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_cache_last_accessed " "ON cache_entries(last_accessed);",
]


class DatabaseManager:
    """Manages SQLite database operations with thread safety and connection pooling."""

    def __init__(self, database_path: str):
        self.logger = get_logger("api_buddy.database.manager")
        # Use shared in-memory DB for ":memory:" or file::memory:?cache=shared
        if database_path == ":memory:":
            self.database_path = "file::memory:?cache=shared"
            self._use_uri = True
        else:
            self.database_path = database_path
            self._use_uri = database_path.startswith("file:")
        self._lock = threading.Lock()
        self._pool: List[sqlite3.Connection] = []
        self._max_pool_size = 5
        self._initialize_connections()
        self._initialize_schema()

    def _initialize_connections(self):
        for _ in range(self._max_pool_size):
            conn = sqlite3.connect(
                self.database_path, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES, uri=self._use_uri
            )
            # Configure SQLite for better concurrency
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            # Reduce I/O overhead
            conn.execute("PRAGMA synchronous=NORMAL")
            # Increase cache size
            conn.execute("PRAGMA cache_size=10000")
            # Use memory for temp tables
            conn.execute("PRAGMA temp_store=memory")
            # 5 second timeout on locks
            conn.execute("PRAGMA busy_timeout=5000")
            self._pool.append(conn)

    def _initialize_schema(self):
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for stmt in SCHEMA:
                cur.execute(stmt)
            conn.commit()
        finally:
            self.return_connection(conn)

    def get_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._pool:
                return self._pool.pop()
            conn = sqlite3.connect(
                self.database_path, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES, uri=self._use_uri
            )
            # Configure SQLite for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA temp_store=memory")
            conn.execute("PRAGMA busy_timeout=5000")
            return conn

    def return_connection(self, conn: sqlite3.Connection):
        with self._lock:
            if len(self._pool) < self._max_pool_size:
                self._pool.append(conn)
            else:
                conn.close()

    def execute_query(self, query: str, params: tuple = (), retries: int = 10, delay: float = 0.05) -> List[Any]:
        import random
        import time

        for attempt in range(retries):
            conn = self.get_connection()
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                rows = cur.fetchall()
                return rows
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    # Exponential backoff with jitter to avoid thundering herd
                    backoff = delay * (2**attempt) + random.uniform(0, 0.1)
                    time.sleep(min(backoff, 1.0))  # Cap at 1 second
                    continue
                raise
            finally:
                self.return_connection(conn)
        return []

    def execute_update(self, query: str, params: tuple = (), retries: int = 10, delay: float = 0.05) -> int:
        import random
        import time

        for attempt in range(retries):
            conn = self.get_connection()
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                conn.commit()
                return cur.rowcount
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    # Exponential backoff with jitter to avoid thundering herd
                    backoff = delay * (2**attempt) + random.uniform(0, 0.1)
                    time.sleep(min(backoff, 1.0))  # Cap at 1 second
                    continue
                raise
            finally:
                self.return_connection(conn)
        return 0

    def close(self):
        """Close all pooled database connections."""
        with self._lock:
            while self._pool:
                conn = self._pool.pop()
                try:
                    conn.close()
                except Exception:
                    pass

    def store_upstream_metrics(
        self,
        domain: str,
        method: str,
        response_time_ms: int,
        response_size_bytes: int,
        cache_hit: bool,
        status_code: int = 200,
    ) -> bool:
        """Store metrics for upstream requests.

        Args:
            domain: Domain that was contacted
            method: HTTP method used
            response_time_ms: Response time in milliseconds
            response_size_bytes: Size of response body in bytes
            cache_hit: Whether this was a cache hit or miss
            status_code: HTTP status code returned

        Returns:
            True if metrics were stored successfully, False otherwise
        """
        try:
            # First, ensure the metrics table has a status_code column
            try:
                # Check if status_code column exists
                self.execute_query("SELECT status_code FROM metrics LIMIT 1")
            except Exception as e:
                # Add status_code column if it doesn't exist
                self.execute_update("ALTER TABLE metrics ADD COLUMN status_code INTEGER DEFAULT 200")
                self.logger.debug(f"Added status_code column to metrics table: {e}")

            # Store metrics with proper status code
            self.execute_update(
                "INSERT INTO metrics (domain, method, cache_hit, response_time_ms, "
                "response_size_bytes, status_code, timestamp) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (domain, method, cache_hit, response_time_ms, response_size_bytes, status_code),
            )

            return True
        except Exception as e:
            self.logger.debug(f"Failed to store metrics: {e}")
            return False

    def get_upstream_metrics(self, domain: str = None, hours: int = 24) -> dict:
        """Get upstream metrics for the specified time window.

        Args:
            domain: Optional domain filter. If None, gets metrics for all domains
            hours: Number of hours back to look for metrics (default 24)

        Returns:
            Dictionary with overall stats and per-domain breakdowns including
            response times, error rates, and request volumes
        """
        try:
            # Base query conditions
            where_conditions = ["datetime(timestamp) >= datetime('now', '-{} hours')".format(hours)]
            params = []

            if domain:
                where_conditions.append("domain = ?")
                params.append(domain)

            where_clause = " AND ".join(where_conditions)

            # Get overall metrics
            overall_metrics = self._get_domain_metrics(where_clause, tuple(params))

            # Get per-domain metrics if no specific domain was requested
            domain_metrics = {}
            if not domain:
                # Get list of domains
                domains_query = f"SELECT DISTINCT domain FROM metrics WHERE {where_conditions[0]} " "AND cache_hit = 0"
                domains = [row[0] for row in self.execute_query(domains_query)]

                # Get metrics for each domain
                for domain_name in domains:
                    domain_where = where_conditions[0] + " AND domain = ?"
                    domain_params = (domain_name,)
                    domain_metrics[domain_name] = self._get_domain_metrics(domain_where, domain_params)

            result = {"overall": overall_metrics}

            if domain_metrics:
                result["by_domain"] = domain_metrics

            return result

        except Exception as e:
            return {
                "overall": {
                    "response_times": {"average_ms": 0, "recent_samples": [], "total_samples": 0, "error": str(e)},
                    "error_rates": {
                        "total_requests": 0,
                        "error_count": 0,
                        "error_rate": 0.0,
                        "success_rate": 0.0,
                        "by_status_code": {},
                    },
                    "request_volumes": {
                        "total_requests_last_24h": 0,
                        "cache_hits_last_24h": 0,
                        "cache_hit_rate": 0.0,
                        "hourly_breakdown": [],
                    },
                }
            }

    def _get_domain_metrics(self, where_clause: str, params: tuple) -> dict:
        """Get metrics for a specific domain or overall.

        Args:
            where_clause: SQL WHERE clause for filtering
            params: Parameters for the WHERE clause

        Returns:
            Dictionary with response times, error rates, and request volumes
        """
        try:
            # Get response times for cache misses (actual upstream requests) - successful requests only
            response_times_query = f"""
                SELECT response_time_ms
                FROM metrics
                WHERE {where_clause} AND cache_hit = 0 AND status_code < 400
                ORDER BY timestamp DESC
                LIMIT 100
            """
            response_times = [row[0] for row in self.execute_query(response_times_query, params)]

            # Calculate average response time
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0

            # Get total requests (cache misses only - actual upstream requests)
            total_requests_query = f"""
                SELECT COUNT(*)
                FROM metrics
                WHERE {where_clause} AND cache_hit = 0
            """
            total_requests = self.execute_query(total_requests_query, params)[0][0]

            # Get error breakdown by status code
            error_breakdown_query = f"""
                SELECT status_code, COUNT(*) as count
                FROM metrics
                WHERE {where_clause} AND cache_hit = 0 AND status_code >= 400
                GROUP BY status_code
                ORDER BY status_code
            """
            error_breakdown = {row[0]: row[1] for row in self.execute_query(error_breakdown_query, params)}

            # Count total error responses
            error_count = sum(error_breakdown.values())

            # Get request volume by hour for the time window (cache misses only)
            volume_query = f"""
                SELECT strftime('%Y-%m-%d %H:00:00', timestamp) as hour_bucket,
                       COUNT(*) as request_count
                FROM metrics
                WHERE {where_clause} AND cache_hit = 0
                GROUP BY hour_bucket
                ORDER BY hour_bucket DESC
            """
            volume_data = self.execute_query(volume_query, params)

            # Get cache hit ratio
            cache_hits_query = f"""
                SELECT COUNT(*)
                FROM metrics
                WHERE {where_clause} AND cache_hit = 1
            """
            cache_hits = self.execute_query(cache_hits_query, params)[0][0]

            total_with_cache = total_requests + cache_hits
            cache_hit_rate = cache_hits / total_with_cache if total_with_cache > 0 else 0.0

            return {
                "response_times": {
                    "average_ms": round(avg_response_time, 2),
                    "recent_samples": response_times[:10],  # Last 10 response times
                    "total_samples": len(response_times),
                },
                "error_rates": {
                    "total_requests": total_requests,
                    "error_count": error_count,
                    "error_rate": round(error_count / total_requests if total_requests > 0 else 0.0, 4),
                    "success_rate": round(
                        (total_requests - error_count) / total_requests if total_requests > 0 else 0.0, 4
                    ),
                    "by_status_code": error_breakdown,
                },
                "request_volumes": {
                    "total_requests_last_24h": total_requests,
                    "cache_hits_last_24h": cache_hits,
                    "cache_hit_rate": round(cache_hit_rate, 4),
                    "hourly_breakdown": [{"hour": row[0], "requests": row[1]} for row in volume_data],
                },
            }
        except Exception as e:
            return {
                "response_times": {"average_ms": 0, "recent_samples": [], "total_samples": 0, "error": str(e)},
                "error_rates": {
                    "total_requests": 0,
                    "error_count": 0,
                    "error_rate": 0.0,
                    "success_rate": 0.0,
                    "by_status_code": {},
                },
                "request_volumes": {
                    "total_requests_last_24h": 0,
                    "cache_hits_last_24h": 0,
                    "cache_hit_rate": 0.0,
                    "hourly_breakdown": [],
                },
            }

    def __del__(self):
        self.close()

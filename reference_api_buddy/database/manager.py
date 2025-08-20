"""Database manager: connection pooling, schema, thread safety."""

import sqlite3
import threading
from datetime import datetime
from typing import Any, List


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

    def __del__(self):
        self.close()

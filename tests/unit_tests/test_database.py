"""Unit tests for DatabaseManager: connection pooling, schema, CRUD ops."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reference_api_buddy.database.manager import DatabaseManager


@pytest.fixture(scope="function")
def db():
    dbm = DatabaseManager(":memory:")
    yield dbm
    # No explicit cleanup needed for in-memory


def test_schema_created(db):
    # Should have all tables
    tables = db.execute_query("SELECT name FROM sqlite_master WHERE type='table';")
    table_names = {row[0] for row in tables}
    assert "cache_entries" in table_names
    assert "metrics" in table_names
    assert "config_history" in table_names


def test_insert_and_query_cache_entry(db):
    # Insert
    rc = db.execute_update(
        "INSERT INTO cache_entries (cache_key, response_data, headers, status_code, ttl_seconds) VALUES (?, ?, ?, ?, ?)",
        ("abc", b"data", "{}", 200, 60),
    )
    assert rc == 1
    # Query
    rows = db.execute_query("SELECT cache_key, status_code FROM cache_entries WHERE cache_key=?", ("abc",))
    assert rows[0][0] == "abc"
    assert rows[0][1] == 200


def test_connection_pooling(db):
    # Should not exceed pool size
    conns = [db.get_connection() for _ in range(5)]
    for c in conns:
        db.return_connection(c)
    assert len(db._pool) <= db._max_pool_size


def test_thread_safety(db):
    import threading

    results = []

    def worker():
        db.execute_update("INSERT INTO metrics (domain, method, cache_hit) VALUES (?, ?, ?)", ("test", "GET", True))
        results.append(True)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    count = db.execute_query("SELECT COUNT(*) FROM metrics WHERE domain='test'")[0][0]
    assert count == 10
    db.close()

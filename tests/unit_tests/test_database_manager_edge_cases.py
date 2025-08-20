"""Unit tests for DatabaseManager edge cases and error scenarios."""

import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

# Add the project root to the path to import modules
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.database.manager import (
    DatabaseManager,
    adapt_datetime_iso,
    convert_datetime,
    convert_timestamp,
)


class TestDateTimeConverters:
    """Test datetime adapter and converter functions."""

    def test_adapt_datetime_iso(self):
        """Test datetime to ISO string conversion."""
        dt = datetime(2023, 8, 19, 10, 30, 45)
        result = adapt_datetime_iso(dt)
        assert result == "2023-08-19T10:30:45"

    def test_convert_datetime(self):
        """Test ISO string to datetime conversion."""
        iso_bytes = b"2023-08-19T10:30:45"
        result = convert_datetime(iso_bytes)
        assert result == datetime(2023, 8, 19, 10, 30, 45)

    def test_convert_timestamp(self):
        """Test timestamp string to datetime conversion."""
        ts_bytes = b"2023-08-19T10:30:45"
        result = convert_timestamp(ts_bytes)
        assert result == datetime(2023, 8, 19, 10, 30, 45)


class TestDatabaseInitializationFailures:
    """Test database initialization failure scenarios."""

    def test_database_initialization_with_invalid_path(self):
        """Test database initialization with invalid file path."""
        # Try to create a database in a non-existent directory
        invalid_path = "/non/existent/path/test.db"
        with pytest.raises(sqlite3.OperationalError):
            DatabaseManager(invalid_path)

    def test_database_initialization_with_uri_path(self):
        """Test database initialization with URI-style path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            uri_path = f"file:{tmp.name}"
            try:
                db = DatabaseManager(uri_path)
                assert db._use_uri is True
                assert db.database_path == uri_path
                db.close()
            finally:
                os.unlink(tmp.name)

    def test_database_initialization_with_regular_path(self):
        """Test database initialization with regular file path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            try:
                db = DatabaseManager(tmp.name)
                assert db._use_uri is False
                assert db.database_path == tmp.name
                db.close()
            finally:
                os.unlink(tmp.name)


class TestConnectionErrorHandling:
    """Test connection error scenarios."""

    @patch("sqlite3.connect")
    def test_connection_creation_failure(self, mock_connect):
        """Test handling of connection creation failures."""
        # Make connect raise an exception
        mock_connect.side_effect = sqlite3.OperationalError("Database locked")

        with pytest.raises(sqlite3.OperationalError):
            DatabaseManager(":memory:")

    def test_connection_pool_exhaustion(self):
        """Test behavior when connection pool is exhausted."""
        db = DatabaseManager(":memory:")

        # Get all connections from pool
        connections = []
        for _ in range(db._max_pool_size + 2):  # Get more than max pool size
            conn = db.get_connection()
            connections.append(conn)

        # Should have created new connections beyond pool size
        assert len(connections) == db._max_pool_size + 2

        # Return connections
        for conn in connections:
            db.return_connection(conn)

        # Pool should not exceed max size
        assert len(db._pool) <= db._max_pool_size
        db.close()

    def test_return_connection_when_pool_full(self):
        """Test returning connection when pool is at max capacity."""
        db = DatabaseManager(":memory:")

        # Fill the pool
        connections = [db.get_connection() for _ in range(db._max_pool_size)]
        for conn in connections:
            db.return_connection(conn)

        # Pool should be at max capacity
        assert len(db._pool) == db._max_pool_size

        # Create additional connection and return it
        extra_conn = db.get_connection()

        # Return the extra connection - it should be closed since pool is full
        db.return_connection(extra_conn)

        # Pool should still be at max capacity (extra connection was closed)
        assert len(db._pool) == db._max_pool_size
        db.close()


class TestTransactionRollbackScenarios:
    """Test transaction rollback and retry scenarios."""

    def test_execute_query_with_database_locked_retry(self):
        """Test execute_query retry logic with database locked errors."""
        db = DatabaseManager(":memory:")

        # Mock a connection that raises OperationalError then succeeds
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # First call raises locked error, second succeeds
        mock_cursor.execute.side_effect = [sqlite3.OperationalError("database is locked"), None]
        mock_cursor.fetchall.return_value = [("test",)]

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep"):  # Speed up test by mocking sleep
                    result = db.execute_query("SELECT * FROM test", retries=2, delay=0.01)
                    assert result == [("test",)]

        db.close()

    def test_execute_query_with_non_locked_error(self):
        """Test execute_query with non-recoverable database error."""
        db = DatabaseManager(":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("syntax error")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with pytest.raises(sqlite3.OperationalError, match="syntax error"):
                    db.execute_query("INVALID SQL")

        db.close()

    def test_execute_query_max_retries_exceeded(self):
        """Test execute_query when max retries are exceeded."""
        db = DatabaseManager(":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("database is locked")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep"):  # Speed up test
                    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                        db.execute_query("SELECT * FROM test", retries=2, delay=0.01)

        db.close()

    def test_execute_update_with_database_locked_retry(self):
        """Test execute_update retry logic with database locked errors."""
        db = DatabaseManager(":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # First call raises locked error, second succeeds
        mock_cursor.execute.side_effect = [sqlite3.OperationalError("database is locked"), None]
        mock_cursor.rowcount = 1

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep"):  # Speed up test by mocking sleep
                    result = db.execute_update("UPDATE test SET x=1", retries=2, delay=0.01)
                    assert result == 1

        db.close()

    def test_execute_update_with_non_locked_error(self):
        """Test execute_update with non-recoverable database error."""
        db = DatabaseManager(":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("syntax error")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with pytest.raises(sqlite3.OperationalError, match="syntax error"):
                    db.execute_update("INVALID SQL")

        db.close()

    def test_execute_update_max_retries_exceeded(self):
        """Test execute_update when max retries are exceeded."""
        db = DatabaseManager(":memory:")

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("database is locked")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep"):  # Speed up test
                    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                        db.execute_update("UPDATE test SET x=1", retries=2, delay=0.01)

        db.close()


class TestCleanupAndErrorRecovery:
    """Test cleanup procedures and error recovery."""

    def test_close_with_connections_in_pool(self):
        """Test closing database manager with connections in pool."""
        db = DatabaseManager(":memory:")

        # Get some connections and return them to pool
        connections = [db.get_connection() for _ in range(3)]
        for conn in connections:
            db.return_connection(conn)

        # Verify pool has connections
        assert len(db._pool) > 0

        # Close should empty the pool and close all connections
        db.close()

        # Pool should be empty after close
        assert len(db._pool) == 0

    def test_close_with_connection_close_error(self):
        """Test close method handling connection close errors gracefully."""
        db = DatabaseManager(":memory:")

        # Get a connection and return it to pool
        conn = db.get_connection()
        db.return_connection(conn)

        # Create a mock connection that raises an exception when closed
        mock_conn = Mock()
        mock_conn.close.side_effect = Exception("Close error")

        # Replace one of the pooled connections with our mock
        db._pool[0] = mock_conn

        # close() should handle exceptions gracefully
        db.close()  # Should not raise an exception

        # Pool should still be empty after close
        assert len(db._pool) == 0

    def test_destructor_calls_close(self):
        """Test that __del__ calls close method."""
        db = DatabaseManager(":memory:")

        with patch.object(db, "close") as mock_close:
            db.__del__()
            mock_close.assert_called_once()

    def test_close_empty_pool(self):
        """Test closing database manager with empty pool."""
        db = DatabaseManager(":memory:")

        # Empty the pool
        connections = [db.get_connection() for _ in range(db._max_pool_size)]
        # Don't return them, so pool is empty

        # close() should handle empty pool gracefully
        db.close()
        assert len(db._pool) == 0

        # Clean up connections
        for conn in connections:
            conn.close()


class TestDataMigrationEdgeCases:
    """Test data migration and schema edge cases."""

    def test_schema_initialization_with_existing_tables(self):
        """Test schema initialization when tables already exist."""
        # Create database with existing schema
        db1 = DatabaseManager(":memory:")

        # Insert some data
        db1.execute_update(
            "INSERT INTO cache_entries (cache_key, response_data, headers, status_code, ttl_seconds) VALUES (?, ?, ?, ?, ?)",
            ("test", b"data", "{}", 200, 60),
        )

        # Close and recreate - should handle existing schema gracefully
        db1.close()

        # Create new manager with same path (for file-based this would reuse existing DB)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            try:
                # Create first database
                db1 = DatabaseManager(tmp.name)
                db1.execute_update(
                    "INSERT INTO cache_entries (cache_key, response_data, headers, status_code, ttl_seconds) VALUES (?, ?, ?, ?, ?)",
                    ("test", b"data", "{}", 200, 60),
                )
                db1.close()

                # Create second database with same file - should initialize without errors
                db2 = DatabaseManager(tmp.name)

                # Should be able to query existing data
                rows = db2.execute_query("SELECT cache_key FROM cache_entries WHERE cache_key=?", ("test",))
                assert len(rows) == 1
                assert rows[0][0] == "test"

                db2.close()
            finally:
                os.unlink(tmp.name)

    def test_concurrent_schema_initialization(self):
        """Test concurrent schema initialization doesn't cause conflicts."""

        def create_db():
            db = DatabaseManager(":memory:")
            # Try to use the database immediately
            db.execute_update("INSERT INTO metrics (domain, method, cache_hit) VALUES (?, ?, ?)", ("test", "GET", True))
            return db

        # Create multiple databases concurrently
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_db) for _ in range(5)]
            dbs = [future.result() for future in futures]

        # All should be created successfully
        assert len(dbs) == 5

        # Clean up
        for db in dbs:
            db.close()

    def test_execute_query_with_zero_retries(self):
        """Test execute_query with zero retries reaches fallback return."""
        db = DatabaseManager(":memory:")

        # With retries=0, the for loop never executes, reaching the fallback return
        result = db.execute_query("SELECT * FROM test", retries=0)
        assert result == []

        db.close()

    def test_execute_update_with_zero_retries(self):
        """Test execute_update with zero retries reaches fallback return."""
        db = DatabaseManager(":memory:")

        # With retries=0, the for loop never executes, reaching the fallback return
        result = db.execute_update("UPDATE test SET x=1", retries=0)
        assert result == 0

        db.close()


class TestBackoffAndJitter:
    """Test exponential backoff and jitter logic."""

    def test_retry_backoff_timing(self):
        """Test that retry backoff increases exponentially."""
        db = DatabaseManager(":memory:")

        # Store original connections for cleanup
        original_connections = db._pool.copy()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("database is locked")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep") as mock_sleep:
                    with patch("random.uniform", return_value=0.05):  # Fixed jitter for testing
                        try:
                            db.execute_query("SELECT * FROM test", retries=3, delay=0.1)
                        except sqlite3.OperationalError:
                            pass  # Expected to fail after retries

                        # Verify sleep was called with increasing backoff
                        calls = mock_sleep.call_args_list
                        assert len(calls) == 2  # Two retry attempts

                        # First retry: 0.1 * 2^0 + 0.05 = 0.15, capped at 1.0
                        # Second retry: 0.1 * 2^1 + 0.05 = 0.25, capped at 1.0
                        assert abs(calls[0][0][0] - 0.15) < 0.001  # First backoff (allow for float precision)
                        assert abs(calls[1][0][0] - 0.25) < 0.001  # Second backoff (allow for float precision)

        # Manually close original connections before calling db.close()
        for conn in original_connections:
            try:
                conn.close()
            except Exception:
                pass
        db._pool.clear()  # Clear the pool before calling close

        db.close()

    def test_retry_backoff_cap(self):
        """Test that retry backoff is capped at 1 second."""
        db = DatabaseManager(":memory:")

        # Store original connections for cleanup
        original_connections = db._pool.copy()

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.OperationalError("database is locked")

        with patch.object(db, "get_connection", return_value=mock_conn):
            with patch.object(db, "return_connection"):
                with patch("time.sleep") as mock_sleep:
                    with patch("random.uniform", return_value=0.05):  # Fixed jitter for testing
                        try:
                            # Use large delay to test capping
                            db.execute_query("SELECT * FROM test", retries=3, delay=2.0)
                        except sqlite3.OperationalError:
                            pass  # Expected to fail after retries

                        # Verify all sleep calls are capped at 1.0 second
                        calls = mock_sleep.call_args_list
                        for call in calls:
                            assert call[0][0] <= 1.0

        # Manually close original connections before calling db.close()
        for conn in original_connections:
            try:
                conn.close()
            except Exception:
                pass
        db._pool.clear()  # Clear the pool before calling close

        db.close()

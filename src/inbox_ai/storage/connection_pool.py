"""
Database Connection Pool

Provides efficient connection pooling for SQLite database operations.
Improves concurrency performance by reusing connections and managing resources.

Features:
- Connection reuse (reduces connection overhead)
- Configurable pool size (default: 5 connections)
- Automatic connection health checks
- Thread-safe operation with asyncio support
- Graceful shutdown with connection cleanup
"""

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from typing import Iterator

from inbox_ai.core.config import StorageSettings
from inbox_ai.storage import SqliteEmailRepository

LOGGER = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe connection pool for SqliteEmailRepository."""

    def __init__(self, settings: StorageSettings, pool_size: int = 5):
        """
        Initialize connection pool.

        Args:
            settings: Storage settings containing database path
            pool_size: Maximum number of connections in pool (default: 5)
        """
        self.settings = settings
        self.pool_size = pool_size
        self._pool: Queue[SqliteEmailRepository] = Queue(maxsize=pool_size)
        self._lock = Lock()
        self._created_count = 0
        self._closed = False

        # Pre-create connections
        for _ in range(pool_size):
            self._create_connection()

        LOGGER.info("Initialized connection pool with %d connections", pool_size)

    def _create_connection(self) -> SqliteEmailRepository:
        """Create a new repository connection."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Connection pool is closed")

            repository = SqliteEmailRepository(self.settings)
            self._pool.put(repository)
            self._created_count += 1
            LOGGER.debug("Created connection #%d", self._created_count)
            return repository

    def _validate_connection(self, repository: SqliteEmailRepository) -> bool:
        """
        Validate that a connection is still healthy.

        Args:
            repository: Repository to validate

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            # Simple health check - execute a trivial query
            repository._connection.execute("SELECT 1")
            return True
        except (sqlite3.Error, AttributeError):
            LOGGER.warning("Connection validation failed, will create new connection")
            return False

    @contextmanager
    def acquire(self, timeout: float = 10.0) -> Iterator[SqliteEmailRepository]:
        """
        Acquire a connection from the pool (synchronous).

        Args:
            timeout: Maximum seconds to wait for a connection (default: 10)

        Yields:
            SqliteEmailRepository instance

        Raises:
            RuntimeError: If pool is closed
            TimeoutError: If no connection available within timeout
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        repository = None
        try:
            # Try to get connection from pool
            repository = self._pool.get(timeout=timeout)

            # Validate connection health
            if not self._validate_connection(repository):
                repository.close()
                repository = self._create_connection()
                repository = self._pool.get(timeout=timeout)

            yield repository

        except Empty as exc:
            raise TimeoutError(
                f"Could not acquire connection within {timeout} seconds"
            ) from exc

        finally:
            # Return connection to pool
            if repository is not None:
                self._pool.put(repository)

    @asynccontextmanager
    async def acquire_async(
        self, timeout: float = 10.0
    ) -> Iterator[SqliteEmailRepository]:
        """
        Acquire a connection from the pool (asynchronous).

        Args:
            timeout: Maximum seconds to wait for a connection (default: 10)

        Yields:
            SqliteEmailRepository instance

        Raises:
            RuntimeError: If pool is closed
            TimeoutError: If no connection available within timeout
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        repository = None
        start_time = asyncio.get_event_loop().time()

        try:
            # Try to get connection from pool with timeout
            while True:
                try:
                    repository = self._pool.get_nowait()
                    break
                except Empty:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= timeout:
                        raise TimeoutError(
                            f"Could not acquire connection within {timeout} seconds"
                        )
                    # Wait a bit before retrying
                    await asyncio.sleep(0.01)

            # Validate connection health
            if not self._validate_connection(repository):
                repository.close()
                repository = self._create_connection()
                repository = self._pool.get(timeout=timeout)

            yield repository

        finally:
            # Return connection to pool
            if repository is not None:
                self._pool.put(repository)

    def close(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            if self._closed:
                return

            self._closed = True

            # Close all connections
            closed_count = 0
            while not self._pool.empty():
                try:
                    repository = self._pool.get_nowait()
                    repository.close()
                    closed_count += 1
                except Empty:
                    break

            LOGGER.info("Closed connection pool (%d connections closed)", closed_count)

    def __enter__(self):
        """Enter context manager scope."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager scope and close pool."""
        self.close()

    @property
    def size(self) -> int:
        """Get current pool size."""
        return self._pool.qsize()

    @property
    def is_closed(self) -> bool:
        """Check if pool is closed."""
        return self._closed

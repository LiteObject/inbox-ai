"""Simple in-memory cache with TTL support."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

LOGGER = logging.getLogger(__name__)


class CacheEntry:
    """Cache entry with expiration time."""

    def __init__(self, value: Any, ttl_seconds: int = 300) -> None:
        """Initialize cache entry with value and TTL."""
        self.value = value
        self.expires_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.now(tz=UTC) > self.expires_at


class SimpleCache:
    """Simple in-memory cache with TTL and pattern-based invalidation."""

    def __init__(self) -> None:
        """Initialize empty cache."""
        self._cache: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            LOGGER.debug("Cache hit for key: %s", key)
            return entry.value

        # Clean up expired entry
        if entry:
            LOGGER.debug("Cache expired for key: %s", key)
            del self._cache[key]

        LOGGER.debug("Cache miss for key: %s", key)
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Set cache value with TTL."""
        self._cache[key] = CacheEntry(value, ttl_seconds)
        LOGGER.debug("Cache set for key: %s (TTL: %ds)", key, ttl_seconds)

    def invalidate(self, pattern: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: If provided, only invalidate keys containing this pattern.
                    If None, invalidate all entries.

        Returns:
            Number of entries invalidated
        """
        if pattern:
            keys = [k for k in self._cache.keys() if pattern in k]
            for key in keys:
                del self._cache[key]
            LOGGER.info(
                "Invalidated %d cache entries matching pattern: %s", len(keys), pattern
            )
            return len(keys)

        count = len(self._cache)
        self._cache.clear()
        LOGGER.info("Invalidated all %d cache entries", count)
        return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            LOGGER.debug("Cleaned up %d expired cache entries", len(expired_keys))

        return len(expired_keys)

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    @staticmethod
    def make_key(*parts: str | int | None) -> str:
        """
        Create cache key from multiple parts.

        Args:
            parts: Key components to hash together

        Returns:
            MD5 hash of combined parts
        """
        combined = "|".join(str(p) if p is not None else "None" for p in parts)
        return hashlib.md5(combined.encode("utf-8")).hexdigest()


# Global cache instance
response_cache = SimpleCache()


__all__ = ["SimpleCache", "response_cache"]

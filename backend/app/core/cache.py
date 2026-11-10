import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from app.core.config import settings


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    last_accessed: float


class ProductCache:
    """
    In-memory bounded TTL cache for product catalog data.
    Provides async-safe operations, LRU-style eviction upon reaching maximum entries,
    and automatic expiration.
    """

    def __init__(
        self,
        max_entries: int = 500,
        default_ttl: int = 300,
        category_ttl: int = 1800,
    ):
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self.category_ttl = category_ttl
        self._entries: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve an entry if present and not expired."""
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.expires_at <= now:
                # Expired: delete and count as miss
                del self._entries[key]
                self._misses += 1
                return None

            # Hit: update access time
            entry.last_accessed = now
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store an entry with a specific TTL. Evicts expired or LRU entries if full."""
        if value is None:
            return

        now = time.monotonic()
        ttl_seconds = ttl if ttl is not None else self.default_ttl
        expires_at = now + ttl_seconds

        async with self._lock:
            # If entry already exists, update in-place
            if key in self._entries:
                self._entries[key] = CacheEntry(value=value, expires_at=expires_at, last_accessed=now)
                return

            # If capacity reached, purge expired first
            if len(self._entries) >= self.max_entries:
                self._purge_expired(now)

            # If still at or above capacity, evict the least recently accessed item
            if len(self._entries) >= self.max_entries:
                lru_key = min(self._entries, key=lambda k: self._entries[k].last_accessed)
                del self._entries[lru_key]
                self._evictions += 1

            self._entries[key] = CacheEntry(value=value, expires_at=expires_at, last_accessed=now)

    def _purge_expired(self, now: float) -> None:
        """Internal helper to remove expired entries."""
        expired_keys = [k for k, v in self._entries.items() if v.expires_at <= now]
        for k in expired_keys:
            del self._entries[k]

    async def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache key."""
        async with self._lock:
            if key in self._entries:
                del self._entries[key]
                return True
            return False

    async def clear(self) -> None:
        """Clear all cache entries and reset counters."""
        async with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    async def size(self) -> int:
        """Return current valid (non-expired) entry count."""
        now = time.monotonic()
        async with self._lock:
            self._purge_expired(now)
            return len(self._entries)

    def stats(self) -> Dict[str, int]:
        """Return cache performance statistics."""
        return {
            "size": len(self._entries),
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
        }

    # Key generation helpers
    @staticmethod
    def make_product_key(provider: str, product_id: int | str) -> str:
        return f"product:{provider.lower()}:{product_id}"

    @staticmethod
    def make_list_key(
        provider: str,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 200,
        skip: int = 0,
    ) -> str:
        q_norm = (query or "").strip().lower()
        cat_norm = (category or "").strip().lower()
        return f"list:{provider.lower()}:q={q_norm}:c={cat_norm}:l={limit}:s={skip}"

    @staticmethod
    def make_category_key(provider: str) -> str:
        return f"categories:{provider.lower()}"


# Global cache instance configured from settings
product_cache = ProductCache(
    max_entries=settings.PRODUCT_CACHE_MAX_ENTRIES,
    default_ttl=settings.PRODUCT_CACHE_TTL_SECONDS,
    category_ttl=settings.PRODUCT_CATEGORY_CACHE_TTL_SECONDS,
)


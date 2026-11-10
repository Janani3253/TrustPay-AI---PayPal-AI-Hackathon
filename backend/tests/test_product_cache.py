import asyncio
import time
import pytest
from app.core.cache import CacheEntry, ProductCache


@pytest.mark.asyncio
async def test_cache_hit_and_miss():
    """Verify cache returns stored value for hits and None for misses."""
    cache = ProductCache(max_entries=10, default_ttl=60)
    assert await cache.get("missing_key") is None
    assert cache.stats()["misses"] == 1

    await cache.set("test_key", {"title": "Test Product"})
    hit_val = await cache.get("test_key")
    assert hit_val == {"title": "Test Product"}
    assert cache.stats()["hits"] == 1


@pytest.mark.asyncio
async def test_cache_expiration():
    """Verify entries expire after their TTL."""
    # Set a very short TTL: 0.05 seconds
    cache = ProductCache(max_entries=10, default_ttl=1)
    await cache.set("short_key", "value", ttl=0.05)

    # Immediately should hit
    assert await cache.get("short_key") == "value"

    # Wait for TTL to elapse
    await asyncio.sleep(0.06)
    assert await cache.get("short_key") is None
    assert cache.stats()["misses"] == 1


@pytest.mark.asyncio
async def test_cache_invalidation_and_clear():
    """Verify invalidation and clear reset cache state."""
    cache = ProductCache(max_entries=10, default_ttl=60)
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")

    assert await cache.size() == 2

    # Invalidate k1
    removed = await cache.invalidate("k1")
    assert removed is True
    assert await cache.get("k1") is None
    assert await cache.get("k2") == "v2"

    # Invalidate non-existent key returns False
    assert await cache.invalidate("k1") is False

    # Clear all
    await cache.clear()
    assert await cache.size() == 0
    assert await cache.get("k2") is None


@pytest.mark.asyncio
async def test_cache_max_entries_eviction():
    """Verify cache evicts least recently accessed entries when capacity is exceeded."""
    cache = ProductCache(max_entries=3, default_ttl=60)

    await cache.set("item1", "v1")
    await cache.set("item2", "v2")
    await cache.set("item3", "v3")
    assert await cache.size() == 3

    # Access item1 and item2 to make item3 the oldest / LRU
    await asyncio.sleep(0.01)
    await cache.get("item1")
    await asyncio.sleep(0.01)
    await cache.get("item2")

    # Insert item4, which should evict item3
    await cache.set("item4", "v4")
    assert await cache.size() == 3

    assert await cache.get("item1") == "v1"
    assert await cache.get("item2") == "v2"
    assert await cache.get("item4") == "v4"
    assert await cache.get("item3") is None
    assert cache.stats()["evictions"] >= 1


def test_cache_key_helpers():
    """Verify normalized cache key formats."""
    k_prod = ProductCache.make_product_key("DEMO", 42)
    assert k_prod == "product:demo:42"

    k_list = ProductCache.make_list_key("DummyJSON", query="Laptop", category="Smartphones", limit=20, skip=10)
    assert k_list == "list:dummyjson:q=laptop:c=smartphones:l=20:s=10"

    k_cat = ProductCache.make_category_key("DEMO")
    assert k_cat == "categories:demo"


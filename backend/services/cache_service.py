"""
Redis Cache-Aside Service.
Provides high-speed caching for public QR queries and hot batch lookups
with graceful fallbacks when Redis is offline or keys expire.
BCSE406L - NoSQL Databases
"""

import json
from typing import Optional, Any
from backend.config import settings
from backend.database.redis_client import get_redis_client


def get_cache(key: str) -> Optional[Any]:
    """Retrieve and deserialize JSON data from Redis cache."""
    try:
        client = get_redis_client()
        raw = client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def set_cache(key: str, data: Any, ttl: Optional[int] = None) -> bool:
    """Serialize and store data in Redis cache with expiration TTL."""
    try:
        client = get_redis_client()
        expiry = ttl or settings.REDIS_TTL_SECONDS
        payload = json.dumps(data, default=str)
        client.set(key, payload, ex=expiry)
        return True
    except Exception:
        return False


def invalidate_cache_pattern(pattern: str) -> int:
    """Invalidate all keys matching a glob pattern."""
    try:
        client = get_redis_client()
        keys = list(client.scan_iter(match=pattern, count=100))
        if keys:
            return client.delete(*keys)
    except Exception:
        pass
    return 0

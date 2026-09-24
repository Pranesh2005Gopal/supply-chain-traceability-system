"""
Redis Client and Connection Lifecycle Management
High-speed Caching Layer for Public QR and Hot Batch Traces.
"""

from typing import Optional, Dict, Any
import redis
from redis.exceptions import ConnectionError, TimeoutError
from backend.config import settings

_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get or create singleton Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
            decode_responses=True
        )
    return _redis_client


def close_redis_client() -> None:
    """Close Redis client connection."""
    global _redis_client
    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None


def ping_redis() -> Dict[str, Any]:
    """Check connectivity to Redis cache."""
    try:
        client = get_redis_client()
        client.ping()
        return {"status": "healthy", "host": settings.REDIS_HOST, "port": settings.REDIS_PORT}
    except (ConnectionError, TimeoutError, Exception) as e:
        return {"status": "unhealthy", "error": str(e)}

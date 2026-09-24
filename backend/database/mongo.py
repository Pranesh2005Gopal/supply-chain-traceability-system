"""
MongoDB Client and Connection Lifecycle Management
Operational and Document Store for Products, Batches, Actors, and Trace Events.
"""

from typing import Optional, Dict, Any
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from backend.config import settings

_mongo_client: Optional[MongoClient] = None


def get_mongo_client() -> MongoClient:
    """Get or create singleton MongoDB client."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=settings.MONGO_TIMEOUT_MS,
            connectTimeoutMS=settings.MONGO_TIMEOUT_MS
        )
    return _mongo_client


def get_mongo_db() -> Database:
    """Return the application database handle."""
    client = get_mongo_client()
    return client[settings.MONGO_DB_NAME]


def close_mongo_client() -> None:
    """Close MongoDB connection pool."""
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None


def ping_mongo() -> Dict[str, Any]:
    """Check connectivity to MongoDB cluster."""
    try:
        client = get_mongo_client()
        client.admin.command("ping")
        return {"status": "healthy", "database": settings.MONGO_DB_NAME}
    except (ConnectionFailure, ServerSelectionTimeoutError, Exception) as e:
        return {"status": "unhealthy", "error": str(e)}

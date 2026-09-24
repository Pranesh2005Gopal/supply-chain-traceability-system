"""
Neo4j Driver and Connection Lifecycle Management
Relationship and Provenance Graph Store.
"""

from typing import Optional, Dict, Any
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError
from backend.config import settings

_neo4j_driver: Optional[Driver] = None


def get_neo4j_driver() -> Driver:
    """Get or create singleton Neo4j driver."""
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
    return _neo4j_driver


def close_neo4j_driver() -> None:
    """Close Neo4j driver connection pool."""
    global _neo4j_driver
    if _neo4j_driver is not None:
        _neo4j_driver.close()
        _neo4j_driver = None


def ping_neo4j() -> Dict[str, Any]:
    """Check connectivity to Neo4j database."""
    try:
        driver = get_neo4j_driver()
        driver.verify_connectivity()
        return {"status": "healthy", "uri": settings.NEO4J_URI}
    except (ServiceUnavailable, AuthError, Exception) as e:
        return {"status": "unhealthy", "error": str(e)}

"""
Basic Skeleton Tests for Configuration, App Initialization, and Health Endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.config import settings, Settings
from backend.main import app

client = TestClient(app)


def test_settings_loaded():
    """Verify that configuration settings load with expected defaults."""
    assert settings.APP_NAME == "Supply Chain Traceability System"
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.MONGO_DB_NAME == "supply_trace"
    assert settings.NEO4J_USER == "neo4j"
    assert settings.REDIS_PORT == 6379
    assert isinstance(settings.CORS_ORIGINS, list)


def test_cors_origins_parsing():
    """Verify comma-separated string parsing for CORS origins."""
    custom_settings = Settings(CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000")
    assert custom_settings.CORS_ORIGINS == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_root_endpoint():
    """Verify system root endpoint returns 200 and metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "Supply Chain Traceability System"
    assert data["status"] == "online"
    assert "databases" in data
    assert "docs_url" in data


def test_health_endpoint_degraded_or_unhealthy_when_no_dbs():
    """Verify /health endpoint executes without crash even when local DBs are offline."""
    response = client.get("/health")
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert data["services"]["api"] == "healthy"
    assert "mongodb" in data["services"]
    assert "neo4j" in data["services"]
    assert "redis" in data["services"]


def test_health_endpoint_healthy_when_mocked():
    """Verify /health endpoint returns 200 and 'healthy' when all DB pings succeed."""
    with patch("backend.main.ping_mongo", return_value={"status": "healthy", "database": "supply_trace"}), \
         patch("backend.main.ping_neo4j", return_value={"status": "healthy", "uri": "bolt://localhost:7687"}), \
         patch("backend.main.ping_redis", return_value={"status": "healthy", "host": "localhost", "port": 6379}):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["mongodb"]["status"] == "healthy"
        assert data["services"]["neo4j"]["status"] == "healthy"
        assert data["services"]["redis"]["status"] == "healthy"

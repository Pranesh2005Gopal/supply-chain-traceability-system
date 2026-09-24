"""
Supply Chain Traceability System - FastAPI Application Entry Point
BCSE406L - NoSQL Databases
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.database.mongo import ping_mongo, close_mongo_client
from backend.database.neo4j_driver import ping_neo4j, close_neo4j_driver
from backend.database.redis_client import ping_redis, close_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown hooks."""
    # Startup logic
    yield
    # Shutdown logic
    close_mongo_client()
    close_neo4j_driver()
    close_redis_client()


app = FastAPI(
    title=settings.APP_NAME,
    description="NoSQL-based Supply Chain Traceability System implementing GS1 EPCIS 2.0 standards with MongoDB, Neo4j, and Redis.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["System"])
async def root():
    """System metadata and status root endpoint."""
    return {
        "project": "Supply Chain Traceability System",
        "course": "BCSE406L - NoSQL Databases",
        "version": "0.1.0",
        "status": "online",
        "databases": {
            "mongodb": "Operational / Document Store",
            "neo4j": "Provenance Graph Store",
            "redis": "High-Speed Query Cache Layer"
        },
        "docs_url": "/docs",
        "health_url": "/health"
    }


@app.get("/health", tags=["System"])
async def health_check():
    """
    Comprehensive multi-database health check.
    Pings MongoDB, Neo4j, and Redis and returns structured status.
    """
    mongo_health = ping_mongo()
    neo4j_health = ping_neo4j()
    redis_health = ping_redis()

    all_healthy = (
        mongo_health.get("status") == "healthy" and
        neo4j_health.get("status") == "healthy" and
        redis_health.get("status") == "healthy"
    )

    any_healthy = (
        mongo_health.get("status") == "healthy" or
        neo4j_health.get("status") == "healthy" or
        redis_health.get("status") == "healthy"
    )

    overall_status = "healthy" if all_healthy else ("degraded" if any_healthy else "unhealthy")

    response_payload = {
        "status": overall_status,
        "services": {
            "api": "healthy",
            "mongodb": mongo_health,
            "neo4j": neo4j_health,
            "redis": redis_health
        }
    }

    status_code = status.HTTP_200_OK if (all_healthy or overall_status == "degraded") else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=response_payload, status_code=status_code)


# Mount API v1 Routers
from backend.routers import (
    products,
    batches,
    actors,
    events,
    trace,
    public,
    cold_chain,
    export
)

api_v1_prefix = settings.API_V1_PREFIX

app.include_router(products.router, prefix=api_v1_prefix)
app.include_router(batches.router, prefix=api_v1_prefix)
app.include_router(actors.router, prefix=api_v1_prefix)
app.include_router(events.router, prefix=api_v1_prefix)
app.include_router(trace.router, prefix=api_v1_prefix)
app.include_router(public.router, prefix=api_v1_prefix)
app.include_router(cold_chain.router, prefix=api_v1_prefix)
app.include_router(export.router, prefix=api_v1_prefix)

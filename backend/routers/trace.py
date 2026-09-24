"""
Traceability REST API Endpoints.
Provides Forward Traversal, Backward Traversal, and Full Provenance Reports.
BCSE406L - NoSQL Databases
"""

from fastapi import APIRouter, HTTPException, Query, status

from backend.models.trace import TraceResponse, ProvenanceResponse
from backend.services.trace_service import (
    forward_trace,
    backward_trace,
    get_provenance_summary
)
from backend.services.cache_service import get_cache, set_cache

router = APIRouter(prefix="/trace", tags=["Traceability & Provenance"])


@router.get("/forward/{target_id:path}", response_model=TraceResponse)
async def trace_forward(
    target_id: str,
    max_depth: int = Query(50, ge=1, le=100, description="Maximum traversal depth (hops)")
):
    """
    Perform forward traceability from an event, batch, or product.
    Discovers all downstream handling facilities, shipments, and customer destinations.
    """
    cache_key = f"trace:forward:{target_id.strip()}:{max_depth}"
    cached = get_cache(cache_key)
    if cached:
        return TraceResponse(**cached)

    result = forward_trace(target_id, max_depth=max_depth)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Forward trace target '{target_id}' not found or has no downstream events."
        )

    set_cache(cache_key, result.model_dump(), ttl=600)
    return result


@router.get("/backward/{target_id:path}", response_model=TraceResponse)
async def trace_backward(
    target_id: str,
    max_depth: int = Query(50, ge=1, le=100, description="Maximum traversal depth (hops)")
):
    """
    Perform backward traceability from a finished batch, distribution node, or event.
    Traces upstream custody all the way to harvest origins and raw ingredient sources.
    """
    cache_key = f"trace:backward:{target_id.strip()}:{max_depth}"
    cached = get_cache(cache_key)
    if cached:
        return TraceResponse(**cached)

    result = backward_trace(target_id, max_depth=max_depth)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backward trace target '{target_id}' not found or has no upstream origins."
        )

    set_cache(cache_key, result.model_dump(), ttl=600)
    return result


@router.get("/provenance/{batch_id:path}", response_model=ProvenanceResponse)
async def trace_provenance(batch_id: str):
    """
    Generate an auditable provenance report for a specific batch.
    Summarizes origin farm, chain of custody, handling actors, and full timeline.
    """
    cache_key = f"trace:provenance:{batch_id.strip()}"
    cached = get_cache(cache_key)
    if cached:
        return ProvenanceResponse(**cached)

    result = get_provenance_summary(batch_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provenance report for batch '{batch_id}' not found."
        )

    set_cache(cache_key, result.model_dump(), ttl=900)
    return result

"""
Public QR Code & Consumer Trace Lookup Endpoints.
High-speed, unauthenticated read-only endpoint cached with Redis.
BCSE406L - NoSQL Databases
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.services.trace_service import get_provenance_summary
from backend.services.cache_service import get_cache, set_cache

router = APIRouter(prefix="/public", tags=["Public Consumer Verification"])


class PublicTraceSummary(BaseModel):
    batch_id: str
    product_name: str
    gtin: str
    lot_number: str
    verified_origin_facility: Optional[str] = None
    origin_location: Optional[str] = None
    harvest_date: Optional[str] = None
    current_status: Optional[str] = None
    handling_facilities_count: int
    data_origin: str = "SOURCE"
    qr_lookup_url: str


@router.get("/trace/{batch_id:path}", response_model=PublicTraceSummary)
async def public_batch_trace(batch_id: str):
    """
    Public consumer-facing authenticity and trace lookup.
    Encodable in consumer QR codes. Powered by Redis cache-aside.
    """
    clean_bid = batch_id.strip()
    cache_key = f"cache:public:qr:{clean_bid}"

    cached = get_cache(cache_key)
    if cached:
        return PublicTraceSummary(**cached)

    prov = get_provenance_summary(clean_bid)
    if not prov:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found for public verification."
        )

    origin_fac = prov.origin_facility or {}
    origin_loc_str = f"{origin_fac.get('city', '')}, {origin_fac.get('state', '')} US".strip()

    summary = PublicTraceSummary(
        batch_id=prov.batch_id,
        product_name=prov.product_name or f"Product {prov.gtin}",
        gtin=prov.gtin,
        lot_number=prov.lot_number,
        verified_origin_facility=origin_fac.get("name"),
        origin_location=origin_loc_str if origin_loc_str != "US" else "United States",
        harvest_date=prov.origin_time,
        current_status=prov.latest_step,
        handling_facilities_count=prov.actors_count,
        data_origin="SOURCE",
        qr_lookup_url=f"/api/v1/public/trace/{clean_bid}"
    )

    # Cache for 30 minutes in Redis
    set_cache(cache_key, summary.model_dump(), ttl=1800)
    return summary

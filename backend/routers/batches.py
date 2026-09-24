"""
Batches REST API Endpoints.
BCSE406L - NoSQL Databases
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.models.batch import (
    BatchCreate,
    BatchUpdate,
    BatchResponse,
    BatchListResponse
)
from backend.services.cache_service import invalidate_cache_pattern

router = APIRouter(prefix="/batches", tags=["Batches"])


@router.get("", response_model=BatchListResponse)
async def list_batches(
    skip: int = Query(0, ge=0, description="Offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    product_id: Optional[str] = Query(None, description="Filter by parent Product GTIN"),
    lot_number: Optional[str] = Query(None, description="Filter by lot number"),
    search: Optional[str] = Query(None, description="Search across batch ID or product")
):
    """List batches with pagination and optional filters."""
    db = get_mongo_db()
    query_filter = {}

    if product_id:
        query_filter["product_id"] = product_id.strip()
    if lot_number:
        query_filter["lot_number"] = lot_number.strip()
    if search:
        s = search.strip()
        query_filter["$or"] = [
            {"batch_id": {"$regex": s, "$options": "i"}},
            {"lot_number": {"$regex": s, "$options": "i"}},
            {"product_id": {"$regex": s, "$options": "i"}}
        ]

    total = db.batches.count_documents(query_filter)
    cursor = db.batches.find(query_filter).skip(skip).limit(limit).sort("batch_id", 1)
    items = [BatchResponse(**doc) for doc in cursor]

    return BatchListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items
    )


@router.get("/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: str):
    """Retrieve batch details by batch_id (canonical compound GTIN:LOT format)."""
    db = get_mongo_db()
    bid = batch_id.strip()
    doc = db.batches.find_one({"batch_id": bid})
    if not doc:
        # Fallback: check if queried by lot number only
        doc = db.batches.find_one({"lot_number": bid})

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with ID '{batch_id}' not found."
        )
    return BatchResponse(**doc)


@router.post("", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(payload: BatchCreate):
    """Register a new batch, verify product existence, and link in MongoDB and Neo4j."""
    db = get_mongo_db()
    pid = payload.product_id.strip()
    lot = payload.lot_number.strip()
    batch_id = f"{pid}:{lot}"

    # Verify parent product
    prod = db.products.find_one({"product_id": pid})
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create batch: parent product '{pid}' does not exist. Register product first."
        )

    existing = db.batches.find_one({"batch_id": batch_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Batch with ID '{batch_id}' already exists."
        )

    doc = {
        "_id": batch_id,
        "batch_id": batch_id,
        "gtin": pid,
        "lot_number": lot,
        "product_id": pid,
        "uri": f"https://id.gs1.org/01/{pid}/10/{lot}",
        "origin_location_id": payload.origin_location_id,
        "data_origin": "APPLICATION"
    }

    db.batches.insert_one(doc)

    # Sync to Neo4j
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (b:Batch {batch_id: $bid})
                SET b.lot_number = $lot, b.gtin = $pid
                WITH b
                MATCH (p:Product {product_id: $pid})
                MERGE (b)-[:INSTANCE_OF]->(p)
                """,
                bid=batch_id,
                lot=lot,
                pid=pid
            )
    except Exception:
        pass

    return BatchResponse(**doc)


@router.put("/{batch_id:path}", response_model=BatchResponse)
@router.patch("/{batch_id:path}", response_model=BatchResponse)
async def update_batch(batch_id: str, payload: BatchUpdate):
    """Update batch metadata in MongoDB and invalidate related cache."""
    db = get_mongo_db()
    bid = batch_id.strip()

    doc = db.batches.find_one({"batch_id": bid})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with ID '{batch_id}' not found."
        )

    updates = {}
    if payload.origin_location_id is not None:
        updates["origin_location_id"] = payload.origin_location_id.strip()
    if payload.uri is not None:
        updates["uri"] = payload.uri.strip()

    if updates:
        db.batches.update_one({"batch_id": bid}, {"$set": updates})
        doc.update(updates)
        # Invalidate Redis caches for this batch
        invalidate_cache_pattern(f"*{bid}*")

    return BatchResponse(**doc)


@router.delete("/{batch_id:path}", status_code=status.HTTP_200_OK)
async def delete_batch(batch_id: str):
    """
    Delete a batch only if no historical trace events reference it.
    Strictly prevents orphaning historical traceability records.
    """
    db = get_mongo_db()
    bid = batch_id.strip()

    doc = db.batches.find_one({"batch_id": bid})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch with ID '{batch_id}' not found."
        )

    # Reference integrity check
    event_count = db.trace_events.count_documents({"batch_ids": bid})
    if event_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete batch '{bid}': it is referenced by {event_count} historical trace event(s). "
                f"Historical traceability records cannot be orphaned."
            )
        )

    # Safe delete from MongoDB
    db.batches.delete_one({"batch_id": bid})

    # Delete from Neo4j
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run("MATCH (b:Batch {batch_id: $bid}) DETACH DELETE b", bid=bid)
    except Exception:
        pass

    # Invalidate cache
    invalidate_cache_pattern(f"*{bid}*")

    return {
        "success": True,
        "message": f"Batch '{bid}' deleted successfully.",
        "batch_id": bid
    }


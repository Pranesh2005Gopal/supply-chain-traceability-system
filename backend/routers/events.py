"""
Trace Events REST API Endpoints.
Strictly APPEND-ONLY: Supports POST (create) and GET (retrieve/filter).
PUT, PATCH, and DELETE are strictly disallowed to maintain auditable historical integrity.
BCSE406L - NoSQL Databases
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, status

from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.models.trace_event import (
    TraceEventCreate,
    TraceEventResponse,
    TraceEventListResponse
)
from etl.parser import extract_canonical_hash

router = APIRouter(prefix="/events", tags=["Trace Events (Append-Only)"])


@router.get("", response_model=TraceEventListResponse)
async def list_events(
    skip: int = Query(0, ge=0, description="Offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    batch_id: Optional[str] = Query(None, description="Filter by compound batch ID"),
    product_id: Optional[str] = Query(None, description="Filter by product GTIN"),
    biz_step: Optional[str] = Query(None, description="Filter by business step"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    location_id: Optional[str] = Query(None, description="Filter by location GLN URI"),
    start_date: Optional[datetime] = Query(None, description="Filter events on or after ISO timestamp"),
    end_date: Optional[datetime] = Query(None, description="Filter events on or before ISO timestamp")
):
    """
    List and filter historical trace events.
    Utilizes MongoDB indexes on batch_ids, event_time, and biz_step.
    """
    db = get_mongo_db()
    query_filter = {}

    if batch_id:
        query_filter["batch_ids"] = batch_id.strip()
    if product_id:
        query_filter["product_ids"] = product_id.strip()
    if biz_step:
        query_filter["biz_step"] = biz_step.strip()
    if event_type:
        query_filter["event_type"] = event_type.strip()
    if location_id:
        query_filter["location_id"] = location_id.strip()

    if start_date or end_date:
        query_filter["event_time"] = {}
        if start_date:
            query_filter["event_time"]["$gte"] = start_date
        if end_date:
            query_filter["event_time"]["$lte"] = end_date

    total = db.trace_events.count_documents(query_filter)
    cursor = db.trace_events.find(query_filter).skip(skip).limit(limit).sort("event_time", -1)
    items = [TraceEventResponse(**doc) for doc in cursor]

    return TraceEventListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items
    )


@router.get("/{event_id:path}", response_model=TraceEventResponse)
async def get_event(event_id: str):
    """
    Retrieve single trace event by canonical SHA-256 hash or raw GS1 NI URI.
    """
    db = get_mongo_db()
    clean_id = event_id.strip()
    canonical = extract_canonical_hash(clean_id)

    doc = db.trace_events.find_one({"canonical_hash": canonical})
    if not doc:
        doc = db.trace_events.find_one({"event_id": clean_id})

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace event '{event_id}' not found."
        )
    return TraceEventResponse(**doc)


@router.post("", response_model=TraceEventResponse, status_code=status.HTTP_201_CREATED)
async def append_trace_event(payload: TraceEventCreate):
    """
    Append an auditable trace event to the supply chain history.
    Strictly append-only: updates MongoDB and connects provenance edges in Neo4j.
    """
    db = get_mongo_db()

    # Generate deterministic event timestamp and canonical hash
    now_dt = payload.event_time or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    record_iso = datetime.now(timezone.utc).isoformat()

    # Normalize prev event hashes
    prev_hashes = [extract_canonical_hash(p) for p in payload.prev_event_ids if p]

    # Compute a unique canonical hash for this new event
    hash_seed = f"{payload.event_type}:{payload.biz_step}:{payload.location_id}:{now_iso}:{','.join(payload.batch_ids)}:{','.join(prev_hashes)}"
    canonical_hash = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()
    raw_ni_uri = f"ni:///sha-256;{canonical_hash}?ver=CBV2.0"

    # Extract referenced product IDs from batches
    product_ids = list({b.split(":")[0] for b in payload.batch_ids if ":" in b})

    # Prepare document
    quantities_dump = [q.model_dump() for q in payload.quantities]
    sources_dump = [s.model_dump() for s in payload.sources]
    destinations_dump = [d.model_dump() for d in payload.destinations]
    inputs_dump = [i.model_dump() for i in payload.transformation_inputs]
    outputs_dump = [o.model_dump() for o in payload.transformation_outputs]

    doc = {
        "_id": canonical_hash,
        "canonical_hash": canonical_hash,
        "event_id": raw_ni_uri,
        "event_type": payload.event_type,
        "action": payload.action,
        "biz_step": payload.biz_step,
        "event_time": now_dt,
        "event_time_str": now_iso,
        "record_time": datetime.now(timezone.utc),
        "record_time_str": record_iso,
        "timezone_offset": "+00:00",
        "location_id": payload.location_id,
        "read_point_id": payload.read_point_id or payload.location_id,
        "prev_event_hashes": prev_hashes,
        "batch_ids": payload.batch_ids,
        "product_ids": product_ids,
        "quantities": quantities_dump,
        "child_quantities": [],
        "transformation_inputs": inputs_dump,
        "transformation_outputs": outputs_dump,
        "sources": sources_dump,
        "destinations": destinations_dump,
        "data_origin": "APPLICATION",
        "raw_epcis_payload": {
            "type": payload.event_type,
            "eventID": raw_ni_uri,
            "bizStep": payload.biz_step,
            "action": payload.action,
            "eventTime": now_iso,
            "bizLocation": {"id": payload.location_id},
            "fdaftr:prevID": prev_hashes,
            "batch_ids": payload.batch_ids
        }
    }

    # Append to MongoDB
    db.trace_events.insert_one(doc)

    # Sync to Neo4j graph
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            # Create Event node and link to Location
            session.run(
                """
                MERGE (e:Event {event_id: $eid})
                SET e.raw_id = $raw_id,
                    e.type = $type,
                    e.biz_step = $step,
                    e.action = $action,
                    e.event_time = $time
                WITH e
                MATCH (l:Location {location_id: $lid})
                MERGE (e)-[:OCCURRED_AT]->(l)
                """,
                eid=canonical_hash,
                raw_id=raw_ni_uri,
                type=payload.event_type,
                step=payload.biz_step,
                action=payload.action or "",
                time=now_iso,
                lid=payload.location_id
            )

            # Link PRECEDES relationships
            if prev_hashes:
                session.run(
                    """
                    UNWIND $prevs AS prev_id
                    MATCH (prev:Event {event_id: prev_id})
                    MATCH (curr:Event {event_id: $curr_id})
                    MERGE (prev)-[:PRECEDES]->(curr)
                    """,
                    prevs=prev_hashes,
                    curr_id=canonical_hash
                )

            # Link Batches
            if payload.batch_ids:
                session.run(
                    """
                    UNWIND $bids AS bid
                    MATCH (e:Event {event_id: $eid})
                    MATCH (b:Batch {batch_id: bid})
                    MERGE (e)-[:OBSERVED]->(b)
                    """,
                    bids=payload.batch_ids,
                    eid=canonical_hash
                )
    except Exception:
        pass

    return TraceEventResponse(**doc)

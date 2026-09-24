"""
Actors / Facilities REST API Endpoints.
BCSE406L - NoSQL Databases
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.models.actor import (
    ActorCreate,
    ActorUpdate,
    ActorResponse,
    ActorListResponse
)

router = APIRouter(prefix="/actors", tags=["Actors"])


@router.get("", response_model=ActorListResponse)
async def list_actors(
    skip: int = Query(0, ge=0, description="Offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    role: Optional[str] = Query(None, description="Filter by inferred role"),
    city: Optional[str] = Query(None, description="Filter by city"),
    state: Optional[str] = Query(None, description="Filter by state"),
    search: Optional[str] = Query(None, description="Search across actor ID, name, or city")
):
    """List actors/facilities with pagination and filters."""
    db = get_mongo_db()
    query_filter = {}

    if role:
        query_filter["inferred_role"] = role.strip()
    if city:
        query_filter["address.city"] = {"$regex": city.strip(), "$options": "i"}
    if state:
        query_filter["address.state"] = {"$regex": state.strip(), "$options": "i"}
    if search:
        s = search.strip()
        query_filter["$or"] = [
            {"actor_id": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"address.city": {"$regex": s, "$options": "i"}}
        ]

    total = db.actors.count_documents(query_filter)
    cursor = db.actors.find(query_filter).skip(skip).limit(limit).sort("name", 1)
    items = [ActorResponse(**doc) for doc in cursor]

    return ActorListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items
    )


@router.get("/{actor_id:path}", response_model=ActorResponse)
async def get_actor(actor_id: str):
    """Retrieve actor/facility details by GLN URI or identifier."""
    db = get_mongo_db()
    aid = actor_id.strip()
    doc = db.actors.find_one({"actor_id": aid})
    if not doc:
        # Fallback: try checking if ID passed without URI scheme or partial GLN
        doc = db.actors.find_one({"$or": [{"gln": aid}, {"_id": aid}]})

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Actor with ID '{actor_id}' not found."
        )
    return ActorResponse(**doc)


@router.post("", response_model=ActorResponse, status_code=status.HTTP_201_CREATED)
async def create_actor(payload: ActorCreate):
    """Register a new facility/actor with optional geospatial coordinates."""
    db = get_mongo_db()
    aid = payload.actor_id.strip()

    existing = db.actors.find_one({"actor_id": aid})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Actor with ID '{aid}' already exists."
        )

    geo_point = None
    if payload.latitude is not None and payload.longitude is not None:
        geo_point = {
            "type": "Point",
            "coordinates": [float(payload.longitude), float(payload.latitude)]
        }

    addr = payload.address.model_dump() if payload.address else {}

    doc = {
        "_id": aid,
        "actor_id": aid,
        "location_id": aid,
        "name": payload.name.strip(),
        "address": addr,
        "geo_location": geo_point,
        "inferred_role": payload.role or "DISTRIBUTOR_HUB",
        "role_origin": "INFERRED",
        "inference_rule": "Application registered facility",
        "data_origin": "APPLICATION"
    }

    db.actors.insert_one(doc)

    # Sync to Neo4j
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (l:Location {location_id: $lid})
                SET l.name = $name,
                    l.city = $city,
                    l.state = $state,
                    l.inferred_role = $role
                """,
                lid=aid,
                name=payload.name,
                city=addr.get("city", ""),
                state=addr.get("state", ""),
                role=payload.role or "DISTRIBUTOR_HUB"
            )
    except Exception:
        pass

    return ActorResponse(**doc)


@router.put("/{actor_id:path}", response_model=ActorResponse)
@router.patch("/{actor_id:path}", response_model=ActorResponse)
async def update_actor(actor_id: str, payload: ActorUpdate):
    """Update facility/actor metadata in MongoDB and sync to Neo4j."""
    db = get_mongo_db()
    aid = actor_id.strip()

    doc = db.actors.find_one({"actor_id": aid})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Actor with ID '{actor_id}' not found."
        )

    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.role is not None:
        updates["inferred_role"] = payload.role.strip()
        updates["role_origin"] = "APPLICATION"

    if payload.address:
        updates["address"] = payload.address.model_dump()

    if payload.latitude is not None and payload.longitude is not None:
        updates["geo_location"] = {
            "type": "Point",
            "coordinates": [float(payload.longitude), float(payload.latitude)]
        }

    if updates:
        db.actors.update_one({"actor_id": aid}, {"$set": updates})
        doc.update(updates)

        # Sync to Neo4j
        try:
            driver = get_neo4j_driver()
            with driver.session() as session:
                session.run(
                    """
                    MATCH (l:Location {location_id: $lid})
                    SET l.name = coalesce($name, l.name),
                        l.city = coalesce($city, l.city),
                        l.state = coalesce($state, l.state),
                        l.inferred_role = coalesce($role, l.inferred_role)
                    """,
                    lid=aid,
                    name=updates.get("name"),
                    city=updates.get("address", {}).get("city"),
                    state=updates.get("address", {}).get("state"),
                    role=updates.get("inferred_role")
                )
        except Exception:
            pass

    return ActorResponse(**doc)


@router.delete("/{actor_id:path}", status_code=status.HTTP_200_OK)
async def delete_actor(actor_id: str):
    """
    Delete a facility/actor only if no historical trace events or batches reference it.
    Strictly prevents orphaning historical traceability records.
    """
    db = get_mongo_db()
    aid = actor_id.strip()

    doc = db.actors.find_one({"actor_id": aid})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Actor with ID '{actor_id}' not found."
        )

    # Reference integrity check
    ev_count = db.trace_events.count_documents({
        "$or": [
            {"location_id": aid},
            {"sources.location_id": aid},
            {"destinations.location_id": aid}
        ]
    })
    batch_count = db.batches.count_documents({"origin_location_id": aid})

    if ev_count > 0 or batch_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete facility '{aid}': it is referenced by {ev_count} historical trace event(s) "
                f"and {batch_count} batch origin(s). Deletion would orphan historical records."
            )
        )

    # Safe delete from MongoDB
    db.actors.delete_one({"actor_id": aid})

    # Delete from Neo4j
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run("MATCH (l:Location {location_id: $lid}) DETACH DELETE l", lid=aid)
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Actor '{aid}' deleted successfully.",
        "actor_id": aid
    }


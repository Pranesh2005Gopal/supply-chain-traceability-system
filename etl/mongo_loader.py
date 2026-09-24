"""
MongoDB Ingestion and Index Setup Module.
Provides idempotent bulk upserts for Products, Batches, Actors, and Trace Events.
BCSE406L - NoSQL Databases
"""

from typing import List, Dict, Any
from pymongo import UpdateOne, ASCENDING, GEOSPHERE
from pymongo.database import Database


def setup_mongo_indexes(db: Database) -> Dict[str, List[str]]:
    """
    Create all required indexes idempotently on products, batches, actors, and trace_events.
    """
    created_indexes: Dict[str, List[str]] = {}

    # Products indexes
    db.products.create_index([("product_id", ASCENDING)], unique=True, name="idx_product_id_unique")
    created_indexes["products"] = ["idx_product_id_unique"]

    # Batches indexes
    db.batches.create_index([("batch_id", ASCENDING)], unique=True, name="idx_batch_id_unique")
    db.batches.create_index([("product_id", ASCENDING)], name="idx_batches_product_id")
    db.batches.create_index([("lot_number", ASCENDING)], name="idx_batches_lot_number")
    created_indexes["batches"] = ["idx_batch_id_unique", "idx_batches_product_id", "idx_batches_lot_number"]

    # Actors indexes
    db.actors.create_index([("actor_id", ASCENDING)], unique=True, name="idx_actor_id_unique")
    db.actors.create_index([("geo_location", GEOSPHERE)], name="idx_actors_geo_2dsphere")
    created_indexes["actors"] = ["idx_actor_id_unique", "idx_actors_geo_2dsphere"]

    # Trace Events indexes (Append-Only Event Store)
    db.trace_events.create_index([("canonical_hash", ASCENDING)], unique=True, name="idx_canonical_hash_unique")
    db.trace_events.create_index([("event_id", ASCENDING)], name="idx_event_id")
    db.trace_events.create_index([("batch_ids", ASCENDING)], name="idx_batch_ids_multikey")
    db.trace_events.create_index([("product_ids", ASCENDING)], name="idx_product_ids_multikey")
    db.trace_events.create_index(
        [("batch_ids", ASCENDING), ("event_time", ASCENDING)],
        name="idx_batch_time_compound"
    )
    db.trace_events.create_index([("event_time", ASCENDING)], name="idx_event_time")
    db.trace_events.create_index([("biz_step", ASCENDING)], name="idx_biz_step")
    db.trace_events.create_index([("location_id", ASCENDING)], name="idx_location_id")
    created_indexes["trace_events"] = [
        "idx_canonical_hash_unique",
        "idx_event_id",
        "idx_batch_ids_multikey",
        "idx_product_ids_multikey",
        "idx_batch_time_compound",
        "idx_event_time",
        "idx_biz_step",
        "idx_location_id"
    ]

    return created_indexes


def load_master_data_to_mongo(
    db: Database,
    locations: List[Dict[str, Any]],
    products: List[Dict[str, Any]],
    batches: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Idempotently bulk-upsert locations (actors), products, and batches.
    """
    counts = {"actors": 0, "products": 0, "batches": 0}

    # Upsert Actors / Locations
    if locations:
        ops = [UpdateOne({"_id": loc["_id"]}, {"$set": loc}, upsert=True) for loc in locations]
        res = db.actors.bulk_write(ops, ordered=False)
        counts["actors"] = res.upserted_count + res.matched_count

    # Upsert Products
    if products:
        ops = [UpdateOne({"_id": prod["_id"]}, {"$set": prod}, upsert=True) for prod in products]
        res = db.products.bulk_write(ops, ordered=False)
        counts["products"] = res.upserted_count + res.matched_count

    # Upsert Batches
    if batches:
        ops = [UpdateOne({"_id": b["_id"]}, {"$set": b}, upsert=True) for b in batches]
        res = db.batches.bulk_write(ops, ordered=False)
        counts["batches"] = res.upserted_count + res.matched_count

    return counts


def load_events_batch_to_mongo(
    db: Database,
    normalized_events: List[Dict[str, Any]]
) -> int:
    """
    Idempotently bulk-upsert a batch of normalized trace events into trace_events collection.
    """
    if not normalized_events:
        return 0

    ops = [
        UpdateOne({"_id": ev["_id"]}, {"$set": ev}, upsert=True)
        for ev in normalized_events
    ]
    res = db.trace_events.bulk_write(ops, ordered=False)
    return res.upserted_count + res.matched_count

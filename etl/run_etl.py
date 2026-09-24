"""
Master ETL Pipeline Runner for Supply Chain Traceability System.
Extracts, normalizes, and loads the 9.1 MB EPCIS 2.0 dataset into MongoDB and Neo4j.
Idempotent and batch-oriented.
BCSE406L - NoSQL Databases
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from backend.config import settings
from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.database.redis_client import get_redis_client

from etl.parser import (
    parse_master_data,
    normalize_event,
)
from etl.mongo_loader import (
    setup_mongo_indexes,
    load_master_data_to_mongo,
    load_events_batch_to_mongo,
)
from etl.neo4j_loader import (
    setup_neo4j_constraints,
    load_locations_to_neo4j,
    load_products_and_batches_to_neo4j,
    load_events_batch_to_neo4j,
)


def run_pipeline(batch_size: int = 500) -> Dict[str, Any]:
    """Execute the end-to-end idempotent ETL pipeline."""
    start_time = time.time()
    dataset_path = Path(settings.DATASET_PATH)

    print("================================================================")
    print("      SUPPLY CHAIN TRACEABILITY SYSTEM - EPCIS 2.0 ETL          ")
    print("================================================================")
    print(f"Dataset Path: {dataset_path}")
    if not dataset_path.exists():
        print(f"ERROR: Dataset file not found at {dataset_path}")
        sys.exit(1)

    print(f"Dataset File Size: {dataset_path.stat().st_size:,} bytes")

    # 1. Connect to databases
    print("\n[Step 1/6] Initializing database drivers and configuring schemas...")
    mongo_db = get_mongo_db()
    neo_driver = get_neo4j_driver()

    # Configure MongoDB indexes
    mongo_indexes = setup_mongo_indexes(mongo_db)
    print("  ✓ MongoDB indexes verified:")
    for coll, idxs in mongo_indexes.items():
        print(f"    - {coll}: {len(idxs)} indexes")

    # Configure Neo4j constraints
    neo_constraints = setup_neo4j_constraints(neo_driver)
    print(f"  ✓ Neo4j constraints verified: {len(neo_constraints)} uniqueness constraints applied")

    # 2. Read EPCIS document
    print("\n[Step 2/6] Loading and validating EPCIS 2.0 JSON...")
    with open(dataset_path, "r", encoding="utf-8") as f:
        epcis_doc = json.load(f)

    raw_events = epcis_doc.get("epcisBody", {}).get("eventList", [])
    print(f"  ✓ EPCIS Schema Version: {epcis_doc.get('schemaVersion')}")
    print(f"  ✓ Total Events in Payload: {len(raw_events):,}")

    # 3. Parse and Ingest Master Data
    print("\n[Step 3/6] Parsing master data (locations, products, batches)...")
    locations, products, batches = parse_master_data(epcis_doc, raw_events)
    print(f"  ✓ Extracted {len(locations)} locations/actors")
    print(f"  ✓ Extracted {len(products)} products (GTINs)")
    print(f"  ✓ Extracted {len(batches)} batches (GTIN:LOT)")

    # Load master data to MongoDB
    mongo_master = load_master_data_to_mongo(mongo_db, locations, products, batches)
    print(f"  ✓ MongoDB Master Data Loaded: {mongo_master}")

    # Load master data to Neo4j
    neo_loc_count = load_locations_to_neo4j(neo_driver, locations)
    neo_pb_counts = load_products_and_batches_to_neo4j(neo_driver, products, batches)
    print(f"  ✓ Neo4j Master Data Loaded: {neo_loc_count} Locations, {neo_pb_counts['products']} Products, {neo_pb_counts['batches']} Batches")

    # 4. Stream and Normalize Events
    print(f"\n[Step 4/6] Normalizing and ingesting {len(raw_events):,} events in batches of {batch_size}...")
    total_mongo_events = 0
    total_neo_events = 0
    all_precedes_edges = []

    for i in range(0, len(raw_events), batch_size):
        chunk = raw_events[i : i + batch_size]
        normalized_chunk = [normalize_event(e) for e in chunk]

        # Ingest to MongoDB
        m_count = load_events_batch_to_mongo(mongo_db, normalized_chunk)
        total_mongo_events += m_count

        # Ingest nodes and non-precedes relationships to Neo4j
        n_count = load_events_batch_to_neo4j(neo_driver, normalized_chunk)
        total_neo_events += n_count

        # Collect precedes edges for second pass to ensure all event nodes exist
        for ev in normalized_chunk:
            for prev_h in ev.get("prev_event_hashes", []):
                all_precedes_edges.append({
                    "prev_event_id": prev_h,
                    "curr_event_id": ev["canonical_hash"]
                })

        print(f"  ... processed events {i + len(chunk):,}/{len(raw_events):,} [{(i + len(chunk))/len(raw_events)*100:.1f}%]")

    # 5. Build Complete PRECEDES Provenance Graph in Neo4j
    print(f"\n[Step 5/6] Building Neo4j PRECEDES provenance graph ({len(all_precedes_edges):,} relationships)...")
    precedes_query = """
    UNWIND $batch AS edge
    MATCH (prev:Event {event_id: edge.prev_event_id})
    MATCH (curr:Event {event_id: edge.curr_event_id})
    MERGE (prev)-[:PRECEDES]->(curr)
    """
    precedes_batch_size = 1000
    with neo_driver.session() as session:
        for j in range(0, len(all_precedes_edges), precedes_batch_size):
            p_chunk = all_precedes_edges[j : j + precedes_batch_size]
            session.run(precedes_query, batch=p_chunk)

    print(f"  ✓ Merged {len(all_precedes_edges):,} PRECEDES edges into Neo4j graph")

    # 6. Warm Redis Cache for Selected Hot Lookups
    print("\n[Step 6/6] Warming Redis cache with sample hot batch lookups...")
    redis_client = get_redis_client()
    sample_batches = [b["batch_id"] for b in batches[:5]]
    cached_count = 0
    try:
        for b_id in sample_batches:
            sample_events = list(mongo_db.trace_events.find({"batch_ids": b_id}, {"raw_epcis_payload": 0}).limit(10))
            # Format datetime objects for JSON serialization
            for ev in sample_events:
                if "_id" in ev: ev["_id"] = str(ev["_id"])
                if "event_time" in ev and ev["event_time"]: ev["event_time"] = ev["event_time"].isoformat()
                if "record_time" in ev and ev["record_time"]: ev["record_time"] = ev["record_time"].isoformat()

            cache_key = f"trace:batch:{b_id}"
            redis_client.set(cache_key, json.dumps(sample_events), ex=settings.REDIS_TTL_SECONDS)
            cached_count += 1
        print(f"  ✓ Pre-cached {cached_count} batch traces in Redis (TTL: {settings.REDIS_TTL_SECONDS}s)")
    except Exception as e:
        print(f"  ⚠ Redis cache warming warning: {e}")

    # Summary and Verification
    elapsed = time.time() - start_time
    print("\n================================================================")
    print("                   ETL PIPELINE COMPLETED                       ")
    print("================================================================")
    print(f"Total Execution Time: {elapsed:.2f} seconds")

    # Verification counts
    mongo_counts = {
        "actors": mongo_db.actors.count_documents({}),
        "products": mongo_db.products.count_documents({}),
        "batches": mongo_db.batches.count_documents({}),
        "trace_events": mongo_db.trace_events.count_documents({})
    }

    neo_counts = {}
    with neo_driver.session() as session:
        neo_counts["Event_nodes"] = session.run("MATCH (e:Event) RETURN count(e) AS cnt").single()["cnt"]
        neo_counts["Location_nodes"] = session.run("MATCH (l:Location) RETURN count(l) AS cnt").single()["cnt"]
        neo_counts["Batch_nodes"] = session.run("MATCH (b:Batch) RETURN count(b) AS cnt").single()["cnt"]
        neo_counts["Product_nodes"] = session.run("MATCH (p:Product) RETURN count(p) AS cnt").single()["cnt"]
        neo_counts["PRECEDES_edges"] = session.run("MATCH ()-[r:PRECEDES]->() RETURN count(r) AS cnt").single()["cnt"]
        neo_counts["OCCURRED_AT_edges"] = session.run("MATCH ()-[r:OCCURRED_AT]->() RETURN count(r) AS cnt").single()["cnt"]
        neo_counts["OBSERVED_edges"] = session.run("MATCH ()-[r:OBSERVED]->() RETURN count(r) AS cnt").single()["cnt"]
        neo_counts["CONSUMED_edges"] = session.run("MATCH ()-[r:CONSUMED_IN]->() RETURN count(r) AS cnt").single()["cnt"]
        neo_counts["PRODUCED_edges"] = session.run("MATCH ()-[r:PRODUCED]->() RETURN count(r) AS cnt").single()["cnt"]

    print("\nVerified MongoDB Counts:")
    for k, v in mongo_counts.items():
        print(f"  - {k}: {v:,}")

    print("\nVerified Neo4j Counts:")
    for k, v in neo_counts.items():
        print(f"  - {k}: {v:,}")

    return {
        "execution_time_seconds": elapsed,
        "mongo_counts": mongo_counts,
        "neo_counts": neo_counts
    }


if __name__ == "__main__":
    run_pipeline()

"""
Neo4j Provenance Graph Ingestion Module.
Creates uniqueness constraints and builds lightweight provenance graph
linking Events, Locations, Batches, and Products via Cypher MERGE queries.
BCSE406L - NoSQL Databases
"""

from typing import List, Dict, Any
from neo4j import Driver


def setup_neo4j_constraints(driver: Driver) -> List[str]:
    """
    Create uniqueness constraints for Event, Batch, Product, and Location nodes.
    Safe to execute repeatedly.
    """
    constraints = [
        "CREATE CONSTRAINT unique_event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE",
        "CREATE CONSTRAINT unique_batch_id IF NOT EXISTS FOR (b:Batch) REQUIRE b.batch_id IS UNIQUE",
        "CREATE CONSTRAINT unique_product_id IF NOT EXISTS FOR (p:Product) REQUIRE p.product_id IS UNIQUE",
        "CREATE CONSTRAINT unique_location_id IF NOT EXISTS FOR (l:Location) REQUIRE l.location_id IS UNIQUE",
    ]
    applied = []
    with driver.session() as session:
        for query in constraints:
            session.run(query)
            applied.append(query)
    return applied


def load_locations_to_neo4j(driver: Driver, locations: List[Dict[str, Any]]) -> int:
    """
    Idempotently merge Location nodes in Neo4j.
    """
    if not locations:
        return 0

    batch_data = [
        {
            "location_id": loc["location_id"],
            "name": loc.get("name", "Unknown Location"),
            "city": loc.get("address", {}).get("city", "Unknown City"),
            "state": loc.get("address", {}).get("state", "Unknown State"),
            "inferred_role": loc.get("inferred_role", "UNKNOWN")
        }
        for loc in locations
    ]

    query = """
    UNWIND $batch AS loc
    MERGE (l:Location {location_id: loc.location_id})
    SET l.name = loc.name,
        l.city = loc.city,
        l.state = loc.state,
        l.inferred_role = loc.inferred_role
    """
    with driver.session() as session:
        session.run(query, batch=batch_data)

    return len(batch_data)


def load_products_and_batches_to_neo4j(
    driver: Driver,
    products: List[Dict[str, Any]],
    batches: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Idempotently merge Product and Batch nodes and the INSTANCE_OF relationship.
    """
    # 1. Merge Products
    prod_data = [
        {
            "product_id": p["product_id"],
            "name": p.get("name", f"Product {p['product_id']}"),
            "gtin": p["gtin"]
        }
        for p in products
    ]
    prod_query = """
    UNWIND $batch AS p
    MERGE (prod:Product {product_id: p.product_id})
    SET prod.name = p.name,
        prod.gtin = p.gtin
    """

    # 2. Merge Batches and link to Product
    batch_data = [
        {
            "batch_id": b["batch_id"],
            "lot_number": b["lot_number"],
            "gtin": b["gtin"],
            "product_id": b["product_id"]
        }
        for b in batches
    ]
    batch_query = """
    UNWIND $batch AS b
    MERGE (batch:Batch {batch_id: b.batch_id})
    SET batch.lot_number = b.lot_number,
        batch.gtin = b.gtin
    WITH batch, b
    MATCH (p:Product {product_id: b.product_id})
    MERGE (batch)-[:INSTANCE_OF]->(p)
    """

    with driver.session() as session:
        if prod_data:
            session.run(prod_query, batch=prod_data)
        if batch_data:
            session.run(batch_query, batch=batch_data)

    return {"products": len(prod_data), "batches": len(batch_data)}


def load_events_batch_to_neo4j(
    driver: Driver,
    normalized_events: List[Dict[str, Any]]
) -> int:
    """
    Idempotently merge a batch of Event nodes, PRECEDES edges, OCCURRED_AT edges,
    and batch tracking relationships.
    """
    if not normalized_events:
        return 0

    # Prepare lightweight event node data
    event_nodes = [
        {
            "event_id": ev["canonical_hash"],
            "raw_id": ev["event_id"],
            "type": ev["event_type"],
            "biz_step": ev["biz_step"],
            "action": ev["action"] or "",
            "event_time": ev["event_time_str"],
            "location_id": ev.get("location_id")
        }
        for ev in normalized_events
    ]

    # Prepare PRECEDES edges
    precedes_edges = []
    for ev in normalized_events:
        for prev_hash in ev.get("prev_event_hashes", []):
            precedes_edges.append({
                "prev_event_id": prev_hash,
                "curr_event_id": ev["canonical_hash"]
            })

    # Prepare item tracking edges
    observed_edges = []
    consumed_edges = []
    produced_edges = []

    for ev in normalized_events:
        eid = ev["canonical_hash"]
        if ev["event_type"] == "TransformationEvent":
            for inp in ev.get("transformation_inputs", []):
                if inp.get("batch_id"):
                    consumed_edges.append({"event_id": eid, "batch_id": inp["batch_id"]})
            for outp in ev.get("transformation_outputs", []):
                if outp.get("batch_id"):
                    produced_edges.append({"event_id": eid, "batch_id": outp["batch_id"]})
        else:
            for b_id in ev.get("batch_ids", []):
                observed_edges.append({"event_id": eid, "batch_id": b_id})

    # Prepare transit corridors
    shipping_corridors = []
    for ev in normalized_events:
        eid = ev["canonical_hash"]
        etime = ev["event_time_str"]
        for s in ev.get("sources", []):
            for d in ev.get("destinations", []):
                if s.get("location_id") and d.get("location_id"):
                    shipping_corridors.append({
                        "event_id": eid,
                        "source_id": s["location_id"],
                        "destination_id": d["location_id"],
                        "event_time": etime
                    })

    # Cypher Queries
    merge_events_query = """
    UNWIND $batch AS ev
    MERGE (e:Event {event_id: ev.event_id})
    SET e.raw_id = ev.raw_id,
        e.type = ev.type,
        e.biz_step = ev.biz_step,
        e.action = ev.action,
        e.event_time = ev.event_time
    WITH e, ev
    WHERE ev.location_id IS NOT NULL
    MATCH (l:Location {location_id: ev.location_id})
    MERGE (e)-[:OCCURRED_AT]->(l)
    """

    merge_precedes_query = """
    UNWIND $batch AS edge
    MATCH (prev:Event {event_id: edge.prev_event_id})
    MATCH (curr:Event {event_id: edge.curr_event_id})
    MERGE (prev)-[:PRECEDES]->(curr)
    """

    merge_observed_query = """
    UNWIND $batch AS item
    MATCH (e:Event {event_id: item.event_id})
    MATCH (b:Batch {batch_id: item.batch_id})
    MERGE (e)-[:OBSERVED]->(b)
    """

    merge_consumed_query = """
    UNWIND $batch AS item
    MATCH (e:Event {event_id: item.event_id})
    MATCH (b:Batch {batch_id: item.batch_id})
    MERGE (b)-[:CONSUMED_IN]->(e)
    """

    merge_produced_query = """
    UNWIND $batch AS item
    MATCH (e:Event {event_id: item.event_id})
    MATCH (b:Batch {batch_id: item.batch_id})
    MERGE (e)-[:PRODUCED]->(b)
    """

    merge_corridors_query = """
    UNWIND $batch AS corridor
    MATCH (src:Location {location_id: corridor.source_id})
    MATCH (dst:Location {location_id: corridor.destination_id})
    MERGE (src)-[r:SHIPPED_TO {event_id: corridor.event_id}]->(dst)
    SET r.event_time = corridor.event_time
    """

    with driver.session() as session:
        # 1. Merge Events & Location Edges
        session.run(merge_events_query, batch=event_nodes)

        # 2. Merge Provenance PRECEDES Edges
        if precedes_edges:
            session.run(merge_precedes_query, batch=precedes_edges)

        # 3. Merge Batch tracking Edges
        if observed_edges:
            session.run(merge_observed_query, batch=observed_edges)
        if consumed_edges:
            session.run(merge_consumed_query, batch=consumed_edges)
        if produced_edges:
            session.run(merge_produced_query, batch=produced_edges)

        # 4. Merge Shipping Corridors
        if shipping_corridors:
            session.run(merge_corridors_query, batch=shipping_corridors)

    return len(event_nodes)

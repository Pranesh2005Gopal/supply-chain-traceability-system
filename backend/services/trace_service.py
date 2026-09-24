"""
Traceability and Provenance Service.
Orchestrates Neo4j multi-hop graph traversals and MongoDB document enrichments.
Supports forward tracing, backward tracing, provenance summaries, and cold chain evaluations.
BCSE406L - NoSQL Databases
"""

from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import random

from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.models.trace import (
    TraceNode,
    TraceEdge,
    TraceTimelineItem,
    TraceResponse,
    ActorHandlingSummary,
    ProvenanceResponse,
    ColdChainReading,
    ColdChainResponse
)
from etl.parser import extract_canonical_hash


def forward_trace(target_id: str, max_depth: int = 50) -> Optional[TraceResponse]:
    """
    Perform forward traceability traversal from a batch, product, or event.
    Traces downstream events and locations through PRECEDES relationships in Neo4j.
    """
    driver = get_neo4j_driver()
    target_clean = target_id.strip()

    # Determine if target is a canonical hash, NI URI, or batch ID
    canonical_hash = extract_canonical_hash(target_clean)

    with driver.session() as session:
        # Check if target is an Event
        is_event = False
        start_event_ids: List[str] = []

        if canonical_hash:
            ev_check = session.run(
                "MATCH (e:Event {event_id: $eid}) RETURN e.event_id AS eid",
                eid=canonical_hash
            ).single()
            if ev_check:
                is_event = True
                start_event_ids = [ev_check["eid"]]

        if not is_event:
            # Query starting events for this Batch (or Product)
            # Find earliest events observing or producing this batch
            start_query = """
            MATCH (e:Event)-[:OBSERVED|PRODUCED]->(b:Batch {batch_id: $bid})
            RETURN e.event_id AS eid
            ORDER BY e.event_time ASC
            LIMIT 5
            """
            records = session.run(start_query, bid=target_clean).data()
            if records:
                start_event_ids = [r["eid"] for r in records]
            else:
                # Try finding by product GTIN
                p_query = """
                MATCH (e:Event)-[:OBSERVED|PRODUCED]->(b:Batch)-[:INSTANCE_OF]->(p:Product {product_id: $pid})
                RETURN e.event_id AS eid
                ORDER BY e.event_time ASC
                LIMIT 5
                """
                p_records = session.run(p_query, pid=target_clean).data()
                if p_records:
                    start_event_ids = [r["eid"] for r in p_records]

        if not start_event_ids:
            return None

        # Multi-hop Forward Traversal via PRECEDES*
        traversal_query = """
        MATCH path = (start:Event)-[:PRECEDES*0..50]->(downstream:Event)
        WHERE start.event_id IN $start_ids
        WITH DISTINCT downstream, length(path) AS depth
        ORDER BY downstream.event_time ASC, depth ASC
        LIMIT 250
        OPTIONAL MATCH (downstream)-[:OCCURRED_AT]->(loc:Location)
        OPTIONAL MATCH (downstream)-[:OBSERVED|CONSUMED_IN|PRODUCED]->(batch:Batch)
        RETURN downstream, loc, collect(DISTINCT batch.batch_id) AS batches, depth
        """
        results = session.run(traversal_query, start_ids=start_event_ids).data()

        if not results:
            return None

        event_ids = [r["downstream"]["event_id"] for r in results]

        # Fetch edges between the discovered events
        edge_query = """
        MATCH (e1:Event)-[r:PRECEDES]->(e2:Event)
        WHERE e1.event_id IN $eids AND e2.event_id IN $eids
        RETURN DISTINCT e1.event_id AS src, e2.event_id AS dst, type(r) AS rel_type
        """
        edge_records = session.run(edge_query, eids=event_ids).data()

        # Build Nodes, Edges, Timeline
        nodes_dict: Dict[str, TraceNode] = {}
        edges_list: List[TraceEdge] = []
        timeline: List[TraceTimelineItem] = []
        max_hops = 0

        for r in results:
            ev = r["downstream"]
            loc = r.get("loc")
            batches = r.get("batches", [])
            depth = r.get("depth", 0)
            if depth > max_hops:
                max_hops = depth

            eid = ev["event_id"]
            if eid not in nodes_dict:
                nodes_dict[eid] = TraceNode(
                    id=eid,
                    label="Event",
                    title=f"{ev.get('biz_step', 'Event')} ({ev.get('type')})",
                    properties={
                        "event_type": ev.get("type"),
                        "biz_step": ev.get("biz_step"),
                        "event_time": ev.get("event_time"),
                        "action": ev.get("action")
                    }
                )

            loc_id = loc.get("location_id") if loc else None
            loc_name = loc.get("name") if loc else None
            loc_city = loc.get("city") if loc else None
            loc_state = loc.get("state") if loc else None

            if loc and loc_id:
                if loc_id not in nodes_dict:
                    nodes_dict[loc_id] = TraceNode(
                        id=loc_id,
                        label="Location",
                        title=loc_name or "Location",
                        properties={
                            "city": loc_city,
                            "state": loc_state,
                            "inferred_role": loc.get("inferred_role")
                        }
                    )
                edges_list.append(TraceEdge(
                    source=eid,
                    target=loc_id,
                    type="OCCURRED_AT"
                ))

            for b in batches:
                if b and b not in nodes_dict:
                    nodes_dict[b] = TraceNode(
                        id=b,
                        label="Batch",
                        title=f"Batch {b}",
                        properties={"batch_id": b}
                    )
                if b:
                    edges_list.append(TraceEdge(
                        source=eid,
                        target=b,
                        type="OBSERVED"
                    ))

            timeline.append(TraceTimelineItem(
                event_id=ev.get("raw_id") or eid,
                canonical_hash=eid,
                event_type=ev.get("type"),
                biz_step=ev.get("biz_step"),
                event_time=ev.get("event_time"),
                location_id=loc_id,
                location_name=loc_name,
                location_city=loc_city,
                location_state=loc_state,
                action=ev.get("action"),
                batch_ids=batches
            ))

        for er in edge_records:
            edges_list.append(TraceEdge(
                source=er["src"],
                target=er["dst"],
                type=er["rel_type"]
            ))

        return TraceResponse(
            query_target=target_id,
            direction="FORWARD",
            total_hops=max_hops,
            events_count=len(timeline),
            nodes=list(nodes_dict.values()),
            edges=edges_list,
            timeline=timeline
        )


def backward_trace(target_id: str, max_depth: int = 50) -> Optional[TraceResponse]:
    """
    Perform backward traceability traversal from a finished batch or event back toward origins.
    Traverses upstream events through <-[:PRECEDES]- relationships in Neo4j.
    """
    driver = get_neo4j_driver()
    target_clean = target_id.strip()
    canonical_hash = extract_canonical_hash(target_clean)

    with driver.session() as session:
        is_event = False
        terminal_event_ids: List[str] = []

        if canonical_hash:
            ev_check = session.run(
                "MATCH (e:Event {event_id: $eid}) RETURN e.event_id AS eid",
                eid=canonical_hash
            ).single()
            if ev_check:
                is_event = True
                terminal_event_ids = [ev_check["eid"]]

        if not is_event:
            # Find latest events for this batch
            end_query = """
            MATCH (e:Event)-[:OBSERVED|CONSUMED_IN|PRODUCED]->(b:Batch {batch_id: $bid})
            RETURN e.event_id AS eid
            ORDER BY e.event_time DESC
            LIMIT 5
            """
            records = session.run(end_query, bid=target_clean).data()
            if records:
                terminal_event_ids = [r["eid"] for r in records]
            else:
                p_query = """
                MATCH (e:Event)-[:OBSERVED|CONSUMED_IN|PRODUCED]->(b:Batch)-[:INSTANCE_OF]->(p:Product {product_id: $pid})
                RETURN e.event_id AS eid
                ORDER BY e.event_time DESC
                LIMIT 5
                """
                p_records = session.run(p_query, pid=target_clean).data()
                if p_records:
                    terminal_event_ids = [r["eid"] for r in p_records]

        if not terminal_event_ids:
            return None

        # Multi-hop Backward Traversal via (upstream)-[:PRECEDES*]->(end_ev)
        traversal_query = """
        MATCH path = (upstream:Event)-[:PRECEDES*0..50]->(end_ev:Event)
        WHERE end_ev.event_id IN $end_ids
        WITH DISTINCT upstream, length(path) AS depth
        ORDER BY upstream.event_time ASC
        LIMIT 250
        OPTIONAL MATCH (upstream)-[:OCCURRED_AT]->(loc:Location)
        OPTIONAL MATCH (upstream)-[:OBSERVED|CONSUMED_IN|PRODUCED]->(batch:Batch)
        RETURN upstream, loc, collect(DISTINCT batch.batch_id) AS batches, depth
        """
        results = session.run(traversal_query, end_ids=terminal_event_ids).data()

        if not results:
            return None

        event_ids = [r["upstream"]["event_id"] for r in results]

        edge_query = """
        MATCH (e1:Event)-[r:PRECEDES]->(e2:Event)
        WHERE e1.event_id IN $eids AND e2.event_id IN $eids
        RETURN DISTINCT e1.event_id AS src, e2.event_id AS dst, type(r) AS rel_type
        """
        edge_records = session.run(edge_query, eids=event_ids).data()

        nodes_dict: Dict[str, TraceNode] = {}
        edges_list: List[TraceEdge] = []
        timeline: List[TraceTimelineItem] = []
        max_hops = 0

        for r in results:
            ev = r["upstream"]
            loc = r.get("loc")
            batches = r.get("batches", [])
            depth = r.get("depth", 0)
            if depth > max_hops:
                max_hops = depth

            eid = ev["event_id"]
            if eid not in nodes_dict:
                nodes_dict[eid] = TraceNode(
                    id=eid,
                    label="Event",
                    title=f"{ev.get('biz_step', 'Event')} ({ev.get('type')})",
                    properties={
                        "event_type": ev.get("type"),
                        "biz_step": ev.get("biz_step"),
                        "event_time": ev.get("event_time"),
                        "action": ev.get("action")
                    }
                )

            loc_id = loc.get("location_id") if loc else None
            loc_name = loc.get("name") if loc else None
            loc_city = loc.get("city") if loc else None
            loc_state = loc.get("state") if loc else None

            if loc and loc_id:
                if loc_id not in nodes_dict:
                    nodes_dict[loc_id] = TraceNode(
                        id=loc_id,
                        label="Location",
                        title=loc_name or "Location",
                        properties={
                            "city": loc_city,
                            "state": loc_state,
                            "inferred_role": loc.get("inferred_role")
                        }
                    )
                edges_list.append(TraceEdge(
                    source=eid,
                    target=loc_id,
                    type="OCCURRED_AT"
                ))

            for b in batches:
                if b and b not in nodes_dict:
                    nodes_dict[b] = TraceNode(
                        id=b,
                        label="Batch",
                        title=f"Batch {b}",
                        properties={"batch_id": b}
                    )
                if b:
                    edges_list.append(TraceEdge(
                        source=eid,
                        target=b,
                        type="OBSERVED"
                    ))

            timeline.append(TraceTimelineItem(
                event_id=ev.get("raw_id") or eid,
                canonical_hash=eid,
                event_type=ev.get("type"),
                biz_step=ev.get("biz_step"),
                event_time=ev.get("event_time"),
                location_id=loc_id,
                location_name=loc_name,
                location_city=loc_city,
                location_state=loc_state,
                action=ev.get("action"),
                batch_ids=batches
            ))

        for er in edge_records:
            edges_list.append(TraceEdge(
                source=er["src"],
                target=er["dst"],
                type=er["rel_type"]
            ))

        return TraceResponse(
            query_target=target_id,
            direction="BACKWARD",
            total_hops=max_hops,
            events_count=len(timeline),
            nodes=list(nodes_dict.values()),
            edges=edges_list,
            timeline=timeline
        )


def get_provenance_summary(batch_id: str) -> Optional[ProvenanceResponse]:
    """
    Generate an auditable provenance report for a specific batch.
    Includes origin farm details, complete chain of custody, and handling facilities.
    """
    db = get_mongo_db()
    batch_doc = db.batches.find_one({"batch_id": batch_id})
    if not batch_doc:
        return None

    # Get product info
    prod_doc = db.products.find_one({"product_id": batch_doc.get("product_id")})
    prod_name = prod_doc.get("name") if prod_doc else f"Product {batch_doc.get('gtin')}"

    # Query chronological events from MongoDB
    events_cursor = db.trace_events.find(
        {"batch_ids": batch_id}
    ).sort("event_time", 1)
    events = list(events_cursor)

    if not events:
        return None

    # Collect actors
    actor_ids: Set[str] = {ev["location_id"] for ev in events if ev.get("location_id")}
    actors_docs = {a["actor_id"]: a for a in db.actors.find({"actor_id": {"$in": list(actor_ids)}})}

    # Actor handling stats
    actor_stats: Dict[str, Dict[str, Any]] = {}
    timeline: List[TraceTimelineItem] = []

    for ev in events:
        loc_id = ev.get("location_id")
        loc_doc = actors_docs.get(loc_id, {})
        loc_name = loc_doc.get("name", "Unknown Facility")
        addr = loc_doc.get("address", {})

        if loc_id:
            if loc_id not in actor_stats:
                actor_stats[loc_id] = {
                    "actor_id": loc_id,
                    "name": loc_name,
                    "city": addr.get("city"),
                    "state": addr.get("state"),
                    "inferred_role": loc_doc.get("inferred_role", "UNKNOWN"),
                    "events_handled": 0,
                    "steps": set()
                }
            actor_stats[loc_id]["events_handled"] += 1
            actor_stats[loc_id]["steps"].add(ev.get("biz_step"))

        timeline.append(TraceTimelineItem(
            event_id=ev["event_id"],
            canonical_hash=ev["canonical_hash"],
            event_type=ev["event_type"],
            biz_step=ev["biz_step"],
            event_time=ev.get("event_time_str"),
            location_id=loc_id,
            location_name=loc_name,
            location_city=addr.get("city"),
            location_state=addr.get("state"),
            action=ev.get("action"),
            batch_ids=ev.get("batch_ids", [])
        ))

    actors_summary = [
        ActorHandlingSummary(
            actor_id=info["actor_id"],
            name=info["name"],
            city=info["city"],
            state=info["state"],
            inferred_role=info["inferred_role"],
            events_handled=info["events_handled"],
            steps_executed=sorted(list(info["steps"]))
        )
        for info in actor_stats.values()
    ]

    first_ev = events[0]
    last_ev = events[-1]
    first_loc = actors_docs.get(first_ev.get("location_id"), {})
    last_loc = actors_docs.get(last_ev.get("location_id"), {})

    return ProvenanceResponse(
        batch_id=batch_id,
        gtin=batch_doc.get("gtin", ""),
        lot_number=batch_doc.get("lot_number", ""),
        product_name=prod_name,
        origin_facility={
            "id": first_loc.get("actor_id"),
            "name": first_loc.get("name"),
            "city": first_loc.get("address", {}).get("city"),
            "state": first_loc.get("address", {}).get("state"),
            "role": first_loc.get("inferred_role")
        } if first_loc else None,
        origin_time=first_ev.get("event_time_str"),
        latest_facility={
            "id": last_loc.get("actor_id"),
            "name": last_loc.get("name"),
            "city": last_loc.get("address", {}).get("city"),
            "state": last_loc.get("address", {}).get("state"),
            "role": last_loc.get("inferred_role")
        } if last_loc else None,
        latest_time=last_ev.get("event_time_str"),
        latest_step=last_ev.get("biz_step"),
        actors_count=len(actors_summary),
        actors_involved=actors_summary,
        total_events=len(timeline),
        timeline=timeline
    )


def evaluate_cold_chain(batch_id: str, include_simulated: bool = False) -> Optional[ColdChainResponse]:
    """
    Evaluate cold-chain compliance for a batch.
    Per Section 20 of project requirements:
    - Never claim "SAFE" when no sensors exist in source dataset.
    - Default status is strictly "NO_SENSOR_DATA".
    - If include_simulated=True, generates marked SIMULATED readings for demonstration.
    """
    db = get_mongo_db()
    batch_doc = db.batches.find_one({"batch_id": batch_id})
    if not batch_doc:
        return None

    if not include_simulated:
        return ColdChainResponse(
            batch_id=batch_id,
            status="NO_SENSOR_DATA",
            has_sensor_data=False,
            is_simulated=False,
            message="No physical temperature/humidity sensor elements were present in the source EPCIS 2.0 dataset for this batch.",
            temperature_range_celsius=None,
            readings=[],
            data_origin="SOURCE"
        )

    # Simulated Cold Chain Demonstration
    events = list(db.trace_events.find({"batch_ids": batch_id}).sort("event_time", 1))
    readings: List[ColdChainReading] = []
    base_temp = 3.8
    has_violation = False

    for i, ev in enumerate(events):
        etime = ev.get("event_time") or datetime.now(timezone.utc)
        loc_id = ev.get("location_id")
        loc_name = "Transit Hub"
        if loc_id:
            loc_doc = db.actors.find_one({"actor_id": loc_id})
            if loc_doc:
                loc_name = loc_doc.get("name", "Transit Hub")

        # Create reading at event time
        reading_time = etime.isoformat() if isinstance(etime, datetime) else str(etime)

        # Introduce a temperature violation during shipping steps for demo
        is_shipping = ev.get("biz_step") == "shipping" and (i % 3 == 0)
        temp = round(base_temp + (random.uniform(4.5, 6.0) if is_shipping else random.uniform(-0.8, 0.9)), 1)
        humidity = round(random.uniform(82.0, 91.0), 1)

        is_excursion = temp > 7.0
        if is_excursion:
            has_violation = True

        readings.append(ColdChainReading(
            timestamp=reading_time,
            temperature_celsius=temp,
            humidity_percent=humidity,
            facility_name=loc_name,
            status="EXCURSION" if is_excursion else "NORMAL",
            data_origin="SIMULATED"
        ))

    overall_status = "VIOLATION_DETECTED" if has_violation else "NORMAL"
    temps = [r.temperature_celsius for r in readings] if readings else [0.0]

    return ColdChainResponse(
        batch_id=batch_id,
        status=overall_status,
        has_sensor_data=True,
        is_simulated=True,
        message="Simulated telematics generated strictly for demonstration and testing of cold-chain violation alerts.",
        temperature_range_celsius={
            "min": min(temps),
            "max": max(temps),
            "safe_max_threshold": 7.0
        },
        readings=readings,
        data_origin="SIMULATED"
    )

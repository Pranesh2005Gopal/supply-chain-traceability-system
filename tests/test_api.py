"""
End-to-End API Integration Tests.
Verifies all REST API endpoints against live seeded databases (MongoDB, Neo4j, Redis).
BCSE406L - NoSQL Databases
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.mongo import get_mongo_db

client = TestClient(app)


# ---------------- PRODUCTS ----------------

def test_list_products_seeded():
    """Verify listing seeded products returns 200 with total 413."""
    response = client.get("/api/v1/products?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 413
    assert len(data["items"]) == 10
    sample = data["items"][0]
    assert "product_id" in sample
    assert "name" in sample
    assert sample["data_origin"] in ["SOURCE", "INFERRED"]


def test_get_product_detail():
    """Verify retrieving an authentic seeded product by GTIN."""
    response = client.get("/api/v1/products/94011508952714")
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == "94011508952714"
    assert data["data_origin"] == "SOURCE"


def test_get_product_not_found():
    """Verify 404 for nonexistent product."""
    response = client.get("/api/v1/products/00000000000000")
    assert response.status_code == 404


def test_create_product_and_conflict():
    """Verify registering a new product and rejecting duplicate GTINs."""
    test_gtin = "88888888888888"
    db = get_mongo_db()
    db.products.delete_one({"product_id": test_gtin})

    # Create
    payload = {
        "product_id": test_gtin,
        "name": "API Test Organic Apples",
        "description": "Crisp red organic apples",
        "uri": f"https://id.gs1.org/01/{test_gtin}"
    }
    res1 = client.post("/api/v1/products", json=payload)
    assert res1.status_code == 201
    assert res1.json()["product_id"] == test_gtin

    # Duplicate -> 409 Conflict
    res2 = client.post("/api/v1/products", json=payload)
    assert res2.status_code == 409

    # Clean up
    db.products.delete_one({"product_id": test_gtin})


# ---------------- BATCHES ----------------

def test_list_batches_seeded():
    """Verify listing seeded batches returns 200 with total 377."""
    response = client.get("/api/v1/batches?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 377
    assert len(data["items"]) == 10
    sample = data["items"][0]
    assert ":" in sample["batch_id"]
    assert sample["lot_number"] is not None


def test_get_batch_detail():
    """Verify retrieving a seeded batch by compound ID."""
    response = client.get("/api/v1/batches/94011508952714:48300")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "94011508952714:48300"
    assert data["lot_number"] == "48300"
    assert data["gtin"] == "94011508952714"


def test_create_batch_requires_parent_product():
    """Verify batch creation fails if parent product does not exist."""
    payload = {
        "product_id": "00000000000000",
        "lot_number": "ORPHAN-LOT-01"
    }
    response = client.post("/api/v1/batches", json=payload)
    assert response.status_code == 400


# ---------------- ACTORS ----------------

def test_list_actors_seeded():
    """Verify listing actors/facilities returns total 214 with inferred roles."""
    response = client.get("/api/v1/actors?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 214
    assert len(data["items"]) == 10
    sample = data["items"][0]
    assert sample["role_origin"] == "INFERRED"
    assert sample["inferred_role"] in [
        "HARVESTER_PRODUCER",
        "PROCESSOR_MANUFACTURER",
        "DISTRIBUTOR_HUB",
        "RETAILER_POINT_OF_SALE"
    ]


def test_get_actor_detail():
    """Verify retrieving an authentic facility with real address and coordinates."""
    aid = "https://id.gs1.org/414/0012230422385/254/57129"
    response = client.get(f"/api/v1/actors/{aid}")
    assert response.status_code == 200
    data = response.json()
    assert data["actor_id"] == aid
    assert data["name"] == "Coleman, Kennedy and Henderson"
    assert data["geo_location"] is not None
    assert len(data["geo_location"]["coordinates"]) == 2


# ---------------- TRACE EVENTS (APPEND-ONLY) ----------------

def test_list_trace_events_seeded():
    """Verify listing events returns 200 with total 5,650."""
    response = client.get("/api/v1/events?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 5650
    assert len(data["items"]) == 10


def test_filter_trace_events_by_biz_step():
    """Verify filtering events by biz_step='collecting' returns 100 root events."""
    response = client.get("/api/v1/events?biz_step=collecting&limit=200")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 100
    assert all(e["biz_step"] == "collecting" for e in data["items"])


def test_get_trace_event_by_hash_and_ni_uri():
    """Verify retrieving an event by canonical hash and NI URI."""
    h = "7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa"
    res1 = client.get(f"/api/v1/events/{h}")
    assert res1.status_code == 200
    assert res1.json()["canonical_hash"] == h

    ni = f"ni:///sha-256;{h}?ver=CBV2.0"
    res2 = client.get(f"/api/v1/events/{ni}")
    assert res2.status_code == 200
    assert res2.json()["canonical_hash"] == h


def test_append_only_event_creation():
    """Verify appending a new event succeeds and populates MongoDB and Neo4j."""
    payload = {
        "event_type": "ObjectEvent",
        "biz_step": "shipping",
        "action": "ADD",
        "location_id": "https://id.gs1.org/414/0012230422385/254/57129",
        "batch_ids": ["94011508952714:48300"],
        "prev_event_ids": ["7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa"]
    }
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["canonical_hash"] is not None
    assert data["data_origin"] == "APPLICATION"
    assert data["biz_step"] == "shipping"

    # Clean up test event from MongoDB
    db = get_mongo_db()
    db.trace_events.delete_one({"_id": data["canonical_hash"]})


# ---------------- TRACEABILITY (FORWARD / BACKWARD / PROVENANCE) ----------------

def test_forward_trace():
    """Verify forward trace returns downstream graph and chronological timeline."""
    target = "94011508952714:48300"
    response = client.get(f"/api/v1/trace/forward/{target}")
    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "FORWARD"
    assert data["events_count"] > 0
    assert len(data["nodes"]) > 0
    assert len(data["timeline"]) > 0


def test_backward_trace():
    """Verify backward trace traverses back to root harvest origins."""
    target = "94011508952714:48300"
    response = client.get(f"/api/v1/trace/backward/{target}")
    assert response.status_code == 200
    data = response.json()
    assert data["direction"] == "BACKWARD"
    assert data["events_count"] > 0
    assert len(data["nodes"]) > 0
    # First item in timeline must be the collecting/packing step
    assert data["timeline"][0]["biz_step"] in ["collecting", "packing", "commissioning"]


def test_provenance_summary():
    """Verify provenance report returns origin farm, actors, and custody chain."""
    target = "94011508952714:48300"
    response = client.get(f"/api/v1/trace/provenance/{target}")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == target
    assert data["origin_facility"] is not None
    assert data["actors_count"] >= 1
    assert len(data["actors_involved"]) >= 1
    assert data["total_events"] > 0


# ---------------- PUBLIC QR LOOKUP & COLD CHAIN ----------------

def test_public_qr_trace_cached():
    """Verify public verification lookup returns 200 and leverages Redis cache."""
    target = "94011508952714:48300"
    res1 = client.get(f"/api/v1/public/trace/{target}")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["batch_id"] == target
    assert data1["verified_origin_facility"] is not None
    assert data1["data_origin"] == "SOURCE"

    # Second call (Redis cached)
    res2 = client.get(f"/api/v1/public/trace/{target}")
    assert res2.status_code == 200
    assert res2.json() == data1


def test_cold_chain_source_truth_vs_simulated():
    """
    Verify Section 20 requirement:
    - Default returns NO_SENSOR_DATA (preserving source truth).
    - include_simulated=true returns labeled SIMULATED telematics.
    """
    target = "94011508952714:48300"

    # Default -> strictly NO_SENSOR_DATA
    res_source = client.get(f"/api/v1/cold-chain/{target}")
    assert res_source.status_code == 200
    data_source = res_source.json()
    assert data_source["status"] == "NO_SENSOR_DATA"
    assert data_source["has_sensor_data"] is False
    assert data_source["is_simulated"] is False
    assert data_source["data_origin"] == "SOURCE"

    # Simulated demo mode -> labeled SIMULATED
    res_sim = client.get(f"/api/v1/cold-chain/{target}?include_simulated=true")
    assert res_sim.status_code == 200
    data_sim = res_sim.json()
    assert data_sim["is_simulated"] is True
    assert data_sim["data_origin"] == "SIMULATED"
    assert len(data_sim["readings"]) > 0


# ---------------- EXPORT ----------------

def test_export_events_json_and_csv():
    """Verify exporting events in JSON and CSV formats."""
    # JSON export
    res_json = client.get("/api/v1/export/events?limit=5&format=json")
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers["content-type"]

    # CSV export
    res_csv = client.get("/api/v1/export/events?limit=5&format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "canonical_hash,event_type,biz_step" in res_csv.text

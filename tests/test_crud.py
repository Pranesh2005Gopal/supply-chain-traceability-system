"""
CRUD and Reference Integrity Tests.
Verifies Create, Read, Update, and Delete operations for Products, Batches, and Actors.
Verifies reference checks preventing orphaning of historical records.
Verifies that Trace Events remain strictly Append-Only (PUT/PATCH/DELETE forbidden).
BCSE406L - NoSQL Databases
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver

client = TestClient(app)


# ---------------- PRODUCT CRUD ----------------

def test_product_full_crud_lifecycle():
    """Test full CRUD lifecycle for Products including update and safe deletion."""
    test_pid = "77777777777777"
    db = get_mongo_db()
    db.products.delete_one({"product_id": test_pid})

    # 1. CREATE
    create_payload = {
        "product_id": test_pid,
        "name": "CRUD Test Milk",
        "description": "Initial description",
        "uri": f"https://id.gs1.org/01/{test_pid}"
    }
    res_c = client.post("/api/v1/products", json=create_payload)
    assert res_c.status_code == 201
    assert res_c.json()["name"] == "CRUD Test Milk"
    assert res_c.json()["data_origin"] == "APPLICATION"

    # 2. READ
    res_r = client.get(f"/api/v1/products/{test_pid}")
    assert res_r.status_code == 200
    assert res_r.json()["product_id"] == test_pid

    # 3. UPDATE
    update_payload = {
        "name": "CRUD Test Milk (Ultra Pasteurized)",
        "description": "Updated rich organic taste"
    }
    res_u = client.put(f"/api/v1/products/{test_pid}", json=update_payload)
    assert res_u.status_code == 200
    assert res_u.json()["name"] == "CRUD Test Milk (Ultra Pasteurized)"

    # Verify Neo4j was updated
    driver = get_neo4j_driver()
    with driver.session() as session:
        n_name = session.run("MATCH (p:Product {product_id: $pid}) RETURN p.name AS name", pid=test_pid).single()["name"]
        assert n_name == "CRUD Test Milk (Ultra Pasteurized)"

    # 4. DELETE (Safe: no batches or events reference it)
    res_d = client.delete(f"/api/v1/products/{test_pid}")
    assert res_d.status_code == 200
    assert res_d.json()["success"] is True

    # Verify deleted from Mongo and Neo4j
    assert db.products.find_one({"product_id": test_pid}) is None
    with driver.session() as session:
        cnt = session.run("MATCH (p:Product {product_id: $pid}) RETURN count(p) AS cnt", pid=test_pid).single()["cnt"]
        assert cnt == 0


def test_product_delete_blocked_when_referenced():
    """Verify that deleting a product with existing batches or trace events is rejected with 409."""
    # Seeded product with existing batches and events
    seeded_pid = "94011508952714"
    res = client.delete(f"/api/v1/products/{seeded_pid}")
    assert res.status_code == 409
    assert "referenced by" in res.json()["detail"].lower()


# ---------------- BATCH CRUD ----------------

def test_batch_full_crud_lifecycle():
    """Test full CRUD lifecycle for Batches."""
    db = get_mongo_db()
    test_pid = "94011508952714"  # Existing product
    test_lot = "LOT-CRUD-TEST-01"
    test_bid = f"{test_pid}:{test_lot}"

    # Clean up prior test data
    db.batches.delete_one({"batch_id": test_bid})

    # 1. CREATE
    create_payload = {
        "product_id": test_pid,
        "lot_number": test_lot,
        "origin_location_id": "https://id.gs1.org/414/0012230422385/254/57129"
    }
    res_c = client.post("/api/v1/batches", json=create_payload)
    assert res_c.status_code == 201
    assert res_c.json()["batch_id"] == test_bid

    # 2. READ
    res_r = client.get(f"/api/v1/batches/{test_bid}")
    assert res_r.status_code == 200
    assert res_r.json()["lot_number"] == test_lot

    # 3. UPDATE
    update_payload = {
        "origin_location_id": "https://id.gs1.org/414/0012634065522/254/68738"
    }
    res_u = client.put(f"/api/v1/batches/{test_bid}", json=update_payload)
    assert res_u.status_code == 200
    assert res_u.json()["origin_location_id"] == "https://id.gs1.org/414/0012634065522/254/68738"

    # 4. DELETE (Safe: no events reference this new batch)
    res_d = client.delete(f"/api/v1/batches/{test_bid}")
    assert res_d.status_code == 200
    assert res_d.json()["success"] is True

    # Verify deleted from Mongo
    assert db.batches.find_one({"batch_id": test_bid}) is None


def test_batch_delete_blocked_when_referenced_in_trace_events():
    """Verify that deleting an authentic batch with historical trace events is blocked with 409."""
    seeded_bid = "94011508952714:48300"
    res = client.delete(f"/api/v1/batches/{seeded_bid}")
    assert res.status_code == 409
    assert "historical trace event" in res.json()["detail"].lower()


# ---------------- ACTOR CRUD ----------------

def test_actor_full_crud_lifecycle():
    """Test full CRUD lifecycle for Actors/Facilities."""
    test_aid = "https://id.gs1.org/414/TEST_ACTOR/254/999"
    db = get_mongo_db()
    db.actors.delete_one({"actor_id": test_aid})

    # 1. CREATE
    create_payload = {
        "actor_id": test_aid,
        "name": "Greenfield Organic Processing",
        "address": {
            "street": "500 Farm Way",
            "city": "Austin",
            "state": "Texas",
            "postal_code": "78701",
            "country_code": "US"
        },
        "latitude": 30.2672,
        "longitude": -97.7431,
        "role": "PROCESSOR_MANUFACTURER"
    }
    res_c = client.post("/api/v1/actors", json=create_payload)
    assert res_c.status_code == 201
    assert res_c.json()["name"] == "Greenfield Organic Processing"

    # 2. READ
    res_r = client.get(f"/api/v1/actors/{test_aid}")
    assert res_r.status_code == 200
    assert res_r.json()["actor_id"] == test_aid

    # 3. UPDATE
    update_payload = {
        "name": "Greenfield Organic Processing (Main Campus)",
        "role": "DISTRIBUTOR_HUB"
    }
    res_u = client.put(f"/api/v1/actors/{test_aid}", json=update_payload)
    assert res_u.status_code == 200
    assert res_u.json()["name"] == "Greenfield Organic Processing (Main Campus)"
    assert res_u.json()["inferred_role"] == "DISTRIBUTOR_HUB"

    # 4. DELETE (Safe: no events reference this test facility)
    res_d = client.delete(f"/api/v1/actors/{test_aid}")
    assert res_d.status_code == 200
    assert res_d.json()["success"] is True

    # Verify deleted from Mongo and Neo4j
    assert db.actors.find_one({"actor_id": test_aid}) is None
    driver = get_neo4j_driver()
    with driver.session() as session:
        cnt = session.run("MATCH (l:Location {location_id: $lid}) RETURN count(l) AS cnt", lid=test_aid).single()["cnt"]
        assert cnt == 0


def test_actor_delete_blocked_when_referenced():
    """Verify that deleting a facility with historical events is rejected with 409."""
    seeded_aid = "https://id.gs1.org/414/0012230422385/254/57129"
    res = client.delete(f"/api/v1/actors/{seeded_aid}")
    assert res.status_code == 409
    assert "referenced by" in res.json()["detail"].lower()


# ---------------- TRACE EVENTS STRICT APPEND-ONLY ----------------

def test_trace_events_immutable_no_update_or_delete():
    """
    CRITICAL AUDIT REQUIREMENT:
    Verify that trace events cannot be updated or deleted.
    PUT, PATCH, and DELETE requests MUST return 405 Method Not Allowed.
    """
    event_id = "7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa"

    res_put = client.put(f"/api/v1/events/{event_id}", json={"biz_step": "tampered"})
    assert res_put.status_code == 405

    res_patch = client.patch(f"/api/v1/events/{event_id}", json={"biz_step": "tampered"})
    assert res_patch.status_code == 405

    res_delete = client.delete(f"/api/v1/events/{event_id}")
    assert res_delete.status_code == 405

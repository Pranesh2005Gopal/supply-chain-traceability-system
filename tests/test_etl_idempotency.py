"""
Tests for ETL Idempotency across MongoDB and Neo4j.
Verifies that duplicate loads do not produce duplicate records or relationships.
"""

import pytest
from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver

from etl.mongo_loader import (
    setup_mongo_indexes,
    load_master_data_to_mongo,
    load_events_batch_to_mongo
)
from etl.neo4j_loader import (
    setup_neo4j_constraints,
    load_locations_to_neo4j,
    load_products_and_batches_to_neo4j,
    load_events_batch_to_neo4j
)


def test_mongo_index_idempotency():
    """Verify setup_mongo_indexes can be run multiple times safely."""
    db = get_mongo_db()
    idx1 = setup_mongo_indexes(db)
    idx2 = setup_mongo_indexes(db)
    assert idx1 == idx2


def test_neo4j_constraint_idempotency():
    """Verify setup_neo4j_constraints can be run multiple times safely."""
    driver = get_neo4j_driver()
    c1 = setup_neo4j_constraints(driver)
    c2 = setup_neo4j_constraints(driver)
    assert len(c1) == len(c2) == 4


def test_mongo_master_data_idempotency():
    """Verify bulk upserting master data twice does not duplicate records in MongoDB."""
    db = get_mongo_db()

    sample_locations = [
        {
            "_id": "https://id.gs1.org/414/0000000000000/254/99999",
            "actor_id": "https://id.gs1.org/414/0000000000000/254/99999",
            "location_id": "https://id.gs1.org/414/0000000000000/254/99999",
            "name": "Test Test Facility",
            "inferred_role": "DISTRIBUTOR_HUB",
            "data_origin": "TEST"
        }
    ]
    sample_products = [
        {
            "_id": "99999999999999",
            "product_id": "99999999999999",
            "gtin": "99999999999999",
            "name": "Test Product",
            "data_origin": "TEST"
        }
    ]
    sample_batches = [
        {
            "_id": "99999999999999:TESTLOT1",
            "batch_id": "99999999999999:TESTLOT1",
            "gtin": "99999999999999",
            "lot_number": "TESTLOT1",
            "product_id": "99999999999999",
            "data_origin": "TEST"
        }
    ]

    # First load
    load_master_data_to_mongo(db, sample_locations, sample_products, sample_batches)
    count1 = db.actors.count_documents({"_id": sample_locations[0]["_id"]})
    p_count1 = db.products.count_documents({"_id": sample_products[0]["_id"]})
    b_count1 = db.batches.count_documents({"_id": sample_batches[0]["_id"]})

    assert count1 == 1
    assert p_count1 == 1
    assert b_count1 == 1

    # Second load (Idempotency test)
    load_master_data_to_mongo(db, sample_locations, sample_products, sample_batches)
    count2 = db.actors.count_documents({"_id": sample_locations[0]["_id"]})
    p_count2 = db.products.count_documents({"_id": sample_products[0]["_id"]})
    b_count2 = db.batches.count_documents({"_id": sample_batches[0]["_id"]})

    assert count2 == 1
    assert p_count2 == 1
    assert b_count2 == 1

    # Clean up test records
    db.actors.delete_one({"_id": sample_locations[0]["_id"]})
    db.products.delete_one({"_id": sample_products[0]["_id"]})
    db.batches.delete_one({"_id": sample_batches[0]["_id"]})


def test_neo4j_nodes_idempotency():
    """Verify merging nodes in Neo4j twice does not duplicate nodes."""
    driver = get_neo4j_driver()
    setup_neo4j_constraints(driver)

    sample_locations = [
        {
            "location_id": "https://id.gs1.org/414/TEST_LOC/254/001",
            "name": "Idempotency Test Facility",
            "address": {"city": "Test City", "state": "TS"},
            "inferred_role": "TEST_ROLE"
        }
    ]

    # Load 1
    load_locations_to_neo4j(driver, sample_locations)
    with driver.session() as session:
        c1 = session.run(
            "MATCH (l:Location {location_id: $id}) RETURN count(l) AS cnt",
            id=sample_locations[0]["location_id"]
        ).single()["cnt"]
    assert c1 == 1

    # Load 2
    load_locations_to_neo4j(driver, sample_locations)
    with driver.session() as session:
        c2 = session.run(
            "MATCH (l:Location {location_id: $id}) RETURN count(l) AS cnt",
            id=sample_locations[0]["location_id"]
        ).single()["cnt"]
    assert c2 == 1

    # Cleanup
    with driver.session() as session:
        session.run("MATCH (l:Location {location_id: $id}) DETACH DELETE l", id=sample_locations[0]["location_id"])

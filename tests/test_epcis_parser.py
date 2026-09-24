"""
Unit Tests for EPCIS 2.0 Parser and Normalization Utilities.
"""

import pytest
from datetime import datetime

from etl.parser import (
    extract_canonical_hash,
    parse_gs1_digital_link,
    parse_geo_location,
    infer_actor_role,
    normalize_event,
)


def test_extract_canonical_hash():
    """Verify hash extraction from various GS1 NI URI and hex formats."""
    ni_uri = "ni:///sha-256;7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa?ver=CBV2.0"
    expected = "7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa"
    assert extract_canonical_hash(ni_uri) == expected

    # Raw 64-char uppercase hex
    raw_hex = "7BD8D447674856A54B09E5F802C10C20D2B1C972DD1B9C38D141BE415678B5AA"
    assert extract_canonical_hash(raw_hex) == expected

    # Empty / None
    assert extract_canonical_hash(None) is None
    assert extract_canonical_hash("") is None


def test_parse_gs1_digital_link():
    """Verify parsing of GTIN, Lot, Serial, and GLN extension from GS1 Digital Link URIs."""
    # GTIN + Lot
    gtin_lot_uri = "https://id.gs1.org/01/94011508952714/10/48300"
    res1 = parse_gs1_digital_link(gtin_lot_uri)
    assert res1["gtin"] == "94011508952714"
    assert res1["lot"] == "48300"
    assert res1["compound_batch_id"] == "94011508952714:48300"

    # Pure GTIN
    pure_gtin_uri = "https://id.gs1.org/01/64010405743141"
    res2 = parse_gs1_digital_link(pure_gtin_uri)
    assert res2["gtin"] == "64010405743141"
    assert res2["lot"] is None

    # Serialized GTIN
    serial_uri = "https://id.gs1.org/01/64010405743141/21/66100"
    res3 = parse_gs1_digital_link(serial_uri)
    assert res3["gtin"] == "64010405743141"
    assert res3["serial"] == "66100"

    # GLN Location
    gln_uri = "https://id.gs1.org/414/0012230422385/254/57129"
    res4 = parse_gs1_digital_link(gln_uri)
    assert res4["gln"] == "0012230422385"
    assert res4["extension"] == "57129"


def test_parse_geo_location():
    """Verify parsing of geo:lat,lon to GeoJSON [lon, lat] coordinates."""
    geo_str = "geo:43.1009,-75.23266"
    coords = parse_geo_location(geo_str)
    assert coords == [-75.23266, 43.1009]  # Lon, Lat for 2dsphere

    assert parse_geo_location("invalid") is None
    assert parse_geo_location(None) is None


def test_infer_actor_role():
    """Verify deterministic actor role classification from business steps."""
    role, _ = infer_actor_role({"commissioning", "shipping", "receiving"})
    assert role == "PROCESSOR_MANUFACTURER"

    role, _ = infer_actor_role({"collecting", "packing", "shipping"})
    assert role == "HARVESTER_PRODUCER"

    role, _ = infer_actor_role({"receiving"})
    assert role == "RETAILER_POINT_OF_SALE"

    role, _ = infer_actor_role({"receiving", "shipping"})
    assert role == "DISTRIBUTOR_HUB"


def test_normalize_event():
    """Verify event normalization preserving raw payload and populating structured fields."""
    sample_raw = {
        "type": "ObjectEvent",
        "eventID": "ni:///sha-256;7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa?ver=CBV2.0",
        "action": "ADD",
        "bizStep": "collecting",
        "eventTime": "2024-01-01T00:31:02.000000+00:00",
        "eventTimeZoneOffset": "+00:00",
        "recordTime": "2025-03-24T14:27:46.705605+00:00",
        "bizLocation": {"id": "https://id.gs1.org/414/0012634065522/254/68738"},
        "readPoint": {"id": "https://id.gs1.org/414/0012634065522/254/68738"},
        "quantityList": [
            {
                "epcClass": "https://id.gs1.org/01/94011508952714/10/48300",
                "quantity": 1,
                "uom": "LBS"
            }
        ]
    }

    normalized = normalize_event(sample_raw)

    assert normalized["canonical_hash"] == "7bd8d447674856a54b09e5f802c10c20d2b1c972dd1b9c38d141be415678b5aa"
    assert normalized["event_type"] == "ObjectEvent"
    assert normalized["biz_step"] == "collecting"
    assert normalized["batch_ids"] == ["94011508952714:48300"]
    assert normalized["product_ids"] == ["94011508952714"]
    assert normalized["location_id"] == "https://id.gs1.org/414/0012634065522/254/68738"
    assert normalized["prev_event_hashes"] == []
    assert normalized["data_origin"] == "SOURCE"
    assert normalized["raw_epcis_payload"] == sample_raw
    assert isinstance(normalized["event_time"], datetime)

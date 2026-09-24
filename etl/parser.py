"""
EPCIS 2.0 Dataset Parser and Normalization Utilities.
BCSE406L - NoSQL Databases
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set


def extract_canonical_hash(uri_or_hash: Optional[str]) -> Optional[str]:
    """
    Extract a normalized 64-character lowercase SHA-256 hash from an EPCIS event ID
    or fdaftr:prevID reference.
    Handles NI URIs such as: ni:///sha-256;<hash>?ver=CBV2.0
    and raw hex strings: <hash>
    """
    if not uri_or_hash:
        return None
    uri_clean = str(uri_or_hash).strip()
    match = re.search(r"sha-256;([a-fA-F0-9]{64})", uri_clean)
    if match:
        return match.group(1).lower()
    if re.match(r"^[a-fA-F0-9]{64}$", uri_clean):
        return uri_clean.lower()
    return uri_clean


def parse_gs1_digital_link(uri: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Parse GS1 Digital Link URIs into their constituent Application Identifiers (AIs).
    Supported formats:
    - Product + Lot: https://id.gs1.org/01/<GTIN>/10/<LOT>
    - Product only:  https://id.gs1.org/01/<GTIN>
    - Aggregation:   https://id.gs1.org/01/<GTIN>/21/<SERIAL>
    - Location:      https://id.gs1.org/414/<GLN>/254/<EXTENSION>
    """
    result = {
        "gtin": None,
        "lot": None,
        "serial": None,
        "gln": None,
        "extension": None,
        "compound_batch_id": None
    }
    if not uri:
        return result

    uri_str = str(uri).strip()

    # Match GTIN + Lot
    m_gtin_lot = re.match(r"https?://id\.gs1\.org/01/(\d+)/10/([a-zA-Z0-9_\-]+)", uri_str)
    if m_gtin_lot:
        result["gtin"] = m_gtin_lot.group(1)
        result["lot"] = m_gtin_lot.group(2)
        result["compound_batch_id"] = f"{result['gtin']}:{result['lot']}"
        return result

    # Match GTIN + Serial
    m_gtin_serial = re.match(r"https?://id\.gs1\.org/01/(\d+)/21/([a-zA-Z0-9_\-]+)", uri_str)
    if m_gtin_serial:
        result["gtin"] = m_gtin_serial.group(1)
        result["serial"] = m_gtin_serial.group(2)
        return result

    # Match pure GTIN
    m_gtin = re.match(r"https?://id\.gs1\.org/01/(\d+)", uri_str)
    if m_gtin:
        result["gtin"] = m_gtin.group(1)
        return result

    # Match Location GLN + Extension
    m_loc = re.match(r"https?://id\.gs1\.org/414/(\d+)/254/([a-zA-Z0-9_\-]+)", uri_str)
    if m_loc:
        result["gln"] = m_loc.group(1)
        result["extension"] = m_loc.group(2)
        return result

    return result


def parse_geo_location(geo_str: Optional[str]) -> Optional[List[float]]:
    """
    Parse EPCIS geo string 'geo:lat,lon' into GeoJSON coordinate format [longitude, latitude].
    Returns [lon, lat] for MongoDB 2dsphere indexing.
    """
    if not geo_str or not geo_str.startswith("geo:"):
        return None
    try:
        coords_part = geo_str[4:].strip()
        parts = coords_part.split(",")
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            return [lon, lat]
    except (ValueError, IndexError):
        pass
    return None


def infer_actor_role(business_steps: Set[str]) -> Tuple[str, str]:
    """
    Infer actor operational role from observed EPCIS business step patterns.
    Returns (role_code, rule_explanation).
    """
    if "commissioning" in business_steps:
        return (
            "PROCESSOR_MANUFACTURER",
            "Executes transformation events (commissioning) producing new product lots"
        )
    if "collecting" in business_steps or "packing" in business_steps:
        return (
            "HARVESTER_PRODUCER",
            "Executes initial harvest collection and initial lot packing"
        )
    if business_steps == {"receiving"}:
        return (
            "RETAILER_POINT_OF_SALE",
            "Executes only receiving steps as terminal consumer distribution point"
        )
    return (
        "DISTRIBUTOR_HUB",
        "Executes transit shipping and receiving cross-dock operations"
    )


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 string to Python datetime."""
    if not dt_str:
        return None
    try:
        # Replace trailing 'Z' if present
        cleaned = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


def normalize_quantity_item(q_item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a single quantity record."""
    epc_class = q_item.get("epcClass", "")
    parsed = parse_gs1_digital_link(epc_class)
    return {
        "epc_class": epc_class,
        "gtin": parsed["gtin"],
        "lot": parsed["lot"],
        "batch_id": parsed["compound_batch_id"],
        "quantity": float(q_item.get("quantity", 1.0)),
        "uom": q_item.get("uom", "LBS")
    }


def normalize_event(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a raw EPCIS event dictionary into a clean, normalized document
    ready for MongoDB and Neo4j loading while preserving the raw source payload.
    """
    raw_event_id = event_dict.get("eventID", "")
    canonical_hash = extract_canonical_hash(raw_event_id)

    # Normalize prevIDs
    raw_prev_ids = event_dict.get("fdaftr:prevID", [])
    if isinstance(raw_prev_ids, str):
        raw_prev_ids = [raw_prev_ids]
    prev_hashes = [extract_canonical_hash(p) for p in raw_prev_ids if p]

    # Location & ReadPoint
    location_id = event_dict.get("bizLocation", {}).get("id")
    read_point_id = event_dict.get("readPoint", {}).get("id")

    # Quantities & involved items
    quantities = [normalize_quantity_item(q) for q in event_dict.get("quantityList", [])]
    child_quantities = [normalize_quantity_item(q) for q in event_dict.get("childQuantityList", [])]
    input_quantities = [normalize_quantity_item(q) for q in event_dict.get("inputQuantityList", [])]
    output_quantities = [normalize_quantity_item(q) for q in event_dict.get("outputQuantityList", [])]

    # Collect all unique batch IDs and product IDs involved in this event
    batch_ids: Set[str] = set()
    product_ids: Set[str] = set()

    for item in quantities + child_quantities + input_quantities + output_quantities:
        if item.get("batch_id"):
            batch_ids.add(item["batch_id"])
        if item.get("gtin"):
            product_ids.add(item["gtin"])

    # Sources & Destinations
    sources = [
        {"type": s.get("type", "location"), "location_id": s.get("source")}
        for s in event_dict.get("sourceList", []) if s.get("source")
    ]
    destinations = [
        {"type": d.get("type", "location"), "location_id": d.get("destination")}
        for d in event_dict.get("destinationList", []) if d.get("destination")
    ]

    event_time_str = event_dict.get("eventTime")
    record_time_str = event_dict.get("recordTime")

    return {
        "_id": canonical_hash,
        "canonical_hash": canonical_hash,
        "event_id": raw_event_id,
        "event_type": event_dict.get("type"),
        "action": event_dict.get("action"),
        "biz_step": event_dict.get("bizStep"),
        "event_time": parse_iso_datetime(event_time_str),
        "event_time_str": event_time_str,
        "record_time": parse_iso_datetime(record_time_str),
        "record_time_str": record_time_str,
        "timezone_offset": event_dict.get("eventTimeZoneOffset", "+00:00"),
        "location_id": location_id,
        "read_point_id": read_point_id,
        "prev_event_hashes": prev_hashes,
        "parent_id": event_dict.get("parentID"),
        "batch_ids": sorted(list(batch_ids)),
        "product_ids": sorted(list(product_ids)),
        "quantities": quantities,
        "child_quantities": child_quantities,
        "transformation_inputs": input_quantities,
        "transformation_outputs": output_quantities,
        "sources": sources,
        "destinations": destinations,
        "data_origin": "SOURCE",
        "raw_epcis_payload": event_dict
    }


def parse_master_data(
    epcis_doc: Dict[str, Any],
    events: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extract actors (locations), products, and batches from master data and events.
    """
    # 1. Collect business steps per location across all events for accurate role inference
    loc_steps: Dict[str, Set[str]] = {}
    event_gtins: Set[str] = set()

    for e in events:
        loc = e.get("bizLocation", {}).get("id")
        step = e.get("bizStep")
        if loc and step:
            loc_steps.setdefault(loc, set()).add(step)

        # Collect any GTINs from event quantity lists
        for field in ["quantityList", "childQuantityList", "inputQuantityList", "outputQuantityList"]:
            for item in e.get(field, []):
                epc = item.get("epcClass", "")
                parsed = parse_gs1_digital_link(epc)
                if parsed["gtin"]:
                    event_gtins.add(parsed["gtin"])

    # 2. Parse Vocabularies
    vocabs = epcis_doc.get("epcisHeader", {}).get("epcisMasterData", {}).get("vocabularyList", [])
    locations_map: Dict[str, Dict[str, Any]] = {}
    products_map: Dict[str, Dict[str, Any]] = {}
    batches_map: Dict[str, Dict[str, Any]] = {}

    for v in vocabs:
        v_type = v.get("type")

        # Parse Locations
        if v_type == "urn:epcglobal:epcis:vtype:Location":
            for el in v.get("vocabularyElementList", []):
                loc_id = el.get("id")
                attr_dict = {a["id"]: a["attribute"] for a in el.get("attributes", [])}

                parsed_link = parse_gs1_digital_link(loc_id)
                geo_coords = parse_geo_location(attr_dict.get("cbvmda:geoLocation"))

                steps = loc_steps.get(loc_id, set())
                role, explanation = infer_actor_role(steps)

                locations_map[loc_id] = {
                    "_id": loc_id,
                    "actor_id": loc_id,
                    "location_id": loc_id,
                    "gln": parsed_link["gln"],
                    "extension": parsed_link["extension"],
                    "name": attr_dict.get("cbvmda:name"),
                    "address": {
                        "street": attr_dict.get("cbvmda:streetAddressOne"),
                        "city": attr_dict.get("cbvmda:city"),
                        "state": attr_dict.get("cbvmda:state"),
                        "postal_code": attr_dict.get("cbvmda:postalCode"),
                        "country_code": attr_dict.get("cbvmda:countryCode", "US")
                    },
                    "geo_location": {
                        "type": "Point",
                        "coordinates": geo_coords
                    } if geo_coords else None,
                    "inferred_role": role,
                    "role_origin": "INFERRED",
                    "inference_rule": explanation,
                    "data_origin": "SOURCE"
                }

        # Parse EPCClass (Products and Batches)
        elif v_type == "urn:epcglobal:epcis:vtype:EPCClass":
            for el in v.get("vocabularyElementList", []):
                epc_id = el.get("id")
                attr_dict = {a["id"]: a["attribute"] for a in el.get("attributes", [])}
                parsed = parse_gs1_digital_link(epc_id)
                gtin = parsed["gtin"]
                lot = parsed["lot"]

                if gtin:
                    if gtin not in products_map:
                        products_map[gtin] = {
                            "_id": gtin,
                            "product_id": gtin,
                            "gtin": gtin,
                            "name": attr_dict.get("cbvmda:descriptionShort", f"Product {gtin}"),
                            "description": attr_dict.get("cbvmda:descriptionShort"),
                            "uri": f"https://id.gs1.org/01/{gtin}",
                            "data_origin": "SOURCE"
                        }

                    if lot:
                        batch_id = f"{gtin}:{lot}"
                        batches_map[batch_id] = {
                            "_id": batch_id,
                            "batch_id": batch_id,
                            "gtin": gtin,
                            "lot_number": lot,
                            "product_id": gtin,
                            "uri": epc_id,
                            "data_origin": "SOURCE"
                        }

    # 3. Add any products appearing in events that weren't in epcisMasterData
    for gtin in event_gtins:
        if gtin not in products_map:
            products_map[gtin] = {
                "_id": gtin,
                "product_id": gtin,
                "gtin": gtin,
                "name": f"Product {gtin}",
                "description": f"Product identified in event stream {gtin}",
                "uri": f"https://id.gs1.org/01/{gtin}",
                "data_origin": "INFERRED"
            }

    return (
        list(locations_map.values()),
        list(products_map.values()),
        list(batches_map.values())
    )

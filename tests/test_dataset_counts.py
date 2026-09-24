"""
Dataset Counts and Structure Verification Tests.
Verifies ground truth statistics directly against the 9.1 MB EPCIS JSON dataset.
"""

import json
from pathlib import Path
from collections import Counter

from backend.config import settings
from etl.parser import extract_canonical_hash


def test_dataset_exists_and_size():
    """Verify that dataset file is accessible and approximately 9.1 MB."""
    p = Path(settings.DATASET_PATH)
    assert p.exists(), f"Dataset file not found at {p}"
    size_mb = p.stat().st_size / (1024 * 1024)
    assert 8.5 <= size_mb <= 9.5, f"Unexpected file size: {size_mb:.2f} MB"


def test_dataset_header_and_master_data_counts():
    """Verify vocabulary list counts in epcisHeader."""
    with open(settings.DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("schemaVersion") == "2.0"
    vocabs = data.get("epcisHeader", {}).get("epcisMasterData", {}).get("vocabularyList", [])
    assert len(vocabs) == 2

    vocab_dict = {v["type"]: len(v["vocabularyElementList"]) for v in vocabs}
    assert vocab_dict["urn:epcglobal:epcis:vtype:Location"] == 214
    assert vocab_dict["urn:epcglobal:epcis:vtype:EPCClass"] == 377


def test_dataset_event_type_distribution():
    """Verify exact event type counts in epcisBody."""
    with open(settings.DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("epcisBody", {}).get("eventList", [])
    assert len(events) == 5650

    type_counts = Counter(e.get("type") for e in events)
    assert type_counts["ObjectEvent"] == 5409
    assert type_counts["TransformationEvent"] == 86
    assert type_counts["AssociationEvent"] == 83
    assert type_counts["AggregationEvent"] == 72


def test_dataset_prev_id_linkage():
    """Verify that exactly 100 root events exist and all 5,590 prevID references resolve."""
    with open(settings.DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("epcisBody", {}).get("eventList", [])

    all_event_hashes = {extract_canonical_hash(e.get("eventID")) for e in events}
    assert len(all_event_hashes) == 5650

    root_events = [e for e in events if not e.get("fdaftr:prevID")]
    assert len(root_events) == 100
    assert all(e.get("bizStep") == "collecting" for e in root_events)

    total_refs = 0
    resolved_refs = 0
    for e in events:
        prevs = e.get("fdaftr:prevID", [])
        if isinstance(prevs, str):
            prevs = [prevs]
        for p in prevs:
            total_refs += 1
            h = extract_canonical_hash(p)
            if h in all_event_hashes:
                resolved_refs += 1

    assert total_refs == 5590
    assert resolved_refs == 5590  # 100% resolved!

"""
Data Export REST API Endpoints.
Supports compliance auditing exports in CSV and JSON formats.
BCSE406L - NoSQL Databases
"""

import io
import csv
import json
from typing import Optional
from fastapi import APIRouter, Query, Response

from backend.database.mongo import get_mongo_db

router = APIRouter(prefix="/export", tags=["Compliance Export"])


@router.get("/events")
async def export_events(
    format: str = Query("json", description="Export format: 'json' or 'csv'"),
    batch_id: Optional[str] = Query(None, description="Filter exported events by batch ID"),
    biz_step: Optional[str] = Query(None, description="Filter exported events by business step"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of events to export")
):
    """
    Export trace event records for compliance and regulatory reporting.
    """
    db = get_mongo_db()
    query_filter = {}

    if batch_id:
        query_filter["batch_ids"] = batch_id.strip()
    if biz_step:
        query_filter["biz_step"] = biz_step.strip()

    cursor = db.trace_events.find(
        query_filter,
        {"raw_epcis_payload": 0}  # Omit large raw payload for export
    ).sort("event_time", -1).limit(limit)

    events = list(cursor)

    if format.lower() == "csv":
        output = io.StringIO()
        fieldnames = [
            "canonical_hash",
            "event_type",
            "biz_step",
            "action",
            "event_time",
            "location_id",
            "batch_ids",
            "product_ids",
            "data_origin"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for ev in events:
            writer.writerow({
                "canonical_hash": ev.get("canonical_hash", ""),
                "event_type": ev.get("event_type", ""),
                "biz_step": ev.get("biz_step", ""),
                "action": ev.get("action", "") or "",
                "event_time": ev.get("event_time_str", ""),
                "location_id": ev.get("location_id", ""),
                "batch_ids": ";".join(ev.get("batch_ids", [])),
                "product_ids": ";".join(ev.get("product_ids", [])),
                "data_origin": ev.get("data_origin", "SOURCE")
            })

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trace_events.csv"}
        )

    # Default: JSON format
    for ev in events:
        if "_id" in ev:
            ev["_id"] = str(ev["_id"])
        if "event_time" in ev and ev["event_time"]:
            ev["event_time"] = ev["event_time"].isoformat()
        if "record_time" in ev and ev["record_time"]:
            ev["record_time"] = ev["record_time"].isoformat()

    return Response(
        content=json.dumps(events, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=trace_events.json"}
    )

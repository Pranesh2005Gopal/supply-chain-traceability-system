"""
Traceability, Provenance, and Cold-Chain Pydantic Models.
BCSE406L - NoSQL Databases
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TraceNode(BaseModel):
    id: str
    label: str  # "Event", "Location", "Batch", "Product"
    title: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class TraceEdge(BaseModel):
    source: str
    target: str
    type: str  # "PRECEDES", "OCCURRED_AT", "OBSERVED", "SHIPPED_TO", etc.
    properties: Dict[str, Any] = Field(default_factory=dict)


class TraceTimelineItem(BaseModel):
    event_id: str
    canonical_hash: str
    event_type: str
    biz_step: str
    event_time: Optional[str] = None
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    location_city: Optional[str] = None
    location_state: Optional[str] = None
    action: Optional[str] = None
    batch_ids: List[str] = Field(default_factory=list)


class TraceResponse(BaseModel):
    query_target: str
    direction: str  # "FORWARD" or "BACKWARD"
    total_hops: int
    events_count: int
    nodes: List[TraceNode]
    edges: List[TraceEdge]
    timeline: List[TraceTimelineItem]


class ActorHandlingSummary(BaseModel):
    actor_id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    inferred_role: str
    events_handled: int
    steps_executed: List[str]


class ProvenanceResponse(BaseModel):
    batch_id: str
    gtin: str
    lot_number: str
    product_name: Optional[str] = None
    origin_facility: Optional[Dict[str, Any]] = None
    origin_time: Optional[str] = None
    latest_facility: Optional[Dict[str, Any]] = None
    latest_time: Optional[str] = None
    latest_step: Optional[str] = None
    actors_count: int
    actors_involved: List[ActorHandlingSummary]
    total_events: int
    timeline: List[TraceTimelineItem]


class ColdChainReading(BaseModel):
    timestamp: str
    temperature_celsius: float
    humidity_percent: float
    facility_name: Optional[str] = None
    status: str = "NORMAL"  # "NORMAL" or "EXCURSION"
    data_origin: str = "SIMULATED"


class ColdChainResponse(BaseModel):
    batch_id: str
    status: str = "NO_SENSOR_DATA"  # Per Section 20 rule: never claim "SAFE" when no sensors exist
    has_sensor_data: bool = False
    is_simulated: bool = False
    message: str
    temperature_range_celsius: Optional[Dict[str, float]] = None
    readings: List[ColdChainReading] = Field(default_factory=list)
    data_origin: str = "SOURCE"

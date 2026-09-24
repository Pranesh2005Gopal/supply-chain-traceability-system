"""
Trace Event Pydantic Models.
Enforces Append-Only semantics for auditable historical provenance.
BCSE406L - NoSQL Databases
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class QuantityItemModel(BaseModel):
    epc_class: Optional[str] = None
    gtin: Optional[str] = None
    lot: Optional[str] = None
    batch_id: Optional[str] = None
    quantity: float = 1.0
    uom: str = "LBS"


class LocationTransitModel(BaseModel):
    type: str = "location"
    location_id: str


class TraceEventCreate(BaseModel):
    event_type: str = Field(..., description="ObjectEvent, TransformationEvent, AggregationEvent, AssociationEvent", examples=["ObjectEvent"])
    biz_step: str = Field(..., description="collecting, packing, shipping, receiving, commissioning", examples=["shipping"])
    action: Optional[str] = Field("ADD", description="ADD, OBSERVE, DELETE (null for TransformationEvent)")
    event_time: Optional[datetime] = Field(None, description="ISO timestamp of event occurrence")
    location_id: str = Field(..., description="GLN URI where the event occurred", examples=["https://id.gs1.org/414/0012634065522/254/68738"])
    read_point_id: Optional[str] = Field(None, description="Read point GLN URI")
    prev_event_ids: List[str] = Field(default_factory=list, description="Predecessor event IDs or SHA-256 hashes (fdaftr:prevID)")
    batch_ids: List[str] = Field(default_factory=list, description="List of compound batch IDs (GTIN:LOT)")
    quantities: List[QuantityItemModel] = Field(default_factory=list, description="Item quantities involved")
    sources: List[LocationTransitModel] = Field(default_factory=list, description="Source dispatch facilities")
    destinations: List[LocationTransitModel] = Field(default_factory=list, description="Destination receiving facilities")
    transformation_inputs: List[QuantityItemModel] = Field(default_factory=list, description="Inputs for TransformationEvent")
    transformation_outputs: List[QuantityItemModel] = Field(default_factory=list, description="Outputs for TransformationEvent")


class TraceEventResponse(BaseModel):
    id: str = Field(..., alias="_id")
    canonical_hash: str
    event_id: str
    event_type: str
    action: Optional[str] = None
    biz_step: str
    event_time: Optional[datetime] = None
    event_time_str: Optional[str] = None
    record_time: Optional[datetime] = None
    record_time_str: Optional[str] = None
    timezone_offset: Optional[str] = "+00:00"
    location_id: Optional[str] = None
    read_point_id: Optional[str] = None
    prev_event_hashes: List[str] = Field(default_factory=list)
    batch_ids: List[str] = Field(default_factory=list)
    product_ids: List[str] = Field(default_factory=list)
    quantities: List[QuantityItemModel] = Field(default_factory=list)
    child_quantities: List[QuantityItemModel] = Field(default_factory=list)
    transformation_inputs: List[QuantityItemModel] = Field(default_factory=list)
    transformation_outputs: List[QuantityItemModel] = Field(default_factory=list)
    sources: List[LocationTransitModel] = Field(default_factory=list)
    destinations: List[LocationTransitModel] = Field(default_factory=list)
    data_origin: str = "SOURCE"
    raw_epcis_payload: Optional[Dict[str, Any]] = None

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class TraceEventListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[TraceEventResponse]

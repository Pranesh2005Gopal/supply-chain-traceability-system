"""
Actor / Location Pydantic Models.
BCSE406L - NoSQL Databases
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AddressModel(BaseModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country_code: Optional[str] = "US"


class GeoPointModel(BaseModel):
    type: str = "Point"
    coordinates: List[float] = Field(..., description="[longitude, latitude] for GeoJSON")


class ActorBase(BaseModel):
    actor_id: str = Field(..., description="GLN URI or facility identifier", examples=["https://id.gs1.org/414/0012230422385/254/57129"])
    name: str = Field(..., description="Facility or Company Name", examples=["Coleman, Kennedy and Henderson"])
    gln: Optional[str] = None
    extension: Optional[str] = None
    address: Optional[AddressModel] = None
    geo_location: Optional[GeoPointModel] = None
    inferred_role: Optional[str] = Field("DISTRIBUTOR_HUB", description="HARVESTER_PRODUCER, PROCESSOR_MANUFACTURER, DISTRIBUTOR_HUB, RETAILER_POINT_OF_SALE")
    role_origin: str = Field("INFERRED", description="INFERRED or SOURCE")
    inference_rule: Optional[str] = None
    data_origin: str = Field("SOURCE", description="SOURCE or APPLICATION")


class ActorCreate(BaseModel):
    actor_id: str = Field(..., description="GLN URI or unique facility code", examples=["https://id.gs1.org/414/9999999999999/254/10001"])
    name: str = Field(..., description="Facility name", examples=["Sunshine Dairy Farms"])
    address: Optional[AddressModel] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    role: Optional[str] = Field("HARVESTER_PRODUCER", description="Operational role")


class ActorUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Updated facility name", examples=["Updated Facility Name"])
    address: Optional[AddressModel] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    role: Optional[str] = Field(None, description="Updated operational role")


class ActorResponse(ActorBase):
    id: str = Field(..., alias="_id")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class ActorListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[ActorResponse]

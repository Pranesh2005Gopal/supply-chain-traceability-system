"""
Batch Pydantic Models.
BCSE406L - NoSQL Databases
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class BatchBase(BaseModel):
    batch_id: str = Field(..., description="Canonical compound batch identifier (GTIN:LOT)", examples=["94011508952714:48300"])
    gtin: str = Field(..., description="Product GTIN", examples=["94011508952714"])
    lot_number: str = Field(..., description="Lot or Batch number", examples=["48300"])
    product_id: str = Field(..., description="Reference to parent Product GTIN", examples=["94011508952714"])
    uri: Optional[str] = Field(None, description="GS1 Digital Link URI")
    origin_location_id: Optional[str] = Field(None, description="Origin facility GLN URI")
    data_origin: str = Field("SOURCE", description="SOURCE, DERIVED, APPLICATION, or SIMULATED")


class BatchCreate(BaseModel):
    product_id: str = Field(..., description="Parent Product GTIN", examples=["94011508952714"])
    lot_number: str = Field(..., description="Lot or Batch number", examples=["LOT-99881"])
    origin_location_id: Optional[str] = Field(None, description="Origin facility GLN URI")


class BatchResponse(BatchBase):
    id: str = Field(..., alias="_id")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class BatchListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[BatchResponse]

"""
Product Pydantic Models.
BCSE406L - NoSQL Databases
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class ProductBase(BaseModel):
    product_id: str = Field(..., description="GTIN or canonical product identifier", examples=["94011508952714"])
    name: str = Field(..., description="Product display name", examples=["product#532fd37e"])
    description: Optional[str] = Field(None, description="Detailed product description")
    uri: Optional[str] = Field(None, description="GS1 Digital Link URI")
    data_origin: str = Field("SOURCE", description="SOURCE, INFERRED, APPLICATION, or SIMULATED")


class ProductCreate(BaseModel):
    product_id: str = Field(..., description="GTIN (14 digits) or unique product identifier", examples=["12345678901234"])
    name: str = Field(..., description="Product name", examples=["Organic Whole Milk"])
    description: Optional[str] = Field(None, description="Product description")
    uri: Optional[str] = Field(None, description="GS1 Digital Link URI")


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Updated product name", examples=["Premium Organic Whole Milk"])
    description: Optional[str] = Field(None, description="Updated description")
    uri: Optional[str] = Field(None, description="Updated GS1 Digital Link URI")


class ProductResponse(ProductBase):
    id: str = Field(..., alias="_id")

    model_config = {
        "populate_by_name": True,
        "from_attributes": True
    }


class ProductListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[ProductResponse]

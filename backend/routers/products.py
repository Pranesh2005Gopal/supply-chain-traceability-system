"""
Products REST API Endpoints.
BCSE406L - NoSQL Databases
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from backend.database.mongo import get_mongo_db
from backend.database.neo4j_driver import get_neo4j_driver
from backend.models.product import (
    ProductCreate,
    ProductResponse,
    ProductListResponse
)

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=ProductListResponse)
async def list_products(
    skip: int = Query(0, ge=0, description="Offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    search: Optional[str] = Query(None, description="Search query by GTIN or name")
):
    """List products with pagination and optional search filter."""
    db = get_mongo_db()
    query_filter = {}

    if search:
        s = search.strip()
        query_filter["$or"] = [
            {"product_id": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}}
        ]

    total = db.products.count_documents(query_filter)
    cursor = db.products.find(query_filter).skip(skip).limit(limit).sort("product_id", 1)
    items = [ProductResponse(**doc) for doc in cursor]

    return ProductListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    """Retrieve product details by GTIN or product_id."""
    db = get_mongo_db()
    doc = db.products.find_one({"product_id": product_id.strip()})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found."
        )
    return ProductResponse(**doc)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate):
    """Register a new product in MongoDB and sync to Neo4j."""
    db = get_mongo_db()
    pid = payload.product_id.strip()

    existing = db.products.find_one({"product_id": pid})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product with ID '{pid}' already exists."
        )

    doc = {
        "_id": pid,
        "product_id": pid,
        "gtin": pid,
        "name": payload.name.strip(),
        "description": payload.description,
        "uri": payload.uri or f"https://id.gs1.org/01/{pid}",
        "data_origin": "APPLICATION"
    }

    db.products.insert_one(doc)

    # Sync node to Neo4j
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (p:Product {product_id: $pid})
                SET p.name = $name, p.gtin = $pid
                """,
                pid=pid,
                name=payload.name
            )
    except Exception:
        pass

    return ProductResponse(**doc)

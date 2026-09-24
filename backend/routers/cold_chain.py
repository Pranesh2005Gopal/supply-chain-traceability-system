"""
Cold Chain Telematics REST API Endpoints.
Adheres strictly to the Section 20 Data Integrity rule:
Returns 'NO_SENSOR_DATA' for raw EPCIS source data, and only returns readings
when simulated telematics are explicitly requested for demonstration.
BCSE406L - NoSQL Databases
"""

from fastapi import APIRouter, HTTPException, Query, status

from backend.models.trace import ColdChainResponse
from backend.services.trace_service import evaluate_cold_chain

router = APIRouter(prefix="/cold-chain", tags=["Cold-Chain Monitoring"])


@router.get("/{batch_id:path}", response_model=ColdChainResponse)
async def get_cold_chain_status(
    batch_id: str,
    include_simulated: bool = Query(
        False,
        description="Toggle simulation demo mode. When false, reports authentic EPCIS source status ('NO_SENSOR_DATA')."
    )
):
    """
    Retrieve cold-chain compliance and temperature audit for a batch.
    - Default: Accurately reflects EPCIS source data (NO_SENSOR_DATA).
    - Demo mode (?include_simulated=true): Provides simulated IoT cold chain readings clearly tagged as SIMULATED.
    """
    clean_bid = batch_id.strip()
    result = evaluate_cold_chain(clean_bid, include_simulated=include_simulated)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch '{batch_id}' not found."
        )
    return result

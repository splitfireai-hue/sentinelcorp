"""Main company risk profiling endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.company import (
    BatchRiskRequest,
    BatchRiskResponse,
    CompanyRiskProfile,
)
from app.services import risk_service

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _client_id_from_request(request: Request) -> str:
    """Extract client identifier — API key or IP."""
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        return "key:{}".format(api_key[:12])
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return "ip:{}".format(client_ip)


@router.get("/profile", response_model=CompanyRiskProfile)
@limiter.limit(settings.LOOKUP_RATE_LIMIT)
async def company_profile(
    request: Request,
    identifier: str = Query(..., min_length=2, max_length=500, description="CIN, GSTIN, PAN, or company name"),
    type: str = Query("auto", description="Identifier type: auto, gstin, cin, pan, name"),
    db: AsyncSession = Depends(get_db),
):
    """Get unified company risk profile.

    Accepts CIN, GSTIN, PAN, or company name. Auto-detects type by default.

    Combines:
    - Format validation (checksum verification)
    - SEBI/NSE/BSE debarred list match
    - Risk scoring from all signals

    Returns overall risk score 0-100 with level (critical/high/medium/low/minimal).
    """
    client_id = _client_id_from_request(request)
    return await risk_service.profile_company(
        identifier=identifier,
        db=db,
        identifier_type=type if type != "auto" else None,
        client_id=client_id,
    )


@router.post("/batch", response_model=BatchRiskResponse)
@limiter.limit("10/minute")
async def batch_profile(
    request: Request,
    body: BatchRiskRequest,
    db: AsyncSession = Depends(get_db),
):
    """Batch risk profiling for up to 100 identifiers in one request.

    Perfect for agent workflows processing lists of companies.
    """
    client_id = _client_id_from_request(request)
    results = []
    errors = []
    for ident in body.identifiers:
        try:
            profile = await risk_service.profile_company(
                identifier=ident,
                db=db,
                identifier_type=body.identifier_type,
                client_id=client_id,
            )
            results.append(profile)
        except Exception as e:
            errors.append({"identifier": ident, "error": str(e)})

    return BatchRiskResponse(
        total=len(results),
        results=results,
        errors=errors,
    )

"""Format validation endpoints — fast, free, no external calls."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.schemas.company import IdentifierValidationResponse
from app.services.validators import validate_cin, validate_gstin, validate_pan

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/gstin", response_model=IdentifierValidationResponse)
@limiter.limit("120/minute")
async def validate_gstin_endpoint(
    request: Request,
    gstin: str = Query(..., min_length=15, max_length=15),
):
    """Validate GSTIN (Goods and Services Tax Identification Number).

    Checks format, state code, and Luhn mod-36 checksum.
    Pure client-side computation — no external API calls.
    """
    v = validate_gstin(gstin)
    return IdentifierValidationResponse(
        identifier=gstin.upper(),
        identifier_type="gstin",
        is_valid=v.is_valid,
        parsed={
            "state_code": v.state_code,
            "state_name": v.state_name,
            "pan": v.pan,
            "entity_number": v.entity_number,
            "checksum_valid": v.checksum_valid,
        },
        error=v.error,
    )


@router.get("/cin", response_model=IdentifierValidationResponse)
@limiter.limit("120/minute")
async def validate_cin_endpoint(
    request: Request,
    cin: str = Query(..., min_length=21, max_length=21),
):
    """Validate CIN (Corporate Identification Number).

    Checks format and extracts metadata: listing status, state, year of incorporation,
    industry division, company ownership type, registration number.
    """
    v = validate_cin(cin)
    return IdentifierValidationResponse(
        identifier=cin.upper(),
        identifier_type="cin",
        is_valid=v.is_valid,
        parsed={
            "listing_status": v.listing_status,
            "state_code": v.state_code,
            "state_name": v.state_name,
            "year_of_incorporation": v.year_of_incorporation,
            "industry_division": v.industry_division,
            "company_ownership": v.company_ownership,
            "registration_number": v.registration_number,
        },
        error=v.error,
    )


@router.get("/pan", response_model=IdentifierValidationResponse)
@limiter.limit("120/minute")
async def validate_pan_endpoint(
    request: Request,
    pan: str = Query(..., min_length=10, max_length=10),
):
    """Validate PAN (Permanent Account Number)."""
    v = validate_pan(pan)
    return IdentifierValidationResponse(
        identifier=pan.upper(),
        identifier_type="pan",
        is_valid=v.is_valid,
        parsed={"pan_type": v.pan_type},
        error=v.error,
    )

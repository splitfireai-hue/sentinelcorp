"""Core risk profiling service — the main product logic."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import DebarredEntity, LookupHistory
from app.schemas.company import (
    CompanyRiskProfile,
    DebarredMatch,
    IdentifierValidationResponse,
    RiskSignal,
    SuggestedLookup,
)
from app.services import risk_scoring
from app.services.validators import (
    validate_cin,
    validate_gstin,
    validate_pan,
    pan_from_gstin,
)

logger = logging.getLogger(__name__)


def detect_identifier_type(identifier: str) -> str:
    """Heuristically detect whether input is CIN, GSTIN, PAN, or name."""
    s = identifier.strip().upper()
    if len(s) == 15 and s[0:2].isdigit() and not s[0].isalpha():
        return "gstin"
    if len(s) == 21 and s[0] in ("L", "U"):
        return "cin"
    if len(s) == 10 and s[:3].isalpha() and s[3].isalpha():
        return "pan"
    return "name"


async def _find_debarred_matches(db: AsyncSession, name: str, pan: Optional[str] = None) -> List[DebarredMatch]:
    """Find SEBI debarred entries matching a company name or PAN."""
    matches: List[DebarredMatch] = []
    if not name and not pan:
        return matches

    conditions = []
    if pan:
        conditions.append(DebarredEntity.pan == pan)
    if name and len(name) >= 3:
        name_lower = name.strip().lower()
        # Exact match first
        conditions.append(DebarredEntity.name_normalized == name_lower)
        # Substring match
        conditions.append(DebarredEntity.name_normalized.like("%{}%".format(name_lower)))

    if not conditions:
        return matches

    result = await db.execute(
        select(DebarredEntity)
        .where(or_(*conditions))
        .limit(10)
    )
    rows = result.scalars().all()

    name_lower = name.lower() if name else ""
    for row in rows:
        # Confidence: exact match = 1.0, substring = 0.7, PAN match = 1.0
        if pan and row.pan == pan:
            confidence = 1.0
        elif row.name_normalized == name_lower:
            confidence = 1.0
        else:
            # substring match — lower confidence
            confidence = 0.7 if name_lower else 0.5
        matches.append(DebarredMatch(
            matched_name=row.name,
            source=row.source,
            entity_type=row.entity_type,
            confidence=confidence,
            debarment_reason=row.debarment_reason,
            debarment_date=row.debarment_date,
        ))
    # Return highest-confidence matches first
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches[:5]


async def _record_lookup(db: AsyncSession, identifier_type: str, identifier: str,
                         risk_score: float, client_id: str = "") -> int:
    """Record this lookup and return how many times it was looked up before."""
    try:
        count_result = await db.execute(
            select(func.count(LookupHistory.id))
            .where(
                and_(
                    LookupHistory.identifier_type == identifier_type,
                    LookupHistory.identifier_value == identifier,
                )
            )
        )
        prev = count_result.scalar_one() or 0

        db.add(LookupHistory(
            identifier_type=identifier_type,
            identifier_value=identifier,
            risk_score=risk_score,
            client_id=client_id,
        ))
        await db.commit()
        return prev
    except Exception as e:
        logger.warning("Lookup recording failed: %s", e)
        return 0


def _build_suggestions(
    identifier_type: str,
    identifier: str,
    pan: Optional[str],
    name: Optional[str],
    has_debarment: bool,
) -> List[SuggestedLookup]:
    """Build suggested follow-up queries."""
    suggestions = []

    if identifier_type == "gstin" and pan:
        suggestions.append(SuggestedLookup(
            type="pan",
            value=pan,
            reason="Look up PAN — all GSTINs for this PAN share risk signals",
        ))

    if name and not has_debarment:
        suggestions.append(SuggestedLookup(
            type="name",
            value=name,
            reason="Search by name to find associated entities",
        ))

    if has_debarment:
        suggestions.append(SuggestedLookup(
            type="endpoint",
            value="/api/v1/debarred/list",
            reason="Browse all SEBI/NSE debarred entities",
        ))

    # Always suggest threat intel cross-check
    suggestions.append(SuggestedLookup(
        type="endpoint",
        value="https://sentinelx402-production.up.railway.app/api/v1/india/advisories/list",
        reason="Check CERT-In India advisories mentioning this entity",
    ))

    return suggestions[:4]


async def profile_company(
    identifier: str,
    db: AsyncSession,
    identifier_type: Optional[str] = None,
    client_id: str = "",
) -> CompanyRiskProfile:
    """Main risk profiling function.

    Accepts GSTIN, CIN, PAN, or company name.
    Returns unified risk profile with signals from all available sources.
    """
    identifier = identifier.strip()
    if identifier_type is None or identifier_type == "auto":
        identifier_type = detect_identifier_type(identifier)

    signals: List[RiskSignal] = []
    data_sources: List[str] = []
    validation: Optional[IdentifierValidationResponse] = None
    name: Optional[str] = None
    state: Optional[str] = None
    pan: Optional[str] = None

    # --- Step 1: Validate format ---
    if identifier_type == "gstin":
        v = validate_gstin(identifier)
        validation = IdentifierValidationResponse(
            identifier=identifier.upper(),
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
        data_sources.append("format_validator")
        if not v.is_valid:
            signals.append(risk_scoring.signal_format_invalid(identifier, v.error or "Invalid format"))
        elif not v.checksum_valid:
            signals.append(risk_scoring.signal_checksum_invalid())
        state = v.state_name
        pan = v.pan

    elif identifier_type == "cin":
        v = validate_cin(identifier)
        validation = IdentifierValidationResponse(
            identifier=identifier.upper(),
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
        data_sources.append("format_validator")
        if not v.is_valid:
            signals.append(risk_scoring.signal_format_invalid(identifier, v.error or "Invalid format"))
        state = v.state_name

    elif identifier_type == "pan":
        v = validate_pan(identifier)
        validation = IdentifierValidationResponse(
            identifier=identifier.upper(),
            identifier_type="pan",
            is_valid=v.is_valid,
            parsed={"pan_type": v.pan_type},
            error=v.error,
        )
        data_sources.append("format_validator")
        if not v.is_valid:
            signals.append(risk_scoring.signal_format_invalid(identifier, v.error or "Invalid format"))
        pan = identifier.upper() if v.is_valid else None

    elif identifier_type == "name":
        name = identifier

    # --- Step 2: Check SEBI debarred list ---
    debarred_matches = await _find_debarred_matches(db, name or "", pan)
    data_sources.append("sebi_debarred_list")

    # Only the top match contributes to the score (avoid double-counting substring matches)
    if debarred_matches:
        top_match = debarred_matches[0]
        if top_match.confidence >= 0.6:
            signals.append(risk_scoring.signal_sebi_debarred(top_match.matched_name, top_match.confidence))

    # --- Step 3: Compute overall score ---
    score_result = risk_scoring.compute_risk_score(signals)

    # --- Step 4: Build suggestions ---
    suggestions = _build_suggestions(
        identifier_type,
        identifier,
        pan,
        name,
        has_debarment=bool(debarred_matches),
    )

    # --- Step 5: Record in history ---
    historical = await _record_lookup(db, identifier_type, identifier, score_result.score, client_id)

    return CompanyRiskProfile(
        query=identifier,
        query_type=identifier_type,
        name=name,
        state=state,
        validation=validation,
        overall_risk_score=score_result.score,
        risk_level=score_result.level,
        signals=signals,
        is_debarred=any(m.confidence >= 0.6 for m in debarred_matches),
        debarred_matches=debarred_matches,
        data_sources=data_sources,
        historical_occurrences=historical,
        suggested_lookups=suggestions,
    )

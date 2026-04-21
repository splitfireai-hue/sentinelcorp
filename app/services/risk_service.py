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


GENERIC_WORDS = {
    # Legal suffixes
    "limited", "ltd", "private", "pvt", "pvt.", "ltd.", "limited.",
    "llc", "llp", "inc", "inc.", "corporation", "corp", "corp.",
    "co", "co.", "company", "the", "and", "of", "for", "in", "to",
    "india", "indian", "mumbai", "delhi", "bangalore", "chennai",
    # Common business words
    "services", "service", "group", "holdings", "international", "global",
    "solutions", "enterprises", "industries", "industry", "technologies",
    "technology", "systems", "system", "consultancy", "consultants",
    "consulting", "financial", "finance", "finances", "investment",
    "investments", "trading", "trade", "traders", "dealers", "distribution",
    "distributors", "commercial", "business", "businesses", "mrs", "mr",
    "shri", "smt", "proprietor", "partners", "partnership",
    "foundation", "society", "trust", "association", "ventures",
    "retail", "wholesale", "exports", "imports", "import", "export",
    "broking", "brokers", "agencies", "agency", "associates", "&",
}


def _significant_tokens(text: str) -> set:
    """Extract significant tokens (3+ chars, not generic stopwords)."""
    return set(
        w for w in text.split()
        if len(w) >= 3 and w not in GENERIC_WORDS
    )


def _confidence_for_match(query_lower: str, entity_name_lower: str) -> float:
    """Compute match confidence carefully.

    Examples:
    - "Sahara India Limited" vs "Sahara India Commercial Corporation Limited" → partial overlap on "sahara","india" → 0.5
    - "Tata" vs "TATA TELESERVICES LIMITED" → short ambiguous → 0.35
    - "Reliance Industries" vs "Reliance Commercial Finance Limited" → overlap on "reliance" → 0.5
    - Exact match → 1.0
    """
    if query_lower == entity_name_lower:
        return 1.0

    query_tokens = _significant_tokens(query_lower)
    entity_tokens = _significant_tokens(entity_name_lower)
    if not query_tokens:
        # Fall back to non-filtered tokens
        query_tokens = set(w for w in query_lower.split() if len(w) >= 3)
        entity_tokens = set(w for w in entity_name_lower.split() if len(w) >= 3)
        if not query_tokens:
            return 0.0

    overlap = query_tokens & entity_tokens
    if not overlap:
        return 0.0

    overlap_ratio = len(overlap) / len(query_tokens)

    # All query tokens in entity
    if overlap_ratio == 1.0:
        # If entity has significantly more tokens, query is too generic/ambiguous
        # e.g. "Infosys" matching "Tauras Infosys Ltd" (1 token in 2)
        size_ratio = len(entity_tokens) / len(query_tokens)
        if size_ratio >= 2.0:
            return 0.4
        if size_ratio >= 1.5:
            return 0.55  # Could be ambiguous — medium confidence
        # Query covers most of entity name → likely same entity
        return 0.9

    # Partial overlap
    if overlap_ratio >= 0.5:
        return 0.55

    if overlap_ratio > 0:
        return 0.3

    return 0.0


async def _find_debarred_matches(db: AsyncSession, name: str, pan: Optional[str] = None) -> List[DebarredMatch]:
    """Find SEBI debarred entries matching a company name or PAN."""
    matches: List[DebarredMatch] = []
    if not name and not pan:
        return matches

    # Require query to be reasonably specific to avoid false positives
    if name and len(name.strip()) < 5 and not pan:
        # Query too short/generic — only do exact match
        name_lower = name.strip().lower()
        result = await db.execute(
            select(DebarredEntity)
            .where(DebarredEntity.name_normalized == name_lower)
            .limit(5)
        )
        for row in result.scalars().all():
            matches.append(DebarredMatch(
                matched_name=row.name,
                source=row.source,
                entity_type=row.entity_type,
                confidence=1.0,
                debarment_reason=row.debarment_reason,
                debarment_date=row.debarment_date,
            ))
        return matches

    conditions = []
    if pan:
        conditions.append(DebarredEntity.pan == pan)
    if name and len(name) >= 3:
        name_lower = name.strip().lower()
        # Exact match
        conditions.append(DebarredEntity.name_normalized == name_lower)
        # Full-phrase whole-word match (query surrounded by spaces/punctuation)
        # This catches "sahara india" in "m/s sahara india (and its constituent partners)"
        # but NOT "infosys" in "infosystems"
        conditions.append(DebarredEntity.name_normalized.like("{} %".format(name_lower)))
        conditions.append(DebarredEntity.name_normalized.like("% {}".format(name_lower)))
        conditions.append(DebarredEntity.name_normalized.like("% {} %".format(name_lower)))
        # Token-level whole-word match for each significant token
        sig_tokens = _significant_tokens(name_lower)
        long_tokens = [t for t in sig_tokens if len(t) >= 5]
        for token in long_tokens[:5]:
            conditions.append(DebarredEntity.name_normalized.like("{} %".format(token)))
            conditions.append(DebarredEntity.name_normalized.like("% {}".format(token)))
            conditions.append(DebarredEntity.name_normalized.like("% {} %".format(token)))

    if not conditions:
        return matches

    result = await db.execute(
        select(DebarredEntity)
        .where(or_(*conditions))
        .limit(30)
    )
    rows = result.scalars().all()

    name_lower = name.lower() if name else ""
    for row in rows:
        if pan and row.pan == pan:
            confidence = 1.0
        else:
            confidence = _confidence_for_match(name_lower, row.name_normalized)

        # Skip very weak matches
        if confidence < 0.3:
            continue

        matches.append(DebarredMatch(
            matched_name=row.name,
            source=row.source,
            entity_type=row.entity_type,
            confidence=round(confidence, 2),
            debarment_reason=row.debarment_reason,
            debarment_date=row.debarment_date,
        ))

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches[:5]


async def _record_lookup(db: AsyncSession, identifier_type: str, identifier: str,
                         risk_score: float, client_id: str = "") -> int:
    """Record this lookup and return how many times it was looked up before.

    Best-effort: DB failures don't block API responses.
    """
    prev = 0
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
    except Exception as e:
        logger.warning("Lookup count failed: %s", str(e)[:120])

    try:
        db.add(LookupHistory(
            identifier_type=identifier_type,
            identifier_value=identifier,
            risk_score=risk_score,
            client_id=client_id,
        ))
        await db.commit()
    except Exception as e:
        logger.warning("Lookup insert failed: %s", str(e)[:120])
        try:
            await db.rollback()
        except Exception:
            pass

    return prev


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

    # Trigger signal based on match strength
    # - Exact/near-exact match → strong signal (critical/high risk)
    # - Many related matches (cluster) → medium signal (warrants review)
    # - Few weak matches → informational only (shown but no risk score)
    if debarred_matches:
        top_match = debarred_matches[0]
        if top_match.confidence >= 0.8:
            signals.append(risk_scoring.signal_sebi_debarred(top_match.matched_name, top_match.confidence))
        elif len(debarred_matches) >= 4 and top_match.confidence >= 0.3:
            # Cluster signal — 4+ debarred entities share query tokens
            avg_conf = sum(m.confidence for m in debarred_matches) / len(debarred_matches)
            signal_confidence = min(0.7, avg_conf * 1.5)
            signals.append(risk_scoring.signal_sebi_debarred(
                "{} ({} related entities in enforcement actions)".format(
                    top_match.matched_name, len(debarred_matches)
                ),
                signal_confidence,
            ))
        # Fewer than 4 matches with low confidence → no signal
        # But matches still returned for user inspection (transparency)

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
        is_debarred=any(m.confidence >= 0.8 for m in debarred_matches) or len(debarred_matches) >= 3,
        debarred_matches=debarred_matches,
        data_sources=data_sources,
        historical_occurrences=historical,
        suggested_lookups=suggestions,
    )

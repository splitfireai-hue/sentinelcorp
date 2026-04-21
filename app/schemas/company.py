from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class SuggestedLookup(BaseModel):
    type: str
    value: str
    reason: str


class RiskSignal(BaseModel):
    """A single risk signal contributing to the overall score."""
    source: str  # "sebi", "gst", "court", "heuristic"
    signal_type: str  # "debarred", "suspended", "litigation", etc
    severity: str  # "critical", "high", "medium", "low"
    description: str
    weight: float  # 0-1, contribution to overall score
    details: Optional[dict] = None


class IdentifierValidationResponse(BaseModel):
    """Validation-only response (fast, free, no external calls)."""
    identifier: str
    identifier_type: str  # gstin, cin, pan
    is_valid: bool
    parsed: dict = Field(default_factory=dict)
    error: Optional[str] = None


class DebarredMatch(BaseModel):
    """A match against SEBI/NSE/BSE debarred list."""
    matched_name: str
    source: str
    entity_type: str
    confidence: float  # 0-1
    debarment_reason: Optional[str] = None
    debarment_date: Optional[str] = None


class CompanyRiskProfile(BaseModel):
    """Unified company risk profile — the core product."""
    query: str  # what user searched
    query_type: str  # gstin, cin, pan, name

    # Identity
    name: Optional[str] = None
    status: Optional[str] = None  # active, suspended, unknown
    state: Optional[str] = None
    incorporation_date: Optional[str] = None
    industry: Optional[str] = None
    company_type: Optional[str] = None

    # Format validation
    validation: Optional[IdentifierValidationResponse] = None

    # Risk signals
    overall_risk_score: float = Field(ge=0, le=100)
    risk_level: str  # critical, high, medium, low, minimal
    signals: List[RiskSignal] = []

    # Specific risk flags
    is_debarred: bool = False
    debarred_matches: List[DebarredMatch] = []
    is_suspended: bool = False
    has_active_litigation: bool = False
    litigation_cases: int = 0

    # Data provenance
    data_sources: List[str] = []
    last_refreshed: Optional[str] = None
    cache_age_seconds: Optional[int] = None

    # Flywheel fields
    historical_occurrences: int = 0
    suggested_lookups: List[SuggestedLookup] = []


class BatchRiskRequest(BaseModel):
    identifiers: List[str] = Field(..., min_length=1, max_length=100)
    identifier_type: Optional[str] = None  # auto-detect if None


class BatchRiskResponse(BaseModel):
    total: int
    results: List[CompanyRiskProfile]
    errors: List[dict] = []


class TrendingCompany(BaseModel):
    identifier: str
    identifier_type: str
    lookup_count: int
    max_risk_score: float

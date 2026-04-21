"""Risk scoring engine.

Combines signals from multiple sources into a unified 0-100 score.

Reference implementation — production uses proprietary weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.schemas.company import RiskSignal


@dataclass
class RiskScoreResult:
    score: float  # 0-100
    level: str  # critical, high, medium, low, minimal
    signals: List[RiskSignal]
    rationale: str


# Signal weights (reference — production has tuned values)
SIGNAL_WEIGHTS = {
    "sebi_debarred": 0.95,      # Almost maxes out the score
    "sebi_fraud_case": 0.85,
    "gst_suspended": 0.60,
    "gst_cancelled": 0.75,
    "active_litigation_high": 0.45,
    "active_litigation_medium": 0.25,
    "mca_dormant": 0.30,
    "mca_struck_off": 0.80,
    "format_invalid": 0.10,
    "checksum_invalid": 0.15,
    "unknown_state": 0.05,
    "low_paid_up_capital": 0.10,
    "suspicious_name_pattern": 0.20,
}


def _combine_signals(signals: List[RiskSignal]) -> float:
    """Combine signals using a noisy-OR model.

    Score = 100 * (1 - prod(1 - signal_weight))

    This way, multiple moderate signals compound, but no single signal
    over-dominates unless it's critical.
    """
    if not signals:
        return 0.0

    product = 1.0
    for s in signals:
        product *= (1.0 - s.weight)
    score = 100.0 * (1.0 - product)
    return round(score, 1)


def _score_to_level(score: float) -> str:
    if score >= 85:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 15:
        return "low"
    return "minimal"


def compute_risk_score(signals: List[RiskSignal]) -> RiskScoreResult:
    """Compute unified risk score from signals."""
    score = _combine_signals(signals)
    level = _score_to_level(score)

    if not signals:
        rationale = "No adverse signals found. Company appears clean on public records."
    else:
        top = sorted(signals, key=lambda s: s.weight, reverse=True)[:3]
        rationale = "Top risk factors: " + "; ".join(
            "{} ({})".format(s.signal_type, s.severity) for s in top
        )

    return RiskScoreResult(
        score=score,
        level=level,
        signals=signals,
        rationale=rationale,
    )


def signal_sebi_debarred(entity_name: str, match_confidence: float = 1.0) -> RiskSignal:
    return RiskSignal(
        source="sebi",
        signal_type="sebi_debarred",
        severity="critical",
        description="Entity is on SEBI/NSE/BSE debarred list",
        weight=SIGNAL_WEIGHTS["sebi_debarred"] * match_confidence,
        details={"matched_name": entity_name, "confidence": match_confidence},
    )


def signal_gst_cancelled() -> RiskSignal:
    return RiskSignal(
        source="gst",
        signal_type="gst_cancelled",
        severity="high",
        description="GST registration cancelled by authorities",
        weight=SIGNAL_WEIGHTS["gst_cancelled"],
    )


def signal_gst_suspended() -> RiskSignal:
    return RiskSignal(
        source="gst",
        signal_type="gst_suspended",
        severity="high",
        description="GST registration suspended",
        weight=SIGNAL_WEIGHTS["gst_suspended"],
    )


def signal_format_invalid(identifier: str, error: str) -> RiskSignal:
    return RiskSignal(
        source="validator",
        signal_type="format_invalid",
        severity="low",
        description="Invalid format: {}".format(error),
        weight=SIGNAL_WEIGHTS["format_invalid"],
        details={"identifier": identifier, "error": error},
    )


def signal_checksum_invalid() -> RiskSignal:
    return RiskSignal(
        source="validator",
        signal_type="checksum_invalid",
        severity="low",
        description="Checksum verification failed — identifier may be fabricated",
        weight=SIGNAL_WEIGHTS["checksum_invalid"],
    )


def signal_active_litigation(case_count: int) -> RiskSignal:
    if case_count >= 5:
        return RiskSignal(
            source="court",
            signal_type="active_litigation_high",
            severity="high",
            description="{} active court cases".format(case_count),
            weight=SIGNAL_WEIGHTS["active_litigation_high"],
            details={"case_count": case_count},
        )
    return RiskSignal(
        source="court",
        signal_type="active_litigation_medium",
        severity="medium",
        description="{} active court cases".format(case_count),
        weight=SIGNAL_WEIGHTS["active_litigation_medium"],
        details={"case_count": case_count},
    )


def signal_mca_struck_off() -> RiskSignal:
    return RiskSignal(
        source="mca",
        signal_type="mca_struck_off",
        severity="critical",
        description="Company struck off the MCA register — not legally active",
        weight=SIGNAL_WEIGHTS["mca_struck_off"],
    )


def signal_mca_dormant() -> RiskSignal:
    return RiskSignal(
        source="mca",
        signal_type="mca_dormant",
        severity="medium",
        description="Company marked dormant on MCA register",
        weight=SIGNAL_WEIGHTS["mca_dormant"],
    )

"""Unit tests for risk scoring engine."""

from __future__ import annotations

from app.services import risk_scoring


class TestRiskScoring:
    def test_no_signals_zero_score(self):
        result = risk_scoring.compute_risk_score([])
        assert result.score == 0.0
        assert result.level == "minimal"

    def test_sebi_debarred_critical(self):
        signal = risk_scoring.signal_sebi_debarred("Test Ltd", 1.0)
        result = risk_scoring.compute_risk_score([signal])
        assert result.score >= 85
        assert result.level == "critical"

    def test_compound_signals(self):
        signals = [
            risk_scoring.signal_checksum_invalid(),
            risk_scoring.signal_active_litigation(3),
        ]
        result = risk_scoring.compute_risk_score(signals)
        # Noisy-OR: 1 - (1-0.15)(1-0.25) = 1 - 0.6375 = 0.3625
        assert 30 <= result.score <= 40

    def test_format_invalid_low(self):
        signal = risk_scoring.signal_format_invalid("X", "bad")
        result = risk_scoring.compute_risk_score([signal])
        assert result.level == "minimal"

    def test_gst_cancelled_high(self):
        signal = risk_scoring.signal_gst_cancelled()
        result = risk_scoring.compute_risk_score([signal])
        assert result.level == "high"

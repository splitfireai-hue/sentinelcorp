"""Unit tests for validators."""

from __future__ import annotations

from app.services.validators import validate_cin, validate_gstin, validate_pan


class TestGSTIN:
    def test_valid_format(self):
        # Generate a valid one using the checksum algo
        from app.services.validators import _gstin_checksum
        base = "27AAACT1234A1Z"
        checksum = _gstin_checksum(base)
        result = validate_gstin(base + checksum)
        assert result.is_valid
        assert result.state_code == "27"
        assert result.state_name == "Maharashtra"
        assert result.pan == "AAACT1234A"

    def test_invalid_format(self):
        result = validate_gstin("INVALID")
        assert not result.is_valid

    def test_invalid_checksum(self):
        result = validate_gstin("27AAACT1234A1Z9")  # Random checksum
        assert not result.is_valid
        assert "Checksum" in (result.error or "")

    def test_unknown_state(self):
        # State code 99 is valid (Centre Jurisdiction), so use something else
        from app.services.validators import _gstin_checksum
        base = "88AAACT1234A1Z"  # 88 not in STATE_CODES
        checksum = _gstin_checksum(base)
        result = validate_gstin(base + checksum)
        assert not result.is_valid


class TestCIN:
    def test_valid_listed_company(self):
        result = validate_cin("L17110MH1973PLC019786")
        assert result.is_valid
        assert result.listing_status == "Listed (Public)"
        assert result.state_name == "Maharashtra"
        assert result.year_of_incorporation == 1973
        assert "Public Limited" in result.company_ownership

    def test_valid_unlisted_company(self):
        result = validate_cin("U74999KA2020PTC123456")
        assert result.is_valid
        assert result.listing_status == "Unlisted"
        assert result.state_name == "Karnataka"
        assert result.year_of_incorporation == 2020

    def test_invalid_format(self):
        result = validate_cin("INVALID")
        assert not result.is_valid

    def test_invalid_state(self):
        result = validate_cin("L17110ZZ1973PLC019786")
        assert not result.is_valid


class TestPAN:
    def test_valid_individual(self):
        result = validate_pan("ABCPE1234F")  # P = Individual
        assert result.is_valid
        assert result.pan_type == "Individual"

    def test_valid_company(self):
        result = validate_pan("ABCCE1234F")  # C = Company
        assert result.is_valid
        assert result.pan_type == "Company"

    def test_invalid_format(self):
        result = validate_pan("INVALID")
        assert not result.is_valid

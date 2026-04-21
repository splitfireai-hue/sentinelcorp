"""Format validators for Indian company identifiers.

Pure algorithmic validation — no network calls, no legal risk, no rate limits.
These are the 'always works' backbone of SentinelCorp.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Indian state codes (used in GSTIN first 2 digits)
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (before division)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh (after division)", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

# CIN state codes (first 2 chars)
CIN_STATE_CODES = {
    "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
    "BR": "Bihar", "CH": "Chandigarh", "CG": "Chhattisgarh",
    "DL": "Delhi", "DN": "Dadra and Nagar Haveli", "GA": "Goa",
    "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana",
    "JH": "Jharkhand", "JK": "Jammu and Kashmir", "KA": "Karnataka",
    "KL": "Kerala", "LD": "Lakshadweep", "MH": "Maharashtra",
    "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh",
    "MZ": "Mizoram", "NL": "Nagaland", "OR": "Odisha",
    "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan",
    "SK": "Sikkim", "TN": "Tamil Nadu", "TR": "Tripura",
    "UP": "Uttar Pradesh", "UT": "Uttarakhand", "WB": "West Bengal",
    "TG": "Telangana", "LA": "Ladakh",
}

# Company class codes (positions 2-5 in CIN for listed/private)
COMPANY_CLASS = {
    "L": "Listed (Public)",
    "U": "Unlisted",
}

# Industry classification codes (NIC 2008) - major divisions used in CIN
NIC_DIVISIONS = {
    "01": "Agriculture", "02": "Forestry", "03": "Fishing",
    "05": "Mining of coal and lignite", "10": "Manufacture of food products",
    "13": "Textiles", "14": "Wearing apparel", "20": "Chemicals",
    "23": "Non-metallic mineral products", "24": "Basic metals",
    "25": "Fabricated metal products", "26": "Electronic components",
    "27": "Electrical equipment", "28": "Machinery", "29": "Motor vehicles",
    "35": "Electricity", "36": "Water supply", "41": "Construction",
    "45": "Trade/Repair of motor vehicles", "46": "Wholesale trade",
    "47": "Retail trade", "49": "Land transport", "52": "Warehousing",
    "58": "Publishing", "61": "Telecommunications",
    "62": "Computer programming", "63": "Information services",
    "64": "Financial services", "65": "Insurance", "66": "Financial auxiliary",
    "68": "Real estate", "69": "Legal and accounting",
    "70": "Management consultancy", "71": "Architecture/engineering",
    "72": "Scientific R&D", "73": "Advertising", "74": "Professional",
    "78": "Employment activities", "85": "Education", "86": "Human health",
    "90": "Creative arts", "93": "Sports/amusement", "96": "Other services",
}


@dataclass
class GSTINValidation:
    gstin: str
    is_valid: bool
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    pan: Optional[str] = None
    entity_number: Optional[str] = None
    checksum_valid: bool = False
    error: Optional[str] = None


@dataclass
class CINValidation:
    cin: str
    is_valid: bool
    listing_status: Optional[str] = None  # Listed/Unlisted
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    year_of_incorporation: Optional[int] = None
    industry_division: Optional[str] = None
    company_ownership: Optional[str] = None  # PLC/PVT/PUB/NPL etc
    registration_number: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PANValidation:
    pan: str
    is_valid: bool
    pan_type: Optional[str] = None  # Person/Company/HUF/etc
    error: Optional[str] = None


# ============================================================
# GSTIN — Format: 22AAAAA0000A1Z5 (15 chars)
# Position 1-2: State code
# Position 3-12: PAN
# Position 13: Entity code (1-9, A-Z)
# Position 14: Z (default)
# Position 15: Checksum
# ============================================================

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

# Luhn mod 36 checksum chars
GSTIN_CHECKSUM_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gstin_checksum(gstin_first_14: str) -> str:
    """Calculate Luhn mod 36 checksum for GSTIN."""
    factor = 2
    total = 0
    code_len = len(GSTIN_CHECKSUM_CHARS)

    for ch in reversed(gstin_first_14):
        digit = GSTIN_CHECKSUM_CHARS.index(ch)
        digit = digit * factor
        factor = 1 if factor == 2 else 2
        digit = (digit // code_len) + (digit % code_len)
        total += digit

    remainder = total % code_len
    check_code_point = (code_len - remainder) % code_len
    return GSTIN_CHECKSUM_CHARS[check_code_point]


def validate_gstin(gstin: str) -> GSTINValidation:
    """Validate GSTIN format and checksum.

    Works entirely client-side — no API calls.
    """
    gstin = gstin.strip().upper()

    if len(gstin) != 15:
        return GSTINValidation(gstin=gstin, is_valid=False, error="GSTIN must be 15 characters")

    if not GSTIN_RE.match(gstin):
        return GSTINValidation(gstin=gstin, is_valid=False, error="Invalid GSTIN format")

    state_code = gstin[:2]
    pan = gstin[2:12]
    entity = gstin[12]

    if state_code not in STATE_CODES:
        return GSTINValidation(
            gstin=gstin, is_valid=False,
            error="Unknown state code: {}".format(state_code),
        )

    # Verify checksum
    expected_checksum = _gstin_checksum(gstin[:14])
    actual_checksum = gstin[14]
    checksum_ok = expected_checksum == actual_checksum

    return GSTINValidation(
        gstin=gstin,
        is_valid=checksum_ok,
        state_code=state_code,
        state_name=STATE_CODES[state_code],
        pan=pan,
        entity_number=entity,
        checksum_valid=checksum_ok,
        error=None if checksum_ok else "Checksum mismatch",
    )


# ============================================================
# CIN — Format: L/U + 5-digit industry + 2-char state +
#              4-digit year + 3-char ownership + 6-digit number
# Example: L17110MH1973PLC019786
# ============================================================

CIN_RE = re.compile(
    r"^([LU])"                    # 1: Listed/Unlisted
    r"(\d{5})"                    # 2-6: Industry NIC code
    r"([A-Z]{2})"                 # 7-8: State code
    r"(\d{4})"                    # 9-12: Year of incorporation
    r"([A-Z]{3})"                 # 13-15: Ownership type
    r"(\d{6})$"                   # 16-21: Registration number
)

OWNERSHIP_TYPES = {
    "PLC": "Public Limited Company",
    "PTC": "Private Limited Company",
    "FLC": "Foreign Limited Company",
    "FTC": "Foreign Trading Company",
    "GOI": "Government of India",
    "SGC": "State Government Company",
    "NPL": "Not For Profit License",
    "GAP": "General Association Public",
    "GAT": "General Association Trust",
    "ULL": "Unlimited Liability",
    "ULT": "Unlimited Liability with Limited Transferability",
    "OPC": "One Person Company",
}


def validate_cin(cin: str) -> CINValidation:
    """Validate CIN format and extract metadata."""
    cin = cin.strip().upper()

    if len(cin) != 21:
        return CINValidation(cin=cin, is_valid=False, error="CIN must be 21 characters")

    match = CIN_RE.match(cin)
    if not match:
        return CINValidation(cin=cin, is_valid=False, error="Invalid CIN format")

    listing, industry_code, state, year, ownership, reg_number = match.groups()

    if state not in CIN_STATE_CODES:
        return CINValidation(cin=cin, is_valid=False, error="Unknown state code: {}".format(state))

    year_int = int(year)
    if year_int < 1850 or year_int > 2100:
        return CINValidation(cin=cin, is_valid=False, error="Invalid year: {}".format(year))

    # Industry division (first 2 digits of NIC code)
    industry_div = industry_code[:2]
    industry_name = NIC_DIVISIONS.get(industry_div, "Unknown/Other")

    return CINValidation(
        cin=cin,
        is_valid=True,
        listing_status=COMPANY_CLASS.get(listing, "Unknown"),
        state_code=state,
        state_name=CIN_STATE_CODES[state],
        year_of_incorporation=year_int,
        industry_division=industry_name,
        company_ownership=OWNERSHIP_TYPES.get(ownership, "Unknown ({})".format(ownership)),
        registration_number=reg_number,
    )


# ============================================================
# PAN — Format: AAAPL1234C (10 chars)
# Position 4: Type (P=Person, C=Company, H=HUF, F=Firm, A=AOP, T=Trust, B=BOI, L=Local Auth, J=Artificial, G=Gov)
# ============================================================

PAN_RE = re.compile(r"^[A-Z]{3}[PCHFATBLJG][A-Z]{1}\d{4}[A-Z]{1}$")

PAN_TYPES = {
    "P": "Individual",
    "C": "Company",
    "H": "Hindu Undivided Family",
    "F": "Firm/Partnership",
    "A": "Association of Persons",
    "T": "Trust",
    "B": "Body of Individuals",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}


def validate_pan(pan: str) -> PANValidation:
    """Validate PAN format and extract type."""
    pan = pan.strip().upper()

    if len(pan) != 10:
        return PANValidation(pan=pan, is_valid=False, error="PAN must be 10 characters")

    if not PAN_RE.match(pan):
        return PANValidation(pan=pan, is_valid=False, error="Invalid PAN format")

    pan_type = PAN_TYPES.get(pan[3], "Unknown")

    return PANValidation(
        pan=pan,
        is_valid=True,
        pan_type=pan_type,
    )


def pan_from_gstin(gstin: str) -> Optional[str]:
    """Extract PAN from GSTIN (chars 3-12)."""
    if len(gstin) != 15:
        return None
    return gstin[2:12]

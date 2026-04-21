"""OpenAI function calling spec for SentinelCorp."""

from __future__ import annotations

import json
import httpx

API_URL = "https://sentinelcorp-production.up.railway.app"

SENTINELCORP_FUNCTIONS = [
    {
        "name": "company_risk_profile",
        "description": "Get risk profile for an Indian company. Accepts CIN, GSTIN, PAN, or company name. Returns risk score 0-100, SEBI debarment status, and risk signals.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "CIN, GSTIN, PAN, or company name"},
                "type": {"type": "string", "enum": ["auto", "cin", "gstin", "pan", "name"], "default": "auto"},
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "validate_gstin",
        "description": "Validate format and checksum of an Indian GSTIN.",
        "parameters": {
            "type": "object",
            "properties": {"gstin": {"type": "string"}},
            "required": ["gstin"],
        },
    },
    {
        "name": "validate_cin",
        "description": "Validate format of an Indian CIN (Corporate Identification Number) and extract metadata.",
        "parameters": {
            "type": "object",
            "properties": {"cin": {"type": "string"}},
            "required": ["cin"],
        },
    },
    {
        "name": "search_debarred",
        "description": "Search SEBI/NSE/BSE debarred entities database by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Company or person name"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["name"],
        },
    },
]


def handle_sentinelcorp_call(function_call) -> str:
    name = function_call["name"] if isinstance(function_call, dict) else function_call.name
    args_str = function_call["arguments"] if isinstance(function_call, dict) else function_call.arguments
    args = json.loads(args_str)

    if name == "company_risk_profile":
        resp = httpx.get(
            "{}/api/v1/company/profile".format(API_URL),
            params={"identifier": args["identifier"], "type": args.get("type", "auto")},
            timeout=15,
        )
    elif name == "validate_gstin":
        resp = httpx.get("{}/api/v1/validate/gstin".format(API_URL), params={"gstin": args["gstin"]}, timeout=10)
    elif name == "validate_cin":
        resp = httpx.get("{}/api/v1/validate/cin".format(API_URL), params={"cin": args["cin"]}, timeout=10)
    elif name == "search_debarred":
        resp = httpx.get(
            "{}/api/v1/debarred/search".format(API_URL),
            params={"name": args["name"], "limit": args.get("limit", 10)},
            timeout=10,
        )
    else:
        return json.dumps({"error": "Unknown function: {}".format(name)})

    return resp.text


SENTINELCORP_TOOLS = [{"type": "function", "function": f} for f in SENTINELCORP_FUNCTIONS]

"""SentinelCorp MCP Server — Model Context Protocol server for AI agent discovery.

Allows Claude, Cursor, and MCP-compatible clients to auto-discover and use
SentinelCorp tools for India company risk profiling.

Add to MCP client config:
    {
      "mcpServers": {
        "sentinelcorp": {
          "command": "python",
          "args": ["integrations/mcp_server.py"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

API_URL = "https://sentinelcorp-production.up.railway.app"

TOOLS = [
    {
        "name": "company_risk_profile",
        "description": "Get unified risk profile for an Indian company. Accepts CIN, GSTIN, PAN, or company name. Returns risk score (0-100), SEBI debarment status, signals, and historical lookup count.",
        "inputSchema": {
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
        "description": "Validate GSTIN format with checksum verification and extract state, PAN, entity details.",
        "inputSchema": {
            "type": "object",
            "properties": {"gstin": {"type": "string"}},
            "required": ["gstin"],
        },
    },
    {
        "name": "validate_cin",
        "description": "Validate CIN format and extract metadata (listing status, state, year of incorporation, industry, ownership type).",
        "inputSchema": {
            "type": "object",
            "properties": {"cin": {"type": "string"}},
            "required": ["cin"],
        },
    },
    {
        "name": "validate_pan",
        "description": "Validate PAN format and identify PAN type (Individual, Company, HUF, etc).",
        "inputSchema": {
            "type": "object",
            "properties": {"pan": {"type": "string"}},
            "required": ["pan"],
        },
    },
    {
        "name": "search_debarred",
        "description": "Search SEBI/NSE/BSE debarred entities database by name. Essential for compliance/sanctions screening of Indian entities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["name"],
        },
    },
    {
        "name": "batch_profile",
        "description": "Risk profile up to 100 Indian companies in one request. Use for due diligence workflows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifiers": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
            },
            "required": ["identifiers"],
        },
    },
]


def _call(path: str, params: dict = None, method: str = "GET", body: dict = None) -> Any:
    if method == "GET":
        resp = httpx.get("{}{}".format(API_URL, path), params=params or {}, timeout=15)
    else:
        resp = httpx.post("{}{}".format(API_URL, path), json=body or {}, timeout=15)
    return resp.json()


def handle_tool_call(name: str, arguments: dict) -> Any:
    if name == "company_risk_profile":
        return _call("/api/v1/company/profile", {"identifier": arguments["identifier"], "type": arguments.get("type", "auto")})
    if name == "validate_gstin":
        return _call("/api/v1/validate/gstin", {"gstin": arguments["gstin"]})
    if name == "validate_cin":
        return _call("/api/v1/validate/cin", {"cin": arguments["cin"]})
    if name == "validate_pan":
        return _call("/api/v1/validate/pan", {"pan": arguments["pan"]})
    if name == "search_debarred":
        return _call("/api/v1/debarred/search", {"name": arguments["name"], "limit": arguments.get("limit", 10)})
    if name == "batch_profile":
        return _call("/api/v1/company/batch", method="POST", body={"identifiers": arguments["identifiers"]})
    return {"error": "Unknown tool: {}".format(name)}


def run_stdio():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            request = json.loads(line.strip())
        except (json.JSONDecodeError, KeyboardInterrupt):
            break

        method = request.get("method", "")
        req_id = request.get("id")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "sentinelcorp", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            params = request.get("params", {})
            result = handle_tool_call(params.get("name", ""), params.get("arguments", {}))
            response = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        else:
            response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_stdio()

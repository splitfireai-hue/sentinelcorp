"""
SentinelCorp LangChain Tools.

Usage:
    from integrations.langchain_tool import get_sentinelcorp_tools
    tools = get_sentinelcorp_tools()
    agent = initialize_agent(tools, llm, agent="zero-shot-react-description")
    agent.run("Is Sahara India a high-risk company?")
"""

from __future__ import annotations

import httpx
from langchain.tools import BaseTool

API_URL = "https://sentinelcorp-production.up.railway.app"  # Update after deploy


class SentinelCorpCompanyProfile(BaseTool):
    name: str = "sentinelcorp_company_profile"
    description: str = (
        "Get unified risk profile for an Indian company. "
        "Input: CIN, GSTIN, PAN, or company name. "
        "Returns risk score (0-100), risk level, SEBI debarment status, and signals. "
        "Use to check if a company is legitimate before engaging."
    )

    def _run(self, identifier: str) -> str:
        identifier = identifier.strip().strip("'\"")
        resp = httpx.get(
            "{}/api/v1/company/profile".format(API_URL),
            params={"identifier": identifier, "type": "auto"},
            timeout=15,
        )
        if resp.status_code != 200:
            return "Error: {}".format(resp.text)
        d = resp.json()
        lines = [
            "Company: {}".format(d.get("query")),
            "Type: {}".format(d.get("query_type")),
            "Risk Score: {}/100 ({})".format(d["overall_risk_score"], d["risk_level"]),
            "SEBI Debarred: {}".format(d["is_debarred"]),
        ]
        if d.get("debarred_matches"):
            lines.append("Matches in debarred list:")
            for m in d["debarred_matches"][:3]:
                lines.append("  - {} (confidence: {})".format(m["matched_name"], m["confidence"]))
        if d.get("signals"):
            lines.append("Risk signals:")
            for s in d["signals"]:
                lines.append("  - [{}] {}".format(s["severity"], s["description"]))
        return "\n".join(lines)

    async def _arun(self, identifier: str) -> str:
        return self._run(identifier)


class SentinelCorpValidate(BaseTool):
    name: str = "sentinelcorp_validate_identifier"
    description: str = (
        "Validate format and checksum of Indian identifiers (GSTIN, CIN, PAN). "
        "Input format: 'TYPE:VALUE' where TYPE is gstin/cin/pan. Example: 'gstin:27AAACT1234A1Z5'. "
        "Use before looking up companies to ensure identifier is well-formed."
    )

    def _run(self, query: str) -> str:
        parts = query.split(":", 1)
        if len(parts) != 2:
            return "Invalid format. Use 'gstin:VALUE' or 'cin:VALUE' or 'pan:VALUE'"
        id_type, value = parts[0].strip().lower(), parts[1].strip()
        if id_type not in ("gstin", "cin", "pan"):
            return "Unknown type: {}".format(id_type)
        resp = httpx.get("{}/api/v1/validate/{}".format(API_URL, id_type), params={id_type: value}, timeout=10)
        d = resp.json()
        return "Valid: {}, Parsed: {}".format(d["is_valid"], d.get("parsed", {}))

    async def _arun(self, query: str) -> str:
        return self._run(query)


class SentinelCorpDebarredSearch(BaseTool):
    name: str = "sentinelcorp_debarred_search"
    description: str = (
        "Search the SEBI/NSE/BSE debarred entities database by name. "
        "Input: company or person name. "
        "Returns list of debarred entities matching the name. "
        "Use for compliance due diligence."
    )

    def _run(self, name: str) -> str:
        resp = httpx.get(
            "{}/api/v1/debarred/search".format(API_URL),
            params={"name": name.strip(), "limit": 10},
            timeout=10,
        )
        d = resp.json()
        if d["total"] == 0:
            return "No matches found for '{}'".format(name)
        lines = ["Found {} matches:".format(d["total"])]
        for m in d["matches"][:10]:
            lines.append("  - {} [{}]".format(m["name"], m["source"]))
        return "\n".join(lines)

    async def _arun(self, name: str) -> str:
        return self._run(name)


def get_sentinelcorp_tools():
    """Return all SentinelCorp tools for LangChain agent initialization."""
    return [
        SentinelCorpCompanyProfile(),
        SentinelCorpValidate(),
        SentinelCorpDebarredSearch(),
    ]

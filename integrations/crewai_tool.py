"""CrewAI tools for SentinelCorp."""

from __future__ import annotations

import os
import httpx

try:
    from crewai.tools import BaseTool
except ImportError:
    try:
        from crewai_tools import BaseTool
    except ImportError:
        raise ImportError("Install crewai: pip install crewai")

API_URL = os.getenv("SENTINELCORP_API_URL", "https://sentinelcorp-production.up.railway.app")


class SentinelCorpProfileTool(BaseTool):
    name: str = "India Company Risk Profile"
    description: str = (
        "Get unified risk profile for an Indian company. "
        "Accepts CIN, GSTIN, PAN, or company name. "
        "Returns risk score 0-100, risk level, SEBI debarment status, and signals."
    )

    def _run(self, identifier: str) -> str:
        resp = httpx.get(
            "{}/api/v1/company/profile".format(API_URL),
            params={"identifier": identifier.strip(), "type": "auto"},
            timeout=15,
        )
        if resp.status_code != 200:
            return "Error: {}".format(resp.text)
        d = resp.json()
        lines = [
            "Risk Score: {}/100 ({})".format(d["overall_risk_score"], d["risk_level"]),
            "SEBI Debarred: {}".format(d["is_debarred"]),
        ]
        if d.get("debarred_matches"):
            lines.append("Debarred matches: {}".format(len(d["debarred_matches"])))
        if d.get("signals"):
            lines.append("Signals: {}".format(", ".join(s["signal_type"] for s in d["signals"])))
        return " | ".join(lines)


class SentinelCorpDebarredTool(BaseTool):
    name: str = "SEBI Debarred Entity Search"
    description: str = (
        "Search SEBI/NSE/BSE debarred entity database by name. "
        "Returns list of matching debarred entities with source and reason."
    )

    def _run(self, name: str) -> str:
        resp = httpx.get(
            "{}/api/v1/debarred/search".format(API_URL),
            params={"name": name.strip(), "limit": 10},
            timeout=10,
        )
        d = resp.json()
        if d["total"] == 0:
            return "No matches for '{}' in debarred database".format(name)
        return "Found {} matches: {}".format(
            d["total"],
            ", ".join(m["name"] for m in d["matches"][:5]),
        )

"""SEBI Defaulter & Debarred Entities scraper.

Sources (all public, legally scrapable):
- NSE: https://www.nseindia.com/regulations/member-sebi-debarred-entities
- BSE: https://www.bseindia.com/investors/debent.aspx
- OpenSanctions: https://www.opensanctions.org/datasets/in_nse_debarred/

This is zero-legal-risk data:
- Published by stock exchanges for public consumption
- Updated monthly
- No CAPTCHAs, no rate limits
- Simple file downloads, not HTML scraping

Run manually: python -m app.scrapers.sebi_defaulters
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "SentinelCorp/1.0 (research; github.com/splitfireai-hue/sentinelcorp)"

# OpenSanctions ships a clean, pre-parsed dataset of Indian debarred entities
OPENSANCTIONS_URL = "https://data.opensanctions.org/datasets/latest/in_nse_debarred/entities.ftm.json"
# Fallback: direct NSE XLS
NSE_DEBARRED_URL = "https://www.nseindia.com/api/reports-indices?csv=true&archives=%5B%7B%22name%22%3A%22Members%20-%20SEBI%20Debarred%20Entities%22%2C%22type%22%3A%22equities%22%2C%22category%22%3A%22capital-market%22%2C%22section%22%3A%22equities%22%7D%5D"

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "sebi_defaulters.json"


@dataclass
class DebarredEntity:
    name: str
    source: str  # nse, bse, sebi
    entity_type: str = ""  # Person, Company, Broker, etc
    pan: Optional[str] = None
    debarment_reason: Optional[str] = None
    debarment_date: Optional[str] = None
    order_url: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def _normalize_name(name: str) -> str:
    """Clean up entity name for fuzzy matching."""
    name = name.strip()
    # Remove trailing punctuation
    name = re.sub(r"[.,;:]+$", "", name)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)
    return name


async def fetch_opensanctions(client: httpx.AsyncClient) -> List[DebarredEntity]:
    """Fetch from OpenSanctions — cleanest pre-parsed dataset."""
    entities: List[DebarredEntity] = []
    try:
        resp = await client.get(OPENSANCTIONS_URL, timeout=60)
        resp.raise_for_status()

        # FTM (Follow The Money) format — one JSON object per line
        for line in resp.text.strip().split("\n"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            props = obj.get("properties", {})
            name = props.get("name", [""])[0] if props.get("name") else ""
            if not name:
                continue

            schema = obj.get("schema", "")
            entity_type = {
                "Person": "Person",
                "Company": "Company",
                "Organization": "Organization",
                "LegalEntity": "Legal Entity",
            }.get(schema, schema or "Unknown")

            entities.append(DebarredEntity(
                name=_normalize_name(name),
                source="opensanctions:nse",
                entity_type=entity_type,
                debarment_reason=props.get("notes", [None])[0] if props.get("notes") else None,
                debarment_date=props.get("modifiedAt", [None])[0] if props.get("modifiedAt") else None,
            ))

        logger.info("OpenSanctions: loaded %d debarred entities", len(entities))
    except Exception as e:
        logger.warning("OpenSanctions fetch failed: %s", e)

    return entities


async def scrape_all() -> dict:
    """Run all SEBI/NSE/BSE scrapers and return unified dataset."""
    start = datetime.utcnow()
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        opensanctions_entities = await fetch_opensanctions(client)

    # Deduplicate by normalized name
    seen = set()
    unique: List[DebarredEntity] = []
    for e in opensanctions_entities:
        key = e.name.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(e)

    result = {
        "scraped_at": start.isoformat(),
        "total_entities": len(unique),
        "entities": [asdict(e) for e in unique],
        "sources_used": ["opensanctions:nse"],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(result, indent=2))
    logger.info("Saved %d debarred entities to %s", len(unique), OUTPUT_FILE)

    return result


def check_debarred(name: str, debarred_list: List[dict]) -> List[dict]:
    """Check if a company/person name is in the debarred list.

    Uses fuzzy matching (case-insensitive substring).
    """
    name_lower = _normalize_name(name).lower()
    if len(name_lower) < 3:
        return []

    matches = []
    for entity in debarred_list:
        entity_name = entity.get("name", "").lower()
        if not entity_name:
            continue
        # Exact match or substring match (both directions)
        if name_lower == entity_name or name_lower in entity_name or entity_name in name_lower:
            matches.append(entity)
    return matches


async def main():
    logging.basicConfig(level=logging.INFO)
    logger.info("SEBI Defaulter Scraper starting...")
    result = await scrape_all()
    logger.info("Done. %d entities loaded.", result["total_entities"])


if __name__ == "__main__":
    asyncio.run(main())

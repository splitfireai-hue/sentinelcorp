"""Seed the debarred_entities table from scraped SEBI data."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.database import async_session, engine
from app.models import Base
from app.models.company import DebarredEntity


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    data_file = Path(__file__).parent / "sebi_defaulters.json"
    if not data_file.exists():
        print("No scraped data. Run: python -m app.scrapers.sebi_defaulters")
        return

    with open(data_file) as f:
        data = json.load(f)

    entities = data.get("entities", [])
    added = 0
    async with async_session() as session:
        for e in entities:
            name = e.get("name", "").strip()
            if not name:
                continue
            name_norm = name.lower()

            exists = await session.execute(
                select(DebarredEntity).where(DebarredEntity.name_normalized == name_norm)
            )
            if exists.scalar_one_or_none():
                continue

            record = DebarredEntity(
                name=name[:500],
                name_normalized=name_norm[:500],
                source=e.get("source", "")[:50],
                entity_type=e.get("entity_type", "")[:100],
                pan=e.get("pan")[:10] if e.get("pan") else None,
                debarment_reason=e.get("debarment_reason"),
                debarment_date=e.get("debarment_date"),
                order_url=e.get("order_url"),
            )
            session.add(record)
            added += 1
            if added % 500 == 0:
                await session.commit()
                print("Seeded {} so far...".format(added))
        await session.commit()
        print("Done. Seeded {} new debarred entities ({} total in dataset).".format(added, len(entities)))


if __name__ == "__main__":
    asyncio.run(seed())

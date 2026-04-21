"""SEBI/NSE/BSE debarred entity search endpoints."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.company import DebarredEntity

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class DebarredEntry(BaseModel):
    name: str
    source: str
    entity_type: str = ""
    debarment_reason: Optional[str] = None
    debarment_date: Optional[str] = None


class DebarredSearchResponse(BaseModel):
    query: str
    total: int
    matches: List[DebarredEntry]


class DebarredListResponse(BaseModel):
    total: int
    entities: List[DebarredEntry]


@router.get("/search", response_model=DebarredSearchResponse)
@limiter.limit(settings.SEARCH_RATE_LIMIT)
async def search_debarred(
    request: Request,
    name: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search SEBI/NSE/BSE debarred entities by name."""
    name_lower = name.strip().lower()
    stmt = (
        select(DebarredEntity)
        .where(
            or_(
                DebarredEntity.name_normalized == name_lower,
                DebarredEntity.name_normalized.like("%{}%".format(name_lower)),
            )
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    entities = result.scalars().all()

    return DebarredSearchResponse(
        query=name,
        total=len(entities),
        matches=[
            DebarredEntry(
                name=e.name,
                source=e.source,
                entity_type=e.entity_type,
                debarment_reason=e.debarment_reason,
                debarment_date=e.debarment_date,
            )
            for e in entities
        ],
    )


@router.get("/list", response_model=DebarredListResponse)
@limiter.limit(settings.SEARCH_RATE_LIMIT)
async def list_debarred(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List debarred entities (paginated)."""
    count_result = await db.execute(select(func.count(DebarredEntity.id)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(DebarredEntity)
        .order_by(desc(DebarredEntity.updated_at))
        .offset(offset)
        .limit(limit)
    )

    return DebarredListResponse(
        total=total,
        entities=[
            DebarredEntry(
                name=e.name,
                source=e.source,
                entity_type=e.entity_type,
                debarment_reason=e.debarment_reason,
                debarment_date=e.debarment_date,
            )
            for e in result.scalars().all()
        ],
    )

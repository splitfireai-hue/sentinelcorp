from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.company import DebarredEntity, LookupHistory

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

_started_at = time.time()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    checks = {"database": "ok"}
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("DB health check failed: %s", e)
        checks["database"] = "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@router.get("/info")
async def info():
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "tagline": "India Company Risk Profile API for AI Agents",
        "description": "Unified risk scoring from MCA, GST, Court records, and SEBI debarred entities. Built for agents. 1,000 free requests, no signup.",
        "sibling_products": [
            {
                "name": "SentinelX402",
                "description": "Threat intelligence API with CERT-In India advisories",
                "url": "https://sentinelx402-production.up.railway.app",
            },
        ],
        "free_tier": {
            "enabled": settings.FREE_TIER_ENABLED,
            "requests": settings.FREE_TIER_REQUESTS,
        },
        "endpoints": [
            {"path": "/api/v1/validate/gstin", "method": "GET", "description": "Validate GSTIN format and checksum"},
            {"path": "/api/v1/validate/cin", "method": "GET", "description": "Validate CIN format and extract metadata"},
            {"path": "/api/v1/validate/pan", "method": "GET", "description": "Validate PAN format"},
            {"path": "/api/v1/company/profile", "method": "GET", "description": "Get unified company risk profile"},
            {"path": "/api/v1/company/batch", "method": "POST", "description": "Batch risk profiling (up to 100 identifiers)"},
            {"path": "/api/v1/debarred/search", "method": "GET", "description": "Search SEBI/NSE/BSE debarred entities"},
            {"path": "/api/v1/debarred/list", "method": "GET", "description": "List recent debarred entities"},
        ],
    }


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    debarred_count = await db.execute(select(func.count(DebarredEntity.id)))
    lookup_count = await db.execute(select(func.count(LookupHistory.id)))
    unique_clients = await db.execute(
        select(func.count(func.distinct(LookupHistory.client_id)))
        .where(LookupHistory.client_id != "")
    )

    return {
        "uptime_seconds": round(time.time() - _started_at),
        "data_coverage": {
            "debarred_entities": debarred_count.scalar_one() or 0,
        },
        "usage": {
            "total_lookups": lookup_count.scalar_one() or 0,
            "unique_clients": unique_clients.scalar_one() or 0,
        },
        "performance": {
            "target_latency_validation": "<20ms",
            "target_latency_profile": "<300ms",
        },
    }

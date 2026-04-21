from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import APIKey, AnonUsageCounter, UsageCounter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TierConfig:
    name: str
    display_name: str
    monthly_quota: int
    rate_limit_per_min: int
    price_inr_monthly: int
    price_usd_monthly: float


TIERS: dict[str, TierConfig] = {
    "free": TierConfig("free", "Free", 5_000, 30, 0, 0.0),
    "dev": TierConfig("dev", "Dev", 50_000, 120, 499, 6.0),
    "startup": TierConfig("startup", "Startup", 500_000, 600, 2_499, 30.0),
    "enterprise": TierConfig("enterprise", "Enterprise", 10_000_000, 3_000, 0, 0.0),
}

ANON_DAILY_LIMIT = 100
KEY_PREFIX_LIVE = "sk_live_"
KEY_PREFIX_TEST = "sk_test_"
KEY_BODY_BYTES = 24


def _is_sqlite() -> bool:
    return settings.DATABASE_URL.startswith("sqlite")


def _upsert_stmt(table, values: dict, conflict_cols: list[str], update_cols: dict):
    if _is_sqlite():
        stmt = sqlite_insert(table).values(**values)
        return stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
    stmt = pg_insert(table).values(**values)
    return stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_ip(ip: str) -> str:
    salt = settings.ADMIN_SECRET or "sentinelcorp"
    return hashlib.sha256("{}:{}".format(salt, ip).encode("utf-8")).hexdigest()


def generate_raw_key(test: bool = False) -> str:
    prefix = KEY_PREFIX_TEST if test else KEY_PREFIX_LIVE
    body = secrets.token_urlsafe(KEY_BODY_BYTES).rstrip("=")
    return prefix + body


async def issue_key(
    session: AsyncSession,
    email: str,
    name: str = "",
    tier: str = "free",
    notes: Optional[str] = None,
    test: bool = False,
) -> tuple[str, APIKey]:
    if tier not in TIERS:
        raise ValueError("Unknown tier: {}".format(tier))
    cfg = TIERS[tier]
    raw = generate_raw_key(test=test)
    row = APIKey(
        key_hash=hash_key(raw),
        key_prefix=raw[:12],
        key_last4=raw[-4:],
        name=name.strip()[:200],
        email=email.strip().lower()[:200],
        tier=tier,
        status="active",
        monthly_quota=cfg.monthly_quota,
        rate_limit_per_min=cfg.rate_limit_per_min,
        notes=notes,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("Issued API key id=%s tier=%s email=%s", row.id, tier, row.email)
    return raw, row


async def lookup_key(session: AsyncSession, raw_key: str) -> Optional[APIKey]:
    if not raw_key:
        return None
    if not (raw_key.startswith(KEY_PREFIX_LIVE) or raw_key.startswith(KEY_PREFIX_TEST)):
        return None
    key_hash = hash_key(raw_key)
    stmt = select(APIKey).where(APIKey.key_hash == key_hash)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def current_year_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def current_day() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


async def get_monthly_count(
    session: AsyncSession, api_key_id: int, product: str = "sentinelcorp"
) -> int:
    stmt = select(UsageCounter.count).where(
        UsageCounter.api_key_id == api_key_id,
        UsageCounter.product == product,
        UsageCounter.year_month == current_year_month(),
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return int(row or 0)


async def increment_usage(
    session: AsyncSession, api_key_id: int, product: str = "sentinelcorp"
) -> None:
    ym = current_year_month()
    values = {
        "api_key_id": api_key_id,
        "product": product,
        "year_month": ym,
        "count": 1,
    }
    stmt = _upsert_stmt(
        UsageCounter.__table__,
        values,
        ["api_key_id", "product", "year_month"],
        {"count": UsageCounter.__table__.c.count + 1},
    )
    try:
        await session.execute(stmt)
        await session.execute(
            update(APIKey).where(APIKey.id == api_key_id).values(last_used_at=datetime.utcnow())
        )
        await session.commit()
    except Exception:
        logger.exception("increment_usage failed for key_id=%s", api_key_id)
        await session.rollback()


async def anon_count_and_increment(session: AsyncSession, ip: str) -> int:
    """Return the count AFTER increment for today. Used by middleware to enforce anon limit."""
    ip_h = hash_ip(ip)
    day = current_day()
    values = {"ip_hash": ip_h, "day": day, "count": 1}
    stmt = _upsert_stmt(
        AnonUsageCounter.__table__,
        values,
        ["ip_hash", "day"],
        {"count": AnonUsageCounter.__table__.c.count + 1},
    )
    try:
        await session.execute(stmt)
        await session.commit()
    except Exception:
        logger.exception("anon_count_and_increment failed ip_hash=%s", ip_h[:8])
        await session.rollback()
        return 0
    result = await session.execute(
        select(AnonUsageCounter.count).where(
            AnonUsageCounter.ip_hash == ip_h, AnonUsageCounter.day == day
        )
    )
    return int(result.scalar_one_or_none() or 0)


async def revoke_key(session: AsyncSession, api_key_id: int) -> bool:
    stmt = (
        update(APIKey)
        .where(APIKey.id == api_key_id)
        .values(status="revoked", revoked_at=datetime.utcnow())
    )
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0


async def set_tier(session: AsyncSession, api_key_id: int, tier: str) -> bool:
    if tier not in TIERS:
        raise ValueError("Unknown tier: {}".format(tier))
    cfg = TIERS[tier]
    stmt = (
        update(APIKey)
        .where(APIKey.id == api_key_id)
        .values(
            tier=tier,
            monthly_quota=cfg.monthly_quota,
            rate_limit_per_min=cfg.rate_limit_per_min,
            status="active",
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0

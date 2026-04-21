from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class APIKey(Base):
    """Issued API key. Only the hash is stored; the raw key is shown once at creation."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_last4: Mapped[str] = mapped_column(String(4))
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), index=True)

    tier: Mapped[str] = mapped_column(String(32), default="free")
    status: Mapped[str] = mapped_column(String(32), default="active")
    monthly_quota: Mapped[int] = mapped_column(Integer, default=5000)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Subscription(Base):
    """Paid subscription linked to an API key."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)

    rail: Mapped[str] = mapped_column(String(32))
    plan: Mapped[str] = mapped_column(String(32))

    external_customer_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    external_subscription_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    status: Mapped[str] = mapped_column(String(32), default="pending")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    amount_minor: Mapped[int] = mapped_column(Integer, default=0)

    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UsageCounter(Base):
    """Denormalized monthly counter per API key + product. Used for fast quota checks."""
    __tablename__ = "usage_counters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    product: Mapped[str] = mapped_column(String(32), default="sentinelcorp")
    year_month: Mapped[str] = mapped_column(String(7))
    count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("api_key_id", "product", "year_month", name="uq_usage_key_product_month"),
        Index("ix_usage_month", "year_month"),
    )


class AnonUsageCounter(Base):
    """Per-IP daily counter for unauthenticated free-trial traffic."""
    __tablename__ = "anon_usage_counters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10))
    count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("ip_hash", "day", name="uq_anon_ip_day"),
    )

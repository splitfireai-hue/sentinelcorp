from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DebarredEntity(Base):
    """SEBI/NSE/BSE debarred entities — public sanction list."""
    __tablename__ = "debarred_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    name_normalized: Mapped[str] = mapped_column(String(500), index=True)  # lowercased
    source: Mapped[str] = mapped_column(String(50))  # nse, bse, sebi
    entity_type: Mapped[str] = mapped_column(String(100), default="")
    pan: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    debarment_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    debarment_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    order_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyProfile(Base):
    """Cached company profile data.

    Populated from third-party APIs (MCA, GST) when looked up.
    """
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    identifier: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # CIN or GSTIN
    identifier_type: Mapped[str] = mapped_column(String(20))  # cin, gstin, pan
    company_name: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    incorporation_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    registered_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    paid_up_capital: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    company_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    directors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_refreshed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LookupHistory(Base):
    """Every company lookup tracked — compounds into historical data over time."""
    __tablename__ = "lookup_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    identifier_type: Mapped[str] = mapped_column(String(20), index=True)
    identifier_value: Mapped[str] = mapped_column(String(500), index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    looked_up_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    client_id: Mapped[str] = mapped_column(String(256), default="")

    __table_args__ = (
        Index("ix_identifier_lookup", "identifier_type", "identifier_value"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    tier: Mapped[str] = mapped_column(String(20), default="free")
    monthly_quota: Mapped[int] = mapped_column(Integer, default=10000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)

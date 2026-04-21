"""Test fixtures."""

from __future__ import annotations

import os
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["ENVIRONMENT"] = "test"

from app.models import Base
from app.models.company import DebarredEntity

engine = create_async_engine("sqlite+aiosqlite://", echo=False)
test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_factory() as session:
        yield session


@pytest.fixture
async def seeded_db(db: AsyncSession) -> AsyncSession:
    """DB with sample debarred entities."""
    entities = [
        DebarredEntity(
            name="Sahara India Limited",
            name_normalized="sahara india limited",
            source="opensanctions:nse",
            entity_type="Company",
        ),
        DebarredEntity(
            name="Rakesh Jhunjhunwala (associated)",
            name_normalized="rakesh jhunjhunwala (associated)",
            source="opensanctions:nse",
            entity_type="Person",
        ),
    ]
    db.add_all(entities)
    await db.commit()
    return db


@pytest.fixture
async def client(seeded_db):
    from httpx import ASGITransport, AsyncClient
    from app.database import get_db
    from app.main import app

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

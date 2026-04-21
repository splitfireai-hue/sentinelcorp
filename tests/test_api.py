"""Integration tests for API endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_info(client):
    r = await client.get("/info")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "SentinelCorp"


@pytest.mark.asyncio
async def test_validate_gstin_endpoint(client):
    from app.services.validators import _gstin_checksum
    base = "27AAACT1234A1Z"
    gstin = base + _gstin_checksum(base)
    r = await client.get("/api/v1/validate/gstin", params={"gstin": gstin})
    assert r.status_code == 200
    assert r.json()["is_valid"]


@pytest.mark.asyncio
async def test_validate_cin_endpoint(client):
    r = await client.get("/api/v1/validate/cin", params={"cin": "L17110MH1973PLC019786"})
    assert r.status_code == 200
    assert r.json()["is_valid"]


@pytest.mark.asyncio
async def test_company_profile_clean(client):
    r = await client.get("/api/v1/company/profile", params={"identifier": "Random Clean Company", "type": "name"})
    assert r.status_code == 200
    data = r.json()
    assert data["overall_risk_score"] == 0.0
    assert not data["is_debarred"]


@pytest.mark.asyncio
async def test_company_profile_debarred(client):
    r = await client.get("/api/v1/company/profile", params={"identifier": "Sahara", "type": "name"})
    assert r.status_code == 200
    data = r.json()
    assert data["is_debarred"]
    assert len(data["debarred_matches"]) > 0


@pytest.mark.asyncio
async def test_debarred_search(client):
    r = await client.get("/api/v1/debarred/search", params={"name": "sahara"})
    assert r.status_code == 200
    assert r.json()["total"] > 0


@pytest.mark.asyncio
async def test_batch_profile(client):
    r = await client.post(
        "/api/v1/company/batch",
        json={"identifiers": ["Company A", "Company B"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_stats(client):
    r = await client.get("/stats")
    assert r.status_code == 200
    assert "data_coverage" in r.json()

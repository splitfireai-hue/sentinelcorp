"""Billing + API key auth tests."""

from __future__ import annotations

import os

import pytest

from app.services import auth


@pytest.mark.asyncio
async def test_hash_and_generate_key():
    k1 = auth.generate_raw_key()
    assert k1.startswith("sk_live_")
    assert len(k1) > 20
    k2 = auth.generate_raw_key()
    assert k1 != k2
    h1 = auth.hash_key(k1)
    h2 = auth.hash_key(k1)
    assert h1 == h2
    assert h1 != auth.hash_key(k2)


@pytest.mark.asyncio
async def test_issue_and_lookup_key(db):
    raw, row = await auth.issue_key(db, email="alice@example.com", name="Alice", tier="dev")
    assert row.tier == "dev"
    assert row.monthly_quota == auth.TIERS["dev"].monthly_quota
    assert row.email == "alice@example.com"
    assert row.key_prefix == raw[:12]
    assert row.key_last4 == raw[-4:]

    found = await auth.lookup_key(db, raw)
    assert found is not None
    assert found.id == row.id

    assert await auth.lookup_key(db, "sk_live_invalid") is None
    assert await auth.lookup_key(db, "") is None
    assert await auth.lookup_key(db, "not_a_key_format") is None


@pytest.mark.asyncio
async def test_issue_key_invalid_tier(db):
    with pytest.raises(ValueError):
        await auth.issue_key(db, email="x@y.com", tier="premium")


@pytest.mark.asyncio
async def test_usage_counter(db):
    raw, row = await auth.issue_key(db, email="b@c.com", tier="free")
    assert await auth.get_monthly_count(db, row.id) == 0
    await auth.increment_usage(db, row.id)
    await auth.increment_usage(db, row.id)
    await auth.increment_usage(db, row.id)
    assert await auth.get_monthly_count(db, row.id) == 3


@pytest.mark.asyncio
async def test_anon_counter(db):
    n1 = await auth.anon_count_and_increment(db, "9.9.9.9")
    n2 = await auth.anon_count_and_increment(db, "9.9.9.9")
    n3 = await auth.anon_count_and_increment(db, "9.9.9.9")
    assert n1 == 1
    assert n2 == 2
    assert n3 == 3
    other = await auth.anon_count_and_increment(db, "8.8.8.8")
    assert other == 1


@pytest.mark.asyncio
async def test_tier_upgrade(db):
    raw, row = await auth.issue_key(db, email="c@d.com", tier="free")
    assert row.monthly_quota == 5_000
    ok = await auth.set_tier(db, row.id, "startup")
    assert ok
    refreshed = await auth.lookup_key(db, raw)
    assert refreshed.tier == "startup"
    assert refreshed.monthly_quota == 500_000


@pytest.mark.asyncio
async def test_revoke(db):
    raw, row = await auth.issue_key(db, email="d@e.com", tier="free")
    assert row.status == "active"
    ok = await auth.revoke_key(db, row.id)
    assert ok
    refreshed = await auth.lookup_key(db, raw)
    assert refreshed.status == "revoked"


@pytest.mark.asyncio
async def test_pricing_endpoint(client):
    r = await client.get("/pricing")
    assert r.status_code == 200
    d = r.json()
    assert "tiers" in d
    names = {t["name"] for t in d["tiers"]}
    assert {"free", "dev", "startup", "enterprise"}.issubset(names)
    assert d["anon_daily_limit"] == auth.ANON_DAILY_LIMIT


@pytest.mark.asyncio
async def test_signup_creates_free_tier(client):
    r = await client.post("/billing/signup", json={"email": "new@user.com", "name": "Tester"})
    assert r.status_code == 201
    d = r.json()
    assert d["tier"] == "free"
    assert d["monthly_quota"] == 5_000
    assert d["api_key"].startswith("sk_live_")


@pytest.mark.asyncio
async def test_signup_ignores_requested_tier(client):
    r = await client.post("/billing/signup", json={"email": "hacker@x.com", "tier": "enterprise"})
    assert r.status_code == 201
    assert r.json()["tier"] == "free"


@pytest.mark.asyncio
async def test_admin_endpoint_requires_secret(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ADMIN_SECRET", "secret-abc")

    r = await client.post(
        "/billing/admin/keys",
        json={"email": "paid@u.com", "tier": "startup"},
    )
    assert r.status_code == 403

    r = await client.post(
        "/billing/admin/keys",
        headers={"X-Admin-Secret": "wrong"},
        json={"email": "paid@u.com", "tier": "startup"},
    )
    assert r.status_code == 403

    r = await client.post(
        "/billing/admin/keys",
        headers={"X-Admin-Secret": "secret-abc"},
        json={"email": "paid@u.com", "tier": "startup"},
    )
    assert r.status_code == 201
    assert r.json()["tier"] == "startup"
    assert r.json()["monthly_quota"] == 500_000


@pytest.mark.asyncio
async def test_billing_me_requires_key(client):
    r = await client.get("/billing/me")
    assert r.status_code == 401

    r = await client.get("/billing/me", headers={"X-API-Key": "sk_live_invalid"})
    assert r.status_code == 401

    signup = await client.post("/billing/signup", json={"email": "m@e.com"})
    key = signup.json()["api_key"]

    r = await client.get("/billing/me", headers={"X-API-Key": key})
    assert r.status_code == 200
    d = r.json()
    assert d["tier"] == "free"
    assert d["used_this_month"] == 0
    assert d["remaining"] == 5_000


@pytest.mark.asyncio
async def test_signup_page_renders(client):
    r = await client.get("/signup")
    assert r.status_code == 200
    assert "Get your free API key" in r.text

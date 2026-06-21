"""Regression tests for the Stripe webhook handler.

Guards the bug where handle_event 500'd on every event (it called .get() on a
StripeObject), so paid customers' keys were never activated. The router now
hands handle_event a plain dict (json of the signature-verified body); these
tests lock in that contract.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.billing import APIKey, Subscription
from app.services import auth, stripe_service


async def _tier_of(db, key_id: int) -> str:
    row = (await db.execute(select(APIKey).where(APIKey.id == key_id))).scalar_one()
    return row.tier


async def test_checkout_completed_activates_key(db):
    raw, key = await auth.issue_key(db, email="webhook@test.com", name="W", tier="free")
    session_id = "cs_test_regression_activate"
    db.add(
        Subscription(
            api_key_id=key.id,
            rail="stripe",
            plan="dev",
            external_subscription_id=session_id,
            status="pending",
            currency="usd",
            amount_minor=600,
        )
    )
    await db.commit()

    # Exactly what the router passes after verifying the signature: a plain dict.
    event = {
        "id": "evt_regression_activate",
        "type": "checkout.session.completed",
        "data": {"object": {"id": session_id, "subscription": "sub_x", "customer": "cus_x"}},
    }
    result = await stripe_service.handle_event(db, event)

    assert result.get("ok") is True
    assert await _tier_of(db, key.id) == "dev"

    sub = (
        await db.execute(
            select(Subscription).where(Subscription.external_subscription_id == "sub_x")
        )
    ).scalar_one()
    assert sub.status == "active"


async def test_unknown_session_does_not_crash(db):
    # A checkout for a session we never created must be handled gracefully (no 500).
    event = {
        "id": "evt_regression_unknown",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_never_seen", "subscription": "sub_y"}},
    }
    result = await stripe_service.handle_event(db, event)
    assert result.get("ok") is False


async def test_duplicate_event_ignored(db):
    event = {
        "id": "evt_regression_dupe",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_dupe"}},
    }
    first = await stripe_service.handle_event(db, event)
    second = await stripe_service.handle_event(db, event)
    assert second.get("duplicate") is True

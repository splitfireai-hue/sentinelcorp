from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import razorpay
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import APIKey, Subscription
from app.services import auth as auth_service

logger = logging.getLogger(__name__)


PLAN_TO_TIER: dict[str, str] = {}


def _rebuild_plan_map():
    PLAN_TO_TIER.clear()
    if settings.RAZORPAY_PLAN_DEV:
        PLAN_TO_TIER[settings.RAZORPAY_PLAN_DEV] = "dev"
    if settings.RAZORPAY_PLAN_STARTUP:
        PLAN_TO_TIER[settings.RAZORPAY_PLAN_STARTUP] = "startup"


_rebuild_plan_map()


@dataclass
class CheckoutResult:
    subscription_id: str
    short_url: Optional[str]
    razorpay_key_id: str
    api_key: str
    api_key_last4: str
    tier: str


def _is_configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _client() -> razorpay.Client:
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    client.set_app_details({"title": "SentinelCorp", "version": settings.API_VERSION})
    return client


def _plan_id_for_tier(tier: str) -> Optional[str]:
    _rebuild_plan_map()
    for plan_id, t in PLAN_TO_TIER.items():
        if t == tier:
            return plan_id
    return None


def _tier_for_plan(plan_id: str) -> Optional[str]:
    _rebuild_plan_map()
    return PLAN_TO_TIER.get(plan_id)


async def create_checkout(
    session: AsyncSession,
    email: str,
    tier: str,
    name: str = "",
) -> CheckoutResult:
    """Create a Razorpay subscription + issue a pending APIKey that will be upgraded
    when the webhook confirms payment."""
    if not _is_configured():
        raise RuntimeError("Razorpay is not configured on this server")

    plan_id = _plan_id_for_tier(tier)
    if not plan_id:
        raise ValueError("No Razorpay plan configured for tier '{}'".format(tier))

    raw_key, key_row = await auth_service.issue_key(
        session, email=email, name=name, tier="free", notes="Pending razorpay sub for tier=" + tier
    )

    client = _client()
    sub_payload = {
        "plan_id": plan_id,
        "total_count": 120,
        "customer_notify": 1,
        "notes": {
            "api_key_id": str(key_row.id),
            "email": email,
            "pending_tier": tier,
        },
    }
    try:
        subscription = client.subscription.create(sub_payload)
    except Exception as e:
        logger.exception("Razorpay subscription.create failed")
        raise RuntimeError("Failed to create subscription: {}".format(e))

    sub_row = Subscription(
        api_key_id=key_row.id,
        rail="razorpay",
        plan=tier,
        external_subscription_id=subscription["id"],
        status="pending",
        currency="INR",
        amount_minor=auth_service.TIERS[tier].price_inr_monthly * 100,
    )
    session.add(sub_row)
    await session.commit()

    logger.info(
        "Razorpay checkout: sub=%s key_id=%s tier=%s email=%s",
        subscription["id"],
        key_row.id,
        tier,
        email,
    )

    return CheckoutResult(
        subscription_id=subscription["id"],
        short_url=subscription.get("short_url"),
        razorpay_key_id=settings.RAZORPAY_KEY_ID,
        api_key=raw_key,
        api_key_last4=key_row.key_last4,
        tier=tier,
    )


def verify_webhook_signature(body_bytes: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_webhook(session: AsyncSession, payload: dict) -> dict:
    event = payload.get("event", "")
    sub_payload = (payload.get("payload") or {}).get("subscription", {}).get("entity") or {}
    sub_id = sub_payload.get("id") or ""
    plan_id = sub_payload.get("plan_id") or ""

    if not sub_id:
        return {"ok": False, "reason": "no subscription id in payload"}

    result = await session.execute(
        select(Subscription).where(Subscription.external_subscription_id == sub_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        logger.warning("Webhook for unknown subscription %s event=%s", sub_id, event)
        return {"ok": False, "reason": "unknown subscription"}

    pending_tier = sub.plan or _tier_for_plan(plan_id) or "free"

    now = datetime.utcnow()
    if event in ("subscription.activated", "subscription.charged", "subscription.authenticated"):
        sub.status = "active"
        cps = sub_payload.get("current_start")
        cpe = sub_payload.get("current_end")
        if cps:
            sub.current_period_start = datetime.utcfromtimestamp(int(cps))
        if cpe:
            sub.current_period_end = datetime.utcfromtimestamp(int(cpe))
        await auth_service.set_tier(session, sub.api_key_id, pending_tier)
        logger.info("Razorpay: activated sub=%s key_id=%s tier=%s", sub_id, sub.api_key_id, pending_tier)

    elif event in ("subscription.halted", "subscription.paused"):
        sub.status = "halted"
        await auth_service.set_tier(session, sub.api_key_id, "free")
        logger.info("Razorpay: halted sub=%s", sub_id)

    elif event == "subscription.cancelled":
        sub.status = "cancelled"
        sub.cancel_at_period_end = False
        await auth_service.set_tier(session, sub.api_key_id, "free")
        logger.info("Razorpay: cancelled sub=%s", sub_id)

    elif event == "subscription.completed":
        sub.status = "completed"
        await auth_service.set_tier(session, sub.api_key_id, "free")
        logger.info("Razorpay: completed sub=%s", sub_id)

    else:
        logger.info("Razorpay: ignored event=%s sub=%s", event, sub_id)
        return {"ok": True, "ignored": True}

    sub.updated_at = now
    await session.commit()
    return {"ok": True, "event": event, "subscription_id": sub_id}

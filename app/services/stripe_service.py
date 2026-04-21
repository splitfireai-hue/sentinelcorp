from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import Subscription
from app.services import auth as auth_service

logger = logging.getLogger(__name__)


PRICE_TO_TIER: dict[str, str] = {}


def _rebuild_price_map():
    PRICE_TO_TIER.clear()
    if settings.STRIPE_PRICE_DEV:
        PRICE_TO_TIER[settings.STRIPE_PRICE_DEV] = "dev"
    if settings.STRIPE_PRICE_STARTUP:
        PRICE_TO_TIER[settings.STRIPE_PRICE_STARTUP] = "startup"


_rebuild_price_map()


@dataclass
class CheckoutResult:
    checkout_url: str
    session_id: str
    api_key_id: int
    tier: str


def _is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _configure():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = "2024-06-20"


def _price_for_tier(tier: str) -> Optional[str]:
    _rebuild_price_map()
    for price_id, t in PRICE_TO_TIER.items():
        if t == tier:
            return price_id
    return None


def _tier_for_price(price_id: str) -> Optional[str]:
    _rebuild_price_map()
    return PRICE_TO_TIER.get(price_id)


async def create_checkout(
    session: AsyncSession,
    email: str,
    tier: str,
    success_url: str,
    cancel_url: str,
    name: str = "",
) -> CheckoutResult:
    if not _is_configured():
        raise RuntimeError("Stripe is not configured on this server")
    price_id = _price_for_tier(tier)
    if not price_id:
        raise ValueError("No Stripe price configured for tier '{}'".format(tier))

    raw_key, key_row = await auth_service.issue_key(
        session, email=email, name=name, tier="free", notes="Pending stripe sub for tier=" + tier
    )

    _configure()
    try:
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=email,
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(key_row.id),
            metadata={
                "api_key_id": str(key_row.id),
                "pending_tier": tier,
                "email": email,
                "raw_key_last4": key_row.key_last4,
            },
            subscription_data={
                "metadata": {
                    "api_key_id": str(key_row.id),
                    "pending_tier": tier,
                    "email": email,
                },
            },
        )
    except Exception as e:
        logger.exception("Stripe checkout.Session.create failed")
        raise RuntimeError("Failed to create Stripe checkout: {}".format(e))

    sub_row = Subscription(
        api_key_id=key_row.id,
        rail="stripe",
        plan=tier,
        external_subscription_id=checkout.id,
        status="pending",
        currency="USD",
        amount_minor=int(auth_service.TIERS[tier].price_usd_monthly * 100),
    )
    session.add(sub_row)
    await session.commit()

    logger.info(
        "Stripe checkout: session=%s key_id=%s tier=%s email=%s",
        checkout.id,
        key_row.id,
        tier,
        email,
    )

    return CheckoutResult(
        checkout_url=checkout.url,
        session_id=checkout.id,
        api_key_id=key_row.id,
        tier=tier,
    )


def verify_and_parse_event(body_bytes: bytes, sig_header: str):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    _configure()
    return stripe.Webhook.construct_event(
        body_bytes, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )


async def _find_sub_by_external_id(
    session: AsyncSession, external_id: str
) -> Optional[Subscription]:
    result = await session.execute(
        select(Subscription).where(Subscription.external_subscription_id == external_id)
    )
    return result.scalar_one_or_none()


async def handle_event(session: AsyncSession, event) -> dict:
    etype = event.get("type") if isinstance(event, dict) else event["type"]
    data = event["data"]["object"] if isinstance(event, dict) else event["data"]["object"]

    if etype == "checkout.session.completed":
        session_id = data.get("id")
        sub_id = data.get("subscription")
        meta = data.get("metadata") or {}
        pending_tier = meta.get("pending_tier", "dev")
        api_key_id = int(meta.get("api_key_id") or 0)

        existing = await _find_sub_by_external_id(session, session_id)
        if existing is None:
            logger.warning("Stripe checkout.completed for unknown session=%s", session_id)
            return {"ok": False, "reason": "unknown session"}
        if sub_id:
            existing.external_subscription_id = sub_id
        existing.status = "active"
        existing.external_customer_id = data.get("customer")
        existing.updated_at = datetime.utcnow()
        if api_key_id:
            await auth_service.set_tier(session, api_key_id, pending_tier)
        await session.commit()
        logger.info("Stripe: checkout complete key_id=%s tier=%s sub=%s", api_key_id, pending_tier, sub_id)
        return {"ok": True, "event": etype}

    if etype in ("customer.subscription.updated", "customer.subscription.created"):
        sub_id = data.get("id")
        existing = await _find_sub_by_external_id(session, sub_id)
        if existing is None:
            return {"ok": True, "ignored": True}
        existing.status = data.get("status") or existing.status
        cps = data.get("current_period_start")
        cpe = data.get("current_period_end")
        if cps:
            existing.current_period_start = datetime.utcfromtimestamp(int(cps))
        if cpe:
            existing.current_period_end = datetime.utcfromtimestamp(int(cpe))
        existing.cancel_at_period_end = bool(data.get("cancel_at_period_end"))

        items = (data.get("items") or {}).get("data") or []
        if items:
            price_id = (items[0].get("price") or {}).get("id")
            tier = _tier_for_price(price_id) if price_id else None
            if tier and existing.status == "active":
                await auth_service.set_tier(session, existing.api_key_id, tier)
                existing.plan = tier

        existing.updated_at = datetime.utcnow()
        await session.commit()
        return {"ok": True, "event": etype}

    if etype == "customer.subscription.deleted":
        sub_id = data.get("id")
        existing = await _find_sub_by_external_id(session, sub_id)
        if existing is None:
            return {"ok": True, "ignored": True}
        existing.status = "cancelled"
        existing.updated_at = datetime.utcnow()
        await auth_service.set_tier(session, existing.api_key_id, "free")
        await session.commit()
        logger.info("Stripe: cancelled sub=%s", sub_id)
        return {"ok": True, "event": etype}

    if etype in ("invoice.payment_failed", "invoice.payment_action_required"):
        sub_id = data.get("subscription")
        existing = await _find_sub_by_external_id(session, sub_id) if sub_id else None
        if existing:
            existing.status = "past_due"
            existing.updated_at = datetime.utcnow()
            await session.commit()
        return {"ok": True, "event": etype}

    return {"ok": True, "ignored": True, "event": etype}

from __future__ import annotations

import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import auth as auth_service
from app.services import razorpay_service, stripe_service

logger = logging.getLogger(__name__)

router = APIRouter()


class IssueKeyRequest(BaseModel):
    email: EmailStr
    name: str = Field(default="", max_length=200)
    tier: str = Field(default="free")
    notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("name", "notes")
    @classmethod
    def _no_html(cls, v):
        if v and any(c in v for c in "<>"):
            raise ValueError("must not contain '<' or '>'")
        return v


class IssueKeyResponse(BaseModel):
    api_key: str
    prefix: str
    last4: str
    tier: str
    monthly_quota: int
    rate_limit_per_min: int
    email: str
    note: str = "Store this key securely. It will not be shown again."


class KeyInfoResponse(BaseModel):
    prefix: str
    last4: str
    tier: str
    status: str
    email: str
    monthly_quota: int
    used_this_month: int
    remaining: int
    rate_limit_per_min: int


class TierInfo(BaseModel):
    name: str
    display_name: str
    monthly_quota: int
    rate_limit_per_min: int
    price_inr_monthly: int
    price_usd_monthly: float


def _require_admin(x_admin_secret: str = Header(default="", alias="X-Admin-Secret")):
    if not settings.ADMIN_SECRET:
        raise HTTPException(status_code=503, detail="Admin endpoints disabled (ADMIN_SECRET not set)")
    if not secrets.compare_digest(x_admin_secret, settings.ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Invalid admin secret")


async def _require_key(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_db),
):
    raw = x_api_key.strip()
    if not raw and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Provide X-API-Key header")
    api_key = await auth_service.lookup_key(session, raw)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if api_key.status == "revoked":
        raise HTTPException(status_code=403, detail="API key has been revoked")
    return api_key


PRICING_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pricing — SentinelCorp</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;padding:40px 20px}
.wrap{max-width:1100px;margin:0 auto}
h1{text-align:center;font-size:36px;margin-bottom:8px;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{text-align:center;color:#888;font-size:15px;margin-bottom:40px}
.currency{display:flex;justify-content:center;gap:8px;margin-bottom:28px}
.currency button{background:#161616;border:1px solid #222;color:#888;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px}
.currency button.active{background:#3b82f6;color:#fff;border-color:#3b82f6}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;max-width:980px;margin:0 auto}
.plan{background:#161616;border:1px solid #222;border-radius:12px;padding:28px;display:flex;flex-direction:column}
.plan.featured{border-color:#3b82f6}
.name{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px}
.price{font-size:36px;font-weight:700;margin:8px 0 4px}
.period{font-size:13px;color:#666;margin-bottom:16px}
.limit{font-size:14px;color:#4ade80;margin-bottom:16px}
.features{list-style:none;flex:1;margin-bottom:20px;font-size:13px;color:#aaa}
.features li{padding:6px 0;border-bottom:1px solid #222}
.features li::before{content:'OK ';color:#4ade80;font-weight:700}
button.pay{background:#3b82f6;color:#fff;border:none;padding:12px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600;width:100%}
button.pay:hover{background:#2563eb}
button.pay:disabled{background:#333;cursor:not-allowed}
button.pay.secondary{background:#161616;border:1px solid #333;color:#e0e0e0}
.note{text-align:center;margin-top:24px;font-size:12px;color:#555}
#form-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);align-items:center;justify-content:center;z-index:100;padding:20px}
#form-modal.show{display:flex}
.modal-card{background:#161616;border:1px solid #222;border-radius:12px;padding:28px;max-width:420px;width:100%}
.modal-card h2{font-size:20px;margin-bottom:12px}
.modal-card label{display:block;font-size:11px;color:#888;text-transform:uppercase;margin-top:12px;margin-bottom:4px}
.modal-card input{width:100%;padding:10px;background:#0d0d0d;border:1px solid #333;border-radius:6px;color:#fff;font-size:14px}
.row{display:flex;gap:8px;margin-top:20px}
.row button{flex:1}
.error{color:#f87171;font-size:12px;margin-top:8px}
</style></head><body>
<div class="wrap">
<h1>Pricing</h1>
<p class="sub">Pay with UPI, cards, or netbanking. Cancel anytime.</p>
<div class="currency">
<button class="active" id="btn-inr" onclick="setCur('inr')">India (INR)</button>
<button id="btn-usd" onclick="setCur('usd')">Global (USD)</button>
</div>
<div class="grid" id="plans"></div>
<p class="note">Already have a key? <a href="/billing/me" style="color:#60a5fa">Check usage</a></p>
</div>

<div id="form-modal">
<div class="modal-card">
<h2>Checkout: <span id="selected-tier"></span></h2>
<label>Email</label>
<input id="email" type="email" required placeholder="you@company.com">
<label>Name (optional)</label>
<input id="name" type="text" placeholder="Company or project">
<div class="row">
<button class="pay secondary" onclick="closeModal()">Cancel</button>
<button class="pay" id="pay-btn" onclick="doPay()">Continue</button>
</div>
<div class="error" id="err"></div>
</div>
</div>

<script>
let currency = 'inr';
let selectedTier = null;
let pricingData = null;

async function load() {
  const r = await fetch('/pricing.json');
  pricingData = await r.json();
  render();
}

function setCur(c) {
  currency = c;
  document.getElementById('btn-inr').classList.toggle('active', c === 'inr');
  document.getElementById('btn-usd').classList.toggle('active', c === 'usd');
  render();
}

function render() {
  const paidTiers = pricingData.tiers.filter(t => t.name !== 'enterprise');
  const grid = document.getElementById('plans');
  grid.innerHTML = paidTiers.map((t, i) => {
    const price = currency === 'inr'
      ? (t.price_inr_monthly === 0 ? 'Free' : '&#8377;' + t.price_inr_monthly)
      : (t.price_usd_monthly === 0 ? 'Free' : '$' + t.price_usd_monthly);
    const period = t.price_inr_monthly === 0 ? '' : '/month';
    const rail = currency === 'inr' ? 'razorpay' : 'stripe';
    const railAvailable = pricingData.rails[rail];
    const btnLabel = t.name === 'free' ? 'Get free key' : (railAvailable ? 'Subscribe' : 'Coming soon');
    const btnAction = t.name === 'free'
      ? "window.location='/signup'"
      : "openModal('" + t.name + "')";
    const btnDisabled = t.name !== 'free' && !railAvailable ? 'disabled' : '';
    return '<div class="plan ' + (i === 1 ? 'featured' : '') + '">' +
      '<div class="name">' + t.display_name + '</div>' +
      '<div class="price">' + price + '</div>' +
      '<div class="period">' + period + '</div>' +
      '<div class="limit">' + t.monthly_quota.toLocaleString() + ' requests/month</div>' +
      '<ul class="features">' +
      '<li>' + t.rate_limit_per_min + ' req/min rate limit</li>' +
      '<li>All endpoints included</li>' +
      '<li>' + (t.name === 'free' ? 'Community support' : 'Email support') + '</li>' +
      '</ul>' +
      '<button class="pay" ' + btnDisabled + ' onclick="' + btnAction + '">' + btnLabel + '</button>' +
      '</div>';
  }).join('');
}

function openModal(tier) {
  selectedTier = tier;
  document.getElementById('selected-tier').textContent = tier;
  document.getElementById('err').textContent = '';
  document.getElementById('form-modal').classList.add('show');
}

function closeModal() {
  document.getElementById('form-modal').classList.remove('show');
}

async function doPay() {
  const email = document.getElementById('email').value.trim();
  const name = document.getElementById('name').value.trim();
  const err = document.getElementById('err');
  const btn = document.getElementById('pay-btn');
  if (!email) { err.textContent = 'Email is required'; return; }
  btn.disabled = true; btn.textContent = 'Processing...';
  try {
    if (currency === 'inr') {
      const resp = await fetch('/billing/checkout/razorpay', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, name, tier: selectedTier}),
      });
      const d = await resp.json();
      if (!resp.ok) throw new Error(d.detail || 'Checkout failed');
      sessionStorage.setItem('pending_api_key', d.api_key);
      const opts = {
        key: d.razorpay_key_id,
        subscription_id: d.subscription_id,
        name: 'SentinelCorp',
        description: selectedTier.charAt(0).toUpperCase() + selectedTier.slice(1) + ' tier',
        prefill: {email, name},
        theme: {color: '#3b82f6'},
        handler: function() { window.location = '/billing/success'; },
      };
      new Razorpay(opts).open();
      closeModal();
    } else {
      const resp = await fetch('/billing/checkout/stripe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, name, tier: selectedTier}),
      });
      const d = await resp.json();
      if (!resp.ok) throw new Error(d.detail || 'Checkout failed');
      window.location = d.checkout_url;
    }
  } catch (e) {
    err.textContent = e.message;
    btn.disabled = false; btn.textContent = 'Continue';
  }
}

load();
</script>
</body></html>"""


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def pricing_page(accept: str = Header(default="")):
    # Respect Accept: application/json for programmatic clients
    return PRICING_PAGE


@router.get("/pricing.json", response_model=dict)
async def pricing_json():
    tiers = []
    for t in auth_service.TIERS.values():
        tiers.append(
            TierInfo(
                name=t.name,
                display_name=t.display_name,
                monthly_quota=t.monthly_quota,
                rate_limit_per_min=t.rate_limit_per_min,
                price_inr_monthly=t.price_inr_monthly,
                price_usd_monthly=t.price_usd_monthly,
            ).model_dump()
        )
    return {
        "tiers": tiers,
        "anon_daily_limit": auth_service.ANON_DAILY_LIMIT,
        "billing_enabled": settings.BILLING_ENABLED,
        "rails": {
            "razorpay": bool(settings.RAZORPAY_KEY_ID),
            "stripe": bool(settings.STRIPE_SECRET_KEY),
            "x402": settings.X402_ENABLED and bool(settings.X402_WALLET_ADDRESS),
        },
        "x402": {
            "enabled": settings.X402_ENABLED,
            "wallet": settings.X402_WALLET_ADDRESS,
            "network": settings.X402_NETWORK_ID,
            "facilitator": settings.X402_FACILITATOR_URL,
            "prices": {
                "validate": settings.X402_PRICE_VALIDATE,
                "profile": settings.X402_PRICE_PROFILE,
                "debarred": settings.X402_PRICE_DEBARRED,
                "batch": settings.X402_PRICE_BATCH,
            },
        } if settings.X402_ENABLED else None,
    }


@router.post("/billing/signup", response_model=IssueKeyResponse, status_code=201)
async def self_signup_free_key(body: IssueKeyRequest, session: AsyncSession = Depends(get_db)):
    """Free-tier self-signup. Always issues a 'free' tier key regardless of requested tier."""
    raw, row = await auth_service.issue_key(
        session,
        email=body.email,
        name=body.name,
        tier="free",
        notes=body.notes,
    )
    return IssueKeyResponse(
        api_key=raw,
        prefix=row.key_prefix,
        last4=row.key_last4,
        tier=row.tier,
        monthly_quota=row.monthly_quota,
        rate_limit_per_min=row.rate_limit_per_min,
        email=row.email,
    )


@router.post(
    "/billing/admin/keys",
    response_model=IssueKeyResponse,
    status_code=201,
    dependencies=[Depends(_require_admin)],
)
async def admin_issue_key(body: IssueKeyRequest, session: AsyncSession = Depends(get_db)):
    raw, row = await auth_service.issue_key(
        session,
        email=body.email,
        name=body.name,
        tier=body.tier,
        notes=body.notes,
    )
    return IssueKeyResponse(
        api_key=raw,
        prefix=row.key_prefix,
        last4=row.key_last4,
        tier=row.tier,
        monthly_quota=row.monthly_quota,
        rate_limit_per_min=row.rate_limit_per_min,
        email=row.email,
    )


class SetTierRequest(BaseModel):
    tier: str


@router.patch(
    "/billing/admin/keys/{key_id}/tier",
    dependencies=[Depends(_require_admin)],
)
async def admin_set_tier(key_id: int, body: SetTierRequest, session: AsyncSession = Depends(get_db)):
    try:
        ok = await auth_service.set_tier(session, key_id, body.tier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"ok": True, "key_id": key_id, "tier": body.tier}


@router.delete(
    "/billing/admin/keys/{key_id}",
    dependencies=[Depends(_require_admin)],
)
async def admin_revoke_key(key_id: int, session: AsyncSession = Depends(get_db)):
    ok = await auth_service.revoke_key(session, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"ok": True, "key_id": key_id, "status": "revoked"}


@router.get("/billing/me", response_model=KeyInfoResponse)
async def my_key_info(
    api_key=Depends(_require_key),
    session: AsyncSession = Depends(get_db),
):
    used = await auth_service.get_monthly_count(session, api_key.id, settings.BILLING_PRODUCT)
    return KeyInfoResponse(
        prefix=api_key.key_prefix,
        last4=api_key.key_last4,
        tier=api_key.tier,
        status=api_key.status,
        email=api_key.email,
        monthly_quota=api_key.monthly_quota,
        used_this_month=used,
        remaining=max(api_key.monthly_quota - used, 0),
        rate_limit_per_min=api_key.rate_limit_per_min,
    )


SIGNUP_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelCorp — Get your free API key</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{max-width:480px;width:100%;background:#161616;border:1px solid #222;border-radius:12px;padding:32px}
h1{font-size:28px;font-weight:700;margin-bottom:8px;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tagline{font-size:14px;color:#888;margin-bottom:24px}
label{display:block;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;margin-top:16px}
input{width:100%;padding:12px;background:#0d0d0d;border:1px solid #333;border-radius:6px;color:#fff;font-size:14px}
input:focus{outline:none;border-color:#3b82f6}
button{margin-top:24px;width:100%;padding:12px;background:#3b82f6;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#2563eb}
button:disabled{background:#333;cursor:not-allowed}
.free{margin-top:16px;font-size:12px;color:#4ade80;text-align:center}
.result{margin-top:20px;padding:16px;background:#0d0d0d;border:1px solid #1f3d1f;border-radius:6px;font-size:13px;display:none}
.result.show{display:block}
.key{font-family:'SF Mono',Monaco,monospace;font-size:12px;color:#60a5fa;word-break:break-all;margin-top:8px;padding:8px;background:#000;border-radius:4px}
.warn{color:#f59e0b;font-size:11px;margin-top:8px}
a{color:#60a5fa;text-decoration:none}
.footer{margin-top:20px;font-size:11px;color:#555;text-align:center}
</style></head><body>
<div class="card">
<h1>Get your free API key</h1>
<p class="tagline">5,000 requests/month. No credit card. Instant.</p>
<form id="f">
<label>Email</label>
<input id="email" type="email" required placeholder="you@company.com">
<label>Name (optional)</label>
<input id="name" type="text" placeholder="Your company or project">
<button type="submit" id="submit">Get API Key</button>
</form>
<div id="result" class="result"></div>
<p class="free">Already have a key? <a href="/billing/me">Check usage →</a></p>
<div class="footer">Need more? <a href="/pricing">See pricing</a></div>
</div>
<script>
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('submit');
  const result = document.getElementById('result');
  btn.disabled = true; btn.textContent = 'Creating...';
  try {
    const resp = await fetch('/billing/signup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        email: document.getElementById('email').value,
        name: document.getElementById('name').value,
      }),
    });
    const d = await resp.json();
    if (!resp.ok) throw new Error(d.detail || 'Signup failed');
    result.className = 'result show';
    result.innerHTML = '<b style="color:#4ade80">Your API key</b>' +
      '<div class="key">' + d.api_key + '</div>' +
      '<div class="warn">Save this now — it will not be shown again.</div>' +
      '<div style="margin-top:12px;font-size:12px;color:#888">' +
      'Tier: ' + d.tier + ' | ' + d.monthly_quota.toLocaleString() + ' requests/month' +
      '</div>';
    btn.textContent = 'Created';
  } catch (err) {
    result.className = 'result show';
    result.style.borderColor = '#5c1a1a';
    result.innerHTML = '<b style="color:#f87171">Error</b><div style="margin-top:6px">' + err.message + '</div>';
    btn.disabled = false; btn.textContent = 'Get API Key';
  }
});
</script>
</body></html>"""


@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_page():
    return SIGNUP_PAGE


# ---------- Paid checkout + webhooks ----------


class CheckoutRequest(BaseModel):
    email: EmailStr
    tier: str = Field(..., description="dev or startup")
    name: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _no_html(cls, v):
        if v and any(c in v for c in "<>"):
            raise ValueError("must not contain '<' or '>'")
        return v


class RazorpayCheckoutResponse(BaseModel):
    subscription_id: str
    short_url: Optional[str]
    razorpay_key_id: str
    api_key: str
    api_key_last4: str
    tier: str


class StripeCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    tier: str


def _public_url(path: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/") if settings.PUBLIC_BASE_URL else ""
    if not base:
        return path
    return base + path


@router.post("/billing/checkout/razorpay", response_model=RazorpayCheckoutResponse)
async def razorpay_checkout(body: CheckoutRequest, session: AsyncSession = Depends(get_db)):
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Razorpay is not configured on this server")
    if body.tier not in ("dev", "startup"):
        raise HTTPException(status_code=400, detail="tier must be 'dev' or 'startup'")
    try:
        result = await razorpay_service.create_checkout(
            session=session,
            email=body.email,
            tier=body.tier,
            name=body.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return RazorpayCheckoutResponse(
        subscription_id=result.subscription_id,
        short_url=result.short_url,
        razorpay_key_id=result.razorpay_key_id,
        api_key=result.api_key,
        api_key_last4=result.api_key_last4,
        tier=result.tier,
    )


@router.post("/billing/checkout/stripe", response_model=StripeCheckoutResponse)
async def stripe_checkout(body: CheckoutRequest, session: AsyncSession = Depends(get_db)):
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured on this server")
    if body.tier not in ("dev", "startup"):
        raise HTTPException(status_code=400, detail="tier must be 'dev' or 'startup'")
    success_url = _public_url("/billing/success?session_id={CHECKOUT_SESSION_ID}")
    cancel_url = _public_url("/pricing")
    try:
        result = await stripe_service.create_checkout(
            session=session,
            email=body.email,
            tier=body.tier,
            success_url=success_url,
            cancel_url=cancel_url,
            name=body.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return StripeCheckoutResponse(
        checkout_url=result.checkout_url,
        session_id=result.session_id,
        tier=result.tier,
    )


@router.post("/billing/webhooks/razorpay", include_in_schema=False)
async def razorpay_webhook(request: Request, session: AsyncSession = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not razorpay_service.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="invalid signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    result = await razorpay_service.handle_webhook(session, payload)
    return JSONResponse(result)


@router.post("/billing/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_service.verify_and_parse_event(body, signature)
    except Exception as e:
        logger.warning("Stripe webhook verification failed: %s", e)
        raise HTTPException(status_code=400, detail="invalid signature")
    result = await stripe_service.handle_event(session, event)
    return JSONResponse(result)


class SubscriptionInfo(BaseModel):
    rail: str
    plan: str
    status: str
    currency: str
    amount_minor: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    cancel_at_period_end: bool


class DashboardData(BaseModel):
    key: KeyInfoResponse
    subscription: Optional[SubscriptionInfo] = None


async def _latest_subscription(session: AsyncSession, api_key_id: int):
    from sqlalchemy import desc, select as _select

    from app.models.billing import Subscription

    result = await session.execute(
        _select(Subscription)
        .where(Subscription.api_key_id == api_key_id)
        .order_by(desc(Subscription.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/billing/subscription", response_model=DashboardData)
async def my_subscription(
    api_key=Depends(_require_key),
    session: AsyncSession = Depends(get_db),
):
    used = await auth_service.get_monthly_count(session, api_key.id, settings.BILLING_PRODUCT)
    key_info = KeyInfoResponse(
        prefix=api_key.key_prefix,
        last4=api_key.key_last4,
        tier=api_key.tier,
        status=api_key.status,
        email=api_key.email,
        monthly_quota=api_key.monthly_quota,
        used_this_month=used,
        remaining=max(api_key.monthly_quota - used, 0),
        rate_limit_per_min=api_key.rate_limit_per_min,
    )
    sub = await _latest_subscription(session, api_key.id)
    sub_info = None
    if sub is not None:
        sub_info = SubscriptionInfo(
            rail=sub.rail,
            plan=sub.plan,
            status=sub.status,
            currency=sub.currency,
            amount_minor=sub.amount_minor,
            current_period_start=sub.current_period_start.isoformat() if sub.current_period_start else None,
            current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
            cancel_at_period_end=sub.cancel_at_period_end,
        )
    return DashboardData(key=key_info, subscription=sub_info)


@router.post("/billing/cancel")
async def cancel_my_subscription(
    api_key=Depends(_require_key),
    session: AsyncSession = Depends(get_db),
):
    sub = await _latest_subscription(session, api_key.id)
    if sub is None:
        raise HTTPException(status_code=404, detail="No subscription found for this key")
    if sub.status not in ("active", "authenticated", "past_due"):
        raise HTTPException(status_code=400, detail="Subscription is already {}".format(sub.status))
    try:
        if sub.rail == "razorpay":
            return await razorpay_service.cancel_subscription(session, sub)
        if sub.rail == "stripe":
            return await stripe_service.cancel_subscription(session, sub)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    raise HTTPException(status_code=400, detail="Unknown rail: {}".format(sub.rail))


@router.get("/billing/portal")
async def billing_portal(
    api_key=Depends(_require_key),
    session: AsyncSession = Depends(get_db),
):
    sub = await _latest_subscription(session, api_key.id)
    if sub is None or sub.rail != "stripe":
        raise HTTPException(
            status_code=400,
            detail="Self-serve portal only available for Stripe subscriptions",
        )
    return_url = _public_url("/billing/dashboard")
    try:
        url = await stripe_service.create_billing_portal(sub, return_url)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"url": url}


DASHBOARD_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Billing dashboard — SentinelCorp</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;padding:32px 16px}
.wrap{max-width:720px;margin:0 auto}
h1{font-size:28px;margin-bottom:24px;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#161616;border:1px solid #222;border-radius:12px;padding:24px;margin-bottom:16px}
.row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #1a1a1a}
.row:last-child{border:none}
.label{color:#888;font-size:13px}
.val{color:#e0e0e0;font-size:14px;font-weight:500}
.bar{height:10px;background:#0d0d0d;border-radius:5px;overflow:hidden;margin:8px 0 4px}
.fill{height:100%;background:linear-gradient(90deg,#3b82f6,#a78bfa);transition:width 0.4s}
.warn .fill{background:#f59e0b}
.crit .fill{background:#ef4444}
.usage-num{font-size:24px;font-weight:700;margin-bottom:4px}
.usage-sub{font-size:12px;color:#666}
button{padding:10px 18px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600}
.btn-primary{background:#3b82f6;color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-danger{background:#161616;color:#f87171;border:1px solid #5c1a1a}
.btn-danger:hover{background:#2a0e0e}
.actions{display:flex;gap:8px;margin-top:16px}
.tag{display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
.tag-active{background:#1a3d1a;color:#4ade80}
.tag-cancelled,.tag-past_due{background:#3d1a1a;color:#f87171}
.tag-pending{background:#3d2f1a;color:#f59e0b}
.tag-free,.tag-dev,.tag-startup,.tag-enterprise{background:#1a2a3d;color:#60a5fa}
#login{max-width:420px;margin:80px auto;background:#161616;border:1px solid #222;border-radius:12px;padding:32px}
#login h2{margin-bottom:8px;font-size:22px}
#login p{color:#888;font-size:13px;margin-bottom:16px}
#login input{width:100%;padding:11px;background:#0d0d0d;border:1px solid #333;border-radius:6px;color:#fff;font-size:13px;font-family:'SF Mono',Monaco,monospace;margin-bottom:12px}
#main{display:none}
.error{color:#f87171;font-size:12px;margin-top:8px}
a{color:#60a5fa;text-decoration:none}
.foot{text-align:center;font-size:12px;color:#555;margin-top:24px}
</style></head><body>
<div class="wrap">
<div id="login">
<h2>Sign in with API key</h2>
<p>Paste your <code>sk_live_...</code> key. Stored in your browser, never sent anywhere except sentinelcorp.</p>
<input id="key-input" placeholder="sk_live_..." autocomplete="off">
<button class="btn-primary" onclick="signIn()" style="width:100%">Continue</button>
<div id="login-err" class="error"></div>
<p style="margin-top:16px">Don't have a key? <a href="/signup">Get one free</a></p>
</div>

<div id="main">
<h1>Billing dashboard</h1>

<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
<div>
<div class="usage-num" id="used">0</div>
<div class="usage-sub">of <span id="quota">0</span> requests this month</div>
</div>
<div style="text-align:right">
<div class="usage-num" id="remaining">0</div>
<div class="usage-sub">remaining</div>
</div>
</div>
<div class="bar" id="bar-wrap"><div class="fill" id="bar"></div></div>
</div>

<div class="card">
<h2 style="font-size:16px;margin-bottom:12px;color:#aaa">API key</h2>
<div class="row"><span class="label">Key</span><span class="val" id="prefix"></span></div>
<div class="row"><span class="label">Tier</span><span class="val"><span class="tag" id="tier"></span></span></div>
<div class="row"><span class="label">Status</span><span class="val"><span class="tag" id="status"></span></span></div>
<div class="row"><span class="label">Email</span><span class="val" id="email"></span></div>
<div class="row"><span class="label">Rate limit</span><span class="val" id="ratelimit"></span></div>
</div>

<div class="card" id="sub-card" style="display:none">
<h2 style="font-size:16px;margin-bottom:12px;color:#aaa">Subscription</h2>
<div class="row"><span class="label">Plan</span><span class="val" id="sub-plan"></span></div>
<div class="row"><span class="label">Rail</span><span class="val" id="sub-rail"></span></div>
<div class="row"><span class="label">Amount</span><span class="val" id="sub-amount"></span></div>
<div class="row"><span class="label">Status</span><span class="val"><span class="tag" id="sub-status"></span></span></div>
<div class="row"><span class="label">Renews</span><span class="val" id="sub-renews"></span></div>
<div class="actions">
<button class="btn-primary" id="portal-btn" onclick="portal()" style="display:none">Manage subscription</button>
<button class="btn-danger" id="cancel-btn" onclick="cancelSub()">Cancel</button>
</div>
<div id="action-msg" class="error" style="margin-top:10px"></div>
</div>

<div class="actions">
<button class="btn-danger" onclick="signOut()">Sign out</button>
<a href="/pricing"><button class="btn-primary">Upgrade plan</button></a>
</div>

<p class="foot">Need help? Email support@sentinelcorp.dev</p>
</div>
</div>

<script>
const KEY_STORE = 'sentinelcorp_api_key';

function signIn() {
  const k = document.getElementById('key-input').value.trim();
  if (!k.startsWith('sk_live_') && !k.startsWith('sk_test_')) {
    document.getElementById('login-err').textContent = "Doesn't look like a SentinelCorp key.";
    return;
  }
  localStorage.setItem(KEY_STORE, k);
  load();
}

function signOut() {
  localStorage.removeItem(KEY_STORE);
  document.getElementById('main').style.display = 'none';
  document.getElementById('login').style.display = 'block';
}

function fmtAmount(currency, minor) {
  if (!minor) return 'Free';
  const major = (minor / 100).toFixed(2);
  return (currency === 'INR' ? '\u20B9' : '$') + major + '/mo';
}

function fmtDate(iso) {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleDateString();
}

async function load() {
  const k = localStorage.getItem(KEY_STORE);
  if (!k) return;
  try {
    const r = await fetch('/billing/subscription', {headers: {'X-API-Key': k}});
    if (r.status === 401) { signOut(); return; }
    const d = await r.json();
    document.getElementById('login').style.display = 'none';
    document.getElementById('main').style.display = 'block';

    const ki = d.key;
    document.getElementById('used').textContent = ki.used_this_month.toLocaleString();
    document.getElementById('quota').textContent = ki.monthly_quota.toLocaleString();
    document.getElementById('remaining').textContent = ki.remaining.toLocaleString();
    const pct = Math.min(100, (ki.used_this_month / ki.monthly_quota) * 100);
    document.getElementById('bar').style.width = pct + '%';
    const wrap = document.getElementById('bar-wrap');
    wrap.classList.remove('warn', 'crit');
    if (pct >= 90) wrap.classList.add('crit');
    else if (pct >= 75) wrap.classList.add('warn');

    document.getElementById('prefix').textContent = ki.prefix + '...' + ki.last4;
    const tagTier = document.getElementById('tier');
    tagTier.textContent = ki.tier;
    tagTier.className = 'tag tag-' + ki.tier;
    const tagStatus = document.getElementById('status');
    tagStatus.textContent = ki.status;
    tagStatus.className = 'tag tag-' + ki.status;
    document.getElementById('email').textContent = ki.email;
    document.getElementById('ratelimit').textContent = ki.rate_limit_per_min + ' req/min';

    if (d.subscription) {
      const s = d.subscription;
      document.getElementById('sub-card').style.display = 'block';
      document.getElementById('sub-plan').textContent = s.plan;
      document.getElementById('sub-rail').textContent = s.rail;
      document.getElementById('sub-amount').textContent = fmtAmount(s.currency, s.amount_minor);
      const sst = document.getElementById('sub-status');
      sst.textContent = s.status;
      sst.className = 'tag tag-' + s.status;
      document.getElementById('sub-renews').textContent =
        s.cancel_at_period_end
          ? 'Cancels on ' + fmtDate(s.current_period_end)
          : (s.current_period_end ? fmtDate(s.current_period_end) : 'Pending payment');
      if (s.rail === 'stripe' && s.status === 'active') {
        document.getElementById('portal-btn').style.display = 'inline-block';
      }
      if (s.status !== 'active' || s.cancel_at_period_end) {
        document.getElementById('cancel-btn').style.display = 'none';
      }
    }
  } catch (e) {
    document.getElementById('login-err').textContent = 'Failed to load: ' + e.message;
  }
}

async function cancelSub() {
  if (!confirm('Cancel subscription? You will keep access until the period ends, then drop to free tier.')) return;
  const k = localStorage.getItem(KEY_STORE);
  const msg = document.getElementById('action-msg');
  msg.textContent = '';
  try {
    const r = await fetch('/billing/cancel', {method: 'POST', headers: {'X-API-Key': k}});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Cancel failed');
    msg.style.color = '#4ade80';
    msg.textContent = 'Cancelled. Access continues until period end.';
    setTimeout(load, 800);
  } catch (e) {
    msg.style.color = '#f87171';
    msg.textContent = e.message;
  }
}

async function portal() {
  const k = localStorage.getItem(KEY_STORE);
  try {
    const r = await fetch('/billing/portal', {headers: {'X-API-Key': k}});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Portal unavailable');
    window.location = d.url;
  } catch (e) {
    document.getElementById('action-msg').style.color = '#f87171';
    document.getElementById('action-msg').textContent = e.message;
  }
}

if (localStorage.getItem(KEY_STORE)) load();
</script>
</body></html>"""


@router.get("/billing/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page():
    return DASHBOARD_PAGE


ADMIN_DASHBOARD_PAGE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Dashboard — SentinelCorp</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;padding:24px 16px}
.wrap{max-width:1200px;margin:0 auto}
h1{font-size:26px;font-weight:700;margin-bottom:4px;background:linear-gradient(135deg,#f87171,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:#555;font-size:13px;margin-bottom:24px}
#login{max-width:440px;margin:80px auto;background:#161616;border:1px solid #222;border-radius:12px;padding:32px}
#login h2{font-size:22px;margin-bottom:8px}
#login p{color:#666;font-size:13px;margin-bottom:16px}
#login input{width:100%;padding:11px;background:#0d0d0d;border:1px solid #333;border-radius:6px;color:#fff;font-size:13px;font-family:'SF Mono',Monaco,monospace;margin-bottom:12px}
#main{display:none}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
.stat{background:#161616;border:1px solid #222;border-radius:10px;padding:16px}
.stat .num{font-size:28px;font-weight:700;color:#4ade80}
.stat .label{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:0.5px;margin-top:4px}
.stat .num.warn{color:#f59e0b}
.stat .num.blue{color:#60a5fa}
.stat .num.purple{color:#a78bfa}
.stat .num.red{color:#f87171}
section{margin-bottom:28px}
section h2{font-size:15px;font-weight:600;color:#888;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px}
table{width:100%;border-collapse:collapse;background:#111;border-radius:8px;overflow:hidden;font-size:13px}
th{text-align:left;padding:10px 12px;color:#555;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #1a1a1a;background:#0d0d0d}
td{padding:10px 12px;border-bottom:1px solid #141414;vertical-align:middle}
tr:last-child td{border:none}
tr:hover td{background:#161616}
.tag{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;text-transform:uppercase;letter-spacing:0.4px;font-weight:600}
.tag-free{background:#1a2a3d;color:#60a5fa}
.tag-dev{background:#1a3d2a;color:#34d399}
.tag-startup{background:#3d2a1a;color:#f59e0b}
.tag-enterprise{background:#3d1a3d;color:#e879f9}
.tag-active{background:#1a3d1a;color:#4ade80}
.tag-revoked{background:#3d1a1a;color:#f87171}
.tag-pending{background:#3d2f1a;color:#f59e0b}
.tag-cancelled{background:#2a1a1a;color:#888}
.bar-wrap{height:6px;background:#1a1a1a;border-radius:3px;width:100px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:6px}
.bar{height:100%;background:#3b82f6;border-radius:3px}
.bar.warn{background:#f59e0b}
.bar.crit{background:#ef4444}
.mono{font-family:'SF Mono',Monaco,monospace;font-size:12px;color:#888}
button.btn{padding:8px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600}
.btn-primary{background:#3b82f6;color:#fff}
.btn-sm{padding:5px 10px;font-size:11px;border-radius:4px;border:none;cursor:pointer;font-weight:600}
.btn-danger-sm{background:#2a0e0e;color:#f87171;border:1px solid #5c1a1a}
.btn-upgrade-sm{background:#1a2a3d;color:#60a5fa;border:1px solid #1a3d5c}
.actions-row{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-bottom:16px}
.search{background:#111;border:1px solid #222;border-radius:6px;padding:8px 12px;color:#e0e0e0;font-size:13px;width:240px}
.search:focus{outline:none;border-color:#3b82f6}
#toast{position:fixed;bottom:24px;right:24px;background:#161616;border:1px solid #333;border-radius:8px;padding:12px 20px;font-size:13px;display:none;z-index:1000}
#toast.show{display:block}
#toast.ok{border-color:#1f3d1f;color:#4ade80}
#toast.err{border-color:#5c1a1a;color:#f87171}
.err-msg{color:#f87171;font-size:12px;margin-top:8px}
.empty{text-align:center;padding:32px;color:#444;font-size:13px}
.product-badge{display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;background:#1a1a2a;color:#6b7280;margin-left:4px}
</style></head><body>
<div class="wrap">

<div id="login">
<h2 style="background:linear-gradient(135deg,#f87171,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent">Admin Dashboard</h2>
<p>Enter your ADMIN_SECRET to continue. This is the secret set in your Railway environment.</p>
<input id="secret-input" type="password" placeholder="Admin secret..." autocomplete="off">
<button class="btn btn-primary" onclick="doLogin()" style="width:100%">Sign In</button>
<div id="login-err" class="err-msg"></div>
</div>

<div id="main">
<h1>Admin Dashboard</h1>
<p class="subtitle">SentinelCorp — API usage, customers, and subscriptions</p>

<div class="stats" id="stats-grid"></div>

<section>
<div class="actions-row">
<input class="search" id="search" placeholder="Filter by email..." oninput="filterTable()">
<button class="btn btn-primary" onclick="reload()">Refresh</button>
</div>
<h2>API Keys & Customer Usage</h2>
<table>
<thead><tr>
<th>#</th>
<th>Email</th>
<th>Key</th>
<th>Tier</th>
<th>Status</th>
<th>SentinelCorp usage</th>
<th>SentinelX402 usage</th>
<th>Quota</th>
<th>Joined</th>
<th>Last used</th>
<th></th>
</tr></thead>
<tbody id="keys-tbody"></tbody>
</table>
</section>

<section>
<h2>Active Subscriptions</h2>
<table>
<thead><tr>
<th>Email</th>
<th>Plan</th>
<th>Rail</th>
<th>Amount</th>
<th>Status</th>
<th>Period ends</th>
</tr></thead>
<tbody id="subs-tbody"></tbody>
</table>
</section>
</div>

<div id="toast"></div>
</div>

<script>
const STORE = 'sc_admin_secret';
let allKeys = [];

function doLogin() {
  const s = document.getElementById('secret-input').value.trim();
  if (!s) return;
  sessionStorage.setItem(STORE, s);
  load();
}

function secret() { return sessionStorage.getItem(STORE) || ''; }

function toast(msg, ok) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + (ok ? 'ok' : 'err');
  setTimeout(() => t.className = '', 2800);
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'2-digit'});
}

function fmtAmount(currency, minor) {
  if (!minor) return 'Free';
  const major = (minor/100).toFixed(0);
  return (currency === 'INR' ? '₹' : '$') + major + '/mo';
}

function barHtml(used, quota) {
  const pct = Math.min(100, quota > 0 ? (used/quota)*100 : 0);
  const cls = pct >= 90 ? 'crit' : pct >= 70 ? 'warn' : '';
  return '<span class="bar-wrap"><span class="bar ' + cls + '" style="width:' + pct.toFixed(1) + '%"></span></span>' +
    '<span style="font-size:12px;color:#666">' + used.toLocaleString() + '</span>';
}

function renderStats(data) {
  const byTier = {};
  for (const k of data.keys) { byTier[k.tier] = (byTier[k.tier]||0) + 1; }
  const activeCount = data.keys.filter(k => k.status === 'active').length;
  const totalCorp = data.keys.reduce((s,k) => s + (k.usage_sentinelcorp||0), 0);
  const totalX402 = data.keys.reduce((s,k) => s + (k.usage_sentinelx402||0), 0);
  const subsActive = (data.subscriptions||[]).filter(s => s.status === 'active').length;

  const stats = [
    {label:'Total Keys', num: data.keys.length, cls:''},
    {label:'Active Keys', num: activeCount, cls:''},
    {label:'Free tier', num: byTier.free||0, cls:'blue'},
    {label:'Dev tier', num: byTier.dev||0, cls:''},
    {label:'Startup tier', num: byTier.startup||0, cls:'warn'},
    {label:'Enterprise', num: byTier.enterprise||0, cls:'purple'},
    {label:'Corp requests (mo)', num: totalCorp.toLocaleString(), cls:''},
    {label:'X402 requests (mo)', num: totalX402.toLocaleString(), cls:''},
    {label:'Active subscriptions', num: subsActive, cls: subsActive > 0 ? 'purple' : ''},
  ];
  const grid = document.getElementById('stats-grid');
  grid.replaceChildren();
  for (const s of stats) {
    const card = el('div', {cls: 'stat'});
    card.appendChild(el('div', {text: String(s.num), cls: 'num ' + s.cls}));
    card.appendChild(el('div', {text: s.label, cls: 'label'}));
    grid.appendChild(card);
  }
}

// Build a DOM element instead of innerHTML concatenation — values are never
// interpreted as HTML, blocking stored XSS via attacker-supplied email/name.
function el(tag, opts) {
  const e = document.createElement(tag);
  if (opts) {
    if (opts.text != null) e.textContent = opts.text;
    if (opts.cls) e.className = opts.cls;
    if (opts.style) e.setAttribute('style', opts.style);
    if (opts.html) e.innerHTML = opts.html;  // ONLY for trusted static markup (icons/bars)
  }
  return e;
}

function renderKeys(keys) {
  const tbody = document.getElementById('keys-tbody');
  tbody.replaceChildren();
  if (!keys.length) {
    const tr = el('tr');
    tr.appendChild(el('td', {text: 'No keys found', cls: 'empty'}));
    tr.firstChild.colSpan = 11;
    tbody.appendChild(tr);
    return;
  }
  for (const k of keys) {
    const tr = el('tr');
    tr.appendChild(el('td', {text: String(k.id), style: 'color:#444'}));
    const emailTd = el('td', {text: k.email});
    if (k.name) emailTd.appendChild(el('div', {text: k.name, style: 'font-size:11px;color:#555'}));
    tr.appendChild(emailTd);
    tr.appendChild(el('td', {text: k.key_prefix + '...' + k.key_last4, cls: 'mono'}));
    const tierTd = el('td');
    tierTd.appendChild(el('span', {text: k.tier, cls: 'tag tag-' + k.tier}));
    tr.appendChild(tierTd);
    const statusTd = el('td');
    statusTd.appendChild(el('span', {text: k.status, cls: 'tag tag-' + k.status}));
    tr.appendChild(statusTd);
    tr.appendChild(el('td', {html: barHtml(k.usage_sentinelcorp||0, k.monthly_quota)}));
    tr.appendChild(el('td', {html: barHtml(k.usage_sentinelx402||0, k.monthly_quota)}));
    tr.appendChild(el('td', {text: (k.monthly_quota||0).toLocaleString() + '/mo', style: 'font-size:12px;color:#666'}));
    tr.appendChild(el('td', {text: fmtDate(k.created_at), style: 'font-size:12px;color:#666'}));
    tr.appendChild(el('td', {text: k.last_used_at ? fmtDate(k.last_used_at) : 'never', style: 'font-size:12px;color:#666'}));

    const actionsTd = el('td');
    const actionsDiv = el('div', {style: 'display:flex;gap:4px'});
    if (k.status === 'active') {
      const tierBtn = el('button', {text: 'Tier', cls: 'btn-sm btn-upgrade-sm'});
      tierBtn.addEventListener('click', () => upgradeTier(k.id, k.tier));
      actionsDiv.appendChild(tierBtn);
      const revokeBtn = el('button', {text: 'Revoke', cls: 'btn-sm btn-danger-sm'});
      revokeBtn.addEventListener('click', () => revokeKey(k.id));
      actionsDiv.appendChild(revokeBtn);
    }
    actionsTd.appendChild(actionsDiv);
    tr.appendChild(actionsTd);
    tbody.appendChild(tr);
  }
}

function renderSubs(subs) {
  const tbody = document.getElementById('subs-tbody');
  tbody.replaceChildren();
  if (!subs || !subs.length) {
    const tr = el('tr');
    const td = el('td', {text: 'No subscriptions yet', cls: 'empty'});
    td.colSpan = 6;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const s of subs) {
    const tr = el('tr');
    tr.appendChild(el('td', {text: s.email}));
    tr.appendChild(el('td', {text: s.plan}));
    tr.appendChild(el('td', {text: s.rail}));
    tr.appendChild(el('td', {text: fmtAmount(s.currency, s.amount_minor)}));
    const stTd = el('td');
    stTd.appendChild(el('span', {text: s.status, cls: 'tag tag-' + s.status}));
    tr.appendChild(stTd);
    tr.appendChild(el('td', {text: fmtDate(s.current_period_end), style: 'font-size:12px;color:#666'}));
    tbody.appendChild(tr);
  }
}

function filterTable() {
  const q = document.getElementById('search').value.toLowerCase();
  const filtered = q ? allKeys.filter(k => k.email.toLowerCase().includes(q) || (k.name||'').toLowerCase().includes(q)) : allKeys;
  renderKeys(filtered);
}

async function load() {
  const s = secret();
  if (!s) return;
  try {
    const r = await fetch('/billing/admin/stats', {headers: {'X-Admin-Secret': s}});
    if (r.status === 403 || r.status === 401) {
      document.getElementById('login-err').textContent = 'Invalid admin secret';
      sessionStorage.removeItem(STORE);
      return;
    }
    const data = await r.json();
    allKeys = data.keys || [];
    document.getElementById('login').style.display = 'none';
    document.getElementById('main').style.display = 'block';
    renderStats(data);
    renderKeys(allKeys);
    renderSubs(data.subscriptions || []);
  } catch (e) {
    document.getElementById('login-err').textContent = 'Load failed: ' + e.message;
  }
}

function reload() { load(); toast('Refreshed', true); }

const TIERS = ['free', 'dev', 'startup', 'enterprise'];

async function upgradeTier(keyId, currentTier) {
  const idx = TIERS.indexOf(currentTier);
  const next = TIERS[(idx + 1) % TIERS.length];
  const choice = prompt('Set tier for key #' + keyId + ' (current: ' + currentTier + '):\\n' + TIERS.join(' / '), next);
  if (!choice || !TIERS.includes(choice)) return;
  const r = await fetch('/billing/admin/keys/' + keyId + '/tier', {
    method: 'PATCH',
    headers: {'X-Admin-Secret': secret(), 'Content-Type': 'application/json'},
    body: JSON.stringify({tier: choice}),
  });
  if (r.ok) { toast('Tier updated to ' + choice, true); load(); }
  else { const d = await r.json(); toast(d.detail || 'Failed', false); }
}

async function revokeKey(keyId) {
  if (!confirm('Revoke key #' + keyId + '? The customer will immediately lose access.')) return;
  const r = await fetch('/billing/admin/keys/' + keyId, {
    method: 'DELETE',
    headers: {'X-Admin-Secret': secret()},
  });
  if (r.ok) { toast('Key #' + keyId + ' revoked', true); load(); }
  else { const d = await r.json(); toast(d.detail || 'Revoke failed', false); }
}

if (sessionStorage.getItem(STORE)) load();
</script>
</body></html>"""


@router.get("/billing/admin/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard_page():
    """Admin dashboard UI — auth handled client-side via X-Admin-Secret."""
    return ADMIN_DASHBOARD_PAGE


@router.get("/billing/admin/stats", dependencies=[Depends(_require_admin)])
async def admin_stats(session: AsyncSession = Depends(get_db)):
    """Return all API keys with their current-month usage across both products, plus subscriptions."""
    from datetime import datetime

    from sqlalchemy import func, select

    from app.models.billing import APIKey, Subscription, UsageCounter

    year_month = datetime.utcnow().strftime("%Y-%m")

    # All keys
    keys_result = await session.execute(select(APIKey).order_by(APIKey.created_at.desc()))
    keys = keys_result.scalars().all()

    # Usage counters for this month, keyed by (api_key_id, product)
    usage_result = await session.execute(
        select(UsageCounter).where(UsageCounter.year_month == year_month)
    )
    usage_by_key_product: dict[tuple, int] = {}
    for uc in usage_result.scalars().all():
        usage_by_key_product[(uc.api_key_id, uc.product)] = uc.count

    # Subscriptions with email join
    subs_result = await session.execute(
        select(Subscription, APIKey.email)
        .join(APIKey, Subscription.api_key_id == APIKey.id)
        .order_by(Subscription.created_at.desc())
    )
    subs = []
    for sub, email in subs_result.all():
        subs.append({
            "id": sub.id,
            "email": email,
            "rail": sub.rail,
            "plan": sub.plan,
            "status": sub.status,
            "currency": sub.currency,
            "amount_minor": sub.amount_minor,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        })

    keys_out = []
    for k in keys:
        keys_out.append({
            "id": k.id,
            "email": k.email,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "key_last4": k.key_last4,
            "tier": k.tier,
            "status": k.status,
            "monthly_quota": k.monthly_quota,
            "rate_limit_per_min": k.rate_limit_per_min,
            "usage_sentinelcorp": usage_by_key_product.get((k.id, "sentinelcorp"), 0),
            "usage_sentinelx402": usage_by_key_product.get((k.id, "sentinelx402"), 0),
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "notes": k.notes,
        })

    return {
        "year_month": year_month,
        "keys": keys_out,
        "subscriptions": subs,
    }


@router.get("/billing/success", response_class=HTMLResponse, include_in_schema=False)
async def billing_success(session_id: str = ""):
    return """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Payment successful — SentinelCorp</title>
<style>
body{{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;margin:0}}
.card{{max-width:520px;background:#161616;border:1px solid #1f3d1f;border-radius:12px;padding:40px;text-align:center}}
h1{{color:#4ade80;margin:0 0 12px;font-size:26px}}
p{{color:#888;margin:8px 0;line-height:1.6}}
a{{color:#60a5fa;text-decoration:none}}
.tick{{font-size:48px;margin-bottom:12px}}
</style></head><body>
<div class="card">
<div class="tick">OK</div>
<h1>Payment received</h1>
<p>Your subscription is being activated. Your API key was emailed / shown at checkout.</p>
<p>Check it here: <a href="/billing/me">/billing/me</a> (with your key in <code>X-API-Key</code>)</p>
<p style="margin-top:24px"><a href="/">Back home</a></p>
</div></body></html>"""

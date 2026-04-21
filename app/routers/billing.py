from __future__ import annotations

import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
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
        handler: function() { window.location = '/billing/success?api_key=' + encodeURIComponent(d.api_key); },
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
        },
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

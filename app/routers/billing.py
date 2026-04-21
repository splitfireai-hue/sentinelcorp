from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import auth as auth_service

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


@router.get("/pricing", response_model=dict)
async def pricing():
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

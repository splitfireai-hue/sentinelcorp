from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings, setup_logging
from app.database import engine
from app.middleware.auth import BillingAuthMiddleware
from app.models import Base
from app.routers import billing, company, debarred, health, validate

logger = logging.getLogger(__name__)


async def _migrate_api_keys_if_needed(conn) -> None:
    """One-shot migration: the legacy api_keys table stored raw keys. Drop it if present
    so the new billing schema can be created. Safe because the legacy table was never
    written to in any deployed version."""
    from sqlalchemy import inspect

    def _inspect(sync_conn):
        insp = inspect(sync_conn)
        if not insp.has_table("api_keys"):
            return False
        cols = {c["name"] for c in insp.get_columns("api_keys")}
        return "key_hash" not in cols

    needs_drop = await conn.run_sync(_inspect)
    if needs_drop:
        logger.warning("Dropping legacy api_keys table to apply new billing schema")
        from sqlalchemy import text

        await conn.execute(text("DROP TABLE IF EXISTS api_keys"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting SentinelCorp (env=%s)", settings.ENVIRONMENT)
    async with engine.begin() as conn:
        await _migrate_api_keys_if_needed(conn)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    yield
    logger.info("SentinelCorp shutdown")


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="India Company Risk Profile API for AI Agents. Unified risk scoring from MCA, GST, Court, SEBI data.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate limiting — attach shared limiter to app state
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=86400,
)

# Billing: API key auth + quota (no-op when BILLING_ENABLED=false)
app.add_middleware(BillingAuthMiddleware, product=settings.BILLING_PRODUCT)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled: %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "detail": "An unexpected error occurred"},
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    duration_ms = (time.time() - start) * 1000
    logger.info("%s %s %d %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.exception("Error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "An unexpected error occurred"},
    )


# --- Discovery endpoints ---

@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt():
    return "User-agent: *\nAllow: /\n"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/.well-known/mcp", include_in_schema=False)
async def well_known_mcp():
    return {
        "name": "SentinelCorp",
        "url": "",  # Set this to deployed URL
        "metadata": "/info",
        "mcp_config": "https://github.com/splitfireai-hue/sentinelcorp/blob/main/mcp.json",
    }


@app.get("/.well-known/agent.json", include_in_schema=False)
async def well_known_agent():
    return {
        "name": "SentinelCorp",
        "description": "India Company Risk Profile API for AI Agents. Validate GSTIN/CIN/PAN, check SEBI debarment, get unified risk scores.",
        "capabilities": [
            "validate_gstin", "validate_cin", "validate_pan",
            "company_profile", "batch_profile",
            "debarred_search",
        ],
        "free_tier": {"requests": 1000, "signup_required": False},
    }


# --- Landing page ---

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing():
    return """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelCorp — India Company Risk API for AI Agents</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.container{max-width:720px;text-align:center}
h1{font-size:40px;font-weight:700;margin-bottom:8px;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tagline{font-size:18px;color:#888;margin-bottom:32px}
.stats{display:flex;gap:16px;justify-content:center;margin-bottom:32px;flex-wrap:wrap}
.stat{background:#161616;border:1px solid #222;border-radius:8px;padding:14px 20px;min-width:140px}
.stat .num{font-size:24px;font-weight:700;color:#4ade80}
.stat .label{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px;margin-top:4px}
.try{background:#161616;border:1px solid #222;border-radius:8px;padding:20px;margin-bottom:32px;text-align:left}
.try code{display:block;background:#0d0d0d;padding:12px;border-radius:4px;font-family:'SF Mono',Monaco,monospace;font-size:13px;color:#60a5fa;overflow-x:auto;margin-top:8px;word-break:break-all}
.try .label{font-size:13px;color:#888}
.links{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.links a{display:inline-block;padding:10px 24px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600}
.primary{background:#3b82f6;color:#fff}
.secondary{background:#161616;color:#e0e0e0;border:1px solid #333}
.free{margin-top:24px;font-size:13px;color:#4ade80}
.footer{margin-top:32px;font-size:12px;color:#444}
.footer a{color:#888;text-decoration:none}
</style></head><body><div class="container">
<h1>SentinelCorp</h1>
<p class="tagline">India Company Risk Profile API for AI Agents</p>
<div class="stats">
  <div class="stat"><div class="num">14K+</div><div class="label">SEBI Debarred</div></div>
  <div class="stat"><div class="num">&lt;50ms</div><div class="label">Validation</div></div>
  <div class="stat"><div class="num">FREE</div><div class="label">1,000 Requests</div></div>
</div>
<div class="try">
<span class="label">Try it now:</span>
<code>curl "https://YOUR_URL/api/v1/company/profile?identifier=27AAAAA0000A1Z5"</code>
</div>
<div class="links">
<a href="/signup" class="primary">Get API Key</a>
<a href="/docs" class="secondary">API Docs</a>
<a href="/pricing" class="secondary">Pricing</a>
<a href="https://github.com/splitfireai-hue/sentinelcorp" class="secondary">GitHub</a>
</div>
<p class="free">5,000 free requests/month &mdash; email signup, no credit card</p>
<div class="footer">
Part of the Sentinel Series &mdash; <a href="https://sentinelx402-production.up.railway.app">SentinelX402</a> (threat intel) + SentinelCorp (company risk)
</div>
</div></body></html>"""


# --- Routers ---
app.include_router(health.router, tags=["Health"])
app.include_router(billing.router, tags=["Billing"])
app.include_router(validate.router, prefix="/api/v1/validate", tags=["Format Validation"])
app.include_router(company.router, prefix="/api/v1/company", tags=["Company Risk Profile"])
app.include_router(debarred.router, prefix="/api/v1/debarred", tags=["SEBI Debarred Entities"])

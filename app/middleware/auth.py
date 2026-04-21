from __future__ import annotations

import logging
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import async_session
from app.services import auth as auth_service

logger = logging.getLogger(__name__)

EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/info",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/robots.txt",
    "/favicon.ico",
    "/.well-known",
    "/stats",
    "/billing",
    "/pricing",
    "/signup",
)


def _is_exempt(path: str) -> bool:
    if path == "/":
        return True
    for prefix in EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    return False


def _extract_key(request: Request) -> str:
    key = request.headers.get("x-api-key", "").strip()
    if key:
        return key
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class BillingAuthMiddleware(BaseHTTPMiddleware):
    """Validates API keys and enforces monthly quota + anon IP trial limit.

    When `BILLING_ENABLED=false` the middleware is a passthrough — used for dev and to
    let the migration to paid tiers land without breaking existing traffic.
    """

    def __init__(self, app, product: str = "sentinelcorp"):
        super().__init__(app)
        self.product = product

    async def dispatch(self, request: Request, call_next):
        if not settings.BILLING_ENABLED:
            return await call_next(request)

        path = request.url.path
        if _is_exempt(path) or request.method == "OPTIONS":
            return await call_next(request)

        raw_key = _extract_key(request)

        async with async_session() as session:
            if raw_key:
                api_key = await auth_service.lookup_key(session, raw_key)
                if api_key is None:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": "invalid_api_key",
                            "detail": "API key not recognized. Get one at /signup.",
                        },
                    )
                if api_key.status != "active":
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "api_key_{}".format(api_key.status),
                            "detail": "API key is {}. Reactivate at /billing.".format(api_key.status),
                        },
                    )

                used = await auth_service.get_monthly_count(session, api_key.id, self.product)
                if used >= api_key.monthly_quota:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "quota_exceeded",
                            "detail": "Monthly quota of {} reached on tier '{}'. Upgrade at /pricing.".format(
                                api_key.monthly_quota, api_key.tier
                            ),
                            "used": used,
                            "quota": api_key.monthly_quota,
                            "tier": api_key.tier,
                        },
                    )

                request.state.api_key_id = api_key.id
                request.state.api_key_tier = api_key.tier
                request.state.api_key_email = api_key.email

                response = await call_next(request)
                try:
                    await auth_service.increment_usage(session, api_key.id, self.product)
                except Exception:
                    logger.exception("Failed to increment usage for key_id=%s", api_key.id)

                response.headers["X-RateLimit-Tier"] = api_key.tier
                response.headers["X-RateLimit-Quota"] = str(api_key.monthly_quota)
                response.headers["X-RateLimit-Used"] = str(used + 1)
                response.headers["X-RateLimit-Remaining"] = str(max(api_key.monthly_quota - used - 1, 0))
                return response

            ip = _client_ip(request)
            count = await auth_service.anon_count_and_increment(session, ip)
            if count > auth_service.ANON_DAILY_LIMIT:
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "trial_limit_reached",
                        "detail": "Anonymous trial limit of {} req/day reached. Get a free key at /signup for {} req/month.".format(
                            auth_service.ANON_DAILY_LIMIT,
                            auth_service.TIERS["free"].monthly_quota,
                        ),
                        "signup_url": (settings.PUBLIC_BASE_URL or "") + "/signup",
                    },
                )

            request.state.api_key_id = None
            request.state.api_key_tier = "anon"
            response = await call_next(request)
            response.headers["X-RateLimit-Tier"] = "anon"
            response.headers["X-RateLimit-Quota"] = str(auth_service.ANON_DAILY_LIMIT)
            response.headers["X-RateLimit-Used"] = str(count)
            response.headers["X-RateLimit-Remaining"] = str(max(auth_service.ANON_DAILY_LIMIT - count, 0))
            return response

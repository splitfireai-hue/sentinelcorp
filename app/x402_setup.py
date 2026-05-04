"""x402 per-call USDC payment configuration for autonomous agents.

This module is loaded only when ``X402_ENABLED=true``. It mirrors the pattern used
in SentinelX402 so a wallet that can speak x402 to one product can speak x402 to
the other.

Pricing rationale: validation endpoints are essentially pure compute (checksum
math) so price them at $0.005. Risk profile aggregates multiple data sources so
charge $0.01. Batch is metered as a flat $0.10 since per-identifier billing
inside a batch creates settlement complexity not worth solving day one.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def create_x402_server():
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=settings.X402_FACILITATOR_URL))
    server = x402ResourceServer(facilitator)
    server.register(settings.X402_NETWORK_ID, ExactEvmServerScheme())
    return server


def get_routes_config():
    from x402.http import PaymentOption
    from x402.http.types import RouteConfig

    wallet = settings.X402_WALLET_ADDRESS
    network = settings.X402_NETWORK_ID

    def _option(price: str) -> list:
        return [
            PaymentOption(
                scheme="exact",
                pay_to=wallet,
                price=price,
                network=network,
            )
        ]

    return {
        "GET /api/v1/validate/gstin": RouteConfig(
            accepts=_option(settings.X402_PRICE_VALIDATE),
            description="Validate GSTIN format and checksum",
            mime_type="application/json",
        ),
        "GET /api/v1/validate/cin": RouteConfig(
            accepts=_option(settings.X402_PRICE_VALIDATE),
            description="Validate CIN format",
            mime_type="application/json",
        ),
        "GET /api/v1/validate/pan": RouteConfig(
            accepts=_option(settings.X402_PRICE_VALIDATE),
            description="Validate PAN format",
            mime_type="application/json",
        ),
        "GET /api/v1/company/profile": RouteConfig(
            accepts=_option(settings.X402_PRICE_PROFILE),
            description="Unified company risk profile",
            mime_type="application/json",
        ),
        "POST /api/v1/company/batch": RouteConfig(
            accepts=_option(settings.X402_PRICE_BATCH),
            description="Batch risk profiling (up to 100 identifiers)",
            mime_type="application/json",
        ),
        "GET /api/v1/debarred/search": RouteConfig(
            accepts=_option(settings.X402_PRICE_DEBARRED),
            description="Search SEBI/NSE/BSE debarred entities",
            mime_type="application/json",
        ),
        "GET /api/v1/debarred/list": RouteConfig(
            accepts=_option(settings.X402_PRICE_DEBARRED),
            description="List recent debarred entities",
            mime_type="application/json",
        ),
    }


def is_available() -> bool:
    """Return True if the x402 SDK can be imported in this environment."""
    try:
        import x402  # noqa: F401
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI  # noqa: F401
        return True
    except Exception as e:
        logger.warning("x402 unavailable: %s", e)
        return False

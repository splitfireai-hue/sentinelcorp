"""SentinelCorp API client — sync and async."""

from __future__ import annotations

from typing import List, Optional

import httpx


class SentinelCorpError(Exception):
    """Raised when the API returns an error response."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__("SentinelCorp API error {}: {}".format(status_code, detail))


def _handle(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise SentinelCorpError(resp.status_code, str(detail))
    return resp.json()


class SentinelCorp:
    """Sync client for SentinelCorp API.

    Usage:
        client = SentinelCorp()
        profile = client.profile("Sahara India")
        print(profile["overall_risk_score"])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        api_key: Optional[str] = None,
    ):
        headers = {"User-Agent": "sentinelcorp-sdk/0.1.0"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.Client(base_url=base_url, timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # Validators
    def validate_gstin(self, gstin: str) -> dict:
        return _handle(self._client.get("/api/v1/validate/gstin", params={"gstin": gstin}))

    def validate_cin(self, cin: str) -> dict:
        return _handle(self._client.get("/api/v1/validate/cin", params={"cin": cin}))

    def validate_pan(self, pan: str) -> dict:
        return _handle(self._client.get("/api/v1/validate/pan", params={"pan": pan}))

    # Risk profile
    def profile(self, identifier: str, identifier_type: str = "auto") -> dict:
        return _handle(self._client.get(
            "/api/v1/company/profile",
            params={"identifier": identifier, "type": identifier_type},
        ))

    def batch(self, identifiers: List[str], identifier_type: Optional[str] = None) -> dict:
        body = {"identifiers": identifiers}
        if identifier_type:
            body["identifier_type"] = identifier_type
        return _handle(self._client.post("/api/v1/company/batch", json=body))

    # Debarred
    def search_debarred(self, name: str, limit: int = 20) -> dict:
        return _handle(self._client.get(
            "/api/v1/debarred/search",
            params={"name": name, "limit": limit},
        ))

    def list_debarred(self, limit: int = 50, offset: int = 0) -> dict:
        return _handle(self._client.get(
            "/api/v1/debarred/list",
            params={"limit": limit, "offset": offset},
        ))


class AsyncSentinelCorp:
    """Async client for SentinelCorp API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        api_key: Optional[str] = None,
    ):
        headers = {"User-Agent": "sentinelcorp-sdk/0.1.0"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def validate_gstin(self, gstin: str) -> dict:
        return _handle(await self._client.get("/api/v1/validate/gstin", params={"gstin": gstin}))

    async def validate_cin(self, cin: str) -> dict:
        return _handle(await self._client.get("/api/v1/validate/cin", params={"cin": cin}))

    async def validate_pan(self, pan: str) -> dict:
        return _handle(await self._client.get("/api/v1/validate/pan", params={"pan": pan}))

    async def profile(self, identifier: str, identifier_type: str = "auto") -> dict:
        return _handle(await self._client.get(
            "/api/v1/company/profile",
            params={"identifier": identifier, "type": identifier_type},
        ))

    async def batch(self, identifiers: List[str], identifier_type: Optional[str] = None) -> dict:
        body = {"identifiers": identifiers}
        if identifier_type:
            body["identifier_type"] = identifier_type
        return _handle(await self._client.post("/api/v1/company/batch", json=body))

    async def search_debarred(self, name: str, limit: int = 20) -> dict:
        return _handle(await self._client.get(
            "/api/v1/debarred/search",
            params={"name": name, "limit": limit},
        ))

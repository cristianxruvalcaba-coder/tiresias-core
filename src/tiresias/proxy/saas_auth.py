"""
SaaS Auth Middleware for Tiresias Proxy.

In SaaS mode (TIRESIAS_MODE=saas), resolves tenant_id from the Tiresias API key
on every request. The API key is passed via:
  - Authorization: Bearer tir_<slug>_<hex32>
  - X-Tiresias-Api-Key: tir_<slug>_<hex32>

The key is SHA-256 hashed and looked up against tiresias_licenses.api_key_hash.
On match, request.state.tenant_id and request.state.tenant_tier are set.

In dedicated/onprem modes, this middleware is a no-op.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasLicense

if TYPE_CHECKING:
    from tiresias.config import TiresiasSettings

logger = logging.getLogger(__name__)

# Paths that bypass tenant auth (health, docs, OpenAPI)
_AUTH_EXEMPT_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})

# In-memory cache: api_key_hash -> (tenant_id, tier, cached_at)
_tenant_cache: dict[str, tuple[str, str, float]] = {}
_CACHE_TTL_SECONDS = 60


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key, matching the stored api_key_hash."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _extract_api_key(request: Request) -> str | None:
    """Extract Tiresias API key from Authorization header or X-Tiresias-Api-Key."""
    # Check custom header first (preferred for passthrough scenarios)
    key = request.headers.get("x-tiresias-api-key")
    if key:
        return key.strip()

    # Fall back to Authorization: Bearer
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].strip().startswith("tir_"):
        return auth[7:].strip()

    return None


def clear_tenant_cache() -> None:
    """Clear the in-memory tenant cache (useful for testing and key rotation)."""
    _tenant_cache.clear()


class SaaSAuthMiddleware(BaseHTTPMiddleware):
    """Resolves tenant from Tiresias API key in SaaS mode.

    Injects request.state.tenant_id and request.state.tenant_tier.
    Returns 401 if no valid key is found.
    """

    def __init__(self, app, settings: "TiresiasSettings", engine_factory):
        super().__init__(app)
        self.settings = settings
        self.engine_factory = engine_factory

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip in non-SaaS modes
        if self.settings.mode != "saas":
            request.state.tenant_id = self.settings.tenant_id
            return await call_next(request)

        # Skip exempt paths
        if request.url.path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)

        # Extract API key
        raw_key = _extract_api_key(request)
        if not raw_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "missing_api_key",
                    "detail": "Tiresias API key required. Pass via Authorization: Bearer tir_... or X-Tiresias-Api-Key header.",
                },
            )

        key_hash = _hash_api_key(raw_key)

        # Check cache first
        now = time.monotonic()
        cached = _tenant_cache.get(key_hash)
        if cached and (now - cached[2]) < _CACHE_TTL_SECONDS:
            request.state.tenant_id = cached[0]
            request.state.tenant_tier = cached[1]
            return await call_next(request)

        # Cache miss — look up in DB
        try:
            engine = await self.engine_factory()
            async with AsyncSession(engine) as session:
                result = await session.execute(
                    select(TiresiasLicense.tenant_id, TiresiasLicense.tier).where(
                        TiresiasLicense.api_key_hash == key_hash
                    )
                )
                row = result.first()
        except Exception:
            logger.exception("SaaS auth DB lookup failed")
            return JSONResponse(
                status_code=503,
                content={"error": "auth_unavailable", "detail": "Authentication service temporarily unavailable."},
            )

        if not row:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_api_key", "detail": "Invalid Tiresias API key."},
            )

        tenant_id, tier = row[0], row[1]

        # Populate cache
        _tenant_cache[key_hash] = (tenant_id, tier, now)

        # Inject into request state
        request.state.tenant_id = tenant_id
        request.state.tenant_tier = tier

        return await call_next(request)


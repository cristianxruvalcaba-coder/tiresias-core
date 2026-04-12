"""
Redis-backed rate limit middleware for Tiresias proxy (SaaS mode).

Enforces per-tenant RPM limits based on tier using Redis INCR + EXPIRE
for cross-pod distributed counting. Falls back to in-memory counters
when Redis is unavailable (graceful degradation).

No-op in dedicated/onprem modes.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from tiresias.config import TiresiasSettings

logger = logging.getLogger(__name__)

# RPM limits per tier (from spec)
TIER_RPM: dict[str, int] = {
    "community": 30,
    "starter": 60,
    "pro": 300,
    "enterprise": 1000,
    "mssp": 2000,
}

_DEFAULT_RPM = 60

# Paths that bypass rate limiting
_EXEMPT_PATHS = frozenset({
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})

# ---------------------------------------------------------------------------
# In-memory fallback (single-pod, used when Redis is down)
# ---------------------------------------------------------------------------
# key -> list of timestamps (monotonic seconds)
_local_windows: dict[str, list[float]] = defaultdict(list)


def _check_local(key: str, rpm: int) -> tuple[bool, int, int]:
    """In-memory sliding window check. Returns (allowed, remaining, retry_after)."""
    now = time.monotonic()
    window_start = now - 60.0
    timestamps = _local_windows[key]
    # prune
    timestamps[:] = [ts for ts in timestamps if ts > window_start]
    count = len(timestamps)
    if count >= rpm:
        retry_after = max(1, int(timestamps[0] + 60.0 - now))
        return False, 0, retry_after
    timestamps.append(now)
    return True, rpm - count - 1, 0


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _minute_bucket() -> int:
    """Current UTC minute as epoch // 60."""
    return int(time.time()) // 60


async def _check_redis(redis, key: str, rpm: int) -> tuple[bool, int, int]:
    """
    Redis INCR + EXPIRE sliding-minute check.
    Returns (allowed, remaining, retry_after).
    """
    bucket = _minute_bucket()
    redis_key = f"rl:{key}:{bucket}"
    try:
        current = await redis.incr(redis_key)
        if current == 1:
            # first request in this bucket — set TTL to 120s (covers clock drift)
            await redis.expire(redis_key, 120)
        if current > rpm:
            # how many seconds left in the current minute bucket
            retry_after = max(1, 60 - (int(time.time()) % 60))
            return False, 0, retry_after
        return True, rpm - current, 0
    except Exception as exc:
        logger.warning("Redis rate-limit check failed, falling back to local: %s", exc)
        return _check_local(key, rpm)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant RPM enforcement. Redis-backed in SaaS mode, no-op otherwise."""

    def __init__(self, app, settings: "TiresiasSettings", redis_url: str | None = None):
        super().__init__(app)
        self.settings = settings
        self._redis = None
        self._redis_url = redis_url

    async def _get_redis(self):
        """Lazy-init Redis connection (or None)."""
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            from redis.asyncio import from_url
            self._redis = from_url(self._redis_url, decode_responses=True)
            # quick connectivity check
            await self._redis.ping()
            logger.info("Rate limiter connected to Redis at %s", self._redis_url)
            return self._redis
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiting, using in-memory fallback: %s", exc)
            self._redis = None
            return None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # No-op in non-SaaS modes
        if self.settings.mode != "saas":
            return await call_next(request)

        # Skip exempt paths
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # Tenant and tier are set by SaaSAuthMiddleware upstream
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant_tier = getattr(request.state, "tenant_tier", "starter")

        if not tenant_id:
            # No tenant resolved yet (auth failed upstream) — let it pass through
            # so the auth middleware's 401 response is returned instead.
            return await call_next(request)

        rpm = TIER_RPM.get(tenant_tier, _DEFAULT_RPM)
        key = tenant_id

        redis = await self._get_redis()
        if redis:
            allowed, remaining, retry_after = await _check_redis(redis, key, rpm)
        else:
            allowed, remaining, retry_after = _check_local(key, rpm)

        if not allowed:
            logger.warning(
                "rate_limit.exceeded tenant=%s tier=%s rpm=%d",
                tenant_id, tenant_tier, rpm,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": f"Rate limit of {rpm} requests/minute exceeded for tier '{tenant_tier}'.",
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rpm),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasApiLog, TiresiasApiEndpointBucket
from tiresias.tracking.api_pricing import calculate_api_cost

logger = logging.getLogger(__name__)

# Regex to match ID-like path segments.
# Applied to each segment between slashes individually.
_SEGMENT_ID_RE = re.compile(
    r"^("
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|[0-9]+"                                                           # pure numeric
    r"|[A-Za-z]{1,6}_[A-Za-z0-9]{8,}"                                   # Stripe/Twilio: ch_xxx, cus_xxx, AC...
    r"|[0-9a-f]{24,}"                                                    # long hex (MongoDB-style)
    r")$",
    re.IGNORECASE,
)


def normalize_path(path: str) -> str:
    """
    Replace ID-like path segments with ``{id}`` placeholders.

    Examples:
        /v1/customers/cus_abc123/subscriptions  ->  /v1/customers/{id}/subscriptions
        /v1/charges/ch_1AbCdE2fGhI3jK          ->  /v1/charges/{id}
        /2010-04-01/Accounts/AC1234567890abcdef ->  /2010-04-01/Accounts/{id}
    """
    # Split on '/' and normalize each segment
    segments = path.split("/")
    normalized = []
    for seg in segments:
        if seg and _SEGMENT_ID_RE.match(seg):
            normalized.append("{id}")
        else:
            normalized.append(seg)
    return "/".join(normalized)


def _bucket_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


async def record_api_call(
    *,
    tenant_id: str,
    api_service: str | None,
    method: str,
    path: str,
    path_pattern: str,
    status_code: int,
    latency_ms: float,
    request_size: int,
    response_size: int,
    cost_usd: float,
    db_session: AsyncSession,
) -> str:
    """Persist one API call to tiresias_api_log and update endpoint bucket."""
    now = datetime.now(timezone.utc)
    row_id = str(uuid4())

    row = TiresiasApiLog(
        id=row_id,
        tenant_id=tenant_id,
        api_service=api_service,
        method=method.upper(),
        path=path,
        path_pattern=path_pattern,
        status_code=status_code,
        latency_ms=latency_ms,
        request_size=request_size,
        response_size=response_size,
        cost_usd=cost_usd,
        created_at=now,
    )
    db_session.add(row)

    await _upsert_endpoint_bucket(
        tenant_id=tenant_id,
        api_service=api_service,
        method=method.upper(),
        path_pattern=path_pattern,
        bucket_dt=_bucket_hour(now),
        latency_ms=latency_ms,
        is_error=status_code >= 400,
        cost_usd=cost_usd,
        db_session=db_session,
    )

    await db_session.commit()
    return row_id


async def _upsert_endpoint_bucket(
    *,
    tenant_id: str,
    api_service: str | None,
    method: str,
    path_pattern: str,
    bucket_dt: datetime,
    latency_ms: float,
    is_error: bool,
    cost_usd: float,
    db_session: AsyncSession,
) -> None:
    stmt = select(TiresiasApiEndpointBucket).where(
        TiresiasApiEndpointBucket.tenant_id == tenant_id,
        TiresiasApiEndpointBucket.api_service == api_service,
        TiresiasApiEndpointBucket.method == method,
        TiresiasApiEndpointBucket.path_pattern == path_pattern,
        TiresiasApiEndpointBucket.bucket_hour == bucket_dt,
    )
    result = await db_session.execute(stmt)
    bucket = result.scalar_one_or_none()

    if bucket is None:
        bucket = TiresiasApiEndpointBucket(
            id=str(uuid4()),
            tenant_id=tenant_id,
            api_service=api_service,
            method=method,
            path_pattern=path_pattern,
            bucket_hour=bucket_dt,
            request_count=0,
            error_count=0,
            latency_sum_ms=0.0,
            latency_min_ms=latency_ms,
            latency_max_ms=latency_ms,
            cost_usd=0.0,
        )
        db_session.add(bucket)
    else:
        if latency_ms < bucket.latency_min_ms:
            bucket.latency_min_ms = latency_ms
        if latency_ms > bucket.latency_max_ms:
            bucket.latency_max_ms = latency_ms

    bucket.request_count += 1
    bucket.latency_sum_ms += latency_ms
    bucket.cost_usd += cost_usd
    if is_error:
        bucket.error_count += 1


async def forward_generic_request(
    *,
    client: httpx.AsyncClient,
    upstream_url: str,
    api_service: str | None,
    method: str,
    path: str,
    headers: dict,
    body_bytes: bytes,
    params: dict,
    tenant_id: str,
    db_session: AsyncSession,
) -> httpx.Response:
    """
    Forward a generic HTTP request to the upstream, record telemetry, return upstream response.
    """
    target_url = upstream_url.rstrip("/") + "/" + path.lstrip("/")
    path_pattern = normalize_path("/" + path.lstrip("/"))

    t0 = time.monotonic()
    try:
        upstream_resp = await client.request(
            method=method,
            url=target_url,
            headers=headers,
            content=body_bytes,
            params=params,
        )
        latency_ms = (time.monotonic() - t0) * 1000.0
        status_code = upstream_resp.status_code
        response_size = len(upstream_resp.content)
    except httpx.RequestError as exc:
        latency_ms = (time.monotonic() - t0) * 1000.0
        logger.error("Generic proxy upstream error: %s", exc)
        # Record as a 502
        await record_api_call(
            tenant_id=tenant_id,
            api_service=api_service,
            method=method,
            path=path,
            path_pattern=normalize_path("/" + path.lstrip("/")),
            status_code=502,
            latency_ms=latency_ms,
            request_size=len(body_bytes),
            response_size=0,
            cost_usd=0.0,
            db_session=db_session,
        )
        raise

    cost_usd = calculate_api_cost(api_service, path_pattern)

    await record_api_call(
        tenant_id=tenant_id,
        api_service=api_service,
        method=method,
        path=path,
        path_pattern=path_pattern,
        status_code=status_code,
        latency_ms=latency_ms,
        request_size=len(body_bytes),
        response_size=response_size,
        cost_usd=cost_usd,
        db_session=db_session,
    )

    return upstream_resp


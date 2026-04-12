from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasApiLog, TiresiasApiEndpointBucket


async def get_endpoint_metrics(
    tenant_id: str,
    db_session: AsyncSession,
    hours: int = 24,
    api_service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return per-endpoint aggregated metrics for the last ``hours`` hours.

    Returns a list of dicts with keys:
        method, path_pattern, api_service,
        request_count, error_count, error_rate,
        latency_avg_ms, latency_min_ms, latency_max_ms,
        cost_usd_total
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    conditions = [
        TiresiasApiEndpointBucket.tenant_id == tenant_id,
        TiresiasApiEndpointBucket.bucket_hour >= since,
    ]
    if api_service is not None:
        conditions.append(TiresiasApiEndpointBucket.api_service == api_service)

    stmt = select(
        TiresiasApiEndpointBucket.method,
        TiresiasApiEndpointBucket.path_pattern,
        TiresiasApiEndpointBucket.api_service,
        func.sum(TiresiasApiEndpointBucket.request_count).label("request_count"),
        func.sum(TiresiasApiEndpointBucket.error_count).label("error_count"),
        func.sum(TiresiasApiEndpointBucket.latency_sum_ms).label("latency_sum"),
        func.min(TiresiasApiEndpointBucket.latency_min_ms).label("latency_min"),
        func.max(TiresiasApiEndpointBucket.latency_max_ms).label("latency_max"),
        func.sum(TiresiasApiEndpointBucket.cost_usd).label("cost_usd"),
    ).where(and_(*conditions)).group_by(
        TiresiasApiEndpointBucket.method,
        TiresiasApiEndpointBucket.path_pattern,
        TiresiasApiEndpointBucket.api_service,
    )

    result = await db_session.execute(stmt)
    rows = result.all()

    out = []
    for row in rows:
        req_count = row.request_count or 0
        err_count = row.error_count or 0
        latency_sum = row.latency_sum or 0.0
        avg_latency = latency_sum / req_count if req_count > 0 else 0.0
        error_rate = err_count / req_count if req_count > 0 else 0.0

        out.append(
            {
                "method": row.method,
                "path_pattern": row.path_pattern,
                "api_service": row.api_service,
                "request_count": req_count,
                "error_count": err_count,
                "error_rate": round(error_rate, 4),
                "latency_avg_ms": round(avg_latency, 2),
                "latency_min_ms": round(row.latency_min or 0.0, 2),
                "latency_max_ms": round(row.latency_max or 0.0, 2),
                "cost_usd_total": round(row.cost_usd or 0.0, 8),
            }
        )

    return out


async def get_error_breakdown(
    tenant_id: str,
    db_session: AsyncSession,
    hours: int = 24,
    api_service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return error counts grouped by (path_pattern, status_code).
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    conditions = [
        TiresiasApiLog.tenant_id == tenant_id,
        TiresiasApiLog.created_at >= since,
        TiresiasApiLog.status_code >= 400,
    ]
    if api_service is not None:
        conditions.append(TiresiasApiLog.api_service == api_service)

    stmt = select(
        TiresiasApiLog.path_pattern,
        TiresiasApiLog.status_code,
        TiresiasApiLog.method,
        func.count(TiresiasApiLog.id).label("count"),
    ).where(and_(*conditions)).group_by(
        TiresiasApiLog.path_pattern,
        TiresiasApiLog.status_code,
        TiresiasApiLog.method,
    )

    result = await db_session.execute(stmt)
    rows = result.all()

    return [
        {
            "method": row.method,
            "path_pattern": row.path_pattern,
            "status_code": row.status_code,
            "count": row.count,
        }
        for row in rows
    ]


async def get_cost_by_endpoint(
    tenant_id: str,
    db_session: AsyncSession,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """
    Return total cost grouped by (api_service, path_pattern).
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = select(
        TiresiasApiLog.api_service,
        TiresiasApiLog.path_pattern,
        func.sum(TiresiasApiLog.cost_usd).label("cost_usd"),
        func.count(TiresiasApiLog.id).label("request_count"),
    ).where(
        and_(
            TiresiasApiLog.tenant_id == tenant_id,
            TiresiasApiLog.created_at >= since,
        )
    ).group_by(
        TiresiasApiLog.api_service,
        TiresiasApiLog.path_pattern,
    )

    result = await db_session.execute(stmt)
    rows = result.all()

    return [
        {
            "api_service": row.api_service,
            "path_pattern": row.path_pattern,
            "cost_usd_total": round(row.cost_usd or 0.0, 8),
            "request_count": row.request_count,
        }
        for row in rows
    ]


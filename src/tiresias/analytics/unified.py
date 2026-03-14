from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasAuditLog, TiresiasUsageBucket, TiresiasApiLog
from tiresias.analytics.api_telemetry import get_endpoint_metrics, get_error_breakdown


async def get_unified_analytics(
    tenant_id: str,
    db_session: AsyncSession,
    hours: int = 24,
) -> dict[str, Any]:
    """
    Return a unified analytics payload combining LLM telemetry and API telemetry.

    Shape:
    {
        "tenant_id": str,
        "window_hours": int,
        "llm": {
            "request_count": int,
            "error_count": int,
            "total_tokens": int,
            "cost_usd_total": float,
            "by_model": [ {model, provider, request_count, cost_usd} ],
        },
        "api": {
            "request_count": int,
            "error_count": int,
            "cost_usd_total": float,
            "endpoints": [ {method, path_pattern, api_service, ...} ],
            "error_breakdown": [ {method, path_pattern, status_code, count} ],
        },
        "totals": {
            "request_count": int,
            "cost_usd_total": float,
        }
    }
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # --- LLM telemetry ---
    llm_stmt = select(
        func.count(TiresiasAuditLog.id).label("request_count"),
        func.coalesce(func.sum(TiresiasAuditLog.token_count), 0).label("total_tokens"),
        func.coalesce(func.sum(TiresiasAuditLog.cost_usd), 0.0).label("cost_usd"),
    ).where(
        and_(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= since,
            TiresiasAuditLog.deleted_at.is_(None),
        )
    )
    llm_result = await db_session.execute(llm_stmt)
    llm_row = llm_result.one()

    # LLM error count from usage buckets
    bucket_stmt = select(
        func.coalesce(func.sum(TiresiasUsageBucket.error_count), 0).label("error_count"),
    ).where(
        and_(
            TiresiasUsageBucket.tenant_id == tenant_id,
            TiresiasUsageBucket.bucket_hour >= since,
        )
    )
    bucket_result = await db_session.execute(bucket_stmt)
    bucket_row = bucket_result.one()

    # LLM by-model breakdown
    model_stmt = select(
        TiresiasAuditLog.model,
        TiresiasAuditLog.provider,
        func.count(TiresiasAuditLog.id).label("request_count"),
        func.coalesce(func.sum(TiresiasAuditLog.cost_usd), 0.0).label("cost_usd"),
    ).where(
        and_(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= since,
            TiresiasAuditLog.deleted_at.is_(None),
        )
    ).group_by(TiresiasAuditLog.model, TiresiasAuditLog.provider)
    model_result = await db_session.execute(model_stmt)
    model_rows = model_result.all()

    llm_data = {
        "request_count": llm_row.request_count or 0,
        "error_count": int(bucket_row.error_count or 0),
        "total_tokens": int(llm_row.total_tokens or 0),
        "cost_usd_total": round(float(llm_row.cost_usd or 0.0), 8),
        "by_model": [
            {
                "model": r.model,
                "provider": r.provider,
                "request_count": r.request_count,
                "cost_usd": round(float(r.cost_usd or 0.0), 8),
            }
            for r in model_rows
        ],
    }

    # --- API telemetry ---
    api_stmt = select(
        func.count(TiresiasApiLog.id).label("request_count"),
        func.coalesce(func.sum(TiresiasApiLog.cost_usd), 0.0).label("cost_usd"),
    ).where(
        and_(
            TiresiasApiLog.tenant_id == tenant_id,
            TiresiasApiLog.created_at >= since,
        )
    )
    api_result = await db_session.execute(api_stmt)
    api_row = api_result.one()

    api_error_stmt = select(
        func.count(TiresiasApiLog.id).label("error_count"),
    ).where(
        and_(
            TiresiasApiLog.tenant_id == tenant_id,
            TiresiasApiLog.created_at >= since,
            TiresiasApiLog.status_code >= 400,
        )
    )
    api_error_result = await db_session.execute(api_error_stmt)
    api_error_row = api_error_result.one()

    endpoints = await get_endpoint_metrics(tenant_id, db_session, hours=hours)
    error_breakdown = await get_error_breakdown(tenant_id, db_session, hours=hours)

    api_data = {
        "request_count": int(api_row.request_count or 0),
        "error_count": int(api_error_row.error_count or 0),
        "cost_usd_total": round(float(api_row.cost_usd or 0.0), 8),
        "endpoints": endpoints,
        "error_breakdown": error_breakdown,
    }

    total_requests = llm_data["request_count"] + api_data["request_count"]
    total_cost = round(llm_data["cost_usd_total"] + api_data["cost_usd_total"], 8)

    return {
        "tenant_id": tenant_id,
        "window_hours": hours,
        "llm": llm_data,
        "api": api_data,
        "totals": {
            "request_count": total_requests,
            "cost_usd_total": total_cost,
        },
    }

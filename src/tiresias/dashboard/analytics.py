from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.schema import TiresiasAuditLog, TiresiasUsageBucket


async def get_spend_summary(db_session: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> dict:
    """Total spend in USD between start and end."""
    stmt = (
        select(
            func.sum(TiresiasAuditLog.cost_usd).label("total_cost"),
            func.count(TiresiasAuditLog.id).label("request_count"),
            func.sum(TiresiasAuditLog.token_count).label("total_tokens"),
        )
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= start,
            TiresiasAuditLog.created_at <= end,
            TiresiasAuditLog.deleted_at.is_(None),
        )
    )
    result = await db_session.execute(stmt)
    row = result.one()
    return {
        "total_cost_usd": round(float(row.total_cost or 0.0), 8),
        "request_count": int(row.request_count or 0),
        "total_tokens": int(row.total_tokens or 0),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


async def get_requests_per_day(db_session: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> list[dict]:
    """Return request counts grouped by day (UTC date)."""
    stmt = (
        select(TiresiasAuditLog.created_at, TiresiasAuditLog.cost_usd)
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= start,
            TiresiasAuditLog.created_at <= end,
            TiresiasAuditLog.deleted_at.is_(None),
        )
        .order_by(TiresiasAuditLog.created_at.asc())
    )
    result = await db_session.execute(stmt)
    rows = result.all()

    day_counts: dict[str, dict] = {}
    for row in rows:
        dt = row.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        if day_key not in day_counts:
            day_counts[day_key] = {"date": day_key, "request_count": 0, "cost_usd": 0.0}
        day_counts[day_key]["request_count"] += 1
        day_counts[day_key]["cost_usd"] = round(
            day_counts[day_key]["cost_usd"] + float(row.cost_usd or 0.0), 8
        )

    return sorted(day_counts.values(), key=lambda x: x["date"])


async def get_latency_percentiles(db_session: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> list[dict]:
    """Return p50/p95/p99 latency per provider extracted from metadata_json.latency_ms."""
    stmt = (
        select(TiresiasAuditLog.provider, TiresiasAuditLog.metadata_json)
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= start,
            TiresiasAuditLog.created_at <= end,
            TiresiasAuditLog.deleted_at.is_(None),
            TiresiasAuditLog.provider.isnot(None),
        )
    )
    result = await db_session.execute(stmt)
    rows = result.all()

    provider_latencies: dict[str, list[float]] = {}
    for row in rows:
        provider = row.provider or "unknown"
        latency_ms = None
        if row.metadata_json:
            try:
                meta = json.loads(row.metadata_json)
                latency_ms = meta.get("latency_ms")
            except (json.JSONDecodeError, TypeError):
                pass
        if latency_ms is not None:
            provider_latencies.setdefault(provider, []).append(float(latency_ms))

    output = []
    for provider, latencies in sorted(provider_latencies.items()):
        if not latencies:
            continue
        sorted_lat = sorted(latencies)

        def percentile(data: list[float], pct: int) -> float:
            idx = min(int(len(data) * pct / 100), len(data) - 1)
            return round(data[idx], 2)

        output.append({
            "provider": provider,
            "sample_count": len(sorted_lat),
            "p50_ms": percentile(sorted_lat, 50),
            "p95_ms": percentile(sorted_lat, 95),
            "p99_ms": percentile(sorted_lat, 99),
        })

    return output


async def get_error_rates(db_session: AsyncSession, tenant_id: str, start: datetime, end: datetime) -> list[dict]:
    """Return error rate per provider from metadata_json.status_code or .error flag."""
    stmt = (
        select(TiresiasAuditLog.provider, TiresiasAuditLog.metadata_json)
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= start,
            TiresiasAuditLog.created_at <= end,
            TiresiasAuditLog.deleted_at.is_(None),
        )
    )
    result = await db_session.execute(stmt)
    rows = result.all()

    provider_stats: dict[str, dict] = {}
    for row in rows:
        provider = row.provider or "unknown"
        if provider not in provider_stats:
            provider_stats[provider] = {"total": 0, "errors": 0, "status_codes": {}}
        provider_stats[provider]["total"] += 1

        status_code = None
        if row.metadata_json:
            try:
                meta = json.loads(row.metadata_json)
                status_code = meta.get("status_code")
                if meta.get("error"):
                    status_code = status_code or 500
            except (json.JSONDecodeError, TypeError):
                pass

        if status_code and int(status_code) >= 400:
            provider_stats[provider]["errors"] += 1
            sc_key = str(status_code)
            provider_stats[provider]["status_codes"][sc_key] = (
                provider_stats[provider]["status_codes"].get(sc_key, 0) + 1
            )

    output = []
    for provider, stats in sorted(provider_stats.items()):
        total = stats["total"]
        errors = stats["errors"]
        output.append({
            "provider": provider,
            "total_requests": total,
            "error_count": errors,
            "error_rate": round(errors / total, 4) if total > 0 else 0.0,
            "status_codes": stats["status_codes"],
        })

    return output


async def get_top_sessions(
    db_session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> list[dict]:
    """Return top N sessions by total cost."""
    stmt = (
        select(
            TiresiasAuditLog.session_id,
            func.sum(TiresiasAuditLog.cost_usd).label("total_cost"),
            func.count(TiresiasAuditLog.id).label("request_count"),
            func.sum(TiresiasAuditLog.token_count).label("total_tokens"),
            func.min(TiresiasAuditLog.created_at).label("first_at"),
            func.max(TiresiasAuditLog.created_at).label("last_at"),
        )
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.created_at >= start,
            TiresiasAuditLog.created_at <= end,
            TiresiasAuditLog.deleted_at.is_(None),
            TiresiasAuditLog.session_id.isnot(None),
        )
        .group_by(TiresiasAuditLog.session_id)
        .order_by(func.sum(TiresiasAuditLog.cost_usd).desc())
        .limit(limit)
    )
    result = await db_session.execute(stmt)
    rows = result.all()

    output = []
    for row in rows:
        first_at = row.first_at
        last_at = row.last_at
        if first_at and hasattr(first_at, "isoformat"):
            first_at = first_at.isoformat()
        if last_at and hasattr(last_at, "isoformat"):
            last_at = last_at.isoformat()
        output.append({
            "session_id": row.session_id,
            "total_cost_usd": round(float(row.total_cost or 0.0), 8),
            "request_count": int(row.request_count or 0),
            "total_tokens": int(row.total_tokens or 0),
            "first_request_at": first_at,
            "last_request_at": last_at,
        })

    return output


async def get_session_replay(
    db_session: AsyncSession,
    tenant_id: str,
    session_id: str,
    envelope,
) -> list[dict]:
    """Return full decrypted turn history for a session."""
    stmt = (
        select(TiresiasAuditLog)
        .where(
            TiresiasAuditLog.tenant_id == tenant_id,
            TiresiasAuditLog.session_id == session_id,
            TiresiasAuditLog.deleted_at.is_(None),
        )
        .order_by(TiresiasAuditLog.created_at.asc())
    )
    result = await db_session.execute(stmt)
    rows = result.scalars().all()

    turns = []
    for row in rows:
        prompt_text = None
        completion_text = None

        if row.encrypted_prompt and envelope is not None:
            try:
                raw = await envelope.decrypt(tenant_id, row.encrypted_prompt, db_session)
                prompt_text = raw.decode("utf-8", errors="replace")
            except Exception:
                prompt_text = "[decryption failed]"

        if row.encrypted_completion and envelope is not None:
            try:
                raw = await envelope.decrypt(tenant_id, row.encrypted_completion, db_session)
                completion_text = raw.decode("utf-8", errors="replace")
            except Exception:
                completion_text = "[decryption failed]"

        metadata: dict = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        turns.append({
            "id": row.id,
            "model": row.model,
            "provider": row.provider,
            "token_count": row.token_count,
            "cost_usd": row.cost_usd,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "prompt": prompt_text,
            "completion": completion_text,
            "metadata": metadata,
        })

    return turns

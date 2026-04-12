"""Dashboard APIRouter — mountable on the main proxy app.

This module exposes the same /dash/* endpoints as dashboard/app.py but as an
APIRouter that can be included in any FastAPI app (e.g. the proxy) *before*
catch-all routes.  It re-uses the proxy app's settings and health tracker via
the module-level accessors in proxy.app.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


# ---------------------------------------------------------------------------
# Helpers (same as dashboard/app.py but import-safe)
# ---------------------------------------------------------------------------

def _default_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    return start, now


def _parse_dt_param(dt_str: str | None, default: datetime) -> datetime:
    if not dt_str:
        return default
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return default


def _get_proxy_settings():
    from tiresias.proxy.app import get_settings
    return get_settings()


async def _get_proxy_engine():
    from tiresias.storage.engine import get_engine
    cfg = _get_proxy_settings()
    return await get_engine(cfg.tenant_id, cfg.data_root)


def _get_proxy_health():
    from tiresias.proxy.app import get_health
    return get_health()


# ---------------------------------------------------------------------------
# Auth dependency — accepts X-SoulKey OR X-Tiresias-Api-Key / Bearer
# ---------------------------------------------------------------------------

async def _require_auth(request: Request) -> str:
    from tiresias.dashboard.auth import make_auth_dependency
    dep = make_auth_dependency(_get_proxy_settings, _get_proxy_engine)
    return await dep(request)

AuthDep = Annotated[str, Depends(_require_auth)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dash/health")
async def dash_health() -> dict:
    return {"status": "ok", "service": "tiresias-dashboard"}


@router.get("/dash/v1/spend")
async def spend_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict:
    from tiresias.dashboard.analytics import get_spend_summary
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        return await get_spend_summary(session, cfg.tenant_id, t_start, t_end)


@router.get("/dash/v1/requests")
async def requests_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict:
    from tiresias.dashboard.analytics import get_requests_per_day
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        return await get_requests_per_day(session, cfg.tenant_id, t_start, t_end)


@router.get("/dash/v1/latency")
async def latency_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict:
    from tiresias.dashboard.analytics import get_latency_percentiles
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        data = await get_latency_percentiles(session, cfg.tenant_id, t_start, t_end)
    return {"providers": data}


@router.get("/dash/v1/errors")
async def errors_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> dict:
    from tiresias.dashboard.analytics import get_error_rates
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        data = await get_error_rates(session, cfg.tenant_id, t_start, t_end)
    return {"providers": data}


@router.get("/dash/v1/sessions/top")
async def top_sessions_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    from tiresias.dashboard.analytics import get_top_sessions
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        return await get_top_sessions(session, cfg.tenant_id, t_start, t_end, limit=limit)


@router.get("/dash/v1/sessions/{session_id}/replay")
async def session_replay_endpoint(
    session_id: str,
    _key: AuthDep,
) -> dict:
    from tiresias.dashboard.analytics import get_session_replay
    from tiresias.proxy.app import get_envelope
    cfg = _get_proxy_settings()
    envelope = get_envelope()
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        result = await get_session_replay(session, cfg.tenant_id, session_id, envelope)
    if not result["turns"]:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
    return result




@router.get('/dash/v1/traces')
async def traces_endpoint(
    _key: AuthDep,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> dict:
    from tiresias.dashboard.analytics import get_traces
    cfg = _get_proxy_settings()
    default_start, default_end = _default_window()
    t_start = _parse_dt_param(start, default_start)
    t_end = _parse_dt_param(end, default_end)
    engine = await _get_proxy_engine()
    async with AsyncSession(engine) as session:
        return await get_traces(
            session, cfg.tenant_id, t_start, t_end,
            page=page, limit=limit,
            provider=provider, model=model, status=status,
            date=date, search=search,
        )

@router.get("/dash/v1/providers/health")
async def provider_health_endpoint(_key: AuthDep) -> dict:
    from tiresias.config import parse_providers
    health = _get_proxy_health()
    cfg = _get_proxy_settings()
    cascade = parse_providers(cfg.providers)
    statuses = health.status()
    for s in statuses:
        if s["is_healthy"]:
            s["status"] = "UP"
        elif s["consecutive_errors"] >= 3:
            s["status"] = "DOWN"
        else:
            s["status"] = "DEGRADED"
    return {"cascade": cascade, "providers": statuses}


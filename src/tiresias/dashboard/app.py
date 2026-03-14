import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.config import TiresiasSettings, parse_providers
from tiresias.encryption.envelope import EnvelopeEncryption
from tiresias.encryption.providers import resolve_kek_provider
from tiresias.providers.health import HealthTracker
from tiresias.storage.engine import get_engine

logger = logging.getLogger(__name__)

_dash_settings: TiresiasSettings | None = None
_dash_envelope: EnvelopeEncryption | None = None
_dash_health: HealthTracker | None = None

_STATIC_DIR = Path(__file__).parent / "static"


def get_dash_settings() -> TiresiasSettings:
    if _dash_settings is None:
        raise RuntimeError("Dashboard app not initialized")
    return _dash_settings


def get_dash_envelope() -> EnvelopeEncryption:
    if _dash_envelope is None:
        raise RuntimeError("Dashboard app not initialized")
    return _dash_envelope


async def get_dash_engine():
    cfg = get_dash_settings()
    return await get_engine(cfg.tenant_id, cfg.data_root)


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


def create_dashboard_app(
    settings: TiresiasSettings | None = None,
    health_tracker: HealthTracker | None = None,
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _dash_settings, _dash_envelope, _dash_health
        cfg = settings or TiresiasSettings()
        _dash_settings = cfg
        provider = resolve_kek_provider(cfg)
        _dash_envelope = EnvelopeEncryption(provider)
        if health_tracker is not None:
            _dash_health = health_tracker
        else:
            cascade = parse_providers(cfg.providers)
            _dash_health = HealthTracker(cascade)
        logger.info("Tiresias dashboard started. Tenant: %s", cfg.tenant_id)
        yield

    app = FastAPI(
        title="Tiresias Dashboard API",
        description="Analytics API for Tiresias dashboard",
        version="0.4.0",
        lifespan=lifespan,
    )

    # Build the auth dependency using the factory (no circular imports)
    from tiresias.dashboard.auth import make_api_key_dependency
    _require_api_key = make_api_key_dependency(get_dash_settings, get_dash_engine)
    AuthDep = Annotated[str, Depends(_require_api_key)]

    # ─── Health (no auth) ────────────────────────────────────────────────────

    @app.get("/dash/health")
    async def dash_health() -> dict:
        return {"status": "ok", "service": "tiresias-dashboard"}

    # ─── Spend ───────────────────────────────────────────────────────────────

    @app.get("/dash/v1/spend")
    async def spend_endpoint(
        _key: AuthDep,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> dict:
        from tiresias.dashboard.analytics import get_spend_summary
        cfg = get_dash_settings()
        default_start, default_end = _default_window()
        t_start = _parse_dt_param(start, default_start)
        t_end = _parse_dt_param(end, default_end)
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            return await get_spend_summary(session, cfg.tenant_id, t_start, t_end)

    # ─── Requests per day ────────────────────────────────────────────────────

    @app.get("/dash/v1/requests")
    async def requests_endpoint(
        _key: AuthDep,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> list:
        from tiresias.dashboard.analytics import get_requests_per_day
        cfg = get_dash_settings()
        default_start, default_end = _default_window()
        t_start = _parse_dt_param(start, default_start)
        t_end = _parse_dt_param(end, default_end)
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            return await get_requests_per_day(session, cfg.tenant_id, t_start, t_end)

    # ─── Latency percentiles ─────────────────────────────────────────────────

    @app.get("/dash/v1/latency")
    async def latency_endpoint(
        _key: AuthDep,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> list:
        from tiresias.dashboard.analytics import get_latency_percentiles
        cfg = get_dash_settings()
        default_start, default_end = _default_window()
        t_start = _parse_dt_param(start, default_start)
        t_end = _parse_dt_param(end, default_end)
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            return await get_latency_percentiles(session, cfg.tenant_id, t_start, t_end)

    # ─── Error rates ─────────────────────────────────────────────────────────

    @app.get("/dash/v1/errors")
    async def errors_endpoint(
        _key: AuthDep,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> list:
        from tiresias.dashboard.analytics import get_error_rates
        cfg = get_dash_settings()
        default_start, default_end = _default_window()
        t_start = _parse_dt_param(start, default_start)
        t_end = _parse_dt_param(end, default_end)
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            return await get_error_rates(session, cfg.tenant_id, t_start, t_end)

    # ─── Top sessions ────────────────────────────────────────────────────────

    @app.get("/dash/v1/sessions/top")
    async def top_sessions_endpoint(
        _key: AuthDep,
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list:
        from tiresias.dashboard.analytics import get_top_sessions
        cfg = get_dash_settings()
        default_start, default_end = _default_window()
        t_start = _parse_dt_param(start, default_start)
        t_end = _parse_dt_param(end, default_end)
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            return await get_top_sessions(session, cfg.tenant_id, t_start, t_end, limit=limit)

    # ─── Session replay ──────────────────────────────────────────────────────

    @app.get("/dash/v1/sessions/{session_id}/replay")
    async def session_replay_endpoint(
        session_id: str,
        _key: AuthDep,
    ) -> list:
        from tiresias.dashboard.analytics import get_session_replay
        cfg = get_dash_settings()
        envelope = get_dash_envelope()
        engine = await get_dash_engine()
        async with AsyncSession(engine) as session:
            turns = await get_session_replay(session, cfg.tenant_id, session_id, envelope)
        if not turns:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
        return turns

    # ─── Provider health ─────────────────────────────────────────────────────

    @app.get("/dash/v1/providers/health")
    async def provider_health_endpoint(_key: AuthDep) -> dict:
        health = _dash_health
        if health is None:
            raise HTTPException(status_code=503, detail="Health tracker not initialized.")
        cfg = get_dash_settings()
        cascade = parse_providers(cfg.providers)
        statuses = health.status()
        for s in statuses:
            if s["is_healthy"]:
                s["status"] = "up"
            elif s["consecutive_errors"] >= 3:
                s["status"] = "down"
            else:
                s["status"] = "degraded"
        return {"cascade": cascade, "providers": statuses}

    # ─── Static files (must be last) ─────────────────────────────────────────

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app


dashboard_app = create_dashboard_app()

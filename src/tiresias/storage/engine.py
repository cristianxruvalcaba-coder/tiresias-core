from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tiresias.storage.schema import Base

_engine_registry: dict[str, AsyncEngine] = {}
_registry_lock = asyncio.Lock()

DATABASE_URL = os.environ.get("TIRESIAS_DATABASE_URL")


def _is_postgres() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith("postgresql"))


async def get_engine(tenant_id: str, data_root: Path = Path("/data")) -> AsyncEngine:
    """Return (or create and cache) the AsyncEngine for the given tenant.

    If TIRESIAS_DATABASE_URL is set to a postgresql:// URL, a single shared
    Postgres engine is used (tenants isolated by the tenant_id column).
    Otherwise, falls back to per-tenant SQLite databases at:
        <data_root>/tenants/<tenant_id>/tiresias.db
    """
    if _is_postgres():
        # Postgres mode: single shared engine
        _key = "__pg__"
        if _key in _engine_registry:
            return _engine_registry[_key]

        async with _registry_lock:
            if _key in _engine_registry:
                return _engine_registry[_key]

            pg_url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
            engine = create_async_engine(
                pg_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
            )

            # Tables are created externally (migration / init SQL).
            # Run create_all only to pick up any new columns during dev.
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            _engine_registry[_key] = engine
            return engine

    # ---------- SQLite per-tenant fallback ----------
    if tenant_id in _engine_registry:
        return _engine_registry[tenant_id]

    async with _registry_lock:
        if tenant_id in _engine_registry:
            return _engine_registry[tenant_id]

        db_dir = data_root / "tenants" / tenant_id
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "tiresias.db"

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_pragmas(dbapi_conn, _connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA mmap_size=268435456")
            cursor.close()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        _engine_registry[tenant_id] = engine
        return engine


async def set_tenant_context(session: "AsyncSession", tenant_id: str) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Set the Postgres session variable used by RLS policies.

    Must be called at the start of any DB session in SaaS mode so that
    ``current_setting('app.current_tenant_id', true)`` returns the correct
    tenant for row-level security filtering.  Uses SET LOCAL so the value
    is scoped to the current transaction.

    Note: asyncpg does not support parameterized SET statements, so the
    tenant_id is interpolated directly.  Only UUID-shaped values are accepted
    to prevent injection.
    """
    if not _is_postgres():
        return
    import re
    if not re.fullmatch(r"[0-9a-fA-F\-]{36}", tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id!r}")
    # Use SET (not SET LOCAL) to persist the variable for the connection duration.
    # SET LOCAL is transaction-scoped and is lost between autocommit statements.
    # The variable must be visible when RLS policies evaluate during INSERT/SELECT.
    await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))


async def close_all_engines() -> None:
    """Dispose all cached engines and clear the registry (useful for test teardown)."""
    async with _registry_lock:
        for engine in _engine_registry.values():
            await engine.dispose()
        _engine_registry.clear()

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tiresias.storage.engine import close_all_engines, get_engine


async def test_lazy_db_creation(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """Engine creation should create the DB file at the expected path."""
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    db_path = tmp_data_root / "tenants" / sample_tenant_id / "tiresias.db"
    assert db_path.exists(), f"Expected DB at {db_path}"
    assert isinstance(engine, AsyncEngine)


async def test_engine_cache_returns_same_instance(
    tmp_data_root: Path, sample_tenant_id: str
) -> None:
    """Calling get_engine twice for the same tenant should return the same object."""
    engine1 = await get_engine(sample_tenant_id, tmp_data_root)
    engine2 = await get_engine(sample_tenant_id, tmp_data_root)
    assert engine1 is engine2


async def test_wal_mode_set(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """WAL journal mode should be enabled."""
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA journal_mode"))
        row = result.fetchone()
    assert row is not None
    assert row[0].lower() == "wal"


async def test_foreign_keys_enabled(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """foreign_keys pragma should be ON (1)."""
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        row = result.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_different_tenants_get_different_engines(tmp_data_root: Path) -> None:
    """Different tenant IDs should get separate engines and separate DB files."""
    tenant_a = "aaaaaaaa-0000-0000-0000-000000000001"
    tenant_b = "bbbbbbbb-0000-0000-0000-000000000002"
    engine_a = await get_engine(tenant_a, tmp_data_root)
    engine_b = await get_engine(tenant_b, tmp_data_root)
    assert engine_a is not engine_b
    assert (tmp_data_root / "tenants" / tenant_a / "tiresias.db").exists()
    assert (tmp_data_root / "tenants" / tenant_b / "tiresias.db").exists()

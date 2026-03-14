from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tiresias.storage.engine import get_engine
from tiresias.storage.schema import TiresiasAuditLog, TiresiasLicense, TiresiasUsageBucket


async def _get_session(tenant_id: str, data_root: Path) -> AsyncSession:
    engine = await get_engine(tenant_id, data_root)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return Session()


async def test_all_tables_created(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """All three tiresias_* tables should exist after engine creation."""
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    assert "tiresias_audit_log" in table_names
    assert "tiresias_licenses" in table_names
    assert "tiresias_usage_buckets" in table_names


async def test_write_read_audit_log(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """Should be able to write and read back an audit log entry."""
    async with await _get_session(sample_tenant_id, tmp_data_root) as session:
        entry = TiresiasAuditLog(
            id=str(uuid4()),
            tenant_id=sample_tenant_id,
            encrypted_prompt=b"\x00\x01\x02encrypted_prompt",
            encrypted_completion=b"\x03\x04\x05encrypted_completion",
            model="gpt-4",
            provider="openai",
            token_count=100,
            cost_usd=0.003,
            session_id="test-session-1",
        )
        session.add(entry)
        await session.commit()

        result = await session.get(TiresiasAuditLog, entry.id)
    assert result is not None
    assert result.tenant_id == sample_tenant_id
    assert result.encrypted_prompt == b"\x00\x01\x02encrypted_prompt"
    assert result.model == "gpt-4"
    assert result.token_count == 100


async def test_write_read_license(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """Should be able to write and read back a license record."""
    async with await _get_session(sample_tenant_id, tmp_data_root) as session:
        lic = TiresiasLicense(
            tenant_id=sample_tenant_id,
            tier="pro",
            kek_provider="local",
            retention_days=90,
            wrapped_dek=b"\xde\xad\xbe\xef",
            api_key_hash="abc123hash",
        )
        session.add(lic)
        await session.commit()

        result = await session.get(TiresiasLicense, sample_tenant_id)
    assert result is not None
    assert result.tier == "pro"
    assert result.wrapped_dek == b"\xde\xad\xbe\xef"
    assert result.api_key_hash == "abc123hash"


async def test_usage_bucket_unique_constraint(
    tmp_data_root: Path, sample_tenant_id: str
) -> None:
    """Inserting two usage buckets with the same tenant_id + bucket_hour should raise IntegrityError."""
    bucket_hour = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    async with await _get_session(sample_tenant_id, tmp_data_root) as session:
        b1 = TiresiasUsageBucket(
            id=str(uuid4()),
            tenant_id=sample_tenant_id,
            bucket_hour=bucket_hour,
            token_count=50,
            request_count=5,
        )
        session.add(b1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with await _get_session(sample_tenant_id, tmp_data_root) as session:
            b2 = TiresiasUsageBucket(
                id=str(uuid4()),
                tenant_id=sample_tenant_id,
                bucket_hour=bucket_hour,
                token_count=60,
                request_count=6,
            )
            session.add(b2)
            await session.commit()


async def test_audit_log_nullable_fields(tmp_data_root: Path, sample_tenant_id: str) -> None:
    """encrypted_prompt and encrypted_completion should be nullable (for soft deletes)."""
    async with await _get_session(sample_tenant_id, tmp_data_root) as session:
        entry = TiresiasAuditLog(
            id=str(uuid4()),
            tenant_id=sample_tenant_id,
            encrypted_prompt=None,
            encrypted_completion=None,
        )
        session.add(entry)
        await session.commit()
        result = await session.get(TiresiasAuditLog, entry.id)
    assert result is not None
    assert result.encrypted_prompt is None
    assert result.encrypted_completion is None

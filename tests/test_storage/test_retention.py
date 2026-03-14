from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tiresias.config import TiresiasSettings
from tiresias.storage.engine import get_engine
from tiresias.storage.retention import run_retention_purge
from tiresias.storage.schema import TiresiasAuditLog, TiresiasUsageBucket


def utcnow():
    return datetime.now(timezone.utc)


async def get_session(tenant_id, data_root):
    engine = await get_engine(tenant_id, data_root)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return Session()


async def insert_audit_row(session, tenant_id, days_old, deleted_days_ago=None,
                            request_hash="rh-default", response_hash="rsp-default"):
    """Helper: insert an audit log row with a backdated created_at."""
    now = utcnow()
    created_at = now - timedelta(days=days_old)
    deleted_at = (now - timedelta(days=deleted_days_ago)) if deleted_days_ago is not None else None
    row = TiresiasAuditLog(
        id=str(uuid4()), tenant_id=tenant_id,
        encrypted_prompt=b"encrypted-prompt-bytes" if deleted_at is None else None,
        encrypted_completion=b"encrypted-completion-bytes" if deleted_at is None else None,
        request_hash=request_hash, response_hash=response_hash,
        model="gpt-4", provider="openai", token_count=10, cost_usd=0.001, session_id="test-session",
    )
    session.add(row)
    await session.flush()
    await session.execute(text("UPDATE tiresias_audit_log SET created_at = :ca WHERE id = :id"),
                          {"ca": created_at, "id": row.id})
    if deleted_at is not None:
        await session.execute(text("UPDATE tiresias_audit_log SET deleted_at = :da WHERE id = :id"),
                              {"da": deleted_at, "id": row.id})
    await session.commit()
    await session.refresh(row)
    return row


async def test_soft_delete(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old_row = await insert_audit_row(session, sample_tenant_id, days_old=35)
        young_row = await insert_audit_row(session, sample_tenant_id, days_old=5)
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old = await session.get(TiresiasAuditLog, old_row.id)
        young = await session.get(TiresiasAuditLog, young_row.id)
    assert old is not None
    assert old.encrypted_prompt is None
    assert old.encrypted_completion is None
    assert old.deleted_at is not None
    assert young is not None
    assert young.encrypted_prompt == b"encrypted-prompt-bytes"
    assert young.deleted_at is None
    assert counts["soft_deleted"] == 1


async def test_hard_delete(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old_row = await insert_audit_row(session, sample_tenant_id, days_old=50, deleted_days_ago=10)
        recent_row = await insert_audit_row(session, sample_tenant_id, days_old=40, deleted_days_ago=2)
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old = await session.get(TiresiasAuditLog, old_row.id)
        recent = await session.get(TiresiasAuditLog, recent_row.id)
    assert old is None
    assert recent is not None
    assert counts["hard_deleted"] == 1


async def test_recent_rows_untouched(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        row = await insert_audit_row(session, sample_tenant_id, days_old=10)
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        result = await session.get(TiresiasAuditLog, row.id)
    assert result is not None
    assert result.encrypted_prompt is not None
    assert result.deleted_at is None
    assert counts["soft_deleted"] == 0


async def test_hash_chain_preserved(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        row = await insert_audit_row(
            session, sample_tenant_id, days_old=35,
            request_hash="req-hash-abc", response_hash="resp-hash-xyz"
        )
    await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        result = await session.get(TiresiasAuditLog, row.id)
    assert result is not None
    assert result.request_hash == "req-hash-abc"
    assert result.response_hash == "resp-hash-xyz"
    assert result.model == "gpt-4"
    assert result.token_count == 10


async def test_usage_bucket_purge(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    now = utcnow()
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old_bucket = TiresiasUsageBucket(id=str(uuid4()), tenant_id=sample_tenant_id,
                                          bucket_hour=now - timedelta(days=100), token_count=500, request_count=10)
        recent_bucket = TiresiasUsageBucket(id=str(uuid4()), tenant_id=sample_tenant_id,
                                             bucket_hour=now - timedelta(days=10), token_count=200, request_count=5)
        session.add(old_bucket)
        session.add(recent_bucket)
        await session.commit()
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        old = await session.get(TiresiasUsageBucket, old_bucket.id)
        recent = await session.get(TiresiasUsageBucket, recent_bucket.id)
    assert old is None
    assert recent is not None
    assert counts["usage_purged"] == 1


async def test_retention_env_var(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        row = await insert_audit_row(session, sample_tenant_id, days_old=6)
    settings = TiresiasSettings(TIRESIAS_RETENTION_DAYS=5, TIRESIAS_DATA_ROOT=tmp_data_root)
    counts = await run_retention_purge(engine, retention_days=settings.retention_days,
                                       usage_retention_days=settings.usage_retention_days)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        result = await session.get(TiresiasAuditLog, row.id)
    assert result is not None
    assert result.encrypted_prompt is None
    assert result.deleted_at is not None
    assert counts["soft_deleted"] == 1


async def test_purge_returns_counts(tmp_data_root, sample_tenant_id):
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    assert "soft_deleted" in counts
    assert "hard_deleted" in counts
    assert "usage_purged" in counts
    assert all(isinstance(v, int) for v in counts.values())

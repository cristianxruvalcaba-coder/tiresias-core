from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tiresias.bootstrap import first_boot
from tiresias.config import TiresiasSettings
from tiresias.encryption.envelope import EnvelopeEncryption
from tiresias.encryption.providers.local import LocalKEKProvider
from tiresias.storage.engine import close_all_engines, get_engine
from tiresias.storage.retention import run_retention_purge
from tiresias.storage.schema import TiresiasAuditLog, TiresiasLicense


def utcnow():
    return datetime.now(timezone.utc)


async def get_session(tenant_id, data_root):
    engine = await get_engine(tenant_id, data_root)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return Session()


async def test_write_encrypted_read_decrypted(tmp_data_root, sample_tenant_id):
    settings = TiresiasSettings(TIRESIAS_TENANT_ID=sample_tenant_id, TIRESIAS_DATA_ROOT=tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        api_key = await first_boot(sample_tenant_id, settings, session)
    assert api_key is not None
    provider = LocalKEKProvider.from_api_key(api_key)
    envelope = EnvelopeEncryption(provider)
    prompt_text = "What is the meaning of life?"
    completion_text = "42, of course."
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        enc_prompt = await envelope.encrypt(prompt_text, dek)
        enc_completion = await envelope.encrypt(completion_text, dek)
        row = TiresiasAuditLog(
            id=str(uuid4()), tenant_id=sample_tenant_id,
            encrypted_prompt=enc_prompt, encrypted_completion=enc_completion,
            model="gpt-4", provider="openai", token_count=15, cost_usd=0.001,
            session_id="test-session", request_hash="abc123", response_hash="def456"
        )
        session.add(row)
        await session.commit()
        row_id = row.id
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        fetched = await session.get(TiresiasAuditLog, row_id)
        dek2 = await envelope.get_or_create_dek(sample_tenant_id, session)
        assert await envelope.decrypt(fetched.encrypted_prompt, dek2) == prompt_text
        assert await envelope.decrypt(fetched.encrypted_completion, dek2) == completion_text


async def test_raw_sqlite_no_plaintext(tmp_data_root, sample_tenant_id):
    settings = TiresiasSettings(TIRESIAS_TENANT_ID=sample_tenant_id, TIRESIAS_DATA_ROOT=tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        api_key = await first_boot(sample_tenant_id, settings, session)
    provider = LocalKEKProvider.from_api_key(api_key)
    envelope = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        enc_prompt = await envelope.encrypt("What is the meaning of life?", dek)
        enc_completion = await envelope.encrypt("42, of course.", dek)
        row = TiresiasAuditLog(id=str(uuid4()), tenant_id=sample_tenant_id,
                               encrypted_prompt=enc_prompt, encrypted_completion=enc_completion)
        session.add(row)
        await session.commit()
    await close_all_engines()
    db_path = tmp_data_root / "tenants" / sample_tenant_id / "tiresias.db"
    con = sqlite3.connect(str(db_path))
    cur = con.execute("SELECT encrypted_prompt, encrypted_completion FROM tiresias_audit_log LIMIT 1")
    row_data = cur.fetchone()
    con.close()
    assert row_data is not None
    raw_p = row_data[0]
    raw_c = row_data[1]
    pb = raw_p if isinstance(raw_p, bytes) else raw_p.encode()
    cb = raw_c if isinstance(raw_c, bytes) else raw_c.encode()
    assert b"meaning of life" not in pb
    assert b"42, of course" not in cb


async def test_dek_rotation_preserves_data(tmp_data_root, sample_tenant_id):
    import os as _os
    settings = TiresiasSettings(TIRESIAS_TENANT_ID=sample_tenant_id, TIRESIAS_DATA_ROOT=tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        api_key = await first_boot(sample_tenant_id, settings, session)
    old_provider = LocalKEKProvider.from_api_key(api_key)
    new_provider = LocalKEKProvider(_os.urandom(32))
    envelope = EnvelopeEncryption(old_provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        enc = await envelope.encrypt("Before rotation", dek)
        row = TiresiasAuditLog(id=str(uuid4()), tenant_id=sample_tenant_id, encrypted_prompt=enc)
        session.add(row)
        await session.commit()
        row_id = row.id
        lic = await session.get(TiresiasLicense, sample_tenant_id)
        old_wrapped = bytes(lic.wrapped_dek)
        await envelope.rotate_dek(sample_tenant_id, old_provider, new_provider, session)
        lic2 = await session.get(TiresiasLicense, sample_tenant_id)
        new_wrapped = bytes(lic2.wrapped_dek)
    assert old_wrapped != new_wrapped
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        fetched = await session.get(TiresiasAuditLog, row_id)
        cached_dek = envelope._dek_cache[sample_tenant_id]
        decrypted = await envelope.decrypt(fetched.encrypted_prompt, cached_dek)
    assert decrypted == "Before rotation"


async def test_retention_purge_preserves_hash_chain(tmp_data_root, sample_tenant_id):
    settings = TiresiasSettings(TIRESIAS_TENANT_ID=sample_tenant_id, TIRESIAS_DATA_ROOT=tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        api_key = await first_boot(sample_tenant_id, settings, session)
    provider = LocalKEKProvider.from_api_key(api_key)
    envelope = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        row = TiresiasAuditLog(
            id=str(uuid4()), tenant_id=sample_tenant_id,
            encrypted_prompt=await envelope.encrypt("sensitive data", dek),
            encrypted_completion=await envelope.encrypt("response", dek),
            request_hash="abc123", response_hash="def456",
        )
        session.add(row)
        await session.commit()
        await session.execute(
            text("UPDATE tiresias_audit_log SET created_at = :ca WHERE id = :id"),
            {"ca": utcnow() - timedelta(days=31), "id": row.id},
        )
        await session.commit()
        row_id = row.id
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        result = await session.get(TiresiasAuditLog, row_id)
    assert result is not None
    assert result.encrypted_prompt is None
    assert result.encrypted_completion is None
    assert result.deleted_at is not None
    assert result.request_hash == "abc123"
    assert result.response_hash == "def456"


async def test_full_lifecycle(tmp_data_root, sample_tenant_id):
    import os as _os
    settings = TiresiasSettings(TIRESIAS_TENANT_ID=sample_tenant_id, TIRESIAS_DATA_ROOT=tmp_data_root)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        api_key = await first_boot(sample_tenant_id, settings, session)
    assert api_key is not None
    provider = LocalKEKProvider.from_api_key(api_key)
    envelope = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        row = TiresiasAuditLog(
            id=str(uuid4()), tenant_id=sample_tenant_id,
            encrypted_prompt=await envelope.encrypt("Full lifecycle prompt", dek),
            encrypted_completion=await envelope.encrypt("Full lifecycle completion", dek),
            request_hash="lifecycle-req", response_hash="lifecycle-resp",
        )
        session.add(row)
        await session.commit()
        row_id = row.id
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        fetched = await session.get(TiresiasAuditLog, row_id)
        dek2 = await envelope.get_or_create_dek(sample_tenant_id, session)
        assert await envelope.decrypt(fetched.encrypted_prompt, dek2) == "Full lifecycle prompt"
    new_provider = LocalKEKProvider(_os.urandom(32))
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        await envelope.rotate_dek(sample_tenant_id, provider, new_provider, session)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        fetched2 = await session.get(TiresiasAuditLog, row_id)
        dek3 = envelope._dek_cache[sample_tenant_id]
        assert await envelope.decrypt(fetched2.encrypted_prompt, dek3) == "Full lifecycle prompt"
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        await session.execute(
            text("UPDATE tiresias_audit_log SET created_at = :ca WHERE id = :id"),
            {"ca": utcnow() - timedelta(days=31), "id": row_id},
        )
        await session.commit()
    engine = await get_engine(sample_tenant_id, tmp_data_root)
    counts = await run_retention_purge(engine, retention_days=30, usage_retention_days=90)
    assert counts["soft_deleted"] >= 1
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        final = await session.get(TiresiasAuditLog, row_id)
    assert final.encrypted_prompt is None
    assert final.encrypted_completion is None
    assert final.deleted_at is not None
    assert final.request_hash == "lifecycle-req"
    assert final.response_hash == "lifecycle-resp"

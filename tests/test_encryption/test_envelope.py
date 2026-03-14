from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tiresias.encryption.aead import make_dek
from tiresias.encryption.envelope import EnvelopeEncryption
from tiresias.encryption.providers.local import LocalKEKProvider
from tiresias.storage.engine import get_engine
from tiresias.storage.schema import TiresiasLicense


def make_provider() -> LocalKEKProvider:
    return LocalKEKProvider(os.urandom(32))


async def get_session(tenant_id: str, data_root: Path) -> AsyncSession:
    engine = await get_engine(tenant_id, data_root)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return Session()


async def test_encrypt_decrypt_roundtrip(tmp_data_root: Path, sample_tenant_id: str):
    provider = make_provider()
    envelope = EnvelopeEncryption(provider)
    dek = make_dek()
    plaintext = "sensitive prompt text"
    ct = await envelope.encrypt(plaintext, dek)
    assert await envelope.decrypt(ct, dek) == plaintext


async def test_get_or_create_dek_creates_license_row(
    tmp_data_root: Path, sample_tenant_id: str
):
    provider = make_provider()
    envelope = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
    assert isinstance(dek, bytes)
    assert len(dek) == 32


async def test_get_or_create_dek_caches_dek(tmp_data_root: Path, sample_tenant_id: str):
    provider = make_provider()
    envelope = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek1 = await envelope.get_or_create_dek(sample_tenant_id, session)
        dek2 = await envelope.get_or_create_dek(sample_tenant_id, session)
    assert dek1 is dek2  # same object from cache


async def test_dek_persisted_and_recoverable(tmp_data_root: Path, sample_tenant_id: str):
    """DEK stored in DB should be recoverable with fresh EnvelopeEncryption."""
    provider = make_provider()
    envelope1 = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek1 = await envelope1.get_or_create_dek(sample_tenant_id, session)

    # Fresh instance, no cache
    envelope2 = EnvelopeEncryption(provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek2 = await envelope2.get_or_create_dek(sample_tenant_id, session)

    assert dek1 == dek2


async def test_rotate_dek_re_wraps_without_data_loss(
    tmp_data_root: Path, sample_tenant_id: str
):
    """After DEK rotation, old ciphertext still decrypts correctly."""
    old_provider = make_provider()
    new_provider = make_provider()
    envelope = EnvelopeEncryption(old_provider)

    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        plaintext = "before rotation"
        ct = await envelope.encrypt(plaintext, dek)

        await envelope.rotate_dek(sample_tenant_id, old_provider, new_provider, session)

        # Verify DEK unchanged — decrypt with cached DEK still works
        decrypted = await envelope.decrypt(ct, envelope._dek_cache[sample_tenant_id])
    assert decrypted == plaintext


async def test_rotate_dek_new_provider_can_unwrap(
    tmp_data_root: Path, sample_tenant_id: str
):
    """After rotation, new provider can unwrap the DEK from DB."""
    old_provider = make_provider()
    new_provider = make_provider()
    envelope = EnvelopeEncryption(old_provider)

    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        original_dek = await envelope.get_or_create_dek(sample_tenant_id, session)
        await envelope.rotate_dek(sample_tenant_id, old_provider, new_provider, session)

    # New envelope with new provider can recover DEK
    envelope2 = EnvelopeEncryption(new_provider)
    async with await get_session(sample_tenant_id, tmp_data_root) as session:
        recovered_dek = await envelope2.get_or_create_dek(sample_tenant_id, session)

    assert recovered_dek == original_dek

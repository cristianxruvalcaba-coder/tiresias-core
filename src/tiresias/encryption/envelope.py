from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from tiresias.encryption.aead import decrypt_field, encrypt_field, make_dek
    from tiresias.encryption.providers.base import KEKProvider
    from tiresias.storage.schema import TiresiasLicense
except ModuleNotFoundError:
    from src.tiresias.encryption.aead import decrypt_field, encrypt_field, make_dek
    from src.tiresias.encryption.providers.base import KEKProvider
    from src.tiresias.storage.schema import TiresiasLicense

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EnvelopeEncryption:
    """Manages per-tenant DEKs with KEK-based envelope encryption.

    Flow:
        plaintext -> encrypt_field(plaintext, dek) -> ciphertext (stored in DB)
        ciphertext -> decrypt_field(ciphertext, dek) -> plaintext

        dek is generated once per tenant, wrapped with KEK, and stored in tiresias_licenses.
        plaintext DEK is cached in process memory for the container lifetime.
    """

    def __init__(self, provider: KEKProvider) -> None:
        self._provider = provider
        self._dek_cache: dict[str, bytes] = {}

    async def get_or_create_dek(self, tenant_id: str, session: AsyncSession) -> bytes:
        """Return cached DEK, or load + unwrap from DB, or create if none exists."""
        if tenant_id in self._dek_cache:
            return self._dek_cache[tenant_id]

        stmt = select(TiresiasLicense).where(TiresiasLicense.tenant_id == tenant_id)
        result = await session.execute(stmt)
        license_row = result.scalar_one_or_none()

        if license_row is not None and license_row.wrapped_dek is not None:
            dek = await self._provider.unwrap_dek(license_row.wrapped_dek)
            self._dek_cache[tenant_id] = dek
            return dek

        # No license row or no wrapped DEK — create one
        return await self.create_dek_for_tenant(tenant_id, session)

    async def create_dek_for_tenant(self, tenant_id: str, session: AsyncSession) -> bytes:
        """Generate a new DEK, wrap it, and store in the license row."""
        dek = make_dek()
        wrapped_dek = await self._provider.wrap_dek(dek)

        stmt = select(TiresiasLicense).where(TiresiasLicense.tenant_id == tenant_id)
        result = await session.execute(stmt)
        license_row = result.scalar_one_or_none()

        if license_row is None:
            license_row = TiresiasLicense(
                tenant_id=tenant_id,
                kek_provider=self._provider.provider_name,
            )
            session.add(license_row)

        license_row.wrapped_dek = wrapped_dek
        license_row.kek_provider = self._provider.provider_name
        await session.commit()

        self._dek_cache[tenant_id] = dek
        return dek

    async def encrypt(self, plaintext: str, dek: bytes) -> bytes:
        """Encrypt plaintext using the provided DEK."""
        return encrypt_field(plaintext, dek)

    async def decrypt(self, blob: bytes, dek: bytes) -> str:
        """Decrypt a ciphertext blob using the provided DEK."""
        return decrypt_field(blob, dek)

    async def rotate_dek(
        self,
        tenant_id: str,
        old_provider: KEKProvider,
        new_provider: KEKProvider,
        session: AsyncSession,
    ) -> None:
        """Re-wrap the existing DEK with a new KEK provider.

        Existing encrypted data in audit_log is NOT touched — the DEK itself
        is unchanged, only its wrapping changes.
        """
        stmt = select(TiresiasLicense).where(TiresiasLicense.tenant_id == tenant_id)
        result = await session.execute(stmt)
        license_row = result.scalar_one_or_none()

        if license_row is None or license_row.wrapped_dek is None:
            raise ValueError(f"No wrapped DEK found for tenant {tenant_id}")

        # Unwrap with old provider
        dek = await old_provider.unwrap_dek(license_row.wrapped_dek)

        # Re-wrap with new provider
        new_wrapped_dek = await new_provider.wrap_dek(dek)

        license_row.wrapped_dek = new_wrapped_dek
        license_row.kek_provider = new_provider.provider_name
        await session.commit()

        # Update cache with new provider context (DEK unchanged)
        self._dek_cache[tenant_id] = dek
        logger.info("DEK rotation complete for tenant %s -> provider %s", tenant_id, new_provider.provider_name)


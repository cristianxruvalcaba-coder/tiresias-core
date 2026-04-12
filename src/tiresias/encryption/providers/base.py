from __future__ import annotations

from abc import ABC, abstractmethod


class KEKProvider(ABC):
    """Abstract base class for Key Encryption Key providers.

    Concrete implementations wrap and unwrap Data Encryption Keys (DEKs)
    using the provider's key material (local env var, AWS KMS, Vault, etc.).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier string for this provider (e.g. 'local', 'aws-kms')."""
        ...

    @abstractmethod
    async def wrap_dek(self, dek: bytes) -> bytes:
        """Encrypt (wrap) a plaintext DEK. Returns opaque wrapped bytes."""
        ...

    @abstractmethod
    async def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        """Decrypt (unwrap) a wrapped DEK. Returns plaintext DEK bytes."""
        ...


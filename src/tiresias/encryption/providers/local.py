from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tiresias.encryption.providers.base import KEKProvider

_HKDF_SALT = b"tiresias-kek-v1"
_HKDF_INFO = b"kek-derivation"
_NONCE_SIZE = 12


class LocalKEKProvider(KEKProvider):
    """KEK provider that keeps the master key in process memory.

    Suitable for dev/single-node deployments. For production, use a cloud KMS provider.
    """

    def __init__(self, kek: bytes) -> None:
        if len(kek) != 32:
            raise ValueError(f"KEK must be exactly 32 bytes, got {len(kek)}")
        self._kek = kek

    @classmethod
    def from_explicit_value(cls, kek_hex_or_base64: str) -> "LocalKEKProvider":
        """Create from a hex- or base64-encoded 32-byte KEK string."""
        raw = kek_hex_or_base64.strip()
        # Try hex first (64 chars)
        try:
            decoded = bytes.fromhex(raw)
            if len(decoded) == 32:
                return cls(decoded)
        except (ValueError, binascii.Error):
            pass
        # Try base64
        try:
            decoded = base64.b64decode(raw)
            if len(decoded) == 32:
                return cls(decoded)
        except Exception:
            pass
        raise ValueError(
            "kek_hex_or_base64 must decode to exactly 32 bytes (hex or base64)"
        )

    @classmethod
    def from_api_key(cls, api_key: str) -> "LocalKEKProvider":
        """Derive a KEK from an API key using HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        )
        kek = hkdf.derive(api_key.encode("utf-8"))
        return cls(kek)

    @property
    def provider_name(self) -> str:
        return "local"

    async def wrap_dek(self, dek: bytes) -> bytes:
        """Encrypt the DEK bytes with the local KEK using AES-256-GCM."""
        nonce = os.urandom(_NONCE_SIZE)
        aesgcm = AESGCM(self._kek)
        ct = aesgcm.encrypt(nonce, dek, None)
        return nonce + ct

    async def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        """Decrypt a wrapped DEK produced by wrap_dek."""
        nonce = wrapped_dek[:_NONCE_SIZE]
        ct = wrapped_dek[_NONCE_SIZE:]
        aesgcm = AESGCM(self._kek)
        return aesgcm.decrypt(nonce, ct, None)

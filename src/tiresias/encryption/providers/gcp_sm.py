"""
GCP Secret Manager KEK Provider for Tiresias.

Uses a master KEK stored in GCP Secret Manager to wrap/unwrap per-tenant DEKs.
The KEK is fetched once at initialization and cached in process memory.

Requires:
  - google-cloud-secret-manager package
  - TIRESIAS_GCP_PROJECT_ID and TIRESIAS_GCP_SECRET_ID env vars
  - Application Default Credentials or Workload Identity on GKE
"""

from __future__ import annotations

import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from tiresias.encryption.providers.base import KEKProvider
except ModuleNotFoundError:
    from src.tiresias.encryption.providers.base import KEKProvider

logger = logging.getLogger(__name__)

_NONCE_SIZE = 12


class GCPSecretManagerKEKProvider(KEKProvider):
    """KEK provider backed by GCP Secret Manager.

    Fetches a 32-byte master KEK from a Secret Manager secret at init time.
    The secret value must be exactly 32 bytes (raw) or 64 hex chars.
    """

    def __init__(self, kek: bytes, project_id: str, secret_id: str) -> None:
        if len(kek) != 32:
            raise ValueError(f"KEK must be exactly 32 bytes, got {len(kek)}")
        self._kek = kek
        self._project_id = project_id
        self._secret_id = secret_id

    @classmethod
    def from_settings(cls, project_id: str, secret_id: str, version: str = "latest") -> "GCPSecretManagerKEKProvider":
        """Fetch KEK from GCP Secret Manager and return a provider instance."""
        try:
            from google.cloud import secretmanager
        except ImportError:
            raise ImportError(
                "google-cloud-secret-manager is required for GCP-SM KEK provider. "
                "Install with: pip install google-cloud-secret-manager"
            )

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"

        logger.info("Fetching KEK from GCP Secret Manager: %s", name)
        response = client.access_secret_version(request={"name": name})
        raw = response.payload.data

        # Support hex-encoded secrets (64 chars -> 32 bytes)
        if len(raw) == 64:
            try:
                raw = bytes.fromhex(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                pass

        if len(raw) != 32:
            raise ValueError(
                f"GCP Secret {secret_id} must contain exactly 32 bytes (or 64 hex chars), "
                f"got {len(raw)} bytes"
            )

        logger.info("KEK loaded from GCP Secret Manager successfully")
        return cls(kek=raw, project_id=project_id, secret_id=secret_id)

    @property
    def provider_name(self) -> str:
        return "gcp-sm"

    async def wrap_dek(self, dek: bytes) -> bytes:
        """Encrypt the DEK with the GCP-sourced KEK using AES-256-GCM."""
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


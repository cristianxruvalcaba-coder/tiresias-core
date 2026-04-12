"""
AWS KMS KEK Provider for Tiresias.

Uses an AWS KMS key to wrap/unwrap per-tenant DEKs via the KMS Encrypt/Decrypt API.
Unlike the local and GCP-SM providers, the KEK never leaves KMS — wrapping and
unwrapping happen server-side in AWS.

Requires:
  - boto3 package
  - TIRESIAS_AWS_KMS_KEY_ID and TIRESIAS_AWS_KMS_REGION env vars
  - IAM credentials (instance role, env vars, or ~/.aws/credentials)
  - For cross-account BYOK: customer grants kms:Encrypt + kms:Decrypt to Saluca's role
"""

from __future__ import annotations

import logging

try:
    from tiresias.encryption.providers.base import KEKProvider
except ModuleNotFoundError:
    from src.tiresias.encryption.providers.base import KEKProvider

logger = logging.getLogger(__name__)


class AWSKMSKEKProvider(KEKProvider):
    """KEK provider backed by AWS KMS.

    The KMS key wraps/unwraps DEKs server-side. The plaintext KEK never
    leaves KMS, making this suitable for BYOK (customer-managed keys).
    """

    def __init__(self, key_id: str, region: str) -> None:
        self._key_id = key_id
        self._region = region
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise ImportError(
                    "boto3 is required for AWS KMS KEK provider. "
                    "Install with: pip install boto3"
                )
            self._client = boto3.client("kms", region_name=self._region)
            logger.info(
                "AWS KMS client initialized: key=%s, region=%s",
                self._key_id[:20] + "...",
                self._region,
            )
        return self._client

    @classmethod
    def from_settings(cls, key_id: str, region: str) -> "AWSKMSKEKProvider":
        """Create provider from key ID and region."""
        return cls(key_id=key_id, region=region)

    @property
    def provider_name(self) -> str:
        return "aws-kms"

    async def wrap_dek(self, dek: bytes) -> bytes:
        """Encrypt the DEK using AWS KMS Encrypt API.

        Returns the CiphertextBlob from KMS (opaque, includes key metadata).
        """
        client = self._get_client()
        response = client.encrypt(
            KeyId=self._key_id,
            Plaintext=dek,
            EncryptionAlgorithm="SYMMETRIC_DEFAULT",
        )
        return response["CiphertextBlob"]

    async def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        """Decrypt a wrapped DEK using AWS KMS Decrypt API.

        The KeyId is embedded in the CiphertextBlob, so KMS knows which key to use.
        This enables automatic key rotation without re-wrapping.
        """
        client = self._get_client()
        response = client.decrypt(
            CiphertextBlob=wrapped_dek,
            EncryptionAlgorithm="SYMMETRIC_DEFAULT",
        )
        return response["Plaintext"]


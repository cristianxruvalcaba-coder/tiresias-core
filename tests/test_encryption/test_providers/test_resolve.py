from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tiresias.config import TiresiasSettings
from tiresias.encryption.providers import resolve_kek_provider
from tiresias.encryption.providers.local import LocalKEKProvider


def settings(**kwargs) -> TiresiasSettings:
    return TiresiasSettings(**kwargs)


def test_resolve_local_explicit():
    kek_hex = os.urandom(32).hex()
    s = settings(TIRESIAS_KEK_PROVIDER="local", TIRESIAS_KEK=kek_hex)
    provider = resolve_kek_provider(s)
    assert isinstance(provider, LocalKEKProvider)
    assert provider.provider_name == "local"


def test_resolve_local_api_key():
    s = settings(TIRESIAS_KEK_PROVIDER="local")
    provider = resolve_kek_provider(s, api_key="test-api-key")
    assert isinstance(provider, LocalKEKProvider)


def test_resolve_local_no_key_raises():
    s = settings(TIRESIAS_KEK_PROVIDER="local")
    with pytest.raises(ValueError, match="requires either"):
        resolve_kek_provider(s, api_key=None)


def test_resolve_aws_kms():
    s = settings(
        TIRESIAS_KEK_PROVIDER="aws-kms",
        TIRESIAS_AWS_KMS_KEY_ID="arn:aws:kms:us-east-1:123456789:key/test",
        TIRESIAS_AWS_KMS_REGION="us-east-1",
    )
    with patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        from tiresias.encryption.providers.aws_kms import AwsKmsProvider
        provider = resolve_kek_provider(s)
    assert isinstance(provider, AwsKmsProvider)
    assert provider.provider_name == "aws-kms"


def test_resolve_aws_kms_missing_key_id():
    s = settings(
        TIRESIAS_KEK_PROVIDER="aws-kms",
        TIRESIAS_AWS_KMS_REGION="us-east-1",
    )
    with pytest.raises(ValueError, match="KEY_ID"):
        resolve_kek_provider(s)


def test_resolve_aws_kms_missing_region():
    s = settings(
        TIRESIAS_KEK_PROVIDER="aws-kms",
        TIRESIAS_AWS_KMS_KEY_ID="some-key-id",
    )
    with pytest.raises(ValueError, match="REGION"):
        resolve_kek_provider(s)


def test_resolve_vault():
    s = settings(
        TIRESIAS_KEK_PROVIDER="hashicorp-vault",
        TIRESIAS_VAULT_URL="http://localhost:8200",
        TIRESIAS_VAULT_TOKEN="root",
    )
    with patch("hvac.Client") as mock_hvac:
        mock_hvac.return_value = MagicMock()
        from tiresias.encryption.providers.vault import VaultProvider
        provider = resolve_kek_provider(s)
    assert isinstance(provider, VaultProvider)
    assert provider.provider_name == "hashicorp-vault"


def test_resolve_vault_missing_url():
    s = settings(
        TIRESIAS_KEK_PROVIDER="hashicorp-vault",
        TIRESIAS_VAULT_TOKEN="root",
    )
    with pytest.raises(ValueError, match="URL"):
        resolve_kek_provider(s)


def test_resolve_azure():
    s = settings(
        TIRESIAS_KEK_PROVIDER="azure-kv",
        TIRESIAS_AZURE_VAULT_URL="https://myvault.vault.azure.net",
        TIRESIAS_AZURE_KEY_NAME="my-key",
    )
    with (
        patch("azure.identity.DefaultAzureCredential"),
        patch("azure.keyvault.keys.KeyClient") as mock_kc,
        patch("azure.keyvault.keys.crypto.CryptographyClient"),
    ):
        mock_kc.return_value.get_key.return_value = MagicMock()
        from tiresias.encryption.providers.azure_kv import AzureKeyVaultProvider
        provider = resolve_kek_provider(s)
    assert isinstance(provider, AzureKeyVaultProvider)
    assert provider.provider_name == "azure-kv"


def test_resolve_azure_missing_vault_url():
    s = settings(
        TIRESIAS_KEK_PROVIDER="azure-kv",
        TIRESIAS_AZURE_KEY_NAME="my-key",
    )
    with pytest.raises(ValueError, match="URL"):
        resolve_kek_provider(s)


def test_resolve_gcp():
    s = settings(
        TIRESIAS_KEK_PROVIDER="gcp-sm",
        TIRESIAS_GCP_PROJECT_ID="my-project",
        TIRESIAS_GCP_SECRET_ID="my-secret",
    )
    with patch("google.cloud.secretmanager.SecretManagerServiceClient"):
        from tiresias.encryption.providers.gcp_sm import GcpSecretManagerProvider
        provider = resolve_kek_provider(s)
    assert isinstance(provider, GcpSecretManagerProvider)
    assert provider.provider_name == "gcp-sm"


def test_resolve_gcp_missing_project():
    s = settings(
        TIRESIAS_KEK_PROVIDER="gcp-sm",
        TIRESIAS_GCP_SECRET_ID="my-secret",
    )
    with pytest.raises(ValueError, match="PROJECT"):
        resolve_kek_provider(s)


async def test_bootstrap_uses_resolver(tmp_data_root, sample_tenant_id):
    """first_boot should call resolve_kek_provider."""
    from pathlib import Path
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    from tiresias.storage.engine import get_engine
    from tiresias.bootstrap import first_boot

    s = settings(
        TIRESIAS_TENANT_ID=sample_tenant_id,
        TIRESIAS_DATA_ROOT=tmp_data_root,
        TIRESIAS_KEK_PROVIDER="local",
    )

    with patch("tiresias.bootstrap.resolve_kek_provider", wraps=resolve_kek_provider) as mock_resolver:
        engine = await get_engine(sample_tenant_id, tmp_data_root)
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            api_key = await first_boot(sample_tenant_id, s, session)

    assert api_key is not None
    assert mock_resolver.called
    call_args = mock_resolver.call_args
    assert call_args[0][0] == s  # first positional arg is settings

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tiresias.config import TiresiasSettings
from tiresias.storage.engine import close_all_engines


FIXED_TENANT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


@pytest.fixture
def tmp_data_root(tmp_path: Path) -> Path:
    """Temporary data root directory for tests."""
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    return data_root


@pytest.fixture
def sample_tenant_id() -> str:
    """Fixed tenant UUID for test determinism."""
    return FIXED_TENANT_ID


@pytest.fixture
def test_settings(tmp_data_root: Path, sample_tenant_id: str) -> TiresiasSettings:
    """TiresiasSettings configured for testing."""
    return TiresiasSettings(
        TIRESIAS_TENANT_ID=sample_tenant_id,
        TIRESIAS_DATA_ROOT=tmp_data_root,
    )


@pytest.fixture(autouse=True)
async def cleanup_engines():
    """Ensure all SQLAlchemy engines are disposed after each test."""
    yield
    await close_all_engines()

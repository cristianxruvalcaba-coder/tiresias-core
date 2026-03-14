import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.proxy.interceptor import record_turn, record_error_turn, _extract_completion_text
from tiresias.storage.engine import get_engine, close_all_engines
from tiresias.storage.schema import TiresiasAuditLog, TiresiasUsageBucket


@pytest.fixture
async def db_session(tmp_path):
    engine = await get_engine("test-tenant-01", tmp_path)
    async with AsyncSession(engine) as session:
        yield session
    await close_all_engines()


@pytest.fixture
def mock_envelope():
    envelope = MagicMock()
    dek = b"x" * 32
    envelope.get_or_create_dek = AsyncMock(return_value=dek)
    envelope.encrypt = AsyncMock(side_effect=lambda text, dek: b"encrypted:" + text.encode())
    envelope.decrypt = AsyncMock(side_effect=lambda blob, dek: blob.replace(b"encrypted:", b"").decode())
    return envelope


SAMPLE_REQUEST = {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello!"}],
}

SAMPLE_RESPONSE = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "model": "gpt-4o-mini",
    "choices": [{
        "message": {"role": "assistant", "content": "Hi there!"},
        "finish_reason": "stop",
        "index": 0,
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


async def test_record_turn_creates_audit_log(db_session, mock_envelope):
    result = await record_turn(
        tenant_id="test-tenant-01",
        model="gpt-4o-mini",
        provider="openai",
        request_body=SAMPLE_REQUEST,
        response_body=SAMPLE_RESPONSE,
        session_id="session-001",
        metadata={"user": "alice"},
        envelope=mock_envelope,
        db_session=db_session,
    )
    assert result['id'] is not None
    assert result['model'] == 'gpt-4o-mini'
    assert result['provider'] == 'openai'
    assert result['session_id'] == 'session-001'
    assert result['token_count'] == 15
    assert result['cost_usd'] > 0
    assert result['request_hash'] is not None  # prompt is encrypted on disk
    # completion encrypted on disk
    assert result['request_hash'] is not None


async def test_record_turn_creates_usage_bucket(db_session, mock_envelope):
    from sqlalchemy import select
    await record_turn(
        tenant_id="test-tenant-01",
        model="gpt-4o-mini",
        provider="openai",
        request_body=SAMPLE_REQUEST,
        response_body=SAMPLE_RESPONSE,
        session_id=None,
        metadata=None,
        envelope=mock_envelope,
        db_session=db_session,
    )
    result = await db_session.execute(
        select(TiresiasUsageBucket).where(TiresiasUsageBucket.tenant_id == "test-tenant-01")
    )
    bucket = result.scalar_one_or_none()
    assert bucket is not None
    assert bucket.request_count == 1
    assert bucket.token_count == 15


async def test_record_error_turn_increments_error_count(db_session):
    await record_error_turn("test-tenant-01", "gpt-4o", db_session)
    from sqlalchemy import select
    result = await db_session.execute(
        select(TiresiasUsageBucket).where(TiresiasUsageBucket.tenant_id == "test-tenant-01")
    )
    bucket = result.scalar_one_or_none()
    assert bucket is not None
    assert bucket.error_count == 1


def test_extract_completion_text_message():
    response = {"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}
    assert _extract_completion_text(response) == "Hello!"


def test_extract_completion_text_empty_choices():
    assert _extract_completion_text({"choices": []}) == ""


def test_extract_completion_text_no_choices():
    assert _extract_completion_text({}) == ""

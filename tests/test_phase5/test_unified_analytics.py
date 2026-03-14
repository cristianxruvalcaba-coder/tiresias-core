from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.engine import get_engine, close_all_engines
from tiresias.storage.schema import TiresiasAuditLog, TiresiasApiLog
from tiresias.analytics.unified import get_unified_analytics


@pytest.fixture
async def db_session(tmp_path: Path):
    tenant_id = "unified-test-tenant"
    engine = await get_engine(tenant_id, tmp_path)
    async with AsyncSession(engine) as session:
        yield session, tenant_id
    await close_all_engines()


async def test_unified_empty(db_session):
    session, tenant_id = db_session
    result = await get_unified_analytics(tenant_id, session)
    assert result["tenant_id"] == tenant_id
    assert result["window_hours"] == 24
    assert result["llm"]["request_count"] == 0
    assert result["api"]["request_count"] == 0
    assert result["totals"]["request_count"] == 0
    assert result["totals"]["cost_usd_total"] == 0.0


async def test_unified_with_llm_data(db_session):
    session, tenant_id = db_session
    # Insert an LLM audit log entry
    row = TiresiasAuditLog(
        id=str(uuid4()),
        tenant_id=tenant_id,
        model="gpt-4o-mini",
        provider="openai",
        token_count=100,
        cost_usd=0.0002,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()

    result = await get_unified_analytics(tenant_id, session)
    assert result["llm"]["request_count"] == 1
    assert result["llm"]["total_tokens"] == 100
    assert result["llm"]["cost_usd_total"] == pytest.approx(0.0002)
    assert len(result["llm"]["by_model"]) == 1
    assert result["llm"]["by_model"][0]["model"] == "gpt-4o-mini"


async def test_unified_with_api_data(db_session):
    session, tenant_id = db_session
    # Insert API log entry
    row = TiresiasApiLog(
        id=str(uuid4()),
        tenant_id=tenant_id,
        api_service="twilio",
        method="POST",
        path="/2010-04-01/Accounts/AC123/Messages",
        path_pattern="/2010-04-01/Accounts/{id}/Messages",
        status_code=201,
        latency_ms=85.0,
        request_size=256,
        response_size=512,
        cost_usd=0.0079,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()

    result = await get_unified_analytics(tenant_id, session)
    assert result["api"]["request_count"] == 1
    assert result["api"]["cost_usd_total"] == pytest.approx(0.0079)
    assert result["api"]["error_count"] == 0


async def test_unified_combined(db_session):
    session, tenant_id = db_session

    llm_row = TiresiasAuditLog(
        id=str(uuid4()),
        tenant_id=tenant_id,
        model="gpt-4o",
        provider="openai",
        token_count=500,
        cost_usd=0.005,
        created_at=datetime.now(timezone.utc),
    )
    api_row = TiresiasApiLog(
        id=str(uuid4()),
        tenant_id=tenant_id,
        api_service="stripe",
        method="POST",
        path="/v1/charges",
        path_pattern="/v1/charges",
        status_code=200,
        latency_ms=120.0,
        request_size=100,
        response_size=200,
        cost_usd=0.0,
        created_at=datetime.now(timezone.utc),
    )
    session.add(llm_row)
    session.add(api_row)
    await session.commit()

    result = await get_unified_analytics(tenant_id, session)
    assert result["totals"]["request_count"] == 2
    assert result["totals"]["cost_usd_total"] == pytest.approx(0.005)
    assert result["llm"]["request_count"] == 1
    assert result["api"]["request_count"] == 1


async def test_unified_api_error_count(db_session):
    session, tenant_id = db_session
    # 2 success, 1 error
    for status in [200, 200, 404]:
        row = TiresiasApiLog(
            id=str(uuid4()),
            tenant_id=tenant_id,
            api_service="stripe",
            method="GET",
            path="/v1/charges",
            path_pattern="/v1/charges",
            status_code=status,
            latency_ms=50.0,
            request_size=0,
            response_size=0,
            cost_usd=0.0,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
    await session.commit()

    result = await get_unified_analytics(tenant_id, session)
    assert result["api"]["error_count"] == 1
    assert result["api"]["request_count"] == 3


async def test_unified_custom_window(db_session):
    session, tenant_id = db_session
    result = await get_unified_analytics(tenant_id, session, hours=72)
    assert result["window_hours"] == 72

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.storage.engine import get_engine, close_all_engines
from tiresias.storage.schema import TiresiasApiLog, TiresiasApiEndpointBucket
from tiresias.analytics.api_telemetry import (
    get_endpoint_metrics,
    get_error_breakdown,
    get_cost_by_endpoint,
)


@pytest.fixture
async def db_session(tmp_path: Path):
    tenant_id = "test-telemetry-tenant"
    engine = await get_engine(tenant_id, tmp_path)
    async with AsyncSession(engine) as session:
        yield session, tenant_id
    await close_all_engines()


async def _insert_api_log(
    session: AsyncSession,
    tenant_id: str,
    *,
    method: str = "GET",
    path: str = "/v1/charges",
    path_pattern: str = "/v1/charges",
    status_code: int = 200,
    latency_ms: float = 100.0,
    api_service: str | None = "stripe",
    cost_usd: float = 0.0,
):
    row = TiresiasApiLog(
        id=str(uuid4()),
        tenant_id=tenant_id,
        api_service=api_service,
        method=method,
        path=path,
        path_pattern=path_pattern,
        status_code=status_code,
        latency_ms=latency_ms,
        request_size=100,
        response_size=200,
        cost_usd=cost_usd,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()


async def _insert_bucket(
    session: AsyncSession,
    tenant_id: str,
    *,
    method: str = "GET",
    path_pattern: str = "/v1/charges",
    api_service: str | None = "stripe",
    request_count: int = 5,
    error_count: int = 1,
    latency_sum_ms: float = 500.0,
    latency_min_ms: float = 80.0,
    latency_max_ms: float = 150.0,
    cost_usd: float = 0.0,
):
    from tiresias.storage.schema import TiresiasApiEndpointBucket
    bucket = TiresiasApiEndpointBucket(
        id=str(uuid4()),
        tenant_id=tenant_id,
        api_service=api_service,
        method=method,
        path_pattern=path_pattern,
        bucket_hour=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
        request_count=request_count,
        error_count=error_count,
        latency_sum_ms=latency_sum_ms,
        latency_min_ms=latency_min_ms,
        latency_max_ms=latency_max_ms,
        cost_usd=cost_usd,
    )
    session.add(bucket)
    await session.commit()


async def test_get_endpoint_metrics_empty(db_session):
    session, tenant_id = db_session
    result = await get_endpoint_metrics(tenant_id, session)
    assert result == []


async def test_get_endpoint_metrics_with_data(db_session):
    session, tenant_id = db_session
    await _insert_bucket(session, tenant_id, request_count=10, error_count=2, latency_sum_ms=1000.0)
    result = await get_endpoint_metrics(tenant_id, session)
    assert len(result) == 1
    m = result[0]
    assert m["request_count"] == 10
    assert m["error_count"] == 2
    assert m["error_rate"] == pytest.approx(0.2)
    assert m["latency_avg_ms"] == pytest.approx(100.0)


async def test_get_endpoint_metrics_filter_by_service(db_session):
    session, tenant_id = db_session
    await _insert_bucket(session, tenant_id, api_service="stripe", path_pattern="/v1/charges")
    await _insert_bucket(session, tenant_id, api_service="twilio", path_pattern="/2010/Messages")
    stripe_result = await get_endpoint_metrics(tenant_id, session, api_service="stripe")
    assert len(stripe_result) == 1
    assert stripe_result[0]["api_service"] == "stripe"


async def test_get_error_breakdown_empty(db_session):
    session, tenant_id = db_session
    result = await get_error_breakdown(tenant_id, session)
    assert result == []


async def test_get_error_breakdown_with_errors(db_session):
    session, tenant_id = db_session
    await _insert_api_log(session, tenant_id, status_code=429)
    await _insert_api_log(session, tenant_id, status_code=429)
    await _insert_api_log(session, tenant_id, status_code=500)
    await _insert_api_log(session, tenant_id, status_code=200)  # should not appear
    result = await get_error_breakdown(tenant_id, session)
    assert len(result) >= 2
    codes = {r["status_code"] for r in result}
    assert 429 in codes
    assert 500 in codes
    assert 200 not in codes


async def test_get_cost_by_endpoint_empty(db_session):
    session, tenant_id = db_session
    result = await get_cost_by_endpoint(tenant_id, session)
    assert result == []


async def test_get_cost_by_endpoint_with_data(db_session):
    session, tenant_id = db_session
    await _insert_api_log(session, tenant_id, cost_usd=0.0079, api_service="twilio",
                          path_pattern="/2010/Messages")
    await _insert_api_log(session, tenant_id, cost_usd=0.0079, api_service="twilio",
                          path_pattern="/2010/Messages")
    result = await get_cost_by_endpoint(tenant_id, session)
    assert len(result) >= 1
    twilio = next((r for r in result if r["api_service"] == "twilio"), None)
    assert twilio is not None
    assert twilio["cost_usd_total"] == pytest.approx(0.0158)
    assert twilio["request_count"] == 2

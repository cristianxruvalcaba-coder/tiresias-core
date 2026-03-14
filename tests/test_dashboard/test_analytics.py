"""Tests for dashboard analytics endpoints with seeded data."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.bootstrap import hash_api_key
from tiresias.config import TiresiasSettings
from tiresias.dashboard.app import create_dashboard_app
from tiresias.providers.health import HealthTracker
from tiresias.storage.engine import close_all_engines, get_engine
from tiresias.storage.schema import TiresiasAuditLog, TiresiasLicense

API_KEY = "analytics-test-key-xyz"
TENANT_ID = "test-analytics-tenant"


@pytest.fixture
def settings(tmp_path):
    return TiresiasSettings(
        TIRESIAS_TENANT_ID=TENANT_ID,
        TIRESIAS_DATA_ROOT=str(tmp_path),
        TIRESIAS_KEK_PROVIDER="local",
        TIRESIAS_KEK="45286db43824c34cf7865ae507579d754ffefd59816432d5c5513e25bb7995a4",
    )


async def _seed_data(settings):
    engine = await get_engine(settings.tenant_id, settings.data_root)
    now = datetime.now(timezone.utc)

    async with AsyncSession(engine) as session:
        license_row = TiresiasLicense(
            tenant_id=TENANT_ID,
            api_key_hash=hash_api_key(API_KEY),
        )
        session.add(license_row)

        for i in range(5):
            created = now - timedelta(hours=i * 6)
            meta = json.dumps({"latency_ms": 100 + i * 50, "status_code": 200})
            row = TiresiasAuditLog(
                tenant_id=TENANT_ID,
                model="gpt-4o",
                provider="openai",
                token_count=100 + i * 10,
                cost_usd=0.001 * (i + 1),
                session_id="session-alpha",
                metadata_json=meta,
                created_at=created,
            )
            session.add(row)

        for i in range(3):
            created = now - timedelta(hours=i * 12 + 1)
            meta = json.dumps({"latency_ms": 200 + i * 30, "status_code": 200})
            row = TiresiasAuditLog(
                tenant_id=TENANT_ID,
                model="claude-sonnet-4-6",
                provider="anthropic",
                token_count=200 + i * 20,
                cost_usd=0.002 * (i + 1),
                session_id="session-beta",
                metadata_json=meta,
                created_at=created,
            )
            session.add(row)

        err_meta = json.dumps({"status_code": 500, "error": True})
        err_row = TiresiasAuditLog(
            tenant_id=TENANT_ID,
            model="gpt-4o",
            provider="openai",
            token_count=0,
            cost_usd=0.0,
            session_id="session-alpha",
            metadata_json=err_meta,
            created_at=now - timedelta(hours=1),
        )
        session.add(err_row)

        await session.commit()


@pytest.fixture
async def client(settings):
    await _seed_data(settings)
    health = HealthTracker(["openai", "anthropic"])
    app = create_dashboard_app(settings=settings, health_tracker=health)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    await close_all_engines()


def auth_headers():
    return {"X-Tiresias-Api-Key": API_KEY}


@pytest.mark.asyncio
async def test_spend_total(client):
    resp = await client.get("/dash/v1/spend", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    # 5 + 3 + 1 = 9 rows
    assert data["request_count"] == 9
    assert data["total_cost_usd"] > 0
    assert "start" in data
    assert "end" in data


@pytest.mark.asyncio
async def test_requests_per_day(client):
    resp = await client.get("/dash/v1/requests", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    for entry in data:
        assert "date" in entry
        assert "request_count" in entry
        assert entry["request_count"] > 0


@pytest.mark.asyncio
async def test_latency_percentiles(client):
    resp = await client.get("/dash/v1/latency", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    providers = {d["provider"] for d in data}
    assert "openai" in providers
    assert "anthropic" in providers

    for entry in data:
        assert "p50_ms" in entry
        assert "p95_ms" in entry
        assert "p99_ms" in entry
        assert entry["p50_ms"] <= entry["p95_ms"] <= entry["p99_ms"]


@pytest.mark.asyncio
async def test_error_rates(client):
    resp = await client.get("/dash/v1/errors", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    openai_entry = next((d for d in data if d["provider"] == "openai"), None)
    assert openai_entry is not None
    assert openai_entry["error_count"] >= 1
    assert 0 < openai_entry["error_rate"] <= 1.0
    assert "500" in openai_entry["status_codes"]


@pytest.mark.asyncio
async def test_top_sessions(client):
    resp = await client.get("/dash/v1/sessions/top", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    costs = [d["total_cost_usd"] for d in data]
    assert costs == sorted(costs, reverse=True)
    session_ids = {d["session_id"] for d in data}
    assert "session-alpha" in session_ids
    assert "session-beta" in session_ids


@pytest.mark.asyncio
async def test_top_sessions_limit(client):
    resp = await client.get("/dash/v1/sessions/top?limit=1", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


@pytest.mark.asyncio
async def test_provider_health(client):
    resp = await client.get("/dash/v1/providers/health", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "cascade" in data
    for p in data["providers"]:
        assert p["status"] in ("up", "degraded", "down")
        assert "name" in p
        assert "is_healthy" in p


@pytest.mark.asyncio
async def test_provider_health_simulated_outage(settings):
    """Simulate provider outage: health reflects down status."""
    await _seed_data(settings)
    health = HealthTracker(["openai", "anthropic"])
    for _ in range(3):
        health.record_error("openai")

    app = create_dashboard_app(settings=settings, health_tracker=health)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.get("/dash/v1/providers/health", headers=auth_headers())
    await close_all_engines()

    assert resp.status_code == 200
    data = resp.json()
    openai_status = next(p for p in data["providers"] if p["name"] == "openai")
    assert openai_status["status"] == "down"
    anthropic_status = next(p for p in data["providers"] if p["name"] == "anthropic")
    assert anthropic_status["status"] == "up"


@pytest.mark.asyncio
async def test_spend_accuracy(settings):
    """Spend total must be accurate to within 1% of sum of individual costs."""
    await _seed_data(settings)
    health = HealthTracker(["openai"])
    app = create_dashboard_app(settings=settings, health_tracker=health)

    expected = sum([0.001 * (i + 1) for i in range(5)]) + sum([0.002 * (i + 1) for i in range(3)])

    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.get("/dash/v1/spend", headers=auth_headers())
    await close_all_engines()

    data = resp.json()
    actual = data["total_cost_usd"]
    diff_pct = abs(actual - expected) / expected * 100
    assert diff_pct < 1.0, f"Spend {actual} differs from expected {expected} by {diff_pct:.2f}%"

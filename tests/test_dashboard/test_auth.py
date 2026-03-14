"""Tests for dashboard API key authentication middleware."""
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tiresias.bootstrap import hash_api_key
from tiresias.config import TiresiasSettings
from tiresias.dashboard.app import create_dashboard_app
from tiresias.providers.health import HealthTracker
from tiresias.storage.engine import close_all_engines, get_engine
from tiresias.storage.schema import TiresiasLicense


@pytest.fixture
def dash_settings(tmp_path):
    return TiresiasSettings(
        TIRESIAS_TENANT_ID="test-dash-auth",
        TIRESIAS_DATA_ROOT=str(tmp_path),
        TIRESIAS_KEK_PROVIDER="local",
        TIRESIAS_KEK="45286db43824c34cf7865ae507579d754ffefd59816432d5c5513e25bb7995a4",
    )


@pytest.fixture
async def seeded_db(dash_settings):
    engine = await get_engine(dash_settings.tenant_id, dash_settings.data_root)
    api_key = "test-api-key-abc123"
    async with AsyncSession(engine) as session:
        license_row = TiresiasLicense(
            tenant_id=dash_settings.tenant_id,
            api_key_hash=hash_api_key(api_key),
        )
        session.add(license_row)
        await session.commit()
    return api_key


@pytest.fixture
async def dash_client(dash_settings, seeded_db):
    health = HealthTracker(["openai"])
    app = create_dashboard_app(settings=dash_settings, health_tracker=health)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, seeded_db
    await close_all_engines()


@pytest.mark.asyncio
async def test_health_no_auth(dash_client):
    client, _ = dash_client
    resp = await client.get("/dash/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_spend_missing_key(dash_client):
    client, _ = dash_client
    resp = await client.get("/dash/v1/spend")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_spend_wrong_key(dash_client):
    client, _ = dash_client
    resp = await client.get("/dash/v1/spend", headers={"X-Tiresias-Api-Key": "wrong-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_spend_correct_key(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/spend", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost_usd" in data


@pytest.mark.asyncio
async def test_bearer_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get(
        "/dash/v1/spend",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_requests_endpoint_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/requests", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_latency_endpoint_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/latency", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_errors_endpoint_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/errors", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_top_sessions_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/sessions/top", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_provider_health_auth(dash_client):
    client, api_key = dash_client
    resp = await client.get("/dash/v1/providers/health", headers={"X-Tiresias-Api-Key": api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data

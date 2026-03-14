"""Tests for static file serving."""
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
def settings(tmp_path):
    return TiresiasSettings(
        TIRESIAS_TENANT_ID="test-static-tenant",
        TIRESIAS_DATA_ROOT=str(tmp_path),
        TIRESIAS_KEK_PROVIDER="local",
        TIRESIAS_KEK="45286db43824c34cf7865ae507579d754ffefd59816432d5c5513e25bb7995a4",
    )


@pytest.fixture
async def static_client(settings):
    engine = await get_engine(settings.tenant_id, settings.data_root)
    async with AsyncSession(engine) as session:
        row = TiresiasLicense(
            tenant_id=settings.tenant_id,
            api_key_hash=hash_api_key("static-test-key"),
        )
        session.add(row)
        await session.commit()

    health = HealthTracker(["openai"])
    app = create_dashboard_app(settings=settings, health_tracker=health)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    await close_all_engines()


@pytest.mark.asyncio
async def test_index_html_served(static_client):
    resp = await static_client.get("/index.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Tiresias" in resp.text


@pytest.mark.asyncio
async def test_app_js_served(static_client):
    resp = await static_client.get("/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_root_redirects_to_index(static_client):
    resp = await static_client.get("/", follow_redirects=True)
    assert resp.status_code == 200

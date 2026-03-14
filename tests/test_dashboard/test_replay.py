"""Tests for session replay endpoint."""
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

API_KEY = "replay-test-key-abc"
TENANT_ID = "test-replay-tenant"
SESSION_ID = "replay-session-001"


@pytest.fixture
def settings(tmp_path):
    return TiresiasSettings(
        TIRESIAS_TENANT_ID=TENANT_ID,
        TIRESIAS_DATA_ROOT=str(tmp_path),
        TIRESIAS_KEK_PROVIDER="local",
        TIRESIAS_KEK="45286db43824c34cf7865ae507579d754ffefd59816432d5c5513e25bb7995a4",
    )


async def _seed_session(settings):
    engine = await get_engine(settings.tenant_id, settings.data_root)
    now = datetime.now(timezone.utc)
    async with AsyncSession(engine) as session:
        license_row = TiresiasLicense(
            tenant_id=TENANT_ID,
            api_key_hash=hash_api_key(API_KEY),
        )
        session.add(license_row)

        for i in range(3):
            row = TiresiasAuditLog(
                tenant_id=TENANT_ID,
                model="gpt-4o",
                provider="openai",
                token_count=50 + i * 10,
                cost_usd=0.001 * (i + 1),
                session_id=SESSION_ID,
                created_at=now - timedelta(minutes=(3 - i) * 5),
                metadata_json=json.dumps({"turn": i}),
            )
            session.add(row)

        await session.commit()


@pytest.fixture
async def client(settings):
    await _seed_session(settings)
    health = HealthTracker(["openai"])
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
async def test_session_replay_returns_turns(client):
    resp = await client.get(
        f"/dash/v1/sessions/{SESSION_ID}/replay",
        headers=auth_headers()
    )
    assert resp.status_code == 200
    turns = resp.json()
    assert len(turns) == 3


@pytest.mark.asyncio
async def test_session_replay_turn_structure(client):
    resp = await client.get(
        f"/dash/v1/sessions/{SESSION_ID}/replay",
        headers=auth_headers()
    )
    assert resp.status_code == 200
    turns = resp.json()
    for turn in turns:
        assert "id" in turn
        assert "model" in turn
        assert "provider" in turn
        assert "token_count" in turn
        assert "cost_usd" in turn
        assert "created_at" in turn
        assert "prompt" in turn
        assert "completion" in turn
        assert "metadata" in turn


@pytest.mark.asyncio
async def test_session_replay_ordered_by_time(client):
    resp = await client.get(
        f"/dash/v1/sessions/{SESSION_ID}/replay",
        headers=auth_headers()
    )
    turns = resp.json()
    timestamps = [t["created_at"] for t in turns]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_session_replay_not_found(client):
    resp = await client.get(
        "/dash/v1/sessions/nonexistent-session-id/replay",
        headers=auth_headers()
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_replay_no_auth(client):
    resp = await client.get(f"/dash/v1/sessions/{SESSION_ID}/replay")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_session_replay_metadata_parsed(client):
    resp = await client.get(
        f"/dash/v1/sessions/{SESSION_ID}/replay",
        headers=auth_headers()
    )
    turns = resp.json()
    for turn in turns:
        assert isinstance(turn["metadata"], dict)

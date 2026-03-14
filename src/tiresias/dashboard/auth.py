"""Dashboard API key authentication.

NOTE: This module does NOT import from tiresias.dashboard.app to avoid circular imports.
The auth dependency is wired in app.py via a closure that injects settings + engine.
"""
import hashlib
import hmac
import logging

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tiresias.bootstrap import verify_api_key
from tiresias.storage.schema import TiresiasLicense

logger = logging.getLogger(__name__)


def make_api_key_dependency(get_settings_fn, get_engine_fn):
    """Factory: return an async FastAPI dependency that validates the API key.

    Parameters
    ----------
    get_settings_fn : callable
        No-arg callable that returns TiresiasSettings.
    get_engine_fn : async callable
        No-arg async callable that returns AsyncEngine.
    """

    async def require_api_key(request: Request) -> str:
        # Extract key from X-Tiresias-Api-Key header or Authorization: Bearer
        api_key = request.headers.get("x-tiresias-api-key")
        if not api_key:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                api_key = auth[7:].strip()

        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="Missing API key. Provide X-Tiresias-Api-Key header.",
            )

        cfg = get_settings_fn()
        engine = await get_engine_fn()

        async with AsyncSession(engine) as session:
            stmt = select(TiresiasLicense).where(
                TiresiasLicense.tenant_id == cfg.tenant_id
            )
            result = await session.execute(stmt)
            license_row = result.scalar_one_or_none()

        if license_row is None or license_row.api_key_hash is None:
            raise HTTPException(status_code=401, detail="Tenant not initialized.")

        if not verify_api_key(api_key, license_row.api_key_hash):
            raise HTTPException(status_code=401, detail="Invalid API key.")

        return api_key

    return require_api_key

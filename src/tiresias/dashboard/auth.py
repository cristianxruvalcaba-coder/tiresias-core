"""Dashboard API key authentication.

NOTE: This module does NOT import from tiresias.dashboard.app to avoid circular imports.
The auth dependency is wired in app.py via a closure that injects settings + engine.

Supports three authentication methods (checked in order):
  1. X-SoulKey header — validated against SoulAuth's session verification endpoint
  2. X-Tiresias-Api-Key header — validated against tenant's stored API key hash
  3. Authorization: Bearer <token> — treated as Tiresias API key
"""
import hashlib
import hmac
import logging
import os

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tiresias.bootstrap import verify_api_key
from tiresias.storage.schema import TiresiasLicense

logger = logging.getLogger(__name__)

# SoulAuth base URL for X-SoulKey session verification
_SOULAUTH_URL = os.environ.get("SOULAUTH_URL", "http://soulauth-mssp:8000")


async def _verify_soulkey(soul_key: str) -> bool:
    """Verify an X-SoulKey against SoulAuth's session verification endpoint.

    Returns True if the session is valid, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(
                f"{_SOULAUTH_URL}/v1/auth/local/session/verify",
                headers={"Authorization": f"Bearer {soul_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("valid", False) or data.get("status") == "active"
            return False
    except Exception as exc:
        logger.warning("soulkey.verification_failed", error=str(exc))
        return False


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


def make_auth_dependency(get_settings_fn, get_engine_fn):
    """Factory: return an async FastAPI dependency that accepts X-SoulKey OR API key.

    Tries X-SoulKey first (portal session tokens), then falls back to
    X-Tiresias-Api-Key / Authorization: Bearer (programmatic API keys).

    Parameters
    ----------
    get_settings_fn : callable
        No-arg callable that returns TiresiasSettings.
    get_engine_fn : async callable
        No-arg async callable that returns AsyncEngine.
    """
    _api_key_dep = make_api_key_dependency(get_settings_fn, get_engine_fn)

    async def require_auth(request: Request) -> str:
        # --- Path 1: X-SoulKey (portal session token) ---
        soul_key = request.headers.get("x-soulkey")
        if soul_key:
            if await _verify_soulkey(soul_key):
                return soul_key
            # If SoulKey was provided but invalid, reject immediately
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired SoulKey session.",
            )

        # --- Path 2: fall through to API key validation ---
        return await _api_key_dep(request)

    return require_auth


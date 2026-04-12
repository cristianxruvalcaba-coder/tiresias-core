"""SOP compliance evaluation endpoint."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tiresias.auth.pdp import PolicyDecisionPoint
from tiresias.audit.logger import AuditLogger
from tiresias.config import TiresiasSettings
from tiresias.policy.loader import PolicyLoader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class EvaluateSOPRequest(BaseModel):
    soulkey: str  # Agent identity key
    sop_id: str  # e.g. "SOP-011"
    action: str  # e.g. "generate_report"
    context: dict[str, Any] = {}


class EvaluateSOPResponse(BaseModel):
    decision: str
    sop_id: str
    action: str
    reason: str
    audit_ref: str
    approval_id: str | None = None


@router.post("/evaluate-sop", response_model=EvaluateSOPResponse)
async def evaluate_sop(request: EvaluateSOPRequest) -> EvaluateSOPResponse:
    """Evaluate SOP compliance for an agent action.

    Returns grant/deny/queue_for_approval with audit trail.
    """
    # Resolve identity from soulkey
    identity = await _resolve_identity(request.soulkey)
    if not identity:
        raise HTTPException(status_code=401, detail="Invalid soulkey")

    tenant = identity.get("tenant", "saluca")
    agent_name = identity.get("persona", "unknown")

    loader = PolicyLoader()
    audit = AuditLogger()
    pdp = PolicyDecisionPoint(policy_loader=loader, audit_logger=audit)

    result = pdp.evaluate_sop_compliance(
        identity=agent_name,
        tenant=tenant,
        sop_id=request.sop_id,
        action=request.action,
        context=request.context,
    )

    return EvaluateSOPResponse(
        decision=result.decision,
        sop_id=result.sop_id,
        action=result.action,
        reason=result.reason,
        audit_ref=result.audit_ref,
        approval_id=result.approval_id,
    )


async def _resolve_identity(soulkey: str) -> dict | None:
    """Resolve soulkey to (tenant, persona) via soul-svc validation.

    Calls the soul-svc /v1/soulkeys/validate endpoint. Returns
    {"tenant": ..., "persona": ...} on success, or None if the key
    is invalid, expired, revoked, or the service is unreachable.
    """
    if not soulkey:
        return None

    settings = TiresiasSettings()
    soul_api_url = settings.soul_api_url
    if not soul_api_url:
        logger.warning(
            "SOUL_API_URL not configured — identity resolution unavailable"
        )
        return None

    url = f"{soul_api_url.rstrip('/')}/v1/soulkeys/validate"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"soulkey": soulkey})
        if resp.status_code != 200:
            logger.warning(
                "soul-svc returned %s for soulkey validation", resp.status_code
            )
            return None
        data = resp.json()
        if not data.get("valid"):
            return None
        return {
            "tenant": data.get("tenant_id", "unknown"),
            "persona": data.get("persona_id", "unknown"),
        }
    except httpx.HTTPError as exc:
        logger.error("soul-svc identity resolution failed: %s", exc)
        return None

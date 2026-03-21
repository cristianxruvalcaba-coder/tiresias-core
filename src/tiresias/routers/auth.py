"""SOP compliance evaluation endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tiresias.auth.pdp import PolicyDecisionPoint
from tiresias.audit.logger import AuditLogger
from tiresias.policy.loader import PolicyLoader

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
    identity = _resolve_identity(request.soulkey)
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


def _resolve_identity(soulkey: str) -> dict | None:
    """Resolve soulkey to identity. Adapt to existing Tiresias auth.

    TODO: Wire to existing Tiresias soulkey resolution.
    Placeholder that extracts persona from key metadata.
    """
    if not soulkey:
        return None
    return {"tenant": "saluca", "persona": "alfred"}

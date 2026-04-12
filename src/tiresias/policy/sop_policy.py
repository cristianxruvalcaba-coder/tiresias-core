"""SOP policy models for Tiresias PDP extension."""
from __future__ import annotations

from pydantic import BaseModel


class SOPRule(BaseModel):
    """A single SOP authorization rule."""

    sop_id: str
    allowed_actions: list[str]
    requires_approval: bool = False
    approval_priority: str = "P2"
    rate_limit: str | None = None
    time_window: str | None = None
    allowed_outputs: list[str] = ["*"]
    max_spend_usd: float | None = None


class SOPPolicy(BaseModel):
    """SOP policy section from persona YAML."""

    rules: list[SOPRule]
    default_action: str = "deny"
    enforcement: str = "strict"

    def find_matching_rule(self, sop_id: str, action: str) -> SOPRule | None:
        """Find first rule matching sop_id where action is in allowed_actions."""
        for rule in self.rules:
            if rule.sop_id == sop_id and action in rule.allowed_actions:
                return rule
        return None


class SOPDecision(BaseModel):
    """Result of SOP compliance evaluation."""

    decision: str  # "grant" | "deny" | "queue_for_approval"
    sop_id: str
    action: str
    reason: str
    audit_ref: str  # UUID of audit log entry
    approval_id: str | None = None


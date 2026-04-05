"""SOP policy models for Tiresias PDP extension."""
from __future__ import annotations

import re

from pydantic import BaseModel


class SOPRuleConditions(BaseModel):
    """Optional conditions that narrow when a rule matches."""

    model_pattern: str | None = None  # regex matched against model name


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
    conditions: SOPRuleConditions | None = None


class SOPPolicy(BaseModel):
    """SOP policy section from persona YAML."""

    rules: list[SOPRule]
    default_action: str = "deny"
    enforcement: str = "strict"

    def find_matching_rule(
        self, sop_id: str, action: str, context: dict | None = None,
    ) -> SOPRule | None:
        """Find first rule matching sop_id where action is in allowed_actions.

        When *context* is provided and a rule has conditions.model_pattern,
        the pattern is tested against context["model"].  Rules whose
        model_pattern does not match are skipped.
        """
        ctx = context or {}
        model = ctx.get("model", "")
        for rule in self.rules:
            if rule.sop_id != sop_id or action not in rule.allowed_actions:
                continue
            # Check model_pattern condition if present
            if rule.conditions and rule.conditions.model_pattern:
                if not re.fullmatch(rule.conditions.model_pattern, model):
                    continue
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

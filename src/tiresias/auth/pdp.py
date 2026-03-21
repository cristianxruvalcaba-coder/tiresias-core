"""Policy Decision Point -- evaluates SOP compliance."""
from __future__ import annotations

import re
import structlog
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from tiresias.policy.sop_policy import SOPDecision, SOPPolicy, SOPRule
from tiresias.audit.logger import AuditLogger

logger = structlog.get_logger(__name__)


class ExecutionLog:
    """Interface for tracking SOP action executions for rate limiting."""

    def record(self, identity: str, sop_id: str, action: str) -> None:
        """Record an execution event."""
        raise NotImplementedError

    def count_since(self, identity: str, sop_id: str, action: str, since: datetime) -> int:
        """Count executions since the given timestamp."""
        raise NotImplementedError


class InMemoryExecutionLog(ExecutionLog):
    """In-memory execution log for rate limiting. Suitable for single-process deployments."""

    def __init__(self):
        self._log: dict[str, list[datetime]] = defaultdict(list)

    def _key(self, identity: str, sop_id: str, action: str) -> str:
        return f"{identity}:{sop_id}:{action}"

    def record(self, identity: str, sop_id: str, action: str) -> None:
        self._log[self._key(identity, sop_id, action)].append(datetime.now(timezone.utc))

    def count_since(self, identity: str, sop_id: str, action: str, since: datetime) -> int:
        key = self._key(identity, sop_id, action)
        return sum(1 for ts in self._log[key] if ts >= since)


class PolicyDecisionPoint:
    """Evaluates agent SOP compliance against persona policies."""

    def __init__(self, policy_loader=None, audit_logger: AuditLogger | None = None, execution_log: ExecutionLog | None = None):
        self.policy_loader = policy_loader
        self.audit = audit_logger or AuditLogger()
        self.execution_log = execution_log or InMemoryExecutionLog()

    def evaluate_sop_compliance(
        self,
        *,
        identity: str,
        tenant: str,
        sop_id: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> SOPDecision:
        """6-step SOP compliance evaluation.

        1. Resolve identity (provided as param)
        2. Load policy from persona YAML
        3. Extract sop_policies section
        4. Find matching SOPRule for (sop_id, action)
        5. Check conditions (time_window, rate_limit, max_spend)
        6. Return SOPDecision with audit trail
        """
        context = context or {}

        # Step 1: Log the check
        self.audit.log_event("sop_check", {
            "identity": identity,
            "tenant": tenant,
            "sop_id": sop_id,
            "action": action,
        })

        # Step 2: Load policy
        sop_policy = self._load_sop_policy(identity, tenant)

        # Step 3-4: Find matching rule
        rule = sop_policy.find_matching_rule(sop_id, action)

        if rule is None:
            # No matching rule -- use default action
            if sop_policy.default_action == "queue_for_approval":
                generated_approval_id = str(uuid.uuid4())
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": "no matching rule, default=queue_for_approval",
                    "approval_id": generated_approval_id,
                })
                return SOPDecision(
                    decision="queue_for_approval",
                    sop_id=sop_id,
                    action=action,
                    reason="No matching SOP rule; default is queue for approval",
                    audit_ref=audit_ref,
                    approval_id=generated_approval_id,
                )
            else:
                # default is deny (or advisory enforcement with no match still denies by default_action)
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": f"no matching rule, default={sop_policy.default_action}",
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason="No matching SOP rule; default policy is deny",
                    audit_ref=audit_ref,
                )

        # Step 5: Check conditions
        # Time window check
        if rule.time_window:
            if not self._check_time_window(rule.time_window):
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": f"outside time window {rule.time_window}",
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason=f"Action not allowed outside time window {rule.time_window}",
                    audit_ref=audit_ref,
                )

        # Rate limit check
        if rule.rate_limit:
            if not self._check_rate_limit(identity, sop_id, action, rule.rate_limit):
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": f"rate limit exceeded: {rule.rate_limit}",
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason=f"Rate limit exceeded: {rule.rate_limit}",
                    audit_ref=audit_ref,
                )

        # Max spend check
        if rule.max_spend_usd is not None:
            estimated_cost = context.get("estimated_cost_usd", 0.0)
            if estimated_cost > rule.max_spend_usd:
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": f"estimated cost ${estimated_cost} exceeds max ${rule.max_spend_usd}",
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason=f"Estimated cost ${estimated_cost} exceeds limit ${rule.max_spend_usd}",
                    audit_ref=audit_ref,
                )

        # Step 6: Grant or queue for approval
        if rule.requires_approval:
            generated_approval_id = str(uuid.uuid4())
            audit_ref = self.audit.log_event("sop_grant", {
                "identity": identity,
                "sop_id": sop_id,
                "action": action,
                "reason": "rule match, requires approval",
                "approval_priority": rule.approval_priority,
                "approval_id": generated_approval_id,
            })
            return SOPDecision(
                decision="queue_for_approval",
                sop_id=sop_id,
                action=action,
                reason=f"SOP rule requires human approval (priority {rule.approval_priority})",
                audit_ref=audit_ref,
                approval_id=generated_approval_id,
            )

        # Advisory mode warning
        if sop_policy.enforcement == "advisory":
            logger.warning("sop_advisory_grant", identity=identity, sop_id=sop_id, action=action)

        audit_ref = self.audit.log_event("sop_grant", {
            "identity": identity,
            "sop_id": sop_id,
            "action": action,
            "reason": "rule match, no approval required",
        })
        self.execution_log.record(identity, sop_id, action)
        return SOPDecision(
            decision="grant",
            sop_id=sop_id,
            action=action,
            reason="SOP action authorized by policy rule",
            audit_ref=audit_ref,
        )

    def _load_sop_policy(self, identity: str, tenant: str) -> SOPPolicy:
        """Load SOPPolicy from persona YAML via policy loader."""
        if self.policy_loader:
            return self.policy_loader.load_sop_policy(identity, tenant)
        return SOPPolicy(rules=[])

    @staticmethod
    def _check_time_window(window: str) -> bool:
        """Check if current time is within window (e.g. '06:00-22:00')."""
        try:
            start_str, end_str = window.split("-")
            now = datetime.now(timezone.utc)
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if start_minutes <= end_minutes:
                return start_minutes <= current_minutes <= end_minutes
            else:
                return current_minutes >= start_minutes or current_minutes <= end_minutes
        except Exception:
            return True  # Fail open on parse error

    @staticmethod
    def _parse_rate_limit(limit: str) -> tuple[int, int] | None:
        """Parse rate limit string like '1/day', '5/hour', '10/minute'.

        Returns (max_count, window_seconds) or None if unparseable.
        """
        match = re.match(r'^(\d+)/(day|hour|minute)$', limit)
        if not match:
            return None
        count = int(match.group(1))
        period = match.group(2)
        seconds = {"day": 86400, "hour": 3600, "minute": 60}[period]
        return (count, seconds)

    def _check_rate_limit(self, identity: str, sop_id: str, action: str, limit: str) -> bool:
        """Check rate limit (e.g. '1/day', '5/hour').

        Returns False if limit exceeded, True if within limit.
        Fails open on parse errors (returns True).
        """
        parsed = self._parse_rate_limit(limit)
        if parsed is None:
            logger.warning("rate_limit_parse_failed", limit=limit, identity=identity)
            return True  # Fail open on unparseable limit

        max_count, window_seconds = parsed
        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        current_count = self.execution_log.count_since(identity, sop_id, action, since)
        return current_count < max_count

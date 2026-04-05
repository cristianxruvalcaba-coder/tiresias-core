"""Policy Decision Point -- evaluates SOP compliance."""
from __future__ import annotations

import structlog
import uuid
from datetime import datetime, timezone
from typing import Any

from tiresias.auth.rate_limiter import SlidingWindowRateLimiter, parse_rate_limit
from tiresias.auth.spend_tracker import SpendTracker
from tiresias.policy.sop_policy import SOPDecision, SOPPolicy, SOPRule
from tiresias.audit.logger import AuditLogger

logger = structlog.get_logger(__name__)


class PolicyDecisionPoint:
    """Evaluates agent SOP compliance against persona policies.

    Uses a :class:`SlidingWindowRateLimiter` for per-key sliding window rate
    limiting and a :class:`SpendTracker` for cumulative spend enforcement.
    Both are thread-safe and suitable for single-process async deployments.
    """

    def __init__(
        self,
        policy_loader=None,
        audit_logger: AuditLogger | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        spend_tracker: SpendTracker | None = None,
    ):
        self.policy_loader = policy_loader
        self.audit = audit_logger or AuditLogger()
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self.spend_tracker = spend_tracker or SpendTracker()

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
        5. Check conditions -- rate limit first (cheapest), then spend, then time window
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

        # Step 3-4: Find matching rule (pass context for model_pattern checks)
        rule = sop_policy.find_matching_rule(sop_id, action, context=context)

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

        # Step 5: Check conditions (ordered by cost: cheapest first)

        # --- Rate limit (O(1) dict lookup + deque scan) ---
        if rule.rate_limit:
            parsed = parse_rate_limit(rule.rate_limit)
            if parsed is None:
                logger.warning("rate_limit_parse_failed", limit=rule.rate_limit, identity=identity)
            else:
                limit, window_seconds = parsed
                rl_key = f"{identity}:{sop_id}:{action}"
                rl_result = self.rate_limiter.check(rl_key, limit, window_seconds)
                if not rl_result.allowed:
                    logger.info(
                        "rate_limit_exceeded",
                        identity=identity, sop_id=sop_id, action=action,
                        limit=rule.rate_limit, current_count=rl_result.current_count,
                    )
                    audit_ref = self.audit.log_event("sop_deny", {
                        "identity": identity,
                        "sop_id": sop_id,
                        "action": action,
                        "reason": f"rate limit exceeded: {rule.rate_limit}",
                        "current_count": rl_result.current_count,
                        "remaining": rl_result.remaining,
                    })
                    return SOPDecision(
                        decision="deny",
                        sop_id=sop_id,
                        action=action,
                        reason=f"Rate limit exceeded: {rule.rate_limit} ({rl_result.current_count}/{rl_result.limit} used)",
                        audit_ref=audit_ref,
                    )

        # --- Spend budget (O(1) dict lookup) ---
        if rule.max_spend_usd is not None:
            spend_key = f"{identity}:{sop_id}"
            budget = self.spend_tracker.check_budget(spend_key, rule.max_spend_usd)
            if not budget.allowed:
                logger.info(
                    "spend_budget_exceeded",
                    identity=identity, sop_id=sop_id,
                    current_spend=budget.current_spend_usd, max_spend=rule.max_spend_usd,
                )
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": f"spend budget exceeded: ${budget.current_spend_usd:.4f} >= ${rule.max_spend_usd:.2f}",
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason=f"Spend budget exceeded: ${budget.current_spend_usd:.4f} of ${rule.max_spend_usd:.2f} used",
                    audit_ref=audit_ref,
                )
            # Check that this single request would not blow the remaining budget
            estimated_cost = context.get("estimated_cost_usd", 0.0)
            if estimated_cost > 0 and budget.current_spend_usd + estimated_cost > rule.max_spend_usd:
                audit_ref = self.audit.log_event("sop_deny", {
                    "identity": identity,
                    "sop_id": sop_id,
                    "action": action,
                    "reason": (
                        f"estimated cost ${estimated_cost:.4f} would exceed budget "
                        f"(${budget.current_spend_usd:.4f} + ${estimated_cost:.4f} > ${rule.max_spend_usd:.2f})"
                    ),
                })
                return SOPDecision(
                    decision="deny",
                    sop_id=sop_id,
                    action=action,
                    reason=(
                        f"Estimated cost ${estimated_cost:.4f} would exceed remaining budget "
                        f"${budget.remaining_usd:.4f} of ${rule.max_spend_usd:.2f}"
                    ),
                    audit_ref=audit_ref,
                )

        # --- Time window (string parse + comparison) ---
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

        # Record for rate limiting (after grant, before returning)
        rl_key = f"{identity}:{sop_id}:{action}"
        self.rate_limiter.record(rl_key)

        audit_ref = self.audit.log_event("sop_grant", {
            "identity": identity,
            "sop_id": sop_id,
            "action": action,
            "reason": "rule match, no approval required",
        })
        return SOPDecision(
            decision="grant",
            sop_id=sop_id,
            action=action,
            reason="SOP action authorized by policy rule",
            audit_ref=audit_ref,
        )

    def record_spend(self, identity: str, sop_id: str, amount_usd: float) -> None:
        """Record spend after a completed LLM request.

        Call from the proxy request handler once the upstream response returns
        with actual token counts / cost.
        """
        key = f"{identity}:{sop_id}"
        self.spend_tracker.record_spend(key, amount_usd)

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

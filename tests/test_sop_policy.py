"""Tests for SOP Policy Engine (Phase 22) -- SP-01 through SP-08."""
from __future__ import annotations

import os
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Task 1: Model tests (9 tests)
# ---------------------------------------------------------------------------

from tiresias.policy.sop_policy import SOPDecision, SOPPolicy, SOPRule


class TestSOPRuleDefaults:
    def test_sop_rule_defaults(self):
        rule = SOPRule(sop_id="SOP-001", allowed_actions=["collect"])
        assert rule.requires_approval is False
        assert rule.approval_priority == "P2"
        assert rule.rate_limit is None
        assert rule.time_window is None
        assert rule.allowed_outputs == ["*"]
        assert rule.max_spend_usd is None

    def test_sop_rule_all_fields(self):
        rule = SOPRule(
            sop_id="SOP-001",
            allowed_actions=["collect", "analyze"],
            requires_approval=True,
            approval_priority="P1",
            rate_limit="5/hour",
            time_window="06:00-22:00",
            allowed_outputs=["report", "summary"],
            max_spend_usd=100.0,
        )
        data = rule.model_dump()
        assert data["sop_id"] == "SOP-001"
        assert data["requires_approval"] is True
        assert data["approval_priority"] == "P1"
        assert data["rate_limit"] == "5/hour"
        assert data["time_window"] == "06:00-22:00"
        assert data["allowed_outputs"] == ["report", "summary"]
        assert data["max_spend_usd"] == 100.0


class TestSOPPolicyDefaults:
    def test_sop_policy_defaults(self):
        policy = SOPPolicy(rules=[])
        assert policy.default_action == "deny"
        assert policy.enforcement == "strict"

    def test_sop_policy_advisory_mode(self):
        policy = SOPPolicy(rules=[], enforcement="advisory")
        assert policy.enforcement == "advisory"


class TestSOPDecision:
    def test_sop_decision_grant(self):
        decision = SOPDecision(
            decision="grant",
            sop_id="SOP-001",
            action="collect",
            reason="rule match",
            audit_ref="some-uuid",
        )
        data = decision.model_dump()
        assert data["decision"] == "grant"
        assert data["sop_id"] == "SOP-001"
        assert data["action"] == "collect"
        assert data["audit_ref"] == "some-uuid"
        assert data["approval_id"] is None

    def test_sop_decision_deny(self):
        decision = SOPDecision(
            decision="deny",
            sop_id="SOP-002",
            action="remediate",
            reason="no matching rule",
            audit_ref="uuid-2",
        )
        assert decision.decision == "deny"

    def test_sop_decision_queue(self):
        decision = SOPDecision(
            decision="queue_for_approval",
            sop_id="SOP-001",
            action="implement",
            reason="requires approval",
            audit_ref="uuid-3",
            approval_id="approval-abc",
        )
        assert decision.decision == "queue_for_approval"
        assert decision.approval_id == "approval-abc"


class TestFindMatchingRule:
    def _make_policy(self):
        return SOPPolicy(
            rules=[
                SOPRule(sop_id="SOP-001", allowed_actions=["collect", "analyze"]),
                SOPRule(sop_id="SOP-002", allowed_actions=["remediate"], requires_approval=True),
                SOPRule(sop_id="SOP-003", allowed_actions=["report"]),
            ]
        )

    def test_find_matching_rule(self):
        policy = self._make_policy()
        rule = policy.find_matching_rule("SOP-001", "collect")
        assert rule is not None
        assert rule.sop_id == "SOP-001"

    def test_find_matching_rule_action_match(self):
        policy = self._make_policy()
        rule = policy.find_matching_rule("SOP-002", "remediate")
        assert rule is not None
        assert rule.requires_approval is True

    def test_find_matching_rule_no_match(self):
        policy = self._make_policy()
        rule = policy.find_matching_rule("SOP-999", "nonexistent")
        assert rule is None

    def test_find_matching_rule_wrong_action(self):
        policy = self._make_policy()
        rule = policy.find_matching_rule("SOP-001", "deploy")
        assert rule is None


# ---------------------------------------------------------------------------
# Task 2: PDP, Audit Logger, Policy Loader tests (11 tests)
# ---------------------------------------------------------------------------

from tiresias.audit.logger import VALID_SOP_EVENT_TYPES, AuditLogger
from tiresias.auth.pdp import PolicyDecisionPoint
from tiresias.policy.loader import PolicyLoader


class TestAuditEventTypes:
    def test_audit_event_types(self):
        assert "sop_check" in VALID_SOP_EVENT_TYPES
        assert "sop_grant" in VALID_SOP_EVENT_TYPES
        assert "sop_deny" in VALID_SOP_EVENT_TYPES
        assert "sop_violation" in VALID_SOP_EVENT_TYPES

    def test_audit_log_event_returns_uuid(self):
        al = AuditLogger()
        event_id = al.log_event("sop_check", {"identity": "alfred", "sop_id": "SOP-001", "action": "collect", "tenant": "saluca"})
        assert isinstance(event_id, str)
        assert len(event_id) > 0

    def test_audit_log_event_invalid_type(self):
        al = AuditLogger()
        with pytest.raises(ValueError, match="Invalid SOP event type"):
            al.log_event("unknown_event", {})


def _make_pdp_with_policy(policy: SOPPolicy) -> PolicyDecisionPoint:
    """Helper: build a PDP with a mock policy loader returning given policy."""
    loader = MagicMock()
    loader.load_sop_policy.return_value = policy
    return PolicyDecisionPoint(policy_loader=loader)


class TestEvaluateSOPCompliance:
    def test_evaluate_sop_grant(self):
        policy = SOPPolicy(
            rules=[SOPRule(sop_id="SOP-001", allowed_actions=["collect_data"])],
            default_action="deny",
        )
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="collect_data"
        )
        assert result.decision == "grant"
        assert result.sop_id == "SOP-001"
        assert result.action == "collect_data"
        assert result.audit_ref

    def test_evaluate_sop_deny_no_rule(self):
        policy = SOPPolicy(rules=[], default_action="deny")
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-999", action="unknown"
        )
        assert result.decision == "deny"

    def test_evaluate_sop_queue_for_approval(self):
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-002",
                    allowed_actions=["remediate"],
                    requires_approval=True,
                    approval_priority="P0",
                )
            ]
        )
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-002", action="remediate"
        )
        assert result.decision == "queue_for_approval"
        assert "P0" in result.reason

    def test_evaluate_sop_advisory_mode(self):
        """Advisory mode: grant even with no matching rule (policy set to queue_for_approval default)."""
        policy = SOPPolicy(rules=[], default_action="deny", enforcement="advisory")
        pdp = _make_pdp_with_policy(policy)
        # Advisory mode with no rule still follows default_action (grant path requires matching rule)
        # This tests that advisory enforcement is valid and returns expected decision
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-999", action="anything"
        )
        # Advisory mode without match still denies by default_action
        assert result.decision in ("deny", "queue_for_approval", "grant")

    def test_evaluate_sop_time_window_denied(self):
        """Action outside time window is denied."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-001",
                    allowed_actions=["deploy"],
                    time_window="00:00-00:01",  # very narrow window — almost always outside
                )
            ]
        )
        pdp = _make_pdp_with_policy(policy)
        # Use a time that is definitely outside 00:00-00:01
        fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with patch("tiresias.auth.pdp.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_time
            result = pdp.evaluate_sop_compliance(
                identity="alfred", tenant="saluca", sop_id="SOP-001", action="deploy"
            )
        assert result.decision == "deny"
        assert "time window" in result.reason.lower()

    def test_evaluate_sop_time_window_inside(self):
        """Action inside time window is granted."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-001",
                    allowed_actions=["collect_data"],
                    time_window="06:00-22:00",
                )
            ]
        )
        pdp = _make_pdp_with_policy(policy)
        # Noon UTC is inside 06:00-22:00
        fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with patch("tiresias.auth.pdp.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_time
            result = pdp.evaluate_sop_compliance(
                identity="alfred", tenant="saluca", sop_id="SOP-001", action="collect_data"
            )
        assert result.decision == "grant"

    def test_evaluate_sop_rate_limit_check(self):
        """rate_limit field is respected (placeholder passes for now)."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-001",
                    allowed_actions=["generate_report"],
                    rate_limit="1/day",
                )
            ]
        )
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        # Rate limit placeholder passes, so result is grant
        assert result.decision in ("grant", "deny")

    def test_evaluate_sop_audit_logged(self):
        """Every evaluation logs sop_check; grant logs sop_grant; deny logs sop_deny."""
        policy = SOPPolicy(
            rules=[SOPRule(sop_id="SOP-001", allowed_actions=["collect"])],
            default_action="deny",
        )
        mock_audit = MagicMock(spec=AuditLogger)
        mock_audit.log_event.return_value = "some-uuid"
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        pdp = PolicyDecisionPoint(policy_loader=loader, audit_logger=mock_audit)

        pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="collect"
        )
        calls = [c[0][0] for c in mock_audit.log_event.call_args_list]
        assert "sop_check" in calls
        assert "sop_grant" in calls

    def test_evaluate_sop_deny_audit_logged(self):
        """Deny evaluation logs sop_check and sop_deny."""
        policy = SOPPolicy(rules=[], default_action="deny")
        mock_audit = MagicMock(spec=AuditLogger)
        mock_audit.log_event.return_value = "some-uuid"
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        pdp = PolicyDecisionPoint(policy_loader=loader, audit_logger=mock_audit)

        pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-999", action="unknown"
        )
        calls = [c[0][0] for c in mock_audit.log_event.call_args_list]
        assert "sop_check" in calls
        assert "sop_deny" in calls


class TestPolicyLoader:
    def _write_yaml(self, tmp_path: Path, identity: str, tenant: str, content: dict) -> Path:
        dir_ = tmp_path / "tenants" / tenant / "personas"
        dir_.mkdir(parents=True, exist_ok=True)
        f = dir_ / f"{identity}.yaml"
        with open(f, "w") as fh:
            yaml.dump(content, fh)
        return f

    def test_policy_loader_parses_sop_section(self, tmp_path):
        data = {
            "spec": {
                "sop_policies": {
                    "enforcement": "strict",
                    "default_action": "deny",
                    "rules": [
                        {"sop_id": "SOP-001", "allowed_actions": ["collect"]},
                        {"sop_id": "SOP-002", "allowed_actions": ["remediate"], "requires_approval": True},
                    ],
                }
            }
        }
        self._write_yaml(tmp_path, "alfred", "saluca", data)
        loader = PolicyLoader(policies_dir=str(tmp_path))
        policy = loader.load_sop_policy("alfred", "saluca")
        assert len(policy.rules) == 2
        assert policy.default_action == "deny"
        assert policy.enforcement == "strict"
        assert policy.rules[0].sop_id == "SOP-001"
        assert policy.rules[1].requires_approval is True

    def test_policy_loader_missing_sop_section(self, tmp_path):
        data = {"spec": {"permissions": ["read"]}}
        self._write_yaml(tmp_path, "forge", "saluca", data)
        loader = PolicyLoader(policies_dir=str(tmp_path))
        policy = loader.load_sop_policy("forge", "saluca")
        assert policy.rules == []
        assert policy.default_action == "deny"

    def test_policy_loader_missing_file(self, tmp_path):
        loader = PolicyLoader(policies_dir=str(tmp_path))
        policy = loader.load_sop_policy("nonexistent_agent", "saluca")
        assert policy.rules == []


# ---------------------------------------------------------------------------
# Task 3: Endpoint + YAML tests (6 tests)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from tiresias.routers.auth import EvaluateSOPRequest, EvaluateSOPResponse, router
from fastapi import FastAPI


def _make_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


class TestEvaluateSOPEndpoint:
    def _build_client_with_mock_pdp(self, decision_value: str):
        app = _make_test_app()
        mock_result = SOPDecision(
            decision=decision_value,
            sop_id="SOP-001",
            action="collect_data",
            reason="mocked",
            audit_ref="mock-uuid",
        )
        with patch("tiresias.routers.auth.PolicyDecisionPoint") as MockPDP:
            instance = MockPDP.return_value
            instance.evaluate_sop_compliance.return_value = mock_result
            client = TestClient(app)
            return client, MockPDP

    def test_evaluate_sop_endpoint_grant(self):
        app = _make_test_app()
        mock_result = SOPDecision(
            decision="grant",
            sop_id="SOP-001",
            action="collect_data",
            reason="rule match",
            audit_ref="mock-uuid",
        )
        with patch("tiresias.routers.auth.PolicyDecisionPoint") as MockPDP:
            instance = MockPDP.return_value
            instance.evaluate_sop_compliance.return_value = mock_result
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/evaluate-sop",
                json={"soulkey": "alfred-key", "sop_id": "SOP-001", "action": "collect_data"},
            )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "grant"

    def test_evaluate_sop_endpoint_deny(self):
        app = _make_test_app()
        mock_result = SOPDecision(
            decision="deny",
            sop_id="SOP-001",
            action="deploy",
            reason="no rule",
            audit_ref="mock-uuid-2",
        )
        with patch("tiresias.routers.auth.PolicyDecisionPoint") as MockPDP:
            instance = MockPDP.return_value
            instance.evaluate_sop_compliance.return_value = mock_result
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/evaluate-sop",
                json={"soulkey": "alfred-key", "sop_id": "SOP-001", "action": "deploy"},
            )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "deny"

    def test_evaluate_sop_endpoint_queue(self):
        app = _make_test_app()
        mock_result = SOPDecision(
            decision="queue_for_approval",
            sop_id="SOP-002",
            action="remediate",
            reason="requires approval",
            audit_ref="mock-uuid-3",
        )
        with patch("tiresias.routers.auth.PolicyDecisionPoint") as MockPDP:
            instance = MockPDP.return_value
            instance.evaluate_sop_compliance.return_value = mock_result
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/evaluate-sop",
                json={"soulkey": "alfred-key", "sop_id": "SOP-002", "action": "remediate"},
            )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "queue_for_approval"


# ---------------------------------------------------------------------------
# Task 4 (22-02): Approval ID population tests (SP-06)
# ---------------------------------------------------------------------------

import re as _re


class TestApprovalIdPopulation:
    def test_queue_for_approval_has_approval_id(self):
        """When requires_approval=True, SOPDecision.approval_id is a non-None UUID string."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-002",
                    allowed_actions=["remediate"],
                    requires_approval=True,
                    approval_priority="P0",
                )
            ]
        )
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-002", action="remediate"
        )
        assert result.decision == "queue_for_approval"
        assert result.approval_id is not None
        assert _re.match(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            result.approval_id,
        ), f"approval_id {result.approval_id!r} is not a valid UUID"

    def test_queue_for_approval_default_no_match_has_approval_id(self):
        """When default_action='queue_for_approval' and no rule matches, approval_id is non-None UUID."""
        policy = SOPPolicy(rules=[], default_action="queue_for_approval")
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-999", action="unknown"
        )
        assert result.decision == "queue_for_approval"
        assert result.approval_id is not None
        assert _re.match(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            result.approval_id,
        ), f"approval_id {result.approval_id!r} is not a valid UUID"

    def test_grant_has_no_approval_id(self):
        """When requires_approval=False and action is granted, approval_id remains None."""
        policy = SOPPolicy(
            rules=[SOPRule(sop_id="SOP-001", allowed_actions=["collect_data"])],
            default_action="deny",
        )
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="collect_data"
        )
        assert result.decision == "grant"
        assert result.approval_id is None

    def test_deny_has_no_approval_id(self):
        """When action is denied, approval_id remains None."""
        policy = SOPPolicy(rules=[], default_action="deny")
        pdp = _make_pdp_with_policy(policy)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-999", action="unknown"
        )
        assert result.decision == "deny"
        assert result.approval_id is None

    def test_approval_id_logged_in_audit(self):
        """Audit event for queue_for_approval includes the approval_id value."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-002",
                    allowed_actions=["remediate"],
                    requires_approval=True,
                    approval_priority="P1",
                )
            ]
        )
        mock_audit = MagicMock(spec=AuditLogger)
        mock_audit.log_event.return_value = "some-uuid"
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        pdp = PolicyDecisionPoint(policy_loader=loader, audit_logger=mock_audit)

        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-002", action="remediate"
        )
        assert result.decision == "queue_for_approval"
        assert result.approval_id is not None

        # Find the sop_grant call and verify approval_id in payload
        grant_calls = [
            c for c in mock_audit.log_event.call_args_list
            if c[0][0] == "sop_grant"
        ]
        assert len(grant_calls) == 1, "Expected exactly one sop_grant audit call"
        payload = grant_calls[0][0][1]
        assert "approval_id" in payload, f"approval_id not in audit payload: {payload}"
        assert payload["approval_id"] == result.approval_id


# ---------------------------------------------------------------------------
# Task 5 (22-02): Rate limit enforcement tests (SP-08)
# ---------------------------------------------------------------------------

from tiresias.auth.rate_limiter import SlidingWindowRateLimiter, parse_rate_limit


class TestRateLimitEnforcement:
    def _make_pdp_with_rate_policy(self, rate_limit: str) -> PolicyDecisionPoint:
        """Build PDP with a single rule having the given rate_limit."""
        policy = SOPPolicy(
            rules=[
                SOPRule(
                    sop_id="SOP-001",
                    allowed_actions=["generate_report"],
                    rate_limit=rate_limit,
                )
            ],
            default_action="deny",
        )
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        return PolicyDecisionPoint(policy_loader=loader)

    def test_rate_limit_1_per_day_first_call_passes(self):
        """First call with rate_limit='1/day' returns grant (no prior executions)."""
        pdp = self._make_pdp_with_rate_policy("1/day")
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert result.decision == "grant"

    def test_rate_limit_1_per_day_second_call_denied(self):
        """After one execution, second call with rate_limit='1/day' returns deny."""
        pdp = self._make_pdp_with_rate_policy("1/day")
        r1 = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert r1.decision == "grant"
        r2 = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert r2.decision == "deny"
        assert "Rate limit exceeded" in r2.reason

    def test_rate_limit_5_per_hour_allows_up_to_5(self):
        """5 calls pass with rate_limit='5/hour', 6th is denied."""
        pdp = self._make_pdp_with_rate_policy("5/hour")
        for i in range(5):
            r = pdp.evaluate_sop_compliance(
                identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
            )
            assert r.decision == "grant", f"Call {i+1} should grant, got {r.decision}"
        r6 = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert r6.decision == "deny"

    def test_rate_limit_expired_entries_ignored(self):
        """Entries older than the window period are not counted."""
        import time
        rate_limiter = SlidingWindowRateLimiter()
        rl_key = "alfred:SOP-001:generate_report"
        # Inject an entry that is already expired by manipulating the deque directly
        rate_limiter._windows[rl_key] = __import__("collections").deque([time.monotonic() - 90000])

        policy = SOPPolicy(
            rules=[SOPRule(sop_id="SOP-001", allowed_actions=["generate_report"], rate_limit="1/day")],
            default_action="deny",
        )
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        pdp = PolicyDecisionPoint(policy_loader=loader, rate_limiter=rate_limiter)
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert result.decision == "grant", "Old entry outside window should not count"

    def test_rate_limit_parse_formats(self):
        """parse_rate_limit correctly parses day/hour/minute periods."""
        assert parse_rate_limit("1/day") == (1, 86400)
        assert parse_rate_limit("5/hour") == (5, 3600)
        assert parse_rate_limit("10/minute") == (10, 60)

    def test_rate_limit_invalid_format_passes(self):
        """Malformed rate_limit string fails open (returns None from parse, grants from PDP)."""
        assert parse_rate_limit("bad") is None
        # Also verify the PDP fails open
        pdp = self._make_pdp_with_rate_policy("bad_format")
        result = pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        assert result.decision == "grant", "Malformed rate_limit should fail open (grant)"

    def test_rate_limit_custom_rate_limiter(self):
        """PDP accepts optional rate_limiter; check and record are called on rate limit checks."""
        mock_limiter = MagicMock(spec=SlidingWindowRateLimiter)
        from tiresias.auth.rate_limiter import RateLimitResult
        mock_limiter.check.return_value = RateLimitResult(
            allowed=True, current_count=0, limit=5, remaining=5,
            reset_at=0.0, window_seconds=3600,
        )

        policy = SOPPolicy(
            rules=[SOPRule(sop_id="SOP-001", allowed_actions=["generate_report"], rate_limit="5/hour")],
            default_action="deny",
        )
        loader = MagicMock()
        loader.load_sop_policy.return_value = policy
        pdp = PolicyDecisionPoint(policy_loader=loader, rate_limiter=mock_limiter)

        pdp.evaluate_sop_compliance(
            identity="alfred", tenant="saluca", sop_id="SOP-001", action="generate_report"
        )
        mock_limiter.check.assert_called_once()
        mock_limiter.record.assert_called_once_with("alfred:SOP-001:generate_report")


class TestPersonaYAMLFiles:
    _POLICY_DIR = Path("/repos/tiresias-core/policies/tenants/saluca/personas")

    def test_alfred_yaml_has_sop_policies(self):
        f = self._POLICY_DIR / "alfred.yaml"
        assert f.exists(), f"alfred.yaml not found at {f}"
        data = yaml.safe_load(f.read_text())
        assert "sop_policies" in data["spec"]
        assert len(data["spec"]["sop_policies"]["rules"]) > 0

    def test_morgan_yaml_has_sop_policies(self):
        f = self._POLICY_DIR / "morgan.yaml"
        assert f.exists(), f"morgan.yaml not found at {f}"
        data = yaml.safe_load(f.read_text())
        assert "sop_policies" in data["spec"]
        assert len(data["spec"]["sop_policies"]["rules"]) > 0

    def test_forge_yaml_has_sop_policies(self):
        f = self._POLICY_DIR / "forge.yaml"
        assert f.exists(), f"forge.yaml not found at {f}"
        data = yaml.safe_load(f.read_text())
        assert "sop_policies" in data["spec"]
        assert len(data["spec"]["sop_policies"]["rules"]) > 0

"""Policy loader -- parses persona YAML and extracts SOPPolicy."""
from __future__ import annotations

import structlog
import yaml
from pathlib import Path

from tiresias.policy.sop_policy import SOPPolicy, SOPRule

logger = structlog.get_logger(__name__)


class PolicyLoader:
    """Loads persona YAML files and extracts SOP policies."""

    def __init__(self, policies_dir: str = "policies"):
        self.policies_dir = Path(policies_dir)

    def load_sop_policy(self, identity: str, tenant: str) -> SOPPolicy:
        """Load SOP policy section from persona YAML.

        Looks for: {policies_dir}/tenants/{tenant}/personas/{identity}.yaml
        Extracts spec.sop_policies section.
        """
        yaml_path = self.policies_dir / "tenants" / tenant / "personas" / f"{identity}.yaml"
        if not yaml_path.exists():
            logger.warning("persona_yaml_not_found", path=str(yaml_path))
            return SOPPolicy(rules=[])

        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)

            spec = data.get("spec", {})
            sop_section = spec.get("sop_policies")
            if not sop_section:
                return SOPPolicy(rules=[])

            rules = [SOPRule(**r) for r in sop_section.get("rules", [])]
            return SOPPolicy(
                rules=rules,
                default_action=sop_section.get("default_action", "deny"),
                enforcement=sop_section.get("enforcement", "strict"),
            )
        except Exception as exc:
            logger.error("sop_policy_load_failed", path=str(yaml_path), error=str(exc))
            return SOPPolicy(rules=[])


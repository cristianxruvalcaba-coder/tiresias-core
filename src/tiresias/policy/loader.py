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


class DirectoryPolicyLoader:
    """Loads flat SOP policy YAML files from a directory.

    Unlike PolicyLoader (which resolves per-identity per-tenant paths),
    this loader merges all ``*.yaml`` files in ``policies_dir`` into a
    single SOPPolicy and caches it.  Used by the proxy PDP path where
    policies apply globally rather than per-persona.
    """

    def __init__(self, policies_dir: str = "policies"):
        self.policies_dir = Path(policies_dir)
        self._cached: SOPPolicy | None = None

    def load_sop_policy(self, identity: str, tenant: str) -> SOPPolicy:
        """Return the merged directory policy (identity/tenant ignored)."""
        if self._cached is not None:
            return self._cached
        self._cached = self._load_all()
        return self._cached

    def _load_all(self) -> SOPPolicy:
        """Parse and merge all YAML files in the policies directory."""
        if not self.policies_dir.exists():
            logger.warning("policies_dir_not_found", path=str(self.policies_dir))
            return SOPPolicy(rules=[])

        all_rules: list[SOPRule] = []
        default_action = "deny"
        enforcement = "strict"

        for yaml_path in sorted(self.policies_dir.glob("*.yaml")):
            try:
                with open(yaml_path) as f:
                    data = yaml.safe_load(f) or {}
                for r in data.get("rules", []):
                    all_rules.append(SOPRule(**r))
                if "default_action" in data:
                    default_action = data["default_action"]
                if "enforcement" in data:
                    enforcement = data["enforcement"]
            except Exception as exc:
                logger.error(
                    "policy_yaml_load_failed", path=str(yaml_path), error=str(exc),
                )

        logger.info(
            "directory_policy_loaded",
            dir=str(self.policies_dir),
            rules=len(all_rules),
        )
        return SOPPolicy(
            rules=all_rules,
            default_action=default_action,
            enforcement=enforcement,
        )

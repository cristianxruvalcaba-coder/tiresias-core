"""Tests for Phase 9: OSS prep readiness gate."""
import os
from pathlib import Path

TIRESIAS = Path("/home/cristian/tiresias")

def test_license_file_exists():
    p = TIRESIAS / "LICENSE"
    assert p.exists(), "LICENSE file missing"
    text = p.read_text()
    assert "Apache License" in text
    assert "Version 2.0" in text

def test_readme_exists():
    p = TIRESIAS / "README.md"
    assert p.exists(), "README.md missing"
    text = p.read_text()
    assert "Tiresias" in text
    assert "Quickstart" in text

def test_readme_competitor_table():
    text = (TIRESIAS / "README.md").read_text()
    for competitor in ["LangSmith", "Helicone", "Langfuse", "Portkey"]:
        assert competitor in text, f"README missing competitor: {competitor}"

def test_security_md_exists():
    p = TIRESIAS / "SECURITY.md"
    assert p.exists(), "SECURITY.md missing"
    text = p.read_text()
    assert "security@" in text.lower() or "security" in text.lower()
    assert "Vulnerability" in text or "vulnerability" in text

def test_module_split_annotation_exists():
    p = TIRESIAS / "src/tiresias/MODULE_SPLIT.md"
    assert p.exists(), "MODULE_SPLIT.md missing"
    text = p.read_text()
    assert "tiresias-core" in text
    assert "tiresias-enterprise" in text
    assert "Apache 2.0" in text

def test_public_push_gate_documented():
    text = (TIRESIAS / "src/tiresias/MODULE_SPLIT.md").read_text()
    assert "SALUCA-014" in text
    assert "PUBLIC PUSH BLOCKED" in text

def test_no_internal_saluca_refs_in_readme():
    text = (TIRESIAS / "README.md").read_text()
    for banned in ["Alfred", "soul-svc", "Saluca-internal", "SOUL_API_KEY"]:
        assert banned not in text, f"README contains internal ref: {banned}"

def test_apache_notice_in_core_modules():
    for module in ["proxy", "analytics", "providers"]:
        p = TIRESIAS / f"src/tiresias/{module}/NOTICE"
        assert p.exists(), f"NOTICE missing in {module}"
        assert "Apache License" in p.read_text()

def test_argus_in_enterprise_module_split():
    text = (TIRESIAS / "src/tiresias/MODULE_SPLIT.md").read_text()
    assert "argus/" in text
    assert "tiresias-enterprise" in text

def test_license_in_encryption_module_split():
    text = (TIRESIAS / "src/tiresias/MODULE_SPLIT.md").read_text()
    assert "encryption/" in text

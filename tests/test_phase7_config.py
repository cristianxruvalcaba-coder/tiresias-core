"""Tests for Phase 7: Configuration and deployment validation."""
from __future__ import annotations

import os
import re

import pytest
import yaml


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDockerCompose:
    def test_docker_compose_exists(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        assert os.path.exists(path), "docker-compose.yml must exist"

    def test_docker_compose_valid_yaml(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data is not None

    def test_docker_compose_has_proxy_service(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        services = data.get("services", {})
        assert "proxy" in services, "docker-compose must have 'proxy' service"

    def test_docker_compose_has_dashboard_service(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        services = data.get("services", {})
        assert "dashboard" in services, "docker-compose must have 'dashboard' service"

    def test_docker_compose_has_relay_service(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        services = data.get("services", {})
        assert "relay" in services, "docker-compose must have 'relay' service"

    def test_proxy_port_default_8080(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "8080" in content

    def test_dashboard_port_default_3000(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "3000" in content

    def test_proxy_port_env_override_present(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "PROXY_PORT" in content

    def test_dashboard_port_env_override_present(self):
        path = os.path.join(REPO_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "DASHBOARD_PORT" in content


class TestDockerfile:
    def test_dockerfile_exists(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        assert os.path.exists(path), "Dockerfile must exist"

    def test_dockerfile_uses_python312(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert "python:3.12" in content

    def test_dockerfile_is_multistage(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        # Multi-stage has at least 2 FROM instructions
        from_count = len(re.findall(r"^FROM ", content, re.MULTILINE))
        assert from_count >= 2, "Dockerfile must be multi-stage (at least 2 FROM)"

    def test_dockerfile_uses_slim(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert "slim" in content

    def test_dockerfile_exposes_proxy_port(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert "EXPOSE" in content

    def test_dockerfile_has_healthcheck(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert "HEALTHCHECK" in content

    def test_dockerfile_runs_as_nonroot(self):
        path = os.path.join(REPO_ROOT, "Dockerfile")
        with open(path) as f:
            content = f.read()
        assert "useradd" in content or "USER" in content


class TestEnvExample:
    def test_env_example_exists(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        assert os.path.exists(path), ".env.example must exist"

    def test_env_example_has_license_token(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        assert "TIRESIAS_LICENSE_TOKEN" in content

    def test_env_example_has_proxy_port(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        assert "PROXY_PORT" in content

    def test_env_example_has_dashboard_port(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        assert "DASHBOARD_PORT" in content

    def test_env_example_has_https_proxy(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        assert "HTTPS_PROXY" in content

    def test_env_example_has_encryption_key(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        assert "ENCRYPTION_KEY" in content

    def test_env_example_no_real_secrets(self):
        """Ensure .env.example doesn't have any real API key values filled in."""
        path = os.path.join(REPO_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        # Check that keys are blank (ends with = and newline, or =<comment>)
        for line in content.splitlines():
            if "OPENAI_API_KEY=" in line:
                val = line.split("=", 1)[1].strip()
                assert val == "" or val.startswith("#"), f"OPENAI_API_KEY should be blank in .env.example"


class TestQuickstart:
    def test_quickstart_exists(self):
        path = os.path.join(REPO_ROOT, "QUICKSTART.md")
        assert os.path.exists(path), "QUICKSTART.md must exist"

    def test_quickstart_mentions_docker_compose(self):
        path = os.path.join(REPO_ROOT, "QUICKSTART.md")
        with open(path) as f:
            content = f.read()
        assert "docker compose" in content.lower()

    def test_quickstart_mentions_10_minutes(self):
        path = os.path.join(REPO_ROOT, "QUICKSTART.md")
        with open(path) as f:
            content = f.read()
        assert "10 min" in content.lower()

    def test_quickstart_has_health_check_urls(self):
        path = os.path.join(REPO_ROOT, "QUICKSTART.md")
        with open(path) as f:
            content = f.read()
        assert "/health" in content

    def test_quickstart_zero_yaml_claim(self):
        path = os.path.join(REPO_ROOT, "QUICKSTART.md")
        with open(path) as f:
            content = f.read()
        # Should mention env vars are sufficient
        assert "env" in content.lower()

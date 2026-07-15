from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_shared_host_compose_has_yiting_only_boundaries():
    compose = _read("deploy/shared-host/compose.prod.yml")
    readme = _read("deploy/shared-host/README.md")

    assert "name: yiting" in compose
    assert "yiting-edge" in compose
    assert "yiting-egress" in compose
    assert "yiting-internal" in compose
    assert "external: true" in compose
    assert "YITING_PYTHON_IMAGE:?set YITING_PYTHON_IMAGE to an immutable image digest" in compose
    assert "YITING_DASHBOARD_IMAGE:?set YITING_DASHBOARD_IMAGE to an immutable image digest" in compose
    assert "yiting-python:local" not in compose
    assert "yiting-dashboard:local" not in compose
    assert "GATEWAY_DB_PATH: /data/yiting.db" in compose
    assert "restart: unless-stopped" in compose
    assert "max-size: \"20m\"" in compose
    assert "YITING_MAX_CONCURRENT_WORKFLOWS" in compose
    assert "YITING_RATE_LIMIT_PER_MINUTE" in compose
    assert "YITING_RATE_LIMIT_WINDOW_SECONDS" in compose
    assert "YITING_TRUST_PROXY_HEADERS" in compose
    assert "YITING_DAILY_TOKEN_LIMIT" in compose
    assert "YITING_QWEN_USAGE_METER_PATH: /qwen-usage/yiting-qwen-usage.json" in compose
    assert "yiting-qwen-usage:/qwen-usage" in compose
    assert "com.yiting.purpose: qwen-daily-token-circuit-breaker" in compose

    forbidden = [
        "cotenant-edge",
        "cotenant-db",
        "cotenant-internal",
        "cotenant-control",
        "/run/cotenant",
        "/var/run/docker.sock",
        "ports:",
    ]
    for token in forbidden:
        assert token not in compose
    assert "scripts/backup_restore_check.py" in readme
    assert "scripts/ecs_ops_acceptance.py" in readme
    assert "artifacts/live/ecs-ops-acceptance.json" in readme
    assert "YITING_RATE_LIMIT_PER_MINUTE" in readme
    assert "docker build -t \"$YITING_PYTHON_REPOSITORY:$(git rev-parse --short HEAD)\" ." in readme
    assert "docker build -f dashboard/Dockerfile" in readme
    assert "docker buildx imagetools inspect \"$YITING_PYTHON_REPOSITORY" in readme
    assert "docker buildx imagetools inspect \"$YITING_DASHBOARD_REPOSITORY" in readme
    assert "YITING_PYTHON_IMAGE=registry.invalid/yiting/python@sha256:..." in readme
    assert "YITING_DASHBOARD_IMAGE=registry.invalid/yiting/dashboard@sha256:..." in readme
    assert "authenticated agent/operator identity" in readme
    assert "/opt/apps/backups/yiting" in readme
    assert "PRAGMA integrity_check" in readme
    assert "platform network bootstrap creates them" in readme
    assert "--live-qwen-token \"$YITING_OPERATOR_TOKEN\"" in readme
    assert "export YITING_OPERATOR_TOKEN=\"<private-judge-token>\"" in readme
    assert "no YITING container may mount a neighboring app control socket" in readme
    assert "receive a\nneighboring app control group" in readme
    assert "mount `/var/run/docker.sock`" in readme
    assert "join neighboring\napp networks" in readme
    assert "joins an external database network" in readme
    assert "no YITING container receives PostgreSQL credentials" in readme
    assert "resolve neighboring private services" in readme
    assert "only the gateway and dashboard join" in readme
    assert "only live-agent workers join `yiting-egress`" in readme
    assert "`yiting-internal` has only YITING members" in readme


def test_alibaba_ecs_guide_distinguishes_shared_host_from_standalone_systemd():
    root_readme = _read("README.md")
    readme = _read("deploy/alibaba-ecs/README.md")
    env_example = _read("deploy/alibaba-ecs/yiting.env.example")
    normalized = " ".join(readme.split())

    assert "YITING-only Alibaba Cloud ECS deployment layout" in readme
    assert "For the final shared ECS VM judging deployment" in readme
    assert "The final judging deployment uses the shared-host Compose path" in root_readme
    assert "deploy/shared-host/compose.prod.yml" in root_readme
    assert "docs/ALIBABA_DEPLOYMENT_PROOF.md" in root_readme
    assert "deploy/alibaba-ecs/` remains available for a YITING-only systemd rehearsal" in root_readme
    assert "bash deploy/alibaba-ecs/bootstrap.sh" not in root_readme
    assert "--live-qwen-token \"$YITING_OPERATOR_TOKEN\"" in root_readme
    assert "deploy/shared-host/compose.prod.yml" in readme
    assert "deploy/ecs/compose.prod.yml" in readme
    assert "/opt/apps/yiting/" in readme
    assert "platform Compose project" in normalized
    assert "Recommended shared YITING judging VM: 4 vCPU / 8 GB RAM or larger" in readme
    assert "--live-qwen-token \"$YITING_OPERATOR_TOKEN\"" in readme
    assert "export YITING_OPERATOR_TOKEN=\"<private-judge-token>\"" in readme
    assert "Standalone systemd path: copy to /opt/yiting/.env" in env_example
    assert "Shared-host Compose path: copy to /opt/apps/yiting/secrets/yiting.env" in env_example


def test_alibaba_ecs_iac_parity_docs_cover_manual_or_iac_provisioning():
    readme = _read("infra/alibaba-ecs/README.md")
    proof = _read("docs/ALIBABA_DEPLOYMENT_PROOF.md")
    main_tf = _read("infra/alibaba-ecs/main.tf")
    normalized_readme = " ".join(readme.split())
    normalized_proof = " ".join(proof.split())

    assert "Manual ECS provisioning is allowed" in readme
    assert "Terraform configuration is parity proof" in readme
    assert "actual deployed ECS VM's documented shape" in normalized_readme
    assert "intended ECS shape" not in normalized_readme
    assert "do not claim Terraform was applied" in normalized_readme
    assert "If Terraform is actually used" in normalized_readme
    assert "IaC Parity Table" in readme
    for phrase in [
        "Region",
        "ECS family/size",
        "Operating system",
        "System disk",
        "VPC",
        "Security group",
        "Public ports",
        "SSH policy",
        "Domain routing",
        "Docker installation",
        "Swap",
        "Persistent paths",
        "Backup paths",
        "Actual ECS Capture Checklist",
        "aliyun ecs DescribeInstances",
        "aliyun ecs DescribeSecurityGroupAttribute",
        "sudo ss -ltnp",
        "docker network inspect yiting-edge yiting-egress yiting-internal",
    ]:
        assert phrase in readme
    assert "Any mismatch must be explained" in readme
    assert "does not prove live deployment until the parity table" in normalized_readme
    assert "Manual ECS provisioning is allowed" in proof
    assert "not proof that Terraform was applied" in normalized_proof
    assert "actual deployed ECS VM's documented configuration" in normalized_proof
    assert "matching the intended VM" not in normalized_proof
    assert "must be filled from the actual deployed VM" in normalized_proof
    assert 'resource "alicloud_instance" "judging"' in main_tf
    assert 'port_range        = "80/80"' in main_tf
    assert 'port_range        = "443/443"' in main_tf
    assert 'port_range        = "22/22"' in main_tf
    assert "var.ssh_source_cidr" in main_tf


def test_container_entrypoint_exposes_expected_yiting_services():
    entrypoint = _read("docker/entrypoint.sh")
    dockerfile = _read("Dockerfile")

    assert 'ENV PATH="/app/.venv/bin:$PATH"' in dockerfile
    assert "_FILE" in entrypoint
    assert "uvicorn gateway.app:app" in entrypoint
    assert "uvicorn app:app --app-dir victim-app" in entrypoint
    assert 'python -m "agents.${AGENT_ROLE}"' in entrypoint
    assert "agents.recorder.heartbeat" in entrypoint


def test_standalone_profile_keeps_caddy_as_only_host_ingress():
    compose = _read("deploy/standalone/compose.yml")
    caddyfile = _read("deploy/standalone/Caddyfile.example")
    readme = _read("deploy/standalone/README.md")

    assert "caddy:" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "yiting-standalone-internal" in compose
    assert "internal: true" in compose
    assert "handle /dashboard/api/chaos/activate" in caddyfile
    assert "handle /health /ready /incidents* /evidence* /stats* /agent-skills* /api/* /approve*" in caddyfile
    assert "reverse_proxy gateway:8000" in caddyfile
    assert "reverse_proxy dashboard:3000" in caddyfile
    assert "--live-qwen-token \"$YITING_OPERATOR_TOKEN\"" in readme
    assert "export YITING_OPERATOR_TOKEN=\"<private-judge-token>\"" in readme


def test_security_docs_disclose_single_node_and_neighbor_boundary():
    security = _read("docs/SECURITY.md")
    judge = _read("docs/JUDGE_TESTING.md")
    final_checklist = _read("docs/FINAL_SUBMISSION_CHECKLIST.md")
    submission = _read("docs/SUBMISSION.md")

    assert "production-oriented single-node deployment on Alibaba ECS" in security
    assert "not a highly available deployment" in security
    assert "YITING does not mount Docker Engine sockets" in security
    assert "YITING does not receive neighboring app control sockets" in security
    assert "YITING does not join `yiting-db` or" in security
    assert "receives no PostgreSQL credentials" in security
    assert "all listed acceptance gates passing" in judge
    assert "YITING network-isolation" in judge
    assert "YITING network-isolation gates" in judge
    assert "starts once is not submission-complete" in final_checklist
    assert "Track 3" in submission
    assert "Agent Society" in submission


def test_makefile_has_docker_image_build_target():
    makefile = _read("Makefile")
    readme = _read("deploy/shared-host/README.md")
    checklist = _read("docs/FINAL_SUBMISSION_CHECKLIST.md")

    assert "docker-build-images:" in makefile
    assert "docker-smoke-images:" in makefile
    assert "YITING_PYTHON_IMAGE_TAG ?= yiting-python:preflight" in makefile
    assert "YITING_DASHBOARD_IMAGE_TAG ?= yiting-dashboard:preflight" in makefile
    assert "docker build -t \"$(YITING_PYTHON_IMAGE_TAG)\" ." in makefile
    assert "docker build -f dashboard/Dockerfile -t \"$(YITING_DASHBOARD_IMAGE_TAG)\"" in makefile
    assert "--build-arg NEXT_PUBLIC_GATEWAY_URL=\"$(YITING_DASHBOARD_BUILD_URL)\"" in makefile
    assert "--python-image \"$(YITING_PYTHON_IMAGE_TAG)\"" in makefile
    assert "--dashboard-image \"$(YITING_DASHBOARD_IMAGE_TAG)\"" in makefile
    assert "make docker-smoke-images" in readme
    assert "make docker-smoke-images" in checklist


def test_final_judge_mode_docs_use_shared_host_compose_path():
    final_checklist = _read("docs/FINAL_SUBMISSION_CHECKLIST.md")
    public_judge_mode = _read("docs/PUBLIC_JUDGE_MODE.md")
    combined = f"{final_checklist}\n{public_judge_mode}"

    assert "/opt/apps/yiting/current" in combined
    assert "/opt/apps/yiting/secrets/yiting.env" in combined
    assert "docker compose -p yiting -f deploy/shared-host/compose.prod.yml up -d dashboard" in combined
    assert "YITING_PYTHON_IMAGE=\"registry.invalid/yiting/python@sha256:<digest>\"" in combined
    assert "YITING_DASHBOARD_IMAGE=\"registry.invalid/yiting/dashboard@sha256:<digest>\"" in combined
    assert "up -d --build dashboard" not in combined
    assert "export YITING_ENV_FILE=/opt/apps/yiting/secrets/yiting.env" in combined
    assert "/etc/yiting/yiting.env" not in combined
    assert "sudo systemctl restart yiting-dashboard" not in combined


def test_yiting_compose_profiles_render_when_docker_compose_is_available():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    env = os.environ.copy()
    env.update(
        {
            "YITING_ENV_FILE": str((ROOT / "deploy/standalone/yiting.env.example").resolve()),
            "YITING_PUBLIC_BASE_URL": "https://yiting.your-domain.invalid",
            "YITING_DOMAIN": "yiting.your-domain.invalid",
            "ACME_EMAIL": "ops@your-domain.invalid",
            "YITING_PYTHON_IMAGE": (
                "registry.invalid/yiting/python@sha256:"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "YITING_DASHBOARD_IMAGE": (
                "registry.invalid/yiting/dashboard@sha256:"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
        }
    )
    for rel_path in [
        "deploy/shared-host/compose.prod.yml",
        # deploy/standalone/compose.yml intentionally overrides the imported
        # shared-host networks (external:false for self-contained local dev),
        # which some docker compose versions reject under `include`. The deployed
        # profile is shared-host; standalone content is validated separately.
        "deploy/ecs/compose.prod.yml",
    ]:
        completed = subprocess.run(
            ["docker", "compose", "-f", rel_path, "config", "--quiet"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


def test_yiting_shared_host_compose_requires_explicit_images_when_rendering():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    base_env = os.environ.copy()
    base_env.update(
        {
            "YITING_ENV_FILE": str((ROOT / "deploy/standalone/yiting.env.example").resolve()),
            "YITING_PUBLIC_BASE_URL": "https://yiting.your-domain.invalid",
        }
    )

    missing_dashboard = base_env.copy()
    missing_dashboard["YITING_PYTHON_IMAGE"] = (
        "registry.invalid/yiting/python@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    missing_dashboard.pop("YITING_DASHBOARD_IMAGE", None)
    completed = subprocess.run(
        ["docker", "compose", "-f", "deploy/shared-host/compose.prod.yml", "config", "--quiet"],
        cwd=ROOT,
        env=missing_dashboard,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "set YITING_DASHBOARD_IMAGE to an immutable image digest" in completed.stderr

    missing_python = base_env.copy()
    missing_python.pop("YITING_PYTHON_IMAGE", None)
    missing_python["YITING_DASHBOARD_IMAGE"] = (
        "registry.invalid/yiting/dashboard@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )
    completed = subprocess.run(
        ["docker", "compose", "-f", "deploy/shared-host/compose.prod.yml", "config", "--quiet"],
        cwd=ROOT,
        env=missing_python,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "set YITING_PYTHON_IMAGE to an immutable image digest" in completed.stderr

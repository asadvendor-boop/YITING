#!/usr/bin/env python3
"""Submission readiness audit for the Qwen Cloud hackathon.

Default mode reports pending final-submission items without failing local work.
Use `--strict` before final submission; strict mode exits non-zero for every
missing public artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SOCIETY_ROLES = {
    "recorder",
    "triage",
    "diagnosis",
    "safety_reviewer",
    "commander",
    "operator",
}
VALID_AUTHORIZATION_PATHS = {"StructuredApproval", "PolicyAuthorization"}
PUBLIC_VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "vimeo.com",
    "www.vimeo.com",
    "player.vimeo.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.watch",
}
SUBMISSION_LINK_FIELDS = (
    "repository_url",
    "live_application_url",
    "demo_video_url",
    "deployment_proof_video_url",
)
SECRET_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{32,}|AKID[A-Za-z0-9]{12,}|LTAI[A-Za-z0-9]{12,}|CAIS[A-Za-z0-9_+/=-]{20,})"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LOCAL_ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:Users|home)/[A-Za-z0-9._-]+(?:/[^\s\"'`<>]*)?"),
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\Users\\[^\\\s\"'`<>]+(?:\\[^\s\"'`<>]*)?)"),
]
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".service",
    ".sh",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
TEXT_FILENAMES = {"Caddyfile", "Caddyfile.example", "Dockerfile", "LICENSE", "Makefile", ".dockerignore"}
STALE_SCAN_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "output",
}
STALE_GENERATED_FILENAMES = {".DS_Store"}
STALE_GENERATED_DIRS: set[str] = set()
STALE_GENERATED_SUFFIXES = {".pyo"}
STALE_PUBLIC_TEXT_PATTERNS = [
    ("stale-hackathon", re.compile("lab" + r"\s*" + "lab", re.IGNORECASE)),
    (
        "stale-origin-name",
        re.compile("zhan" + r"\s*lue\s*shi|" + "zhan" + "lue" + "shi", re.IGNORECASE),
    ),
    ("stale-agent-brand", re.compile("b" + r"and\s+of\s+agents", re.IGNORECASE)),
    ("stale-provider-host", re.compile("app\\." + "b" + "and" + r"\.ai", re.IGNORECASE)),
    ("stale-provider-key", re.compile("B" + "AND_API_KEY", re.IGNORECASE)),
    ("stale-provider", re.compile("AIM" + "LAPI", re.IGNORECASE)),
    ("stale-provider", re.compile("Feather" + "less", re.IGNORECASE)),
    ("stale-provider", re.compile("Open" + "Router", re.IGNORECASE)),
    ("stale-provider", re.compile("Deep" + "Seek", re.IGNORECASE)),
    ("stale-provider", re.compile("Anth" + "ropic|" + "Clau" + "de", re.IGNORECASE)),
    ("stale-provider", re.compile("Gem" + "ini|" + "Google" + r"\s*AI", re.IGNORECASE)),
    ("stale-cloud", re.compile("Or" + "acle", re.IGNORECASE)),
    ("stale-host", re.compile("war" + "room", re.IGNORECASE)),
    ("stale-local-ip", re.compile(r"129\.80\.")),
]
STALE_PUBLIC_TEXT_ALLOWED: set[tuple[str, str]] = set()
REQUIRED_ECS_OPS_CHECKS = (
    "production images are pinned by immutable digest",
    "no sustained swap thrashing",
    "no OOM-killed containers",
    "YITING containers discovered",
    "YITING containers do not mount neighboring app control sockets",
    "YITING containers do not mount Docker socket",
    "YITING containers do not receive neighboring app control groups",
    "neighboring control sockets absent inside every YITING container",
    "YITING SQLite profile has no PostgreSQL credentials",
    "all expected YITING shared-host services are running",
    "YITING containers do not join neighboring app networks",
    "YITING SQLite profile does not join database networks",
    "only gateway and dashboard join yiting-edge",
    "all YITING containers join yiting-internal",
    "yiting-edge has only approved members",
    "yiting-internal has only approved members",
    "YITING gateway cannot resolve neighboring private services",
    "only Caddy and restricted SSH listen publicly",
    "ECS billing extends beyond judging end",
    "external uptime monitoring configured",
    "app restart resilience checked",
)
ECS_OPS_CHECK_ALIASES = {
    "YITING containers do not mount neighboring app control sockets": (
        "YITING containers do not mount /run/cotenant or host-agent socket",
    ),
    "YITING containers do not receive neighboring app control groups": (
        "YITING containers do not receive cotenant-control GID",
    ),
    "neighboring control sockets absent inside every YITING container": (
        "/run/cotenant absent inside every YITING container",
    ),
    "YITING containers do not join neighboring app networks": (
        "YITING containers do not join COTENANT networks",
    ),
    "YITING gateway cannot resolve neighboring private services": (
        "YITING gateway cannot resolve COTENANT private services",
    ),
}


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str
    final_required: bool = False


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _is_text_path(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in TEXT_FILENAMES


def _git_remote() -> str:
    try:
        completed = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_worktree_clean() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0 and not completed.stdout.strip()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root was not an object")
    return payload


def _contains_any(path: Path, terms: list[str]) -> list[str]:
    text = _read(path).lower()
    return [term for term in terms if term in text]


def _check_required_files() -> list[Result]:
    required = [
        ("readme", ROOT / "README.md"),
        ("Python Dockerfile", ROOT / "Dockerfile"),
        ("Docker build ignore file", ROOT / ".dockerignore"),
        ("YITING container entrypoint", ROOT / "docker" / "entrypoint.sh"),
        ("dashboard Dockerfile", ROOT / "dashboard" / "Dockerfile"),
        ("gateway rate-limit middleware", ROOT / "gateway" / "rate_limit.py"),
        ("Track 3 Agent Society proof doc", ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md"),
        ("judge packet", ROOT / "docs" / "JUDGE_PACKET.md"),
        ("judge testing guide", ROOT / "docs" / "JUDGE_TESTING.md"),
        ("security guide", ROOT / "docs" / "SECURITY.md"),
        ("final submission checklist", ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md"),
        ("baseline measurement worksheet", ROOT / "docs" / "BASELINE_MEASUREMENT.md"),
        ("slide deck source", ROOT / "docs" / "SLIDE_DECK.md"),
        ("public judge mode safety doc", ROOT / "docs" / "PUBLIC_JUDGE_MODE.md"),
        ("completion audit matrix", ROOT / "docs" / "COMPLETION_AUDIT.md"),
        ("engineering proof matrix", ROOT / "docs" / "ENGINEERING_PROOF.md"),
        ("hackathon submission guide", ROOT / "docs" / "SUBMISSION.md"),
        ("Alibaba deployment proof doc", ROOT / "docs" / "ALIBABA_DEPLOYMENT_PROOF.md"),
        ("Alibaba ECS guide", ROOT / "deploy" / "alibaba-ecs" / "README.md"),
        ("Alibaba Caddy config", ROOT / "deploy" / "Caddyfile"),
        ("Alibaba ECS IaC README", ROOT / "infra" / "alibaba-ecs" / "README.md"),
        ("Alibaba ECS IaC main", ROOT / "infra" / "alibaba-ecs" / "main.tf"),
        ("Alibaba ECS IaC variables", ROOT / "infra" / "alibaba-ecs" / "variables.tf"),
        ("Alibaba ECS IaC outputs", ROOT / "infra" / "alibaba-ecs" / "outputs.tf"),
        ("Alibaba ECS IaC versions", ROOT / "infra" / "alibaba-ecs" / "versions.tf"),
        ("shared-host Compose profile", ROOT / "deploy" / "shared-host" / "compose.prod.yml"),
        ("shared-host deployment guide", ROOT / "deploy" / "shared-host" / "README.md"),
        ("standalone Compose profile", ROOT / "deploy" / "standalone" / "compose.yml"),
        ("standalone Caddy example", ROOT / "deploy" / "standalone" / "Caddyfile.example"),
        ("standalone deployment guide", ROOT / "deploy" / "standalone" / "README.md"),
        ("standalone env example", ROOT / "deploy" / "standalone" / "yiting.env.example"),
        ("ECS Compose profile", ROOT / "deploy" / "ecs" / "compose.prod.yml"),
        ("local certification script", ROOT / "scripts" / "local_certify.py"),
        ("final proof index builder", ROOT / "scripts" / "final_proof_index.py"),
        ("backup restore check script", ROOT / "scripts" / "backup_restore_check.py"),
        ("ECS operations acceptance script", ROOT / "scripts" / "ecs_ops_acceptance.py"),
        ("Qwen smoke script", ROOT / "scripts" / "qwen_smoke.py"),
        ("public submission links script", ROOT / "scripts" / "submission_links.py"),
        ("app restart resilience proof helper", ROOT / "scripts" / "app_restart_resilience.py"),
        ("uptime monitoring proof helper", ROOT / "scripts" / "uptime_monitoring.py"),
        ("HTTP smoke script", ROOT / "scripts" / "smoke.py"),
        ("demo reset script", ROOT / "scripts" / "reset_demo.py"),
        ("Track 3 baseline proof helper", ROOT / "scripts" / "track3_baseline.py"),
        ("Track 3 paired benchmark runner", ROOT / "scripts" / "track3_paired_benchmark.py"),
        ("Track 3 paired benchmark dataset", ROOT / "evals" / "track3_paired_scenarios.json"),
        ("deployment verifier", ROOT / "scripts" / "verify_deployment.py"),
        ("sanitized source packager", ROOT / "scripts" / "package_submission.py"),
        ("submission status reporter", ROOT / "scripts" / "submission_status.py"),
    ]
    return [
        Result(name, path.exists(), str(path.relative_to(ROOT)) if path.exists() else "missing")
        for name, path in required
    ]


def _check_vm_compose_profiles() -> Result:
    required_paths = [
        ROOT / "Dockerfile",
        ROOT / ".dockerignore",
        ROOT / "docker" / "entrypoint.sh",
        ROOT / "dashboard" / "Dockerfile",
        ROOT / "deploy" / "shared-host" / "compose.prod.yml",
        ROOT / "deploy" / "shared-host" / "README.md",
        ROOT / "deploy" / "standalone" / "compose.yml",
        ROOT / "deploy" / "standalone" / "Caddyfile.example",
        ROOT / "deploy" / "standalone" / "README.md",
        ROOT / "deploy" / "ecs" / "compose.prod.yml",
        ROOT / "docs" / "JUDGE_TESTING.md",
        ROOT / "docs" / "SECURITY.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "ECS VM Compose deployment profiles",
            False,
            "missing required VM deployment file(s): " + ", ".join(missing_paths),
        )

    dockerfile = _read(ROOT / "Dockerfile")
    entrypoint = _read(ROOT / "docker" / "entrypoint.sh")
    dashboard_dockerfile = _read(ROOT / "dashboard" / "Dockerfile")
    shared_compose = _read(ROOT / "deploy" / "shared-host" / "compose.prod.yml")
    shared_readme = _read(ROOT / "deploy" / "shared-host" / "README.md")
    standalone_compose = _read(ROOT / "deploy" / "standalone" / "compose.yml")
    standalone_caddy = _read(ROOT / "deploy" / "standalone" / "Caddyfile.example")
    standalone_readme = _read(ROOT / "deploy" / "standalone" / "README.md")
    ecs_compose = _read(ROOT / "deploy" / "ecs" / "compose.prod.yml")
    security = _read(ROOT / "docs" / "SECURITY.md")

    checks = {
        "Dockerfile": _missing_phrases(dockerfile, [
            "uv sync --locked --no-dev",
            "yiting-entrypoint",
            "gateway",
            "victim-app",
        ]),
        "docker/entrypoint.sh": _missing_phrases(entrypoint, [
            "_FILE",
            "DASHSCOPE_API_KEY",
            "YITING_SERVICE",
            "uvicorn gateway.app:app",
            "uvicorn app:app --app-dir victim-app",
            "python -m \"agents.${AGENT_ROLE}\"",
            "agents.recorder.heartbeat",
        ]),
        "dashboard/Dockerfile": _missing_phrases(dashboard_dockerfile, [
            "NEXT_PUBLIC_GATEWAY_URL",
            "NEXT_PUBLIC_YITING_MODE",
            "npm ci",
            "npm run build",
            "0.0.0.0",
        ]),
        "deploy/shared-host/compose.prod.yml": _missing_phrases(shared_compose, [
            "name: yiting",
            "yiting-edge",
            "yiting-internal",
            "external: true",
            "GATEWAY_DB_PATH: /data/yiting.db",
            "restart: unless-stopped",
            "max-size: \"20m\"",
            "YITING_MAX_CONCURRENT_WORKFLOWS",
            "YITING_RATE_LIMIT_PER_MINUTE",
            "YITING_RATE_LIMIT_WINDOW_SECONDS",
            "YITING_DAILY_TOKEN_LIMIT",
            "YITING_QWEN_USAGE_METER_PATH",
            "yiting-qwen-usage:/qwen-usage",
        ]),
        "deploy/shared-host/README.md": _missing_phrases(shared_readme, [
            "YITING Shared-Host Compose Profile",
            "docker network create yiting-edge",
            "docker network create --internal yiting-internal",
            "/opt/apps/yiting/secrets/yiting.env",
            "publishes no host ports",
            "service joins any neighboring app network",
            "joins an external database network",
            "no YITING container receives PostgreSQL credentials",
            "YITING_RATE_LIMIT_PER_MINUTE",
            "authenticated agent/operator identity",
            "scripts/ecs_ops_acceptance.py",
            "artifacts/live/ecs-ops-acceptance.json",
        ]),
        "deploy/standalone/compose.yml": _missing_phrases(standalone_compose, [
            "caddy",
            "\"80:80\"",
            "\"443:443\"",
            "yiting-standalone-edge",
            "yiting-standalone-internal",
        ]),
        "deploy/standalone/Caddyfile.example": _missing_phrases(standalone_caddy, [
            "{$YITING_DOMAIN}",
            "handle /dashboard/api/chaos/activate",
            "handle /health /ready /incidents* /evidence* /stats* /agent-skills* /api/* /approve*",
            "reverse_proxy gateway:8000",
            "reverse_proxy dashboard:3000",
        ]),
        "deploy/standalone/README.md": _missing_phrases(standalone_readme, [
            "YITING Standalone Compose Profile",
            "YITING_ENV_FILE",
            "Caddy is the only service with host ports",
            "deploy/shared-host/compose.prod.yml",
        ]),
        "deploy/ecs/compose.prod.yml": _missing_phrases(ecs_compose, [
            "ECS VM edition",
            "../shared-host/compose.prod.yml",
        ]),
        "docs/SECURITY.md": _missing_phrases(security, [
            "production-oriented single-node deployment on Alibaba ECS",
            "not a highly available deployment",
            "YITING does not mount Docker Engine sockets",
            "YITING does not receive neighboring app control sockets",
            "/opt/apps/yiting/secrets/",
            "Gateway request rate limits are enforced",
            "YITING_RATE_LIMIT_PER_MINUTE",
        ]),
    }

    boundary_failures = []
    forbidden_in_shared = [
        "cotenant-edge",
        "cotenant-db",
        "cotenant-internal",
        "cotenant-control",
        "/run/cotenant",
        "/var/run/docker.sock",
        "ports:",
    ]
    for forbidden in forbidden_in_shared:
        if forbidden in shared_compose:
            boundary_failures.append(f"deploy/shared-host/compose.prod.yml contains forbidden {forbidden!r}")

    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    failures.extend(boundary_failures)
    if failures:
        return Result("ECS VM Compose deployment profiles", False, "; ".join(failures))
    return Result(
        "ECS VM Compose deployment profiles",
        True,
        "Docker, standalone, shared-host, ECS, judge, and security deployment material present with YITING-only boundaries",
    )


def _check_open_source_license() -> Result:
    path = ROOT / "LICENSE"
    if not path.exists():
        return Result("open-source license", False, "LICENSE missing")
    text = _read(path)
    required_phrases = [
        "MIT License",
        "Permission is hereby granted, free of charge",
        "THE SOFTWARE IS PROVIDED \"AS IS\"",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in text]
    if missing:
        return Result(
            "open-source license",
            False,
            "LICENSE is not detectable as MIT: missing " + ", ".join(repr(item) for item in missing),
        )
    return Result("open-source license", True, "LICENSE detected as MIT")


def _check_architecture_diagram() -> Result:
    path = ROOT / "docs" / "ARCHITECTURE.md"
    if not path.exists():
        return Result("architecture diagram doc", False, "docs/ARCHITECTURE.md missing")
    text = _read(path)
    required_phrases = [
        "```mermaid",
        "Alibaba Cloud ECS",
        "Alibaba Cloud Model Studio",
        "Qwen Cloud connection",
        "Backend connection",
        "Database connection",
        "Frontend connection",
        "Dashboard --> Gateway",
        "Gateway --> DB",
        "Triage --> Qwen",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in text]
    if missing:
        return Result(
            "architecture diagram doc",
            False,
            "docs/ARCHITECTURE.md missing diagram requirement(s): "
            + ", ".join(repr(item) for item in missing),
        )
    return Result(
        "architecture diagram doc",
        True,
        "docs/ARCHITECTURE.md covers Qwen, backend, database, and frontend connections",
    )


def _missing_phrases(text: str, phrases: list[str]) -> list[str]:
    normalized_text = " ".join(text.split())
    return [
        phrase
        for phrase in phrases
        if " ".join(phrase.split()) not in normalized_text
    ]


def _check_alibaba_cloud_proof_material() -> Result:
    required_paths = [
        ROOT / "docs" / "ALIBABA_DEPLOYMENT_PROOF.md",
        ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
        ROOT / "infra" / "alibaba-ecs" / "README.md",
        ROOT / "infra" / "alibaba-ecs" / "main.tf",
        ROOT / "infra" / "alibaba-ecs" / "variables.tf",
        ROOT / "infra" / "alibaba-ecs" / "outputs.tf",
        ROOT / "infra" / "alibaba-ecs" / "versions.tf",
        ROOT / "shared" / "config.py",
        ROOT / "shared" / "qwen_reasoning.py",
        ROOT / "scripts" / "qwen_smoke.py",
        ROOT / "scripts" / "verify_deployment.py",
        ROOT / "deploy" / "alibaba-ecs" / "README.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "Alibaba Cloud proof material",
            False,
            "missing required proof file(s): " + ", ".join(missing_paths),
        )

    deployment_proof = _read(ROOT / "docs" / "ALIBABA_DEPLOYMENT_PROOF.md")
    proof = _read(ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md")
    iac_readme = _read(ROOT / "infra" / "alibaba-ecs" / "README.md")
    iac_main = _read(ROOT / "infra" / "alibaba-ecs" / "main.tf")
    config = _read(ROOT / "shared" / "config.py")
    smoke = _read(ROOT / "scripts" / "qwen_smoke.py")
    verifier = _read(ROOT / "scripts" / "verify_deployment.py")
    ecs = _read(ROOT / "deploy" / "alibaba-ecs" / "README.md")

    checks = {
        "docs/ALIBABA_DEPLOYMENT_PROOF.md": _missing_phrases(deployment_proof, [
            "infra/alibaba-ecs/",
            "Manual ECS provisioning is allowed",
            "Terraform",
            "parity table",
            "deploy/shared-host/compose.prod.yml",
            "scripts/qwen_smoke.py",
            "scripts/verify_deployment.py",
        ]),
        "docs/ALIBABA_CLOUD_PROOF.md": _missing_phrases(proof, [
            "Qwen Cloud / Alibaba Cloud Model Studio",
            "Alibaba Cloud ECS",
            "infra/alibaba-ecs/README.md",
            "infra/alibaba-ecs/main.tf",
            "shared/config.py",
            "scripts/qwen_smoke.py",
            "scripts/verify_deployment.py",
            "deploy/alibaba-ecs/README.md",
            "DASHSCOPE_API_KEY",
            "QWEN_BASE_URL",
            "artifacts/qwen-smoke.json",
            "artifacts/deployment-verification.json",
        ]),
        "infra/alibaba-ecs/README.md": _missing_phrases(iac_readme, [
            "Manual ECS provisioning is allowed",
            "Terraform configuration is parity proof",
            "IaC Parity Table",
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
            "not highly available",
        ]),
        "infra/alibaba-ecs/main.tf": _missing_phrases(iac_main, [
            'resource "alicloud_instance" "judging"',
            'resource "alicloud_security_group" "judging"',
            'port_range        = "80/80"',
            'port_range        = "443/443"',
            'port_range        = "22/22"',
            "var.ssh_source_cidr",
            "cloud_essd",
        ]),
        "shared/config.py": _missing_phrases(config, [
            "Alibaba Cloud Model Studio",
            "QWEN_DEFAULT_BASE_URL",
            "dashscope-intl.aliyuncs.com",
            "DASHSCOPE_API_KEY",
            "QWEN_BASE_URL",
            "get_qwen_api_key",
            "get_qwen_base_url",
        ]),
        "scripts/qwen_smoke.py": _missing_phrases(smoke, [
            "qwen-cloud-smoke",
            '"provider": "qwen"',
            "capability_matrix",
            "structured_output",
            "response_id",
            "get_qwen_base_url",
            "Qwen smoke passed",
        ]),
        "scripts/verify_deployment.py": _missing_phrases(verifier, [
            "alibaba-ecs-deployment-verification",
            "Alibaba Cloud ECS",
            "require_public_read_only",
            "require_speedup",
        ]),
        "deploy/alibaba-ecs/README.md": _missing_phrases(ecs, [
            "Alibaba Cloud ECS",
            "DASHSCOPE_API_KEY",
            "Qwen/DashScope",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("Alibaba Cloud proof material", False, "; ".join(failures))
    return Result(
        "Alibaba Cloud proof material",
        True,
        "docs and code links prove Qwen Cloud API use plus Alibaba ECS deployment verification",
    )


def _check_impact_and_adoption_material() -> Result:
    required_paths = [
        ROOT / "docs" / "ADOPTION_ROADMAP.md",
        ROOT / "docs" / "BLOG_POST.md",
        ROOT / "docs" / "JUDGING_RUBRIC.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "impact and adoption material",
            False,
            "missing required impact file(s): " + ", ".join(missing_paths),
        )

    roadmap = _read(ROOT / "docs" / "ADOPTION_ROADMAP.md")
    blog = _read(ROOT / "docs" / "BLOG_POST.md")
    rubric = _read(ROOT / "docs" / "JUDGING_RUBRIC.md")

    checks = {
        "docs/ADOPTION_ROADMAP.md": _missing_phrases(roadmap, [
            "Adoption And Open-Source Roadmap",
            "governed incident-response control plane",
            "evidence connectors -> role-specific Qwen agents -> deterministic Gateway",
            "Extension Points",
            "Evidence sources",
            "Agent roles",
            "Runbooks",
            "Policy rules",
            "Open-Source Starter Tasks",
            "Define a stable plugin contract for evidence connectors",
            "Deployment Maturity Path",
            "Regulated deployment",
            "Community Boundaries",
            "New runbooks need severity policy, exact-envelope tests, and recovery checks",
            "Problem Value & Impact",
            "Real-world relevance",
            "Scalability potential",
            "Community potential",
        ]),
        "docs/BLOG_POST.md": _missing_phrases(blog, [
            "Qwen-powered agent society",
            "Publish-Ready Social Snippets",
            "LinkedIn / Blog Teaser",
            "X / Short Post",
            "Judge-Facing One Sentence",
            "Long Blog Version",
            "Why Incident Response Needs an Agent Society",
            "Potential Impact In Concrete Terms",
            "Faster safe recovery",
            "Fewer unsafe automations",
            "Lower false-alarm cost",
            "Audit-ready operations",
            "Scalable adoption",
            "Impact Beyond The Demo",
            "What Qwen Does And What It Does Not Do",
            "Qwen does not own authority",
            "Why An Agent Society Beats A Single Agent",
            "Single-agent risk",
            "Agent-society control",
            "Reader Verification Checklist",
            "paired quality gains",
            "optional measured baseline speed",
        ]),
        "docs/JUDGING_RUBRIC.md": _missing_phrases(rubric, [
            "Problem Value & Impact — 25%",
            "Real-world relevance",
            "Authentic business pain",
            "Product potential",
            "Scalable adoption",
            "Trust story",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("impact and adoption material", False, "; ".join(failures))
    return Result(
        "impact and adoption material",
        True,
        "roadmap and blog draft prove real-world value, productization path, community potential, and optional blog narrative",
    )


def _check_judging_rubric_material() -> Result:
    required_paths = [
        ROOT / "docs" / "JUDGING_RUBRIC.md",
        ROOT / "docs" / "TRACK3_SCORECARD.md",
        ROOT / "docs" / "SUBMISSION.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "judging rubric material",
            False,
            "missing required rubric file(s): " + ", ".join(missing_paths),
        )

    rubric = _read(ROOT / "docs" / "JUDGING_RUBRIC.md")
    scorecard = _read(ROOT / "docs" / "TRACK3_SCORECARD.md")
    submission = _read(ROOT / "docs" / "SUBMISSION.md")

    checks = {
        "docs/JUDGING_RUBRIC.md": _missing_phrases(rubric, [
            "Stage One: Baseline Viability",
            "Fits the hackathon theme",
            "Uses required Qwen Cloud APIs",
            "Runs on Alibaba Cloud",
            "Stage Two Scorecard",
            "Innovation & AI Creativity — 30%",
            "Technical Depth & Engineering — 30%",
            "Problem Value & Impact — 25%",
            "Presentation & Documentation — 15%",
            "Sophisticated Qwen Cloud use",
            "Custom agent skills",
            "Non-trivial logic",
            "Architecture docs",
            "One-Sentence Judge Pitch",
            "100-Point Optimization Checklist",
        ]),
        "docs/TRACK3_SCORECARD.md": _missing_phrases(scorecard, [
            "Track 3 Judge Scorecard",
            "Agents with distinct capabilities",
            "Task division and role assignment",
            "Dialogue and negotiation",
            "Execution conflict resolution",
            "Measurable efficiency gain",
            "90-Second Verification Route",
            "speedup_factor > 1",
            "Why Track 3 Beats Track 4 For This Submission",
        ]),
        "docs/SUBMISSION.md": _missing_phrases(submission, [
            "## Rubric Mapping",
            "Technical Depth & Engineering",
            "Innovation & AI Creativity",
            "Problem Value & Impact",
            "Presentation & Documentation",
            "Track 3-specific proof points",
            "Task division:",
            "Disagreement resolution:",
            "Measurable collaboration:",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("judging rubric material", False, "; ".join(failures))
    return Result(
        "judging rubric material",
        True,
        "rubric docs map Stage One and all weighted criteria to concrete Track 3 evidence",
    )


def _check_public_repository_material() -> Result:
    required_paths = [
        ROOT / "docs" / "PUBLIC_REPOSITORY.md",
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / ".gitignore",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "docs" / "INSTALL_AND_RUN.md",
        ROOT / "deploy" / "alibaba-ecs" / "README.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "public repository material",
            False,
            "missing required repository file(s): " + ", ".join(missing_paths),
        )

    guide = _read(ROOT / "docs" / "PUBLIC_REPOSITORY.md")
    readme = _read(ROOT / "README.md")
    license_text = _read(ROOT / "LICENSE")
    gitignore = _read(ROOT / ".gitignore")
    workflow = _read(ROOT / ".github" / "workflows" / "ci.yml")

    checks = {
        "docs/PUBLIC_REPOSITORY.md": _missing_phrases(guide, [
            "public, open-source code repository",
            "Visibility: public",
            "License: detected as MIT from the root `LICENSE` file",
            "YITING — Track 3 Agent Society for governed incident response with Qwen",
            "contains `Track 3 Agent Society` and `Qwen`",
            "git status --short",
            "git ls-files",
            "This command should print nothing",
            "git remote add origin",
            "git remote set-url origin",
            "git push -u origin main",
            "git remote get-url origin",
            "private/incognito browser window",
            "README renders at the top",
            "`LICENSE` is visible and detected as MIT",
            "docs/INSTALL_AND_RUN.md",
            "deploy/alibaba-ecs/README.md",
            "`.env` and local database files are absent",
            ".github/workflows/ci.yml",
            "REPO_URL",
        ]),
        "README.md": _missing_phrases(readme, [
            "YITING",
            "Track 3: Agent Society",
            "docs/INSTALL_AND_RUN.md",
            "docs/PUBLIC_REPOSITORY.md",
            "## License",
            "MIT",
        ]),
        "LICENSE": _missing_phrases(license_text, [
            "MIT License",
            "Permission is hereby granted, free of charge",
        ]),
        ".gitignore": _missing_phrases(gitignore, [
            ".env",
            "*.db",
            "*.db-shm",
            "*.db-wal",
            "node_modules/",
            ".next/",
            "artifacts/*",
            "!artifacts/qwen-smoke.json",
            "!artifacts/track3-baseline.json",
            "!artifacts/track3-paired-benchmark.json",
            "!artifacts/track3-paired-benchmark-raw.json",
            "!artifacts/track3-paired-benchmark.csv",
            "!artifacts/deployment-verification.json",
            "!artifacts/hero-evidence.json",
            "!artifacts/final-proof-index.md",
        ]),
        ".github/workflows/ci.yml": _missing_phrases(workflow, [
            "actions/checkout",
            "uv lock --check",
            "uv sync --locked --all-groups",
            "pytest tests/",
            "scripts/submission_audit.py",
            "scripts/submission_status.py",
            "npm ci",
            "npm run build",
            "npm audit --audit-level=high",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("public repository material", False, "; ".join(failures))
    return Result(
        "public repository material",
        True,
        "repo guide, license, ignore rules, README, CI, and run docs cover public open-source publication",
    )


def _check_submission_text_description() -> Result:
    required_paths = [
        ROOT / "docs" / "SUBMISSION_FORM.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "README.md",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "submission text description",
            False,
            "missing required description file(s): " + ", ".join(missing_paths),
        )

    form = _read(ROOT / "docs" / "SUBMISSION_FORM.md")
    submission = _read(ROOT / "docs" / "SUBMISSION.md")
    readme = _read(ROOT / "README.md")

    checks = {
        "docs/SUBMISSION_FORM.md": _missing_phrases(form, [
            "## Project Name",
            "YITING",
            "## Tagline",
            "Evidence-bound Qwen agent society",
            "## Primary Track",
            "Track 3: Agent Society",
            "## Short Description",
            "## Long Description",
            "## What Makes It Track 3",
            "## Built With",
            "Qwen Cloud / Alibaba Cloud Model Studio",
            "Alibaba Cloud ECS",
            "Python, FastAPI, SQLite",
            "Next.js dashboard",
            "SHA-256 evidence chain",
            "human can approve, reject with instructions, or declare false alarm",
            "Verdict(CHALLENGE)",
            "StructuredApproval(REJECTED)",
            "speedup_factor > 1",
        ]),
        "docs/SUBMISSION.md": _missing_phrases(submission, [
            "## Text Description",
            "Suggested submission description:",
            "Qwen-backed agents triage alerts",
            "human gate for high-risk actions",
            "SHA-256 linked evidence chain",
            "Gateway owns state transitions",
            "## Rubric Mapping",
        ]),
        "README.md": _missing_phrases(readme, [
            "Evidence-bound incident council",
            "Track 3: Agent Society",
            "Three-Way Human Gate",
            "Application of Technology",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("submission text description", False, "; ".join(failures))
    return Result(
        "submission text description",
        True,
        "form packet and README explain features, functionality, Track 3 fit, and built-with stack",
    )


def _check_demo_media_compliance() -> Result:
    required_paths = [
        ROOT / "docs" / "DEMO_SCRIPT.md",
        ROOT / "docs" / "THIRD_PARTY_COMPLIANCE.md",
        ROOT / "scripts" / "finalize_submission.py",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "demo media compliance",
            False,
            "missing required demo/compliance file(s): " + ", ".join(missing_paths),
        )

    demo = _read(ROOT / "docs" / "DEMO_SCRIPT.md")
    compliance = _read(ROOT / "docs" / "THIRD_PARTY_COMPLIANCE.md")
    finalizer = _read(ROOT / "scripts" / "finalize_submission.py")
    checks = {
        "docs/DEMO_SCRIPT.md": _missing_phrases(demo, [
            "Target length: under 3 minutes",
            "three-minute mark",
            "2:55 as the hard edit target",
            "project UI, proof artifacts, and your own narration",
            "Do not add copyrighted music, unrelated third-party logos, stock footage, or external media",
            "Must-Capture Judge Shots",
            "Video contains no copyrighted music",
        ]),
        "docs/THIRD_PARTY_COMPLIANCE.md": _missing_phrases(compliance, [
            "The final demo video should be a screen recording of the project UI and proof artifacts only",
            "Do not add copyrighted music, unrelated third-party logos, or external media",
            "Incident data is synthetic or webhook-shaped sandbox telemetry",
        ]),
        "scripts/finalize_submission.py": _missing_phrases(finalizer, [
            "YouTube/Vimeo/Facebook Video",
            "video URL must be YouTube, Vimeo, or Facebook Video",
            "deployment-proof video URL",
            "youtube.com",
            "vimeo.com",
            "facebook.com",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("demo media compliance", False, "; ".join(failures))
    return Result(
        "demo media compliance",
        True,
        "demo docs enforce under-3-minute public video and permitted media/platform rules",
    )


def _check_third_party_compliance_material() -> Result:
    required_paths = [
        ROOT / "docs" / "THIRD_PARTY_COMPLIANCE.md",
        ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
        ROOT / "docs" / "PUBLIC_JUDGE_MODE.md",
        ROOT / ".env.example",
        ROOT / "deploy" / "alibaba-ecs" / "yiting.env.example",
        ROOT / "pyproject.toml",
        ROOT / "dashboard" / "package.json",
        ROOT / "LICENSE",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "third-party compliance material",
            False,
            "missing required compliance file(s): " + ", ".join(missing_paths),
        )

    compliance = _read(ROOT / "docs" / "THIRD_PARTY_COMPLIANCE.md")
    proof = _read(ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md")
    judge_mode = _read(ROOT / "docs" / "PUBLIC_JUDGE_MODE.md")
    env_examples = "\n".join([
        _read(ROOT / ".env.example"),
        _read(ROOT / "deploy" / "alibaba-ecs" / "yiting.env.example"),
    ])
    pyproject = _read(ROOT / "pyproject.toml")
    dashboard_package = _read(ROOT / "dashboard" / "package.json")
    license_text = _read(ROOT / "LICENSE")

    checks = {
        "docs/THIRD_PARTY_COMPLIANCE.md": _missing_phrases(compliance, [
            "third-party SDKs, APIs, data, assets, or media",
            "Qwen Cloud / Alibaba Cloud Model Studio",
            "entrant-provided `DASHSCOPE_API_KEY`",
            "`QWEN_API_KEY` is accepted only as a backward-compatible alias",
            "no model key is committed to the repository",
            "Alibaba Cloud ECS",
            "does not require a third-party chat-room service for judge mode",
            "MIT-licensed at `LICENSE`",
            "pyproject.toml",
            "dashboard/package.json",
            "node_modules",
            "Incident data is synthetic or webhook-shaped sandbox telemetry",
            "No customer data or proprietary production incident logs are included",
            "Do not add copyrighted music, unrelated third-party logos, or external media",
            "Paid or mutating actions are disabled or rejected in judge mode",
        ]),
        "docs/ALIBABA_CLOUD_PROOF.md": _missing_phrases(proof, [
            "Qwen Cloud / Alibaba Cloud Model Studio",
            "Alibaba Cloud ECS",
            "DASHSCOPE_API_KEY",
            "QWEN_API_KEY",
        ]),
        "docs/PUBLIC_JUDGE_MODE.md": _missing_phrases(judge_mode, [
            "read-only",
            "HTTP `403`",
            "YITING_LIVE_CHAOS",
        ]),
        ".env templates": _missing_phrases(env_examples, [
            "DASHSCOPE_API_KEY",
            "QWEN_BASE_URL",
            "YITING treats DASHSCOPE_API_KEY as the primary model credential",
            "QWEN_API_KEY is accepted only as a backward-compatible alias",
        ]),
        "pyproject.toml": _missing_phrases(pyproject, [
            "fastapi",
            "httpx",
            "litellm",
        ]),
        "dashboard/package.json": _missing_phrases(dashboard_package, [
            '"next"',
            '"react"',
            '"react-dom"',
        ]),
        "LICENSE": _missing_phrases(license_text, [
            "MIT License",
            "Permission is hereby granted, free of charge",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("third-party compliance material", False, "; ".join(failures))
    return Result(
        "third-party compliance material",
        True,
        "docs cover authorized Qwen/Alibaba use, declared dependencies, synthetic data, media hygiene, and judge-mode cost controls",
    )


def _check_install_and_run_material() -> Result:
    required_paths = [
        ROOT / "docs" / "INSTALL_AND_RUN.md",
        ROOT / "README.md",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "dashboard" / "package.json",
        ROOT / "Makefile",
        ROOT / "scripts" / "package_submission.py",
    ]
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_paths:
        return Result(
            "install and run material",
            False,
            "missing required install file(s): " + ", ".join(missing_paths),
        )

    install = _read(ROOT / "docs" / "INSTALL_AND_RUN.md")
    readme = _read(ROOT / "README.md")
    pyproject = _read(ROOT / "pyproject.toml")
    uv_lock = _read(ROOT / "uv.lock")
    dashboard_package = _read(ROOT / "dashboard" / "package.json")
    makefile = _read(ROOT / "Makefile")
    packager = _read(ROOT / "scripts" / "package_submission.py")

    checks = {
        "docs/INSTALL_AND_RUN.md": _missing_phrases(install, [
            "uv sync --locked",
            "npm ci",
            "npm run build",
            "make test",
            "make dashboard-build",
            "make local-certify",
            "make submission-package",
            "python scripts/submission_audit.py",
            "python scripts/submission_status.py",
            "make dev",
            "DASHSCOPE_API_KEY",
            "deploy/alibaba-ecs/bootstrap.sh",
            "python scripts/qwen_smoke.py",
            "python scripts/verify_deployment.py",
            "make submission-proof",
            "dist/yiting-submission-source.zip",
        ]),
        "README.md": _missing_phrases(readme, [
            "docs/INSTALL_AND_RUN.md",
            "uv sync",
            "make dev",
            "DASHSCOPE_API_KEY",
            "deploy/alibaba-ecs/",
        ]),
        "pyproject.toml": _missing_phrases(pyproject, [
            "[project]",
            'name = "yiting"',
            "requires-python",
            "dependencies = [",
            "[dependency-groups]",
            "pytest",
        ]),
        "uv.lock": _missing_phrases(uv_lock, [
            "version =",
            "requires-python",
            "[[package]]",
        ]),
        "dashboard/package.json": _missing_phrases(dashboard_package, [
            '"build": "next build"',
            '"next"',
            '"react"',
        ]),
        "Makefile": _missing_phrases(makefile, [
            "dev:",
            "test:",
            "dashboard-build:",
            "local-certify:",
            "submission-package:",
            "submission-proof:",
            "submission-ready:",
        ]),
        "scripts/package_submission.py": _missing_phrases(packager, [
            "yiting-submission-source.zip",
            "SUBMISSION_MANIFEST.json",
            "EXCLUDED_DIRS",
            "TRACK3_PROOF_SUMMARY",
        ]),
    }
    failures = [
        f"{path} missing {', '.join(repr(item) for item in missing)}"
        for path, missing in checks.items()
        if missing
    ]
    if failures:
        return Result("install and run material", False, "; ".join(failures))
    return Result(
        "install and run material",
        True,
        "docs and manifests cover locked install, local verification, hosted deployment, and source packaging",
    )


def _check_public_copy() -> list[Result]:
    public_files = [
        ROOT / "README.md",
        ROOT / "landing" / "index.html",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "JUDGE_PACKET.md",
        ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md",
        ROOT / "docs" / "JUDGING_RUBRIC.md",
        ROOT / "docs" / "ENGINEERING_PROOF.md",
        ROOT / "docs" / "BLOG_POST.md",
        ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "docs" / "SUBMISSION_FORM.md",
        ROOT / "docs" / "DEMO_SCRIPT.md",
        ROOT / "deploy" / "alibaba-ecs" / "README.md",
    ]
    forbidden = [
        "b" + "and",
        "aim" + "l",
        "feather" + "less",
        "app." + "b" + "and",
        "129." + "80",
        "or" + "acle",
        "war" + "room",
        "from " + "scratch",
        "re" + "build",
        "re" + "built",
        "previous " + "hackathon",
        "github.com/" + "yiting-ai/yiting",
        "github.com/" + "<",
        "github.com/" + "your",
    ]
    offenders: list[str] = []
    for path in public_files:
        if not path.exists():
            continue
        matches = _contains_any(path, forbidden)
        offenders.extend(f"{path.relative_to(ROOT)} contains {match!r}" for match in matches)
    detail = "clean" if not offenders else "; ".join(offenders)
    return [Result("public copy has no stale providers or placeholder repo links", not offenders, detail)]


def _check_secret_patterns() -> Result:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not _is_text_path(path):
            continue
        rel = path.relative_to(ROOT)
        if any(part in STALE_SCAN_SKIP_DIRS for part in rel.parts):
            continue
        if SECRET_PATTERN.search(_read(path)):
            offenders.append(rel.as_posix())
    if offenders:
        return Result(
            "credential pattern scan",
            False,
            "possible credential material in " + ", ".join(offenders[:8]),
        )
    return Result("credential pattern scan", True, "no credential-shaped secrets in text files")


def _check_local_absolute_paths() -> Result:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not _is_text_path(path):
            continue
        rel = path.relative_to(ROOT)
        if any(part in STALE_SCAN_SKIP_DIRS for part in rel.parts):
            continue
        text = _read(path)
        if any(pattern.search(text) for pattern in LOCAL_ABSOLUTE_PATH_PATTERNS):
            offenders.append(rel.as_posix())
    if offenders:
        return Result(
            "local absolute path scan",
            False,
            "local absolute paths in " + ", ".join(offenders[:8]),
        )
    return Result("local absolute path scan", True, "no local absolute paths in text files")


def _check_stale_generated_paths() -> Result:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in STALE_SCAN_SKIP_DIRS for part in rel.parts):
            continue
        if (
            rel.name in STALE_GENERATED_FILENAMES
            or rel.name.startswith("._")
            or rel.name.endswith((".backup", "~"))
            or rel.suffix in STALE_GENERATED_SUFFIXES
            or any(part in STALE_GENERATED_DIRS for part in rel.parts)
        ):
            offenders.append(rel.as_posix())
    if offenders:
        return Result(
            "stale generated file scan",
            False,
            "stale generated files in " + ", ".join(offenders[:8]),
        )
    return Result("stale generated file scan", True, "no stale generated files in release tree")


def _check_stale_public_text() -> Result:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not _is_text_path(path):
            continue
        rel = path.relative_to(ROOT)
        if any(part in STALE_SCAN_SKIP_DIRS for part in rel.parts):
            continue
        text = _read(path)
        for label, pattern in STALE_PUBLIC_TEXT_PATTERNS:
            if (rel.as_posix(), label) in STALE_PUBLIC_TEXT_ALLOWED:
                continue
            if pattern.search(text):
                offenders.append(f"{rel.as_posix()} contains {label}")
                break
    if offenders:
        return Result(
            "stale public text scan",
            False,
            "stale public text in " + ", ".join(offenders[:8]),
        )
    return Result("stale public text scan", True, "no stale origin or provider text in release tree")


def _check_track_choice_locked() -> Result:
    required_phrases = {
        "README.md": [
            "choose Track 3: Agent Society",
            "secondary outcome, not the selected track",
        ],
        "docs/SUBMISSION.md": [
            "Select Track 3 in the hackathon form",
            "not the primary submission category",
        ],
        "docs/SUBMISSION_FORM.md": [
            "Select Track 3 in the form",
            "Do not choose Track 4 as the primary category",
        ],
        "docs/JUDGE_PACKET.md": [
            "evaluated as Track 3: Agent Society",
            "judged behavior is the collaboration itself",
        ],
    }
    missing: list[str] = []
    for rel_path, phrases in required_phrases.items():
        text = " ".join(_read(ROOT / rel_path).split())
        for phrase in phrases:
            if phrase not in text:
                missing.append(f"{rel_path} missing {phrase!r}")
    detail = "Track 3 form choice is explicit" if not missing else "; ".join(missing)
    return Result("Track 3 submission choice locked", not missing, detail)


def _check_track3_baseline_artifact() -> Result:
    path = ROOT / "artifacts" / "track3-baseline.json"
    if not path.exists():
        return Result("Track 3 baseline artifact finalized", False, "artifacts/track3-baseline.json missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("Track 3 baseline artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("project") != "YITING":
        failures.append("project is not YITING")
    if data.get("proof_type") != "track3-manual-baseline":
        failures.append("wrong proof_type")
    if data.get("schema_version") != 2:
        failures.append("schema_version must be 2")
    speedup = data.get("speedup_factor")
    if not isinstance(speedup, (int, float)) or speedup <= 1:
        failures.append("speedup_factor must be > 1")

    baseline = data.get("baseline")
    if not isinstance(baseline, dict):
        failures.append("missing baseline object")
    else:
        label = str(baseline.get("label", "")).strip()
        if not label or "<" in label:
            failures.append("baseline.label must describe how the baseline was measured")
        family = str(baseline.get("incident_family", "")).strip()
        if not family or family == "same incident family as the hosted hero run" or "<" in family:
            failures.append("baseline.incident_family must name the compared incident family")
        measured = baseline.get("measured_seconds")
        if not isinstance(measured, int) or measured <= 0:
            failures.append("baseline.measured_seconds must be positive")
        source_requirement = str(baseline.get("source_requirement", "")).strip()
        if "Measured outside YITING" not in source_requirement:
            failures.append("baseline.source_requirement must document an outside-YITING measurement")

    method = data.get("comparison_method")
    expected_formula = "baseline.measured_seconds / yiting.avg_total_resolution_seconds"
    if not isinstance(method, dict) or method.get("formula") != expected_formula:
        failures.append("comparison_method.formula mismatch")
    elif "same incident family" not in str(method.get("fairness_rule", "")):
        failures.append("comparison_method.fairness_rule must require same incident family")
    elif "Terminal incident state" not in str(method.get("terminal_criterion", "")):
        failures.append("comparison_method.terminal_criterion must describe the terminal state")
    elif "scripts/verify_deployment.py --require-speedup" not in str(method.get("hosted_verifier", "")):
        failures.append("comparison_method.hosted_verifier must point to --require-speedup verifier")

    yiting = data.get("yiting")
    if not isinstance(yiting, dict):
        failures.append("missing yiting comparison object")
    else:
        for key in (
            "avg_total_resolution_seconds",
            "incidents_measured",
            "total_handoffs",
            "disagreement_events",
            "human_interventions",
            "recovery_verified_count",
        ):
            value = yiting.get(key)
            if not isinstance(value, (int, float)) or value <= 0:
                failures.append(f"yiting.{key} must be positive")
        scope = yiting.get("comparison_scope")
        if scope == "same-family runsummary runs":
            matched = yiting.get("matched_run_count")
            incidents = yiting.get("matched_incident_ids")
            if not isinstance(matched, int) or matched <= 0:
                failures.append("same-family comparison must include matched_run_count > 0")
            if not isinstance(incidents, list) or not incidents:
                failures.append("same-family comparison must include matched_incident_ids")
        elif scope != "runsummary aggregate average":
            failures.append("yiting.comparison_scope must describe the comparison basis")

    checks = data.get("track3_requirements_checked")
    if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
        failures.append("track3_requirements_checked must all be true")

    detail = "valid baseline proof" if not failures else "; ".join(failures)
    return Result("Track 3 baseline artifact finalized", not failures, detail, True)


def _check_track3_paired_benchmark_artifacts() -> Result:
    summary_path = ROOT / "artifacts" / "track3-paired-benchmark.json"
    raw_json_path = ROOT / "artifacts" / "track3-paired-benchmark-raw.json"
    raw_csv_path = ROOT / "artifacts" / "track3-paired-benchmark.csv"
    missing = [
        str(path.relative_to(ROOT))
        for path in (summary_path, raw_json_path, raw_csv_path)
        if not path.exists()
    ]
    if missing:
        return Result("Track 3 paired benchmark artifacts", False, "missing " + ", ".join(missing))
    try:
        summary = _read_json(summary_path)
        raw = _read_json(raw_json_path)
        csv_text = raw_csv_path.read_text(encoding="utf-8")
    except Exception as exc:
        return Result("Track 3 paired benchmark artifacts", False, f"unreadable: {exc}")

    failures: list[str] = []
    if summary.get("project") != "YITING":
        failures.append("project is not YITING")
    if summary.get("proof_type") != "track3-paired-reproducible-benchmark":
        failures.append("wrong proof_type")
    if summary.get("schema_version") != 1:
        failures.append("schema_version must be 1")
    dataset_id = str(summary.get("dataset_id", ""))
    rubric_version = str(summary.get("rubric_version", ""))
    if not dataset_id:
        failures.append("dataset_id is required")
    if not rubric_version:
        failures.append("rubric_version is required")
    if summary.get("scenario_count", 0) < 10:
        failures.append("scenario_count must be at least 10")
    if summary.get("scenario_count") != 20:
        failures.append("scenario_count should use the preferred 20 fixed scenarios")
    if summary.get("paired_runs_per_scenario", 0) < 3:
        failures.append("paired_runs_per_scenario must be at least 3")

    controls = summary.get("fairness_controls")
    if not isinstance(controls, dict):
        failures.append("missing fairness_controls")
    else:
        required_true = [
            "same_input_scenarios",
            "same_declared_rubric",
            "same_model_tier",
            "token_normalized_reporting",
        ]
        for key in required_true:
            if controls.get(key) is not True:
                failures.append(f"fairness_controls.{key} must be true")
        if controls.get("manual_removal_of_failed_cases") is not False:
            failures.append("manual_removal_of_failed_cases must be false")

    model_control = summary.get("model_control")
    if not isinstance(model_control, dict):
        failures.append("missing model_control")
    elif model_control.get("same_model_for_single_agent_and_society") is not True:
        failures.append("model_control.same_model_for_single_agent_and_society must be true")

    variants = summary.get("variants")
    if not isinstance(variants, dict):
        failures.append("missing variants")
    else:
        single = variants.get("single_agent")
        society = variants.get("full_yiting_society")
        if not isinstance(single, dict) or not isinstance(society, dict):
            failures.append("missing single_agent or full_yiting_society variant")
        else:
            if society.get("success_rate", 0) <= single.get("success_rate", 0):
                failures.append("society success_rate must exceed single_agent")
            if society.get("mean_score", 0) <= single.get("mean_score", 0):
                failures.append("society mean_score must exceed single_agent")
            if society.get("risks_detected", 0) <= single.get("risks_detected", 0):
                failures.append("society risks_detected must exceed single_agent")
            if society.get("unsupported_claims", 1) >= single.get("unsupported_claims", 0):
                failures.append("society unsupported_claims must be lower than single_agent")
            single_quality = single.get("quality_per_1k_tokens")
            society_quality = society.get("quality_per_1k_tokens")
            if not isinstance(single_quality, (int, float)) or not isinstance(society_quality, (int, float)):
                failures.append("variants must include numeric quality_per_1k_tokens")
            elif society_quality <= single_quality:
                failures.append("society quality_per_1k_tokens must exceed single_agent")

    comparison = summary.get("comparison")
    if not isinstance(comparison, dict):
        failures.append("missing comparison")
    else:
        for key in (
            "higher_task_success",
            "better_mean_score",
            "lower_unsupported_claim_rate",
            "more_risks_detected",
            "better_quality_per_token",
        ):
            if comparison.get(key) is not True:
                failures.append(f"comparison.{key} must be true")
        if comparison.get("speed_improvement_claimed") is not False:
            failures.append("comparison.speed_improvement_claimed must be false")
    claims_not_made = summary.get("claims_not_made")
    if not isinstance(claims_not_made, list) or "speed improvement" not in claims_not_made:
        failures.append("claims_not_made must include speed improvement")

    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) < 20:
        failures.append("raw JSON must include benchmark rows")
    elif len(rows) != summary.get("scenario_count", 0) * summary.get("paired_runs_per_scenario", 0) * 2:
        failures.append("raw JSON row count must equal scenarios * paired runs * variants")
    else:
        pair_groups: dict[tuple[str, int], list[dict]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                failures.append(f"raw row {index} must be an object")
                continue
            variant = row.get("variant")
            if variant not in {"single_agent", "full_yiting_society"}:
                failures.append(f"raw row {index} has invalid variant")
            scenario_id = row.get("scenario_id")
            run_index = row.get("run_index")
            input_hash = row.get("input_hash")
            if not isinstance(scenario_id, str) or not scenario_id:
                failures.append(f"raw row {index}.scenario_id is required")
            if not isinstance(run_index, int) or run_index < 1:
                failures.append(f"raw row {index}.run_index must be a positive integer")
            if not isinstance(input_hash, str) or len(input_hash) != 64:
                failures.append(f"raw row {index}.input_hash must be a sha256 hex string")
            if row.get("same_model_as_pair") is not True:
                failures.append(f"raw row {index}.same_model_as_pair must be true")
            if dataset_id and row.get("dataset_id") != dataset_id:
                failures.append(f"raw row {index}.dataset_id must match summary")
            if rubric_version and row.get("rubric_version") != rubric_version:
                failures.append(f"raw row {index}.rubric_version must match summary")
            if isinstance(scenario_id, str) and isinstance(run_index, int):
                pair_groups.setdefault((scenario_id, run_index), []).append(row)
        expected_pairs = summary.get("scenario_count", 0) * summary.get("paired_runs_per_scenario", 0)
        if len(pair_groups) != expected_pairs:
            failures.append("raw JSON pair count must equal scenarios * paired runs")
        for key, items in pair_groups.items():
            variants_seen = {item.get("variant") for item in items}
            if variants_seen != {"single_agent", "full_yiting_society"} or len(items) != 2:
                failures.append(f"raw pair {key} must contain exactly single_agent and full_yiting_society")
                continue
            input_hashes = {item.get("input_hash") for item in items}
            model_identities = {item.get("model_identity") for item in items}
            if len(input_hashes) != 1:
                failures.append(f"raw pair {key} must share the same input_hash")
            if len(model_identities) != 1:
                failures.append(f"raw pair {key} must share the same model_identity")
    if "single_agent" not in csv_text or "full_yiting_society" not in csv_text:
        failures.append("raw CSV must include both variants")
    for header in ("scenario_id", "run_index", "variant", "input_hash", "model_identity"):
        if header not in csv_text.splitlines()[0].split(","):
            failures.append(f"raw CSV header must include {header}")

    detail = "valid paired benchmark proof" if not failures else "; ".join(failures)
    return Result("Track 3 paired benchmark artifacts", not failures, detail)


def _check_deployment_verification_artifact() -> Result:
    path = ROOT / "artifacts" / "deployment-verification.json"
    if not path.exists():
        return Result(
            "deployment verification artifact finalized",
            False,
            "artifacts/deployment-verification.json missing",
            True,
        )
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("deployment verification artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("project") != "YITING":
        failures.append("project is not YITING")
    if data.get("proof_type") != "alibaba-ecs-deployment-verification":
        failures.append("wrong proof_type")
    if data.get("primary_track") != "Track 3: Agent Society":
        failures.append("primary_track mismatch")
    proof_summary = data.get("track3_proof_summary")
    if not isinstance(proof_summary, dict):
        failures.append("missing track3_proof_summary")
    else:
        if proof_summary.get("primary_track") != "Track 3: Agent Society":
            failures.append("track3_proof_summary primary_track mismatch")
        required_showcase = proof_summary.get("required_showcase")
        if not isinstance(required_showcase, dict):
            failures.append("track3_proof_summary missing required_showcase")
        else:
            for key in (
                "distinct_capabilities",
                "task_decomposition",
                "dialogue_and_negotiation",
                "disagreement_resolution",
                "execution_conflict_resolution",
                "measurable_efficiency_gain",
            ):
                if key not in required_showcase:
                    failures.append(f"track3_proof_summary missing {key}")
    if data.get("passed") is not True:
        failures.append("passed must be true")

    targets = data.get("targets")
    if not isinstance(targets, dict):
        failures.append("missing targets object")
    else:
        if targets.get("require_speedup") is not True:
            failures.append("targets.require_speedup must be true")
        if targets.get("require_public_read_only") is not True:
            failures.append("targets.require_public_read_only must be true")
        incident_id = str(targets.get("incident_id", "")).strip()
        if not incident_id or "<" in incident_id:
            failures.append("targets.incident_id must be finalized")
        public_url = str(targets.get("public_url", "")).strip()
        if not public_url.startswith("https://") or "<" in public_url:
            failures.append("targets.public_url must be finalized https URL")

    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        failures.append("checks must be a nonempty list")
    elif not all(isinstance(item, dict) and item.get("ok") is True for item in checks):
        failures.append("all deployment checks must pass")

    detail = "valid deployment verification" if not failures else "; ".join(failures)
    return Result("deployment verification artifact finalized", not failures, detail, True)


def _check_hero_evidence_artifact() -> Result:
    path = ROOT / "artifacts" / "hero-evidence.json"
    if not path.exists():
        return Result("hero evidence artifact finalized", False, "artifacts/hero-evidence.json missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("hero evidence artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    incident_id = str(data.get("incident_id", "")).strip()
    if not incident_id or "<" in incident_id:
        failures.append("incident_id must be a concrete hero incident id")
    if data.get("state") != "EXECUTED":
        failures.append("state must be EXECUTED")
    if data.get("chain_valid") is not True:
        failures.append("chain_valid must be true")
    incident_family = str(data.get("incident_family", "")).strip()
    if not incident_family or incident_family == "unknown" or "<" in incident_family:
        failures.append("incident_family must name the hero incident family")
    cards = data.get("cards")
    if not isinstance(cards, list) or len(cards) < 7:
        failures.append("cards must contain at least 7 entries")
    if isinstance(cards, list):
        card_types = {
            str(card.get("card_type", ""))
            for card in cards
            if isinstance(card, dict)
        }
        if "ActionReceipt" not in card_types:
            failures.append("cards must include ActionReceipt")
    collaboration = data.get("collaboration")
    if not isinstance(collaboration, dict):
        failures.append("missing collaboration block")
    else:
        required_keys = {
            "role_sequence",
            "handoff_count",
            "challenge_count",
            "human_decision_count",
            "authorization_path",
            "execution_conflict_control",
        }
        missing_keys = sorted(required_keys - set(collaboration))
        if missing_keys:
            failures.append("collaboration missing keys: " + ", ".join(missing_keys))
        role_sequence = collaboration.get("role_sequence")
        if not isinstance(role_sequence, list):
            failures.append("role_sequence must be a list")
        else:
            missing_roles = sorted(REQUIRED_SOCIETY_ROLES - set(role_sequence))
            if missing_roles:
                failures.append("role_sequence missing roles: " + ", ".join(missing_roles))
        handoff_count = collaboration.get("handoff_count")
        if not isinstance(handoff_count, int) or handoff_count < 5:
            failures.append("handoff_count must be >= 5")
        counts: dict[str, int] = {}
        for key in ("challenge_count", "human_decision_count"):
            value = collaboration.get(key)
            if not isinstance(value, int) or value < 0:
                failures.append(f"{key} must be a non-negative integer")
            else:
                counts[key] = value
        human_decisions = collaboration.get("human_decisions")
        if not isinstance(human_decisions, list):
            failures.append("human_decisions must be a list")
            human_rejection_count = 0
        else:
            human_rejection_count = sum(
                1 for item in human_decisions
                if isinstance(item, dict) and item.get("decision") == "REJECTED"
            )
        if counts.get("challenge_count", 0) + human_rejection_count <= 0:
            failures.append(
                "hero evidence must include Verdict(CHALLENGE) or "
                "StructuredApproval(REJECTED)"
            )
        if collaboration.get("authorization_path") not in VALID_AUTHORIZATION_PATHS:
            failures.append("authorization_path must be StructuredApproval or PolicyAuthorization")
        elif (
            collaboration.get("authorization_path") == "StructuredApproval"
            and counts.get("human_decision_count", 0) <= 0
        ):
            failures.append("StructuredApproval hero evidence must include a human decision")
        conflict = collaboration.get("execution_conflict_control")
        if not isinstance(conflict, dict) or conflict.get("exact_match") is not True:
            failures.append("execution_conflict_control.exact_match must be true")

    detail = "valid hero evidence" if not failures else "; ".join(failures)
    return Result("hero evidence artifact finalized", not failures, detail, True)


def _check_final_proof_index_artifact() -> Result:
    path = ROOT / "artifacts" / "final-proof-index.md"
    if not path.exists():
        return Result("final proof index finalized", False, "artifacts/final-proof-index.md missing", True)
    text = _read(path)
    required = [
        "YITING Final Proof Index",
        "Track 3: Agent Society",
        "Hero incident",
        "Qwen smoke",
        "Paired quality benchmark",
        "Hosted timing speedup",
        "Backup restore proof",
        "Required Track 3 Showcase",
        "Task decomposition and handoffs",
        "Execution conflict resolution",
        "Measured quality and timing proof",
        "Public read-only required",
        "Public chaos disabled check",
        "Evidence chain valid",
        "Weighted Judge Score Map",
        "Innovation & AI Creativity — 30%",
        "Technical Depth & Engineering — 30%",
        "Problem Value & Impact — 25%",
        "Presentation & Documentation — 15%",
        "Reviewer Cross-Checks",
        "Track 3 is primary",
        "Live Qwen smoke passed",
        "MCP-style registry and review manifest",
        "not a network MCP server",
        "measured same-family baseline",
        "does not claim speed",
        "Public read-only judge mode required",
        "Exact-envelope execution",
        "Persistence safety",
        "Submission Requirement Cross-Checks",
        "Installability",
        "Public open-source repository",
        "Alibaba Cloud proof",
        "Architecture diagram",
        "Demo media compliance",
        "Final submission runbook",
        "artifacts/track3-paired-benchmark.json",
        "artifacts/live/backup-restore.json",
        "artifacts/hero-evidence.json",
        "dist/yiting-submission-source.zip",
        "docs/INSTALL_AND_RUN.md",
        "docs/PUBLIC_REPOSITORY.md",
        "docs/ARCHITECTURE.md",
        "docs/ALIBABA_CLOUD_PROOF.md",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "docs/FINAL_SUBMISSION_CHECKLIST.md",
    ]
    missing = [phrase for phrase in required if phrase not in text]
    detail = "valid final proof index" if not missing else "missing: " + ", ".join(missing)
    return Result("final proof index finalized", not missing, detail, True)


def _check_source_package_artifact() -> Result:
    path = ROOT / "dist" / "yiting-submission-source.zip"
    if not path.exists():
        return Result("source package finalized", False, "dist/yiting-submission-source.zip missing", True)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("SUBMISSION_MANIFEST.json"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest root was not an object")
    except Exception as exc:
        return Result("source package finalized", False, f"manifest unreadable: {exc}", True)

    current_commit = _git_commit()
    package_commit = str(manifest.get("git_commit", "")).strip()
    failures: list[str] = []
    if package_commit != current_commit:
        failures.append(f"package commit {package_commit or '<missing>'} != current {current_commit or '<unknown>'}")
    if manifest.get("working_tree_clean") is not True:
        failures.append("package was built from a dirty working tree")
    if not _git_worktree_clean():
        failures.append("current working tree has uncommitted changes")
    proof_summary = manifest.get("track3_proof_summary")
    if not isinstance(proof_summary, dict):
        failures.append("missing track3_proof_summary")
    else:
        if proof_summary.get("primary_track") != "Track 3: Agent Society":
            failures.append("track3_proof_summary primary_track mismatch")
        required_showcase = proof_summary.get("required_showcase")
        expected_showcase = {
            "distinct_capabilities",
            "task_decomposition",
            "dialogue_and_negotiation",
            "disagreement_resolution",
            "execution_conflict_resolution",
            "measurable_efficiency_gain",
        }
        if not isinstance(required_showcase, dict):
            failures.append("track3_proof_summary missing required_showcase")
        else:
            missing = sorted(expected_showcase - set(required_showcase))
            if missing:
                failures.append("track3_proof_summary missing " + ", ".join(missing))
            efficiency = required_showcase.get("measurable_efficiency_gain", {})
            efficiency_text = json.dumps(efficiency)
            required_terms = [
                "speed_improvement_claimed=false",
                "higher task success",
                "lower unsupported-claim",
                "better quality per token",
                "speedup_factor > 1",
            ]
            for term in required_terms:
                if term not in efficiency_text:
                    failures.append(f"track3_proof_summary missing {term} check")

    detail = "current clean source package" if not failures else "; ".join(failures)
    return Result("source package finalized", not failures, detail, True)


def _check_qwen_config() -> list[Result]:
    env_examples = [
        ROOT / ".env.example",
        ROOT / "deploy" / "alibaba-ecs" / "yiting.env.example",
    ]
    combined_text = "\n".join(_read(path) for path in env_examples if path.exists())
    source_names = ", ".join(str(path.relative_to(ROOT)) for path in env_examples)
    forbidden_source_credentials = [
        "OPENAI_API_KEY=",
        "OPENAI_API_BASE=",
        "OPENAI_BASE_URL=",
    ]
    results = [
        Result("DashScope key documented", "DASHSCOPE_API_KEY" in combined_text, source_names),
        Result("Qwen endpoint documented", "QWEN_BASE_URL" in combined_text, source_names),
        Result(
            "removed-provider env vars absent",
            all(term not in combined_text for term in ["AIM" + "L", "FEATHER", "B" + "AND_API"]),
            source_names,
        ),
        Result(
            "Qwen env templates avoid generic source credentials",
            all(term not in combined_text for term in forbidden_source_credentials),
            source_names,
        ),
    ]
    return results


def _check_qwen_smoke_artifact() -> Result:
    path = ROOT / "artifacts" / "qwen-smoke.json"
    if not path.exists():
        return Result("Qwen Cloud smoke artifact finalized", False, "artifacts/qwen-smoke.json missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("Qwen Cloud smoke artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("project") != "YITING":
        failures.append("project is not YITING")
    if data.get("proof_type") != "qwen-cloud-smoke":
        failures.append("wrong proof_type")
    if data.get("artifact_class") != "live_qwen_smoke":
        failures.append("artifact_class must be live_qwen_smoke")
    if data.get("submission_evidence") is not True or data.get("verified_live") is not True:
        failures.append("Qwen smoke proof must be credential-backed live submission evidence")
    if data.get("schema_version") != 1:
        failures.append("schema_version must be 1")
    if data.get("passed") is not True:
        failures.append("passed must be true")
    if data.get("provider") != "qwen":
        failures.append("provider must be qwen")
    model = str(data.get("model", ""))
    if "qwen" not in model.lower():
        failures.append("model must name qwen")
    base_url = str(data.get("base_url", ""))
    if not base_url.startswith("https://"):
        failures.append("base_url must be an https URL")
    response = data.get("response")
    if not isinstance(response, dict) or response.get("ok") is not True:
        failures.append("response.ok must be true")
    else:
        if "provider_request_id" not in response:
            failures.append("response.provider_request_id key is required")
        response_usage = response.get("usage")
        if not isinstance(response_usage, dict):
            failures.append("response.usage key is required")
        else:
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = response_usage.get(field)
                if not isinstance(value, int) or value <= 0:
                    failures.append(f"response.usage.{field} must be a positive integer")

    capability_matrix = data.get("capability_matrix")
    if not isinstance(capability_matrix, dict) or not capability_matrix:
        failures.append("capability_matrix must be a non-empty object")
    else:
        for model_name, capabilities in capability_matrix.items():
            if not isinstance(capabilities, dict):
                failures.append(f"capability_matrix.{model_name} must be an object")
                continue
            if capabilities.get("chat") != "required":
                failures.append(f"capability_matrix.{model_name}.chat must be required")
            if capabilities.get("structured_output") != "required":
                failures.append(f"capability_matrix.{model_name}.structured_output must be required")
            if capabilities.get("tools") not in {"required", "not_used", "test_if_used", "not_assumed"}:
                failures.append(f"capability_matrix.{model_name}.tools has an unsupported value")

    checks = data.get("checks")
    if not isinstance(checks, dict) or not checks:
        failures.append("checks must be a non-empty object")
    else:
        for name, check in checks.items():
            if not isinstance(check, dict):
                failures.append(f"check {name} must be an object")
                continue
            if check.get("ok") is not True:
                failures.append(f"check {name}.ok must be true")
            requested_model = str(check.get("requested_model", ""))
            returned_model = str(check.get("returned_model", ""))
            if "qwen" not in requested_model.lower():
                failures.append(f"check {name}.requested_model must name qwen")
            if "qwen" not in returned_model.lower():
                failures.append(f"check {name}.returned_model must name qwen")
            if "response_id" not in check:
                failures.append(f"check {name}.response_id key is required")
            if "provider_request_id" not in check:
                failures.append(f"check {name}.provider_request_id key is required")
            latency_ms = check.get("latency_ms")
            if not isinstance(latency_ms, int) or latency_ms < 0:
                failures.append(f"check {name}.latency_ms must be a non-negative integer")
            usage = check.get("usage")
            if not isinstance(usage, dict):
                failures.append(f"check {name}.usage must be an object")
            else:
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = usage.get(field)
                    if not isinstance(value, int) or value <= 0:
                        failures.append(f"check {name}.usage.{field} must be a positive integer")
            capabilities = check.get("capabilities")
            if not isinstance(capabilities, dict) or capabilities.get("chat") != "required":
                failures.append(f"check {name}.capabilities.chat must be required")
            elif capabilities.get("structured_output") != "required":
                failures.append(f"check {name}.capabilities.structured_output must be required")
            elif capabilities.get("tools") not in {"required", "not_used", "test_if_used", "not_assumed"}:
                failures.append(f"check {name}.capabilities.tools has an unsupported value")

    serialized = json.dumps(data, ensure_ascii=False).lower()
    for marker in ("api_key", "dashscope_api_key", "qwen_api_key", "sk-"):
        if marker in serialized:
            failures.append(f"Qwen smoke proof must not contain secret marker {marker!r}")

    detail = "valid Qwen smoke proof" if not failures else "; ".join(failures)
    return Result("Qwen Cloud smoke artifact finalized", not failures, detail, True)


def _check_docker_image_smoke_artifact() -> Result:
    path = ROOT / "artifacts" / "docker-image-smoke.json"
    if not path.exists():
        return Result("Docker image smoke artifact", False, "artifacts/docker-image-smoke.json missing")
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("Docker image smoke artifact", False, f"unreadable: {exc}")

    failures: list[str] = []
    if data.get("format") != "yiting-docker-image-smoke-v1":
        failures.append("format must be yiting-docker-image-smoke-v1")
    if data.get("project") != "YITING":
        failures.append("project is not YITING")
    if data.get("passed") is not True:
        failures.append("passed must be true")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        failures.append("checks must be an object")
        checks = {}

    gateway = checks.get("gateway")
    if not isinstance(gateway, dict):
        failures.append("checks.gateway must be an object")
    else:
        if gateway.get("ok") is not True:
            failures.append("checks.gateway.ok must be true")
        if gateway.get("health_status") != 200:
            failures.append("checks.gateway.health_status must be 200")
        if gateway.get("ready_status") != 200:
            failures.append("checks.gateway.ready_status must be 200")
        if gateway.get("qwen_required") is not False:
            failures.append("checks.gateway.qwen_required must be false for non-production image smoke")

    victim = checks.get("victim")
    if not isinstance(victim, dict):
        failures.append("checks.victim must be an object")
    else:
        if victim.get("ok") is not True:
            failures.append("checks.victim.ok must be true")
        if victim.get("status_code") != 200:
            failures.append("checks.victim.status_code must be 200")
        if victim.get("source") != "live_synthetic_telemetry":
            failures.append("checks.victim.source must be live_synthetic_telemetry")

    dashboard = checks.get("dashboard")
    if not isinstance(dashboard, dict):
        failures.append("checks.dashboard must be an object")
    else:
        if dashboard.get("ok") is not True:
            failures.append("checks.dashboard.ok must be true")
        if dashboard.get("status_code") != 200:
            failures.append("checks.dashboard.status_code must be 200")
        if dashboard.get("base_path") != "/dashboard":
            failures.append("checks.dashboard.base_path must be /dashboard")

    production_negative = checks.get("production_negative")
    if not isinstance(production_negative, dict):
        failures.append("checks.production_negative must be an object")
    else:
        if production_negative.get("ok") is not True:
            failures.append("checks.production_negative.ok must be true")
        if production_negative.get("status_code") != 503:
            failures.append("checks.production_negative.status_code must be 503")
        if production_negative.get("qwen_required") is not True:
            failures.append("checks.production_negative.qwen_required must be true")
        if production_negative.get("qwen_ready") is not False:
            failures.append("checks.production_negative.qwen_ready must be false")
        errors = production_negative.get("errors")
        if not isinstance(errors, list):
            failures.append("checks.production_negative.errors must be a list")
        else:
            error_text = "\n".join(str(error) for error in errors)
            for marker in ("DASHSCOPE_API_KEY is required", "QWEN_BASE_URL must be set explicitly"):
                if marker not in error_text:
                    failures.append(f"checks.production_negative.errors must include {marker!r}")

    serialized = json.dumps(data, ensure_ascii=False)
    if SECRET_PATTERN.search(serialized):
        failures.append("Docker image smoke proof must not contain credential-shaped secrets")

    detail = "valid Docker image smoke proof" if not failures else "; ".join(failures)
    return Result("Docker image smoke artifact", not failures, detail)


def _check_ecs_ops_acceptance_artifact() -> Result:
    path = ROOT / "artifacts" / "live" / "ecs-ops-acceptance.json"
    if not path.exists():
        return Result(
            "ECS operations acceptance artifact finalized",
            False,
            "artifacts/live/ecs-ops-acceptance.json missing",
            True,
        )
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("ECS operations acceptance artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("format") != "shared-ecs-ops-acceptance-v1":
        failures.append("format must be shared-ecs-ops-acceptance-v1")
    if data.get("passed") is not True:
        failures.append("passed must be true")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        failures.append("checks must be a nonempty list")
        checks_by_name: dict[str, bool] = {}
    else:
        checks_by_name = {
            str(check.get("name")): check.get("ok") is True
            for check in checks
            if isinstance(check, dict)
        }
    for check_name in REQUIRED_ECS_OPS_CHECKS:
        aliases = ECS_OPS_CHECK_ALIASES.get(check_name, ())
        if checks_by_name.get(check_name) is not True and not any(
            checks_by_name.get(alias) is True for alias in aliases
        ):
            failures.append(f"missing passing check: {check_name}")
    if not any(name.startswith("disk use below ") for name, ok in checks_by_name.items() if ok):
        failures.append("missing passing disk-use check")
    if not any(name.startswith("container memory below ") for name, ok in checks_by_name.items() if ok):
        failures.append("missing passing container memory check")

    detail = "valid ECS operations acceptance proof" if not failures else "; ".join(failures)
    return Result("ECS operations acceptance artifact finalized", not failures, detail, True)


def _submission_link_url_errors(value: Any, field_name: str, *, video: bool = False) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{field_name} must be a non-empty URL"]
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    errors: list[str] = []
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"{field_name} must be public https")
    if "<" in value or ">" in value or any(marker in value.upper() for marker in ("PUBLIC_", "YOUR_", "TODO", "TBD")):
        errors.append(f"{field_name} contains placeholder text")
    if (
        host in {"localhost", "127.0.0.1", "example.com", "example.net", "example.org"}
        or "yourdomain" in host
        or host.endswith((".example", ".example.com", ".example.net", ".example.org", ".test", ".invalid"))
    ):
        errors.append(f"{field_name} is not a finalized public host")
    if video and not (host in PUBLIC_VIDEO_HOSTS or host.endswith(".facebook.com")):
        errors.append(f"{field_name} must be YouTube, Vimeo, or Facebook Video")
    return errors


def _check_submission_links_artifact() -> Result:
    path = ROOT / "artifacts" / "live" / "submission-links.json"
    if not path.exists():
        return Result("public submission links artifact finalized", False, str(path.relative_to(ROOT)) + " missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("public submission links artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("artifact_class") != "public_submission_links":
        failures.append("artifact_class must be public_submission_links")
    if data.get("submission_evidence") is not True or data.get("verified_live") is not True:
        failures.append("artifact must be marked as verified live submission evidence")

    for field_name in SUBMISSION_LINK_FIELDS:
        failures.extend(
            _submission_link_url_errors(
                data.get(field_name),
                field_name,
                video=field_name in {"demo_video_url", "deployment_proof_video_url"},
            )
        )
    if "blog_url" in data:
        failures.extend(_submission_link_url_errors(data.get("blog_url"), "blog_url"))

    repository = urlparse(str(data.get("repository_url", "")))
    repo_parts = [part for part in repository.path.strip("/").split("/") if part]
    if repository.hostname != "github.com" or len(repo_parts) != 2 or repo_parts[-1].removesuffix(".git") != "yiting":
        failures.append("repository_url must be the public GitHub repository named yiting")
    if data.get("demo_video_url") == data.get("deployment_proof_video_url"):
        failures.append("demo_video_url and deployment_proof_video_url must be separate public videos")

    if not isinstance(data.get("reachability_checked_at"), str) or not data.get("reachability_checked_at"):
        failures.append("reachability_checked_at is required")
    reachability = data.get("public_reachability")
    if not isinstance(reachability, dict):
        failures.append("public_reachability is required")
        reachability = {}
    fields = [*SUBMISSION_LINK_FIELDS, *(["blog_url"] if "blog_url" in data else [])]
    for field_name in fields:
        check = reachability.get(field_name)
        if not isinstance(check, dict):
            failures.append(f"public_reachability.{field_name} missing")
            continue
        if check.get("url") != data.get(field_name):
            failures.append(f"public_reachability.{field_name}.url mismatch")
        if check.get("passed") is not True:
            failures.append(f"public_reachability.{field_name}.passed must be true")
        status_code = check.get("status_code")
        if not isinstance(status_code, int) or status_code >= 400:
            failures.append(f"public_reachability.{field_name}.status_code must be successful")
        failures.extend(
            _submission_link_url_errors(
                check.get("final_url"),
                f"public_reachability.{field_name}.final_url",
                video=field_name in {"demo_video_url", "deployment_proof_video_url"},
            )
        )

    detail = "valid public submission link reachability proof" if not failures else "; ".join(failures)
    return Result("public submission links artifact finalized", not failures, detail, True)


def _check_uptime_monitoring_artifact() -> Result:
    path = ROOT / "artifacts" / "live" / "uptime-monitoring.json"
    if not path.exists():
        return Result("uptime monitoring artifact finalized", False, str(path.relative_to(ROOT)) + " missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("uptime monitoring artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("format") != "uptime-monitoring-v1":
        failures.append("format must be uptime-monitoring-v1")
    if data.get("artifact_class") != "external_uptime_monitoring":
        failures.append("artifact_class must be external_uptime_monitoring")
    if data.get("submission_evidence") is not True or data.get("verified_live") is not True:
        failures.append("artifact must be marked as verified live submission evidence")
    monitors = data.get("monitors")
    if not isinstance(monitors, list) or not monitors:
        failures.append("monitors must be a nonempty list")
        monitors_by_app: dict[str, dict[str, Any]] = {}
    else:
        monitors_by_app = {
            str(item.get("app", "")).lower(): item
            for item in monitors
            if isinstance(item, dict)
        }
    if "cotenant" in monitors_by_app and "neighbor" not in monitors_by_app:
        monitors_by_app["neighbor"] = monitors_by_app["cotenant"]
    for app in ("yiting",):
        monitor = monitors_by_app.get(app)
        if not monitor:
            failures.append(f"missing {app} monitor")
            continue
        if monitor.get("enabled") is not True:
            failures.append(f"{app}: enabled must be true")
        failures.extend(_submission_link_url_errors(monitor.get("target_url"), f"{app}.target_url"))
        failures.extend(_submission_link_url_errors(monitor.get("monitor_url"), f"{app}.monitor_url"))
        interval = monitor.get("interval_seconds")
        if not isinstance(interval, int) or interval <= 0 or interval > 300:
            failures.append(f"{app}: interval_seconds must be 1..300")
    for app, monitor in monitors_by_app.items():
        if app == "yiting":
            continue
        if monitor.get("enabled") is not True:
            failures.append(f"{app}: enabled must be true")
        failures.extend(_submission_link_url_errors(monitor.get("target_url"), f"{app}.target_url"))
        failures.extend(_submission_link_url_errors(monitor.get("monitor_url"), f"{app}.monitor_url"))
        interval = monitor.get("interval_seconds")
        if not isinstance(interval, int) or interval <= 0 or interval > 300:
            failures.append(f"{app}: interval_seconds must be 1..300")

    detail = "valid uptime monitoring proof" if not failures else "; ".join(failures)
    return Result("uptime monitoring artifact finalized", not failures, detail, True)


def _check_app_restart_resilience_artifact() -> Result:
    path = ROOT / "artifacts" / "live" / "app-restart-resilience.json"
    if not path.exists():
        return Result("app restart resilience artifact finalized", False, str(path.relative_to(ROOT)) + " missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("app restart resilience artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("format") != "shared-ecs-app-restart-resilience-v1":
        failures.append("format must be shared-ecs-app-restart-resilience-v1")
    if data.get("artifact_class") != "live_app_restart_resilience":
        failures.append("artifact_class must be live_app_restart_resilience")
    if data.get("submission_evidence") is not True or data.get("verified_live") is not True:
        failures.append("artifact must be marked as verified live submission evidence")
    if data.get("host_rebooted") is not False:
        failures.append("host_rebooted must be false")
    restart_scope = str(data.get("restart_scope") or "").lower()
    if "app-scoped" not in restart_scope and "compose" not in restart_scope:
        failures.append("restart_scope must describe app-scoped Compose restart")

    apps = data.get("apps")
    apps_by_name = {
        str(item.get("app", "")).lower(): item
        for item in apps
        if isinstance(item, dict)
    } if isinstance(apps, list) else {}
    for app in ("yiting", "cotenant"):
        proof = apps_by_name.get(app)
        if not proof:
            failures.append(f"missing {app} app restart proof")
            continue
        failures.extend(_submission_link_url_errors(proof.get("url"), f"{app}.url"))
        for field in ("healthy_after_restart", "state_persisted", "evidence_persisted", "logs_persisted"):
            if proof.get(field) is not True:
                failures.append(f"{app}: {field} must be true")

    detail = "valid app restart resilience proof" if not failures else "; ".join(failures)
    return Result("app restart resilience artifact finalized", not failures, detail, True)


def _check_backup_restore_artifact() -> Result:
    path = ROOT / "artifacts" / "live" / "backup-restore.json"
    if not path.exists():
        return Result("backup restore artifact finalized", False, str(path.relative_to(ROOT)) + " missing", True)
    try:
        data = _read_json(path)
    except Exception as exc:
        return Result("backup restore artifact finalized", False, f"unreadable: {exc}", True)

    failures: list[str] = []
    if data.get("format") != "yiting-backup-restore-v1":
        failures.append("format must be yiting-backup-restore-v1")
    if data.get("project") != "YITING":
        failures.append("project must be YITING")
    if data.get("artifact_class") != "live_backup_restore":
        failures.append("artifact_class must be live_backup_restore")
    if data.get("submission_evidence") is not True or data.get("verified_live") is not True:
        failures.append("artifact must be marked as verified live submission evidence")
    if data.get("passed") is not True:
        failures.append("passed must be true")
    if not isinstance(data.get("backup_dir_name"), str) or not data.get("backup_dir_name"):
        failures.append("backup_dir_name is required")

    backups = data.get("backups")
    if not isinstance(backups, list) or not backups:
        failures.append("backups must be a nonempty list")
        backups_by_label: dict[str, dict[str, Any]] = {}
    else:
        backups_by_label = {
            str(item.get("label")): item
            for item in backups
            if isinstance(item, dict)
        }
    for label in ("gateway", "victim"):
        item = backups_by_label.get(label)
        if not item:
            failures.append(f"missing {label} backup")
            continue
        if item.get("passed") is not True:
            failures.append(f"{label}.passed must be true")
        backup_name = item.get("backup_name")
        if not isinstance(backup_name, str) or not backup_name.endswith(".sqlite"):
            failures.append(f"{label}.backup_name must name a sqlite backup")
        if isinstance(backup_name, str) and ("/" in backup_name or "\\" in backup_name):
            failures.append(f"{label}.backup_name must be sanitized")
        size_bytes = item.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes <= 0:
            failures.append(f"{label}.size_bytes must be positive")
        sha256 = item.get("sha256")
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            failures.append(f"{label}.sha256 must be a 64-character digest")
        restore = item.get("restore")
        if not isinstance(restore, dict) or restore.get("ok") is not True:
            failures.append(f"{label}.restore.ok must be true")
        else:
            table_count = restore.get("table_count")
            if not isinstance(table_count, int) or table_count < 0:
                failures.append(f"{label}.restore.table_count must be non-negative")

    note = str(data.get("note", "")).lower()
    if "same-vm backups" not in note or "not total ecs host loss" not in note:
        failures.append("same-VM backup limitation must be disclosed")

    serialized = json.dumps(data, ensure_ascii=False).lower()
    for marker in ("password", "database_url", "sqlite://", "dashscope_api_key", "qwen_api_key", "sk-"):
        if marker in serialized:
            failures.append(f"backup restore proof must not contain secret marker {marker!r}")

    detail = "valid backup restore proof" if not failures else "; ".join(failures)
    return Result("backup restore artifact finalized", not failures, detail, True)


def _check_final_artifacts() -> list[Result]:
    remote = _git_remote()
    readme = _read(ROOT / "README.md")
    landing = _read(ROOT / "landing" / "index.html")
    judge_packet = _read(ROOT / "docs" / "JUDGE_PACKET.md")
    submission_form = _read(ROOT / "docs" / "SUBMISSION_FORM.md")
    placeholders = [
        "<your-yiting-domain>",
        "your-yiting-domain.example.com",
    ]
    hero_placeholders = [
        "HERO_INCIDENT_ID_PLACEHOLDER",
        "HERO_EVIDENCE_URL_PLACEHOLDER",
        "RUNSUMMARY_URL_PLACEHOLDER",
        "DASHBOARD_REPLAY_URL_PLACEHOLDER",
    ]
    missing_hero_links = [token for token in hero_placeholders if token in judge_packet]
    pending_hero_markers = [
        "Pending final hosted hero run",
        "human approval-password step",
    ]
    pending_hero_links = [token for token in pending_hero_markers if token in judge_packet]
    form_placeholders = [
        "https://<deployment-domain>",
        "<hero-incident-id>",
        "$PUBLIC_REPOSITORY_URL",
        "https://youtu.be/<video-id>",
        "https://youtu.be/<deployment-proof-video-id>",
    ]
    missing_form_links = [token for token in form_placeholders if token in submission_form]
    return [
        Result("public git remote configured", bool(remote), remote or "origin remote missing", True),
        Result(
            "deployment domain finalized",
            not any(token in readme for token in placeholders),
            "README still uses placeholder domain" if any(token in readme for token in placeholders) else "domain finalized",
            True,
        ),
        Result(
            "landing demo video finalized",
            "Demo video — available during live presentation" not in landing,
            "landing page still has demo-video placeholder",
            True,
        ),
        Result(
            "judge packet hero evidence finalized",
            not missing_hero_links and not pending_hero_links,
            (
                "docs/JUDGE_PACKET.md still has hero placeholders: "
                + ", ".join(missing_hero_links)
                if missing_hero_links
                else "docs/JUDGE_PACKET.md still marks hero evidence pending: "
                + ", ".join(pending_hero_links)
                if pending_hero_links
                else "hero evidence links finalized"
            ),
            True,
        ),
        Result(
            "submission form public links finalized",
            not missing_form_links,
            (
                "docs/SUBMISSION_FORM.md still has placeholders: "
                + ", ".join(missing_form_links)
                if missing_form_links
                else "submission form links finalized"
            ),
            True,
        ),
    ]


def run_audit() -> list[Result]:
    return [
        _check_open_source_license(),
        _check_architecture_diagram(),
        _check_alibaba_cloud_proof_material(),
        _check_vm_compose_profiles(),
        _check_judging_rubric_material(),
        _check_impact_and_adoption_material(),
        _check_public_repository_material(),
        _check_submission_text_description(),
        _check_demo_media_compliance(),
        _check_third_party_compliance_material(),
        _check_install_and_run_material(),
        *_check_required_files(),
        *_check_public_copy(),
        _check_secret_patterns(),
        _check_local_absolute_paths(),
        _check_stale_generated_paths(),
        _check_stale_public_text(),
        _check_track_choice_locked(),
        *_check_qwen_config(),
        *_check_final_artifacts(),
        _check_submission_links_artifact(),
        _check_uptime_monitoring_artifact(),
        _check_app_restart_resilience_artifact(),
        _check_backup_restore_artifact(),
        _check_qwen_smoke_artifact(),
        _check_docker_image_smoke_artifact(),
        _check_ecs_ops_acceptance_artifact(),
        _check_track3_baseline_artifact(),
        _check_track3_paired_benchmark_artifacts(),
        _check_deployment_verification_artifact(),
        _check_hero_evidence_artifact(),
        _check_final_proof_index_artifact(),
        _check_source_package_artifact(),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit YITING submission readiness")
    parser.add_argument("--strict", action="store_true", help="fail on final-submission placeholders")
    args = parser.parse_args()

    results = run_audit()
    failures = [result for result in results if not result.ok and (args.strict or not result.final_required)]

    print("YITING submission audit")
    print("=" * 24)
    for result in results:
        if result.ok:
            mark = "PASS"
        elif result.final_required and not args.strict:
            mark = "PENDING"
        else:
            mark = "FAIL"
        print(f"[{mark}] {result.name}: {result.detail}")

    if failures:
        print(f"\n{len(failures)} required check(s) failed.")
        return 1
    if any(not result.ok for result in results):
        print("\nLocal readiness checks passed; final submission artifacts are still pending.")
    else:
        print("\nAll submission checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

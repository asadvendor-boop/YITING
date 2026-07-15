#!/usr/bin/env python3
"""Create a sanitized source archive for public hackathon submission.

The public repository is still the source of truth, but this script gives a
quick local proof that the tree can be shared without runtime databases,
virtualenvs, local build output, or generated secrets.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "yiting-submission-source.zip"

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "output",
    "venv",
}
EXCLUDED_FILENAMES = {
    ".DS_Store",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "caddy.generated.env",
    "heal_idempotency.db",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".pyc",
    ".pyo",
    ".swp",
    ".swo",
}
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
SECRET_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{32,}|AKID[A-Za-z0-9]{12,}|LTAI[A-Za-z0-9]{12,}|CAIS[A-Za-z0-9_+/=-]{20,})"
)
LOCAL_ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:Users|home)/[A-Za-z0-9._-]+(?:/[^\s\"'`<>]*)?"),
    re.compile(r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\Users\\[^\\\s\"'`<>]+(?:\\[^\s\"'`<>]*)?)"),
]
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
REQUIRED_PATHS = {
    ".dockerignore",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "docs/ADOPTION_ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/BASELINE_MEASUREMENT.md",
    "docs/BLOG_POST.md",
    "docs/DEMO_SCRIPT.md",
    "docs/ALIBABA_DEPLOYMENT_PROOF.md",
    "docs/JUDGE_PACKET.md",
    "docs/JUDGE_TESTING.md",
    "docs/INSTALL_AND_RUN.md",
    "docs/JUDGING_RUBRIC.md",
    "docs/PUBLIC_REPOSITORY.md",
    "docs/PUBLIC_JUDGE_MODE.md",
    "docs/ENGINEERING_PROOF.md",
    "docs/FINAL_SUBMISSION_CHECKLIST.md",
    "docs/SLIDE_DECK.md",
    "docs/TRACK3_AGENT_SOCIETY.md",
    "docs/TRACK3_SCORECARD.md",
    "docs/SECURITY.md",
    "docs/SUBMISSION.md",
    "docs/SUBMISSION_FORM.md",
    "docs/THIRD_PARTY_COMPLIANCE.md",
    "docker/entrypoint.sh",
    "dashboard/Dockerfile",
    "gateway/rate_limit.py",
    "deploy/ecs/compose.prod.yml",
    "deploy/shared-host/README.md",
    "deploy/shared-host/compose.prod.yml",
    "deploy/standalone/Caddyfile.example",
    "deploy/standalone/README.md",
    "deploy/standalone/compose.yml",
    "deploy/standalone/yiting.env.example",
    "deploy/alibaba-ecs/README.md",
    "infra/alibaba-ecs/README.md",
    "infra/alibaba-ecs/main.tf",
    "infra/alibaba-ecs/variables.tf",
    "infra/alibaba-ecs/outputs.tf",
    "infra/alibaba-ecs/versions.tf",
    "evals/track3_paired_scenarios.json",
    "scripts/local_certify.py",
    "scripts/final_proof_index.py",
    "scripts/backup_restore_check.py",
    "scripts/docker_image_smoke.py",
    "scripts/ecs_ops_acceptance.py",
    "scripts/qwen_smoke.py",
    "scripts/reset_demo.py",
    "scripts/app_restart_resilience.py",
    "scripts/submission_links.py",
    "scripts/uptime_monitoring.py",
    "scripts/smoke.py",
    "scripts/track3_baseline.py",
    "scripts/track3_paired_benchmark.py",
    "scripts/verify_deployment.py",
    "shared/skill_registry.py",
}

PROOF_ARTIFACTS = {
    "stage_one_viability": [
        "README.md",
        "docs/TRACK3_AGENT_SOCIETY.md",
        "scripts/qwen_smoke.py",
        "scripts/smoke.py",
        "scripts/reset_demo.py",
        "docs/ALIBABA_DEPLOYMENT_PROOF.md",
        "infra/alibaba-ecs/README.md",
        "deploy/alibaba-ecs/README.md",
    ],
    "innovation_ai_creativity": [
        "shared/skill_registry.py",
        "docs/JUDGE_PACKET.md",
        "docs/JUDGING_RUBRIC.md",
        "docs/TRACK3_SCORECARD.md",
    ],
    "technical_depth": [
        "Dockerfile",
        "docker/entrypoint.sh",
        "docs/ARCHITECTURE.md",
        "docs/ENGINEERING_PROOF.md",
        "infra/alibaba-ecs/main.tf",
        "infra/alibaba-ecs/README.md",
        "deploy/shared-host/compose.prod.yml",
        "deploy/ecs/compose.prod.yml",
        "scripts/local_certify.py",
        "scripts/verify_deployment.py",
        "scripts/app_restart_resilience.py",
        "scripts/uptime_monitoring.py",
    ],
    "problem_value_impact": [
        "docs/ADOPTION_ROADMAP.md",
        "docs/BLOG_POST.md",
        "docs/BASELINE_MEASUREMENT.md",
        "scripts/track3_baseline.py",
        "scripts/track3_paired_benchmark.py",
        "evals/track3_paired_scenarios.json",
        "docs/TRACK3_AGENT_SOCIETY.md",
        "docs/TRACK3_SCORECARD.md",
    ],
    "presentation_documentation": [
        "docs/DEMO_SCRIPT.md",
        "docs/JUDGE_TESTING.md",
        "docs/PUBLIC_JUDGE_MODE.md",
        "docs/PUBLIC_REPOSITORY.md",
        "docs/INSTALL_AND_RUN.md",
        "docs/SECURITY.md",
        "docs/SUBMISSION.md",
        "docs/SUBMISSION_FORM.md",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "docs/SLIDE_DECK.md",
        "docs/JUDGE_PACKET.md",
        "docs/TRACK3_SCORECARD.md",
        "docs/FINAL_SUBMISSION_CHECKLIST.md",
        "deploy/shared-host/README.md",
        "deploy/standalone/README.md",
    ],
    "blog_post_prize": [
        "docs/BLOG_POST.md",
    ],
}
GENERATED_PROOF_ARTIFACTS = [
    "artifacts/docker-image-smoke.json",
    "artifacts/qwen-smoke.json",
    "artifacts/track3-baseline.json",
    "artifacts/track3-baseline-command-log.txt",
    "artifacts/track3-live-paired/summary.json",
    "artifacts/track3-live-paired/rows.json",
    "artifacts/track3-live-paired/rows.jsonl",
    "artifacts/track3-live-paired/rows_full_history.jsonl",
    "artifacts/track3-live-paired/rows_pilot_invalid.jsonl",
    "artifacts/track3-live-paired/solo_raw.jsonl",
    "artifacts/track3-live-paired/NOTES.md",
    "artifacts/track3-live-paired-postfix/summary.json",
    "artifacts/track3-live-paired-postfix/rows.jsonl",
    "artifacts/track3-live-paired-postfix/solo_raw.jsonl",
    "artifacts/track3-live-paired-postfix/NOTES.md",
    "artifacts/track3-paired-benchmark.json",
    "artifacts/track3-paired-benchmark-raw.json",
    "artifacts/track3-paired-benchmark.csv",
    "artifacts/deployment-verification.json",
    "artifacts/hero-evidence.json",
    "artifacts/final-proof-index.md",
    "artifacts/live/backup-restore.json",
    "artifacts/live/ecs-ops-acceptance.json",
    "artifacts/live/app-restart-resilience.json",
    "artifacts/live/uptime-monitoring.json",
    "artifacts/live/submission-links.json",
    "dist/yiting-submission-source.zip",
]
PACKAGE_PROOF_ARTIFACTS = {
    path for path in GENERATED_PROOF_ARTIFACTS
    if path.startswith("artifacts/")
}
TRACK3_PROOF_SUMMARY = {
    "primary_track": "Track 3: Agent Society",
    "core_claim": (
        "YITING is a Qwen-backed emergency change council: specialized agents "
        "divide incident-response work, exchange sealed evidence, challenge weak "
        "reasoning, negotiate revisions with a human, and execute only the final "
        "authorized envelope."
    ),
    "required_showcase": {
        "distinct_capabilities": {
            "claim": (
                "Seven roles expose separate inspectable MCP-style skill contracts, Qwen Cloud use, "
                "Track 3 proof categories, guardrails, judge demo cues, and evidence artifacts."
            ),
            "evidence": [
                "/agent-skills",
                "shared/skill_registry.py",
                "docs/TRACK3_AGENT_SOCIETY.md",
            ],
            "required_fields": [
                "tool_name",
                "input_schema",
                "output_schema",
                "qwen_cloud_use",
                "track3_requirement",
                "judge_demo_cue",
                "deterministic_guardrail",
                "evidence_artifact",
            ],
        },
        "task_decomposition": {
            "claim": "Each incident advances through role-owned cards instead of one generic agent.",
            "evidence": [
                "/evidence/{incident_id}.collaboration.role_sequence",
                "AlertCard -> TriageDecision -> Assessment -> Verdict -> ResponsePlan -> authorization -> ActionReceipt",
            ],
        },
        "dialogue_and_negotiation": {
            "claim": "Agents and humans exchange room messages plus sealed cards before execution.",
            "evidence": [
                "incident room transcript",
                "Verdict(CHALLENGE)",
                "StructuredApproval(REJECTED)",
            ],
        },
        "disagreement_resolution": {
            "claim": "Safety Reviewer can force Diagnosis revision; humans can force Commander replanning.",
            "evidence": [
                "/stats/runsummary.disagreement_events",
                "/evidence/{incident_id}.collaboration.challenges",
                "/evidence/{incident_id}.collaboration.human_decisions",
            ],
        },
        "hero_evidence_standard": {
            "claim": (
                "The final hero incident must be the requested EXECUTED incident, "
                "include ActionReceipt, and show sealed disagreement or human rejection."
            ),
            "evidence": [
                "artifacts/hero-evidence.json.incident_id == HERO_INCIDENT_ID",
                "artifacts/hero-evidence.json.state == EXECUTED",
                "ActionReceipt",
                "Verdict(CHALLENGE) or StructuredApproval(REJECTED)",
                "scripts/final_proof_index.py",
                "scripts/verify_deployment.py",
            ],
            "required_final_check": (
                "incident_id match, state EXECUTED, ActionReceipt present, "
                "and Verdict(CHALLENGE) or StructuredApproval(REJECTED) present"
            ),
        },
        "execution_conflict_resolution": {
            "claim": "Operator executes only the exact approved action envelope and fails closed on stale or modified actions.",
            "evidence": [
                "/evidence/{incident_id}.collaboration.execution_conflict_control.exact_match",
                "agents/operator/__init__.py",
                "docs/ENGINEERING_PROOF.md",
            ],
        },
        "measurable_efficiency_gain": {
            "claim": (
                "The paired benchmark proves society quality and reliability gains "
                "over a single-agent baseline. Hosted speed is a separate timing "
                "claim accepted only when measured same-family runsummary rows "
                "prove speedup_factor > 1."
            ),
            "evidence": [
                "artifacts/track3-paired-benchmark.json",
                "artifacts/track3-paired-benchmark-raw.json",
                "artifacts/track3-paired-benchmark.csv",
                "scripts/track3_paired_benchmark.py",
                "artifacts/track3-baseline.json",
                "/stats/runsummary.speedup_factor",
                "scripts/track3_baseline.py",
                "scripts/verify_deployment.py --require-speedup",
            ],
            "required_final_check": (
                "paired benchmark shows higher task success, lower unsupported-claim "
                "rate, more risks detected, better final score, better quality per "
                "token, and speed_improvement_claimed=false; any hosted speed claim "
                "also requires speedup_factor > 1, matched same-family run IDs "
                "include the hero incident, and disagreement_events > 0 within "
                "that same family comparison"
            ),
            "reproducible_pairing_check": (
                "scripts/track3_paired_benchmark.py compares the same fixed "
                "scenarios, same rubric, same model identity, and token-normalized "
                "metrics for single_agent vs full_yiting_society. It does not "
                "claim speed improvement."
            ),
        },
    },
    "judge_routes": [
        "/agent-skills",
        "/evidence/{incident_id}",
        "/stats/runsummary",
        "docs/TRACK3_SCORECARD.md",
        "artifacts/qwen-smoke.json",
        "artifacts/track3-baseline.json",
        "artifacts/track3-paired-benchmark.json",
        "artifacts/deployment-verification.json",
        "artifacts/hero-evidence.json",
        "artifacts/final-proof-index.md",
        "artifacts/live/backup-restore.json",
        "artifacts/live/ecs-ops-acceptance.json",
        "artifacts/live/app-restart-resilience.json",
        "artifacts/live/uptime-monitoring.json",
        "artifacts/live/submission-links.json",
    ],
}
FINAL_SUBMISSION_CHECKLIST = [
    "freeze hero evidence from /evidence/{incident_id}",
    (
        "finalize README, landing, judge packet, submission form, and install guide links with "
        "make submission-finalize, including separate demo and deployment-proof video URLs"
    ),
    "run make submission-ready",
    "run make docker-build-images and make docker-smoke-images before pushing immutable image digests",
    (
        "run make submission-proof with HERO_INCIDENT_ID, a measured "
        "same-family manual (human) baseline, hero evidence containing "
        "EXECUTED + ActionReceipt + Verdict(CHALLENGE) or "
        "StructuredApproval(REJECTED), nonzero human-intervention proof, "
        "and public read-only chaos disabled"
    ),
    "commit generated proof artifacts, run make submission-package, and push the final proof commit",
    "run python scripts/submission_audit.py --strict",
]
FINAL_HOUR_ORDER = [
    "Push the public GitHub repo and configure origin so source links are real.",
    (
        "Deploy private recording mode with live chaos enabled, run the frontend "
        "demo, and choose the hero incident."
    ),
    "Record and upload the demo video from the live dashboard flow.",
    "Record and upload the separate Alibaba ECS deployment-proof video.",
    "Switch the hosted dashboard to public read-only judge mode.",
    (
        "Run make submission-finalize DOMAIN=... REPO_URL=... "
        "VIDEO_URL=... DEPLOYMENT_PROOF_VIDEO_URL=... HERO_INCIDENT_ID=INC-..."
    ),
    "Run python scripts/submission_links.py ... --check-reachable and review artifacts/live/submission-links.json.",
    "Run python scripts/backup_restore_check.py ... --live-submission-evidence and review artifacts/live/backup-restore.json.",
    "Run app-scoped Compose restarts, verify both apps recover with persisted state/evidence/logs, and review artifacts/live/app-restart-resilience.json.",
    "Run python scripts/uptime_monitoring.py ... and review artifacts/live/uptime-monitoring.json.",
    "Commit finalized public artifacts, run make submission-ready, run make docker-smoke-images, and push the final commit.",
    (
        "Run make submission-proof PUBLIC_BASE_URL=https://... "
        "HERO_INCIDENT_ID=INC-... MEASURED_SINGLE_AGENT_SECS=<seconds> "
        "BASELINE_INCIDENT_FAMILY=<same-family-as-hero-incident>"
    ),
    "Commit generated proof artifacts, run make submission-package, and push the final proof commit.",
    "Run python scripts/submission_audit.py --strict and python scripts/submission_status.py --require-final; fix anything either flags.",
]


@dataclass(frozen=True)
class PackageResult:
    output: Path
    file_count: int
    commit: str


class PackageError(RuntimeError):
    """Raised when the source archive cannot be safely produced."""


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _git_worktree_clean() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0 and not completed.stdout.strip()


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if rel.parts and rel.parts[0] == "artifacts" and rel.as_posix() not in PACKAGE_PROOF_ARTIFACTS:
        return True
    if path.name in EXCLUDED_FILENAMES:
        return True
    if path.name.startswith("._"):
        return True
    if path.name.endswith((".backup", "~")):
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def _iter_package_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _is_excluded(path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def _scan_text_file(path: Path) -> list[str]:
    text_names = {"Caddyfile", "Caddyfile.example", "Dockerfile", "LICENSE", "Makefile", ".dockerignore"}
    if path.suffix not in TEXT_SUFFIXES and path.name not in text_names:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    offenders: list[str] = []
    for forbidden in [
        "AIM" + "LAPI",
        "Feather" + "less",
        "app." + "b" + "and" + ".ai",
        "B" + "AND_API_KEY",
        "129." + "80.",
    ]:
        if forbidden.lower() in text.lower():
            offenders.append(forbidden)
    for label, pattern in STALE_PUBLIC_TEXT_PATTERNS:
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        if (rel, label) in STALE_PUBLIC_TEXT_ALLOWED:
            continue
        if pattern.search(text):
            offenders.append(label)
    if SECRET_PATTERN.search(text):
        offenders.append("credential-pattern")
    if any(pattern.search(text) for pattern in LOCAL_ABSOLUTE_PATH_PATTERNS):
        offenders.append("local-absolute-path")
    return offenders


def _validate_files(files: list[Path]) -> None:
    rels = {path.relative_to(ROOT).as_posix() for path in files}
    missing = sorted(REQUIRED_PATHS - rels)
    if missing:
        raise PackageError(f"required submission files missing from archive: {', '.join(missing)}")

    forbidden_paths = [
        rel
        for rel in rels
        if rel == ".env"
        or rel.endswith(".db")
        or "/node_modules/" in f"/{rel}/"
        or "/.next/" in f"/{rel}/"
    ]
    if forbidden_paths:
        raise PackageError(f"forbidden runtime artifacts selected: {', '.join(sorted(forbidden_paths)[:8])}")

    text_offenders: list[str] = []
    for path in files:
        matches = _scan_text_file(path)
        if matches:
            rel = path.relative_to(ROOT).as_posix()
            text_offenders.extend(f"{rel}: {match}" for match in matches)
    if text_offenders:
        raise PackageError("forbidden public text found: " + "; ".join(text_offenders[:8]))


def _require_clean_source(*, allow_dirty: bool = False) -> None:
    if allow_dirty:
        return
    if not _git_worktree_clean():
        raise PackageError(
            "Refusing to package a dirty working tree. Commit final source/proof artifacts first, "
            "or pass --allow-dirty only for a non-submission rehearsal archive."
        )


def build_submission_archive(output: Path = DEFAULT_OUTPUT, *, allow_dirty: bool = False) -> PackageResult:
    _require_clean_source(allow_dirty=allow_dirty)
    files = _iter_package_files()
    _validate_files(files)

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    commit = _git_commit()
    manifest = {
        "project": "YITING",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "working_tree_clean": _git_worktree_clean(),
        "file_count": len(files),
        "excludes": sorted(EXCLUDED_DIRS | EXCLUDED_FILENAMES),
        "primary_track": "Track 3: Agent Society",
        "track3_proof_summary": TRACK3_PROOF_SUMMARY,
        "proof_artifacts": PROOF_ARTIFACTS,
        "generated_proof_artifacts": GENERATED_PROOF_ARTIFACTS,
        "final_submission_checklist": FINAL_SUBMISSION_CHECKLIST,
        "final_hour_order": FINAL_HOUR_ORDER,
        "final_proof_command": (
            "make submission-proof PUBLIC_BASE_URL=... "
            "HERO_INCIDENT_ID=... "
            "MEASURED_SINGLE_AGENT_SECS=... "
            "BASELINE_INCIDENT_FAMILY=..."
        ),
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("SUBMISSION_MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return PackageResult(output=output, file_count=len(files), commit=commit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create sanitized YITING source submission archive")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty source tree for local rehearsal archives. Do not use for submission packages.",
    )
    args = parser.parse_args()

    try:
        result = build_submission_archive(args.output, allow_dirty=args.allow_dirty)
    except PackageError as exc:
        print(f"package failed: {exc}")
        return 2

    print(f"Created {result.output}")
    print(f"Files: {result.file_count}")
    print(f"Commit: {result.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

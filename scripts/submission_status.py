#!/usr/bin/env python3
"""Summarize local and external submission readiness for YITING."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_submission import DEFAULT_OUTPUT, _git_commit, _git_worktree_clean  # noqa: E402
from scripts.package_submission import FINAL_HOUR_ORDER  # noqa: E402
from scripts.package_submission import FINAL_SUBMISSION_CHECKLIST  # noqa: E402
from scripts.package_submission import GENERATED_PROOF_ARTIFACTS as PACKAGE_GENERATED_PROOF_ARTIFACTS  # noqa: E402
from scripts.package_submission import TRACK3_PROOF_SUMMARY  # noqa: E402
from scripts.submission_audit import Result, run_audit  # noqa: E402

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
if GENERATED_PROOF_ARTIFACTS != PACKAGE_GENERATED_PROOF_ARTIFACTS:
    raise RuntimeError("submission status generated proof artifact list drifted from package manifest")


@dataclass(frozen=True)
class PackageStatus:
    path: Path
    exists: bool
    commit: str
    current: bool
    detail: str


@dataclass(frozen=True)
class SubmissionStatus:
    current_commit: str
    local_ready: bool
    source_package: PackageStatus
    pending_external: list[Result]
    local_failures: list[Result]

    @property
    def ready_to_submit(self) -> bool:
        return self.local_ready and self.source_package.current and not self.pending_external


def rubric_checklist() -> list[dict[str, Any]]:
    """Return the score-criteria checklist exposed in machine-readable status."""
    return [
        {
            "criterion": "Stage One viability",
            "weight": "pass/fail",
            "proof": [
                "Track 3 Agent Society positioning",
                "Qwen Cloud configuration and smoke check",
                "Alibaba ECS deployment verifier",
            ],
            "required_artifacts": [
                "README.md",
                "docs/TRACK3_AGENT_SOCIETY.md",
                "scripts/qwen_smoke.py",
                "scripts/verify_deployment.py",
            ],
        },
        {
            "criterion": "Innovation & AI Creativity",
            "weight": "30%",
            "proof": [
                "Custom agent skill registry",
                "Qwen-backed role society",
                "Challenge and human revision loops",
            ],
            "required_artifacts": [
                "/agent-skills",
                "docs/JUDGE_PACKET.md",
                "docs/JUDGING_RUBRIC.md",
            ],
        },
        {
            "criterion": "Technical Depth & Engineering",
            "weight": "30%",
            "proof": [
                "SHA-256 evidence chain",
                "Nonce-bound authorization",
                "Exact-envelope execution",
                "Recovery verification",
                "Engineering proof matrix",
            ],
            "required_artifacts": [
                "/evidence/{incident_id}",
                "docs/ARCHITECTURE.md",
                "docs/ENGINEERING_PROOF.md",
                "scripts/local_certify.py",
            ],
        },
        {
            "criterion": "Problem Value & Impact",
            "weight": "25%",
            "proof": [
                "Governed emergency change control",
                "False-alarm and high-risk decision handling",
                "Paired quality gains against a single-agent baseline",
                "Separate hosted speed proof when measured",
                "Open-source adoption and extension roadmap",
            ],
            "required_artifacts": [
                "/stats/runsummary",
                "docs/ADOPTION_ROADMAP.md",
                "scripts/track3_baseline.py",
                "docs/BASELINE_MEASUREMENT.md",
                "docs/BLOG_POST.md",
            ],
        },
        {
            "criterion": "Presentation & Documentation",
            "weight": "15%",
            "proof": [
                "Judge packet",
                "Install and run guide",
                "Public repository publication guide",
                "Demo script",
                "Submission form packet",
                "Final submission checklist",
                "Deployment proof",
                "Source package",
            ],
            "required_artifacts": [
                "docs/JUDGE_PACKET.md",
                "docs/INSTALL_AND_RUN.md",
                "docs/PUBLIC_REPOSITORY.md",
                "docs/DEMO_SCRIPT.md",
                "docs/SUBMISSION_FORM.md",
                "docs/SLIDE_DECK.md",
                "docs/PUBLIC_JUDGE_MODE.md",
                "docs/FINAL_SUBMISSION_CHECKLIST.md",
                "docs/ALIBABA_CLOUD_PROOF.md",
                "dist/yiting-submission-source.zip",
            ],
        },
        {
            "criterion": "Blog Post Prize",
            "weight": "separate prize",
            "proof": [
                "Long-form blog draft",
                "Social version",
                "Thoroughness and potential impact narrative",
            ],
            "required_artifacts": [
                "docs/BLOG_POST.md",
            ],
        },
    ]


def _read_package_manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("SUBMISSION_MANIFEST.json"))
    if not isinstance(manifest, dict):
        raise ValueError("SUBMISSION_MANIFEST.json did not contain an object")
    return manifest


def package_status(path: Path = DEFAULT_OUTPUT, *, current_commit: str | None = None) -> PackageStatus:
    current_commit = current_commit or _git_commit()
    path = path.resolve()
    if not path.exists():
        return PackageStatus(
            path=path,
            exists=False,
            commit="",
            current=False,
            detail="missing; run make submission-package or make submission-ready",
        )

    try:
        manifest = _read_package_manifest(path)
    except Exception as exc:
        return PackageStatus(
            path=path,
            exists=True,
            commit="",
            current=False,
            detail=f"manifest unreadable: {exc.__class__.__name__}",
        )

    package_commit = str(manifest.get("git_commit", "")).strip()
    package_clean = manifest.get("working_tree_clean") is True
    worktree_clean = _git_worktree_clean()
    is_current = package_commit == current_commit and package_clean and worktree_clean
    if is_current:
        detail = "matches current clean commit"
    elif package_commit != current_commit:
        detail = f"stale; package={package_commit}, current={current_commit}"
    elif not package_clean:
        detail = "package was built from an uncommitted working tree"
    else:
        detail = "working tree has uncommitted changes; rebuild package after commit"
    return PackageStatus(
        path=path,
        exists=True,
        commit=package_commit,
        current=is_current,
        detail=detail,
    )


def collect_status(package_path: Path = DEFAULT_OUTPUT) -> SubmissionStatus:
    audit_results = run_audit()
    current_commit = _git_commit()
    local_failures = [result for result in audit_results if not result.ok and not result.final_required]
    pending_external = [result for result in audit_results if not result.ok and result.final_required]
    return SubmissionStatus(
        current_commit=current_commit,
        local_ready=not local_failures,
        source_package=package_status(package_path, current_commit=current_commit),
        pending_external=pending_external,
        local_failures=local_failures,
    )


def status_to_dict(status: SubmissionStatus) -> dict[str, Any]:
    return {
        "current_commit": status.current_commit,
        "local_ready": status.local_ready,
        "source_package": {
            "path": str(status.source_package.path),
            "exists": status.source_package.exists,
            "commit": status.source_package.commit,
            "current": status.source_package.current,
            "detail": status.source_package.detail,
        },
        "pending_external": [
            {"name": result.name, "detail": result.detail}
            for result in status.pending_external
        ],
        "local_failures": [
            {"name": result.name, "detail": result.detail}
            for result in status.local_failures
        ],
        "track3_proof_summary": TRACK3_PROOF_SUMMARY,
        "rubric_checklist": rubric_checklist(),
        "generated_proof_artifacts": GENERATED_PROOF_ARTIFACTS,
        "final_submission_checklist": FINAL_SUBMISSION_CHECKLIST,
        "final_hour_order": FINAL_HOUR_ORDER,
        "ready_to_submit": status.ready_to_submit,
    }


def render_status(status: SubmissionStatus) -> str:
    lines = [
        "YITING submission status",
        "========================",
        f"current_commit: {status.current_commit}",
        f"local_checks: {'PASS' if status.local_ready else 'FAIL'}",
        f"source_package: {'CURRENT' if status.source_package.current else 'NOT CURRENT'}",
        f"  path: {status.source_package.path}",
        f"  detail: {status.source_package.detail}",
        f"final_submission: {'READY' if status.ready_to_submit else 'PENDING'}",
    ]

    if status.local_failures:
        lines.append("")
        lines.append("Local failures:")
        lines.extend(f"- {result.name}: {result.detail}" for result in status.local_failures)

    if status.pending_external:
        lines.append("")
        lines.append("External artifacts still needed:")
        lines.extend(f"- {result.name}: {result.detail}" for result in status.pending_external)

    lines.append("")
    lines.append("Recommended final-hour order:")
    lines.extend(f"{index}. {step}" for index, step in enumerate(FINAL_HOUR_ORDER, start=1))

    lines.append("")
    lines.append("Useful commands:")
    lines.append("- make submission-ready")
    lines.append("- make docker-build-images")
    lines.append("- make docker-smoke-images")
    lines.append(
        "- make submission-finalize DOMAIN=... REPO_URL=... "
        "VIDEO_URL=... DEPLOYMENT_PROOF_VIDEO_URL=... HERO_INCIDENT_ID=INC-..."
    )
    lines.append(
        "- make submission-proof PUBLIC_BASE_URL=https://... "
        "HERO_INCIDENT_ID=INC-... "
        "MEASURED_SINGLE_AGENT_SECS=<seconds> "
        "BASELINE_INCIDENT_FAMILY=<same-family-as-hero-incident>"
    )
    lines.append("- python scripts/submission_audit.py --strict")
    lines.append("- python scripts/submission_status.py --require-final")
    lines.append("")
    lines.append("Generated proof artifacts:")
    lines.extend(f"- {artifact}" for artifact in GENERATED_PROOF_ARTIFACTS)
    lines.append("")
    lines.append("Final proof must show:")
    lines.append("- paired benchmark quality gains over the single-agent baseline")
    lines.append("- speedup_factor > 1 only for the separate hosted timing claim")
    lines.append("- baseline artifact names the same incident family as the hero run")
    lines.append("- nonzero handoffs, disagreement events, human interventions, and recovery verification")
    lines.append("- hero evidence incident_id matches HERO_INCIDENT_ID and final state is EXECUTED")
    lines.append("- hero evidence chain with Verdict(CHALLENGE) or StructuredApproval(REJECTED)")
    lines.append("- hero evidence chain includes ActionReceipt")
    lines.append("- hero evidence chain with exact execution conflict resolution")
    lines.append("- public dashboard chaos actions reject with HTTP 403 in judge mode")
    lines.append("")
    lines.append("Score criteria checklist:")
    for item in rubric_checklist():
        proof = "; ".join(str(value) for value in item["proof"])
        lines.append(f"- {item['criterion']} ({item['weight']}): {proof}")
    lines.append("")
    lines.append("Rubric packet:")
    lines.append("- docs/JUDGE_PACKET.md")
    lines.append("- docs/INSTALL_AND_RUN.md")
    lines.append("- docs/PUBLIC_REPOSITORY.md")
    lines.append("- docs/JUDGING_RUBRIC.md")
    lines.append("- docs/TRACK3_SCORECARD.md")
    lines.append("- docs/ENGINEERING_PROOF.md")
    lines.append("- docs/TRACK3_AGENT_SOCIETY.md")
    lines.append("- docs/ADOPTION_ROADMAP.md")
    lines.append("- docs/BASELINE_MEASUREMENT.md")
    lines.append("- docs/SLIDE_DECK.md")
    lines.append("- docs/PUBLIC_JUDGE_MODE.md")
    lines.append("- docs/THIRD_PARTY_COMPLIANCE.md")
    lines.append("- docs/FINAL_SUBMISSION_CHECKLIST.md")
    lines.append("")
    lines.append("Blog Post Prize packet:")
    lines.append("- docs/BLOG_POST.md")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize YITING submission readiness")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--package", type=Path, default=DEFAULT_OUTPUT, help="source package archive path")
    parser.add_argument(
        "--require-final",
        action="store_true",
        help="return nonzero until external proof artifacts and the final source package are ready",
    )
    args = parser.parse_args(argv)

    status = collect_status(args.package)
    if args.json:
        print(json.dumps(status_to_dict(status), indent=2, sort_keys=True))
    else:
        print(render_status(status), end="")
    if args.require_final:
        return 0 if status.ready_to_submit else 1
    return 0 if status.local_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

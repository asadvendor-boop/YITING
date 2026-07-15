from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import submission_status as submission_status_module
from scripts.package_submission import _git_commit
from scripts.submission_audit import Result
from scripts.submission_status import (
    PackageStatus,
    SubmissionStatus,
    package_status,
    render_status,
    rubric_checklist,
    status_to_dict,
)


def _remove_pytest_runtime_caches() -> None:
    for path in Path(__file__).resolve().parents[1].rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)


def _write_package(path: Path, *, commit: str, working_tree_clean: bool = True) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "SUBMISSION_MANIFEST.json",
            json.dumps({
                "git_commit": commit,
                "working_tree_clean": working_tree_clean,
            }),
        )


def test_package_status_reports_current_archive(tmp_path):
    package = tmp_path / "source.zip"
    _write_package(package, commit="abc123")

    with patch("scripts.submission_status._git_worktree_clean", return_value=True):
        status = package_status(package, current_commit="abc123")

    assert status.exists is True
    assert status.current is True
    assert status.commit == "abc123"
    assert status.detail == "matches current clean commit"


def test_package_status_reports_stale_or_missing_archive(tmp_path):
    stale_package = tmp_path / "stale.zip"
    _write_package(stale_package, commit="old")

    dirty_package = tmp_path / "dirty.zip"
    _write_package(dirty_package, commit="new", working_tree_clean=False)

    with patch("scripts.submission_status._git_worktree_clean", return_value=True):
        stale = package_status(stale_package, current_commit="new")
        dirty_manifest = package_status(dirty_package, current_commit="new")
        missing = package_status(tmp_path / "missing.zip", current_commit="new")

    assert stale.current is False
    assert "stale" in stale.detail
    assert dirty_manifest.current is False
    assert "uncommitted working tree" in dirty_manifest.detail
    assert missing.exists is False
    assert "missing" in missing.detail


def test_package_status_rejects_dirty_current_worktree(tmp_path):
    package = tmp_path / "source.zip"
    _write_package(package, commit="abc123", working_tree_clean=True)

    with patch("scripts.submission_status._git_worktree_clean", return_value=False):
        status = package_status(package, current_commit="abc123")

    assert status.current is False
    assert "working tree has uncommitted changes" in status.detail


def test_render_status_lists_external_artifacts_without_failing_local_readiness(tmp_path):
    package = PackageStatus(
        path=tmp_path / "source.zip",
        exists=True,
        commit="abc123",
        current=True,
        detail="matches current commit",
    )
    status = SubmissionStatus(
        current_commit="abc123",
        local_ready=True,
        source_package=package,
        pending_external=[
            Result("deployment domain finalized", False, "README still uses placeholder domain", True),
        ],
        local_failures=[],
    )

    rendered = render_status(status)
    data = status_to_dict(status)

    assert "local_checks: PASS" in rendered
    assert "source_package: CURRENT" in rendered
    assert "final_submission: PENDING" in rendered
    assert "deployment domain finalized" in rendered
    assert "Recommended final-hour order:" in rendered
    assert "1. Push the public GitHub repo and configure origin" in rendered
    assert "2. Deploy private recording mode with live chaos enabled" in rendered
    assert "3. Record and upload the demo video from the live dashboard flow" in rendered
    assert "4. Record and upload the separate Alibaba ECS deployment-proof video" in rendered
    assert "5. Switch the hosted dashboard to public read-only judge mode" in rendered
    assert "6. Run make submission-finalize DOMAIN=..." in rendered
    assert "7. Run python scripts/submission_links.py ... --check-reachable" in rendered
    assert "8. Run python scripts/backup_restore_check.py ... --live-submission-evidence" in rendered
    assert "9. Run app-scoped Compose restarts, verify both apps recover" in rendered
    assert "10. Run python scripts/uptime_monitoring.py ..." in rendered
    assert "11. Commit finalized public artifacts, run make submission-ready, run make docker-smoke-images" in rendered
    assert "12. Run make submission-proof PUBLIC_BASE_URL=https://..." in rendered
    assert "13. Commit generated proof artifacts, run make submission-package" in rendered
    assert "14. Run python scripts/submission_audit.py --strict" in rendered
    assert "python scripts/submission_status.py --require-final" in rendered
    assert "make submission-proof" in rendered
    assert "make docker-build-images" in rendered
    assert "make docker-smoke-images" in rendered
    assert "make submission-finalize" in rendered
    assert "HERO_INCIDENT_ID=INC-..." in rendered
    assert "MEASURED_SINGLE_AGENT_SECS" in rendered
    assert "BASELINE_INCIDENT_FAMILY=<same-family-as-hero-incident>" in rendered
    assert "artifacts/docker-image-smoke.json" in rendered
    assert "artifacts/track3-baseline.json" in rendered
    assert "artifacts/qwen-smoke.json" in rendered
    assert "artifacts/deployment-verification.json" in rendered
    assert "artifacts/hero-evidence.json" in rendered
    assert "artifacts/final-proof-index.md" in rendered
    assert "artifacts/live/backup-restore.json" in rendered
    assert "artifacts/live/ecs-ops-acceptance.json" in rendered
    assert "artifacts/live/app-restart-resilience.json" in rendered
    assert "reboot-persistence" not in rendered
    assert "artifacts/live/uptime-monitoring.json" in rendered
    assert "artifacts/live/submission-links.json" in rendered
    assert "Final proof must show:" in rendered
    assert "paired benchmark quality gains over the single-agent baseline" in rendered
    assert "speedup_factor > 1 only for the separate hosted timing claim" in rendered
    assert "baseline artifact names the same incident family as the hero run" in rendered
    assert "nonzero handoffs, disagreement events, human interventions, and recovery verification" in rendered
    assert "final state is EXECUTED" in rendered
    assert "Verdict(CHALLENGE) or StructuredApproval(REJECTED)" in rendered
    assert "includes ActionReceipt" in rendered
    assert "exact execution conflict resolution" in rendered
    assert "public dashboard chaos actions reject with HTTP 403 in judge mode" in rendered
    assert "Score criteria checklist:" in rendered
    assert "Stage One viability (pass/fail)" in rendered
    assert "Innovation & AI Creativity (30%)" in rendered
    assert "Technical Depth & Engineering (30%)" in rendered
    assert "Problem Value & Impact (25%)" in rendered
    assert "Presentation & Documentation (15%)" in rendered
    assert "Blog Post Prize (separate prize)" in rendered
    assert "Track 3 Agent Society positioning" in rendered
    assert "Custom agent skill registry" in rendered
    assert "Open-source adoption and extension roadmap" in rendered
    assert "Rubric packet:" in rendered
    assert "docs/JUDGE_PACKET.md" in rendered
    assert "docs/INSTALL_AND_RUN.md" in rendered
    assert "docs/PUBLIC_REPOSITORY.md" in rendered
    assert "docs/TRACK3_SCORECARD.md" in rendered
    assert "docs/ENGINEERING_PROOF.md" in rendered
    assert "docs/ADOPTION_ROADMAP.md" in rendered
    assert "docs/BASELINE_MEASUREMENT.md" in rendered
    assert "docs/SLIDE_DECK.md" in rendered
    assert "docs/PUBLIC_JUDGE_MODE.md" in rendered
    assert "docs/THIRD_PARTY_COMPLIANCE.md" in rendered
    assert "docs/FINAL_SUBMISSION_CHECKLIST.md" in rendered
    assert "Blog Post Prize packet:" in rendered
    assert "docs/BLOG_POST.md" in rendered
    assert data["ready_to_submit"] is False
    assert data["final_submission_checklist"] == [
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
    assert data["final_hour_order"] == [
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
        (
            "Run python scripts/backup_restore_check.py ... --live-submission-evidence "
            "and review artifacts/live/backup-restore.json."
        ),
        "Run app-scoped Compose restarts, verify both apps recover with persisted state/evidence/logs, "
        "and review artifacts/live/app-restart-resilience.json.",
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
    assert data["pending_external"][0]["name"] == "deployment domain finalized"
    assert [item["criterion"] for item in data["rubric_checklist"]] == [
        "Stage One viability",
        "Innovation & AI Creativity",
        "Technical Depth & Engineering",
        "Problem Value & Impact",
        "Presentation & Documentation",
        "Blog Post Prize",
    ]
    assert data["track3_proof_summary"]["primary_track"] == "Track 3: Agent Society"
    assert data["generated_proof_artifacts"][0] == "artifacts/docker-image-smoke.json"
    assert set(data["track3_proof_summary"]["required_showcase"]) == {
        "distinct_capabilities",
        "task_decomposition",
        "dialogue_and_negotiation",
        "disagreement_resolution",
        "hero_evidence_standard",
        "execution_conflict_resolution",
        "measurable_efficiency_gain",
    }
    encoded_summary = json.dumps(data["track3_proof_summary"])
    assert "/agent-skills" in encoded_summary
    assert "/evidence/{incident_id}" in encoded_summary
    assert "/stats/runsummary" in encoded_summary
    assert "speed_improvement_claimed=false" in encoded_summary
    assert "better quality per token" in encoded_summary
    assert "speedup_factor > 1" in encoded_summary
    assert "disagreement_events > 0" in encoded_summary


def test_submission_status_script_runs_as_direct_file(tmp_path):
    _remove_pytest_runtime_caches()
    package = tmp_path / "source.zip"
    _write_package(package, commit=_git_commit())

    completed = subprocess.run(
        [sys.executable, "-B", "scripts/submission_status.py", "--json", "--package", str(package)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert data["local_ready"] is True
    assert isinstance(data["source_package"]["current"], bool)
    assert data["track3_proof_summary"]["primary_track"] == "Track 3: Agent Society"
    assert data["rubric_checklist"][0]["criterion"] == "Stage One viability"


def test_submission_status_require_final_controls_exit_code(monkeypatch, tmp_path, capsys):
    package = PackageStatus(
        path=tmp_path / "source.zip",
        exists=True,
        commit="abc123",
        current=False,
        detail="working tree has uncommitted changes",
    )
    pending_status = SubmissionStatus(
        current_commit="abc123",
        local_ready=True,
        source_package=package,
        pending_external=[Result("deployment domain finalized", False, "pending", True)],
        local_failures=[],
    )
    ready_status = SubmissionStatus(
        current_commit="abc123",
        local_ready=True,
        source_package=PackageStatus(
            path=tmp_path / "source.zip",
            exists=True,
            commit="abc123",
            current=True,
            detail="matches current clean commit",
        ),
        pending_external=[],
        local_failures=[],
    )

    monkeypatch.setattr(submission_status_module, "collect_status", lambda package_path: pending_status)
    assert submission_status_module.main(["--json"]) == 0
    assert submission_status_module.main(["--json", "--require-final"]) == 1

    monkeypatch.setattr(submission_status_module, "collect_status", lambda package_path: ready_status)
    assert submission_status_module.main(["--json", "--require-final"]) == 0
    capsys.readouterr()


def test_rubric_checklist_names_track3_and_speedup_proofs():
    checklist = rubric_checklist()
    encoded = json.dumps(checklist)

    assert "Innovation & AI Creativity" in encoded
    assert "Technical Depth & Engineering" in encoded
    assert "Problem Value & Impact" in encoded
    assert "Presentation & Documentation" in encoded
    assert "Blog Post Prize" in encoded
    assert "Thoroughness and potential impact narrative" in encoded
    assert "docs/BLOG_POST.md" in encoded
    assert "/agent-skills" in encoded
    assert "/evidence/{incident_id}" in encoded
    assert "docs/ENGINEERING_PROOF.md" in encoded
    assert "Engineering proof matrix" in encoded
    assert "scripts/track3_baseline.py" in encoded
    assert "single-agent baseline" in encoded
    assert "Open-source adoption and extension roadmap" in encoded
    assert "docs/ADOPTION_ROADMAP.md" in encoded
    assert "docs/BASELINE_MEASUREMENT.md" in encoded
    assert "docs/SUBMISSION_FORM.md" in encoded
    assert "docs/SLIDE_DECK.md" in encoded
    assert "docs/INSTALL_AND_RUN.md" in encoded
    assert "docs/PUBLIC_REPOSITORY.md" in encoded
    assert "docs/PUBLIC_JUDGE_MODE.md" in encoded
    assert "docs/FINAL_SUBMISSION_CHECKLIST.md" in encoded

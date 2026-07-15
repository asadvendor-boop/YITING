from __future__ import annotations

import json
import zipfile

import pytest

from scripts import package_submission
from scripts.package_submission import ROOT, PackageError, _scan_text_file, build_submission_archive

PACKAGE_TEXT_SUFFIXES = {
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


def test_submission_archive_includes_only_curated_public_proof_artifacts(tmp_path):
    artifact = ROOT / "artifacts" / "deployment-verification.json"
    debug_artifact = ROOT / "artifacts" / "local-debug.json"
    stale_generated_artifact = ROOT / "deploy" / ".DS_Store"
    previous_artifact = artifact.read_text(encoding="utf-8") if artifact.exists() else None
    previous_debug = debug_artifact.read_text(encoding="utf-8") if debug_artifact.exists() else None
    previous_stale_generated = (
        stale_generated_artifact.read_bytes() if stale_generated_artifact.exists() else None
    )
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text('{"project": "YITING"}\n', encoding="utf-8")
    debug_artifact.write_text('{"local": true}\n', encoding="utf-8")
    stale_generated_artifact.parent.mkdir(exist_ok=True)
    stale_generated_artifact.write_bytes(b"local finder metadata")
    output = tmp_path / "yiting-source.zip"
    try:
        result = build_submission_archive(output, allow_dirty=True)
    finally:
        if previous_artifact is None:
            artifact.unlink(missing_ok=True)
        else:
            artifact.write_text(previous_artifact, encoding="utf-8")
        if previous_debug is None:
            debug_artifact.unlink(missing_ok=True)
        else:
            debug_artifact.write_text(previous_debug, encoding="utf-8")
        if previous_stale_generated is None:
            stale_generated_artifact.unlink(missing_ok=True)
        else:
            stale_generated_artifact.write_bytes(previous_stale_generated)
        try:
            artifact.parent.rmdir()
        except OSError:
            pass

    assert result.output == output.resolve()
    assert result.file_count > 50

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert "README.md" in names
    assert "LICENSE" in names
    assert ".dockerignore" in names
    assert "Dockerfile" in names
    assert "docker/entrypoint.sh" in names
    assert "dashboard/Dockerfile" in names
    assert "gateway/rate_limit.py" in names
    assert "docs/ADOPTION_ROADMAP.md" in names
    assert "docs/ARCHITECTURE.md" in names
    assert "docs/BASELINE_MEASUREMENT.md" in names
    assert "docs/BLOG_POST.md" in names
    assert "docs/ALIBABA_DEPLOYMENT_PROOF.md" in names
    assert "docs/FINAL_SUBMISSION_CHECKLIST.md" in names
    assert "docs/INSTALL_AND_RUN.md" in names
    assert "docs/JUDGE_PACKET.md" in names
    assert "docs/JUDGE_TESTING.md" in names
    assert "docs/JUDGING_RUBRIC.md" in names
    assert "docs/PUBLIC_JUDGE_MODE.md" in names
    assert "docs/PUBLIC_REPOSITORY.md" in names
    assert "docs/SECURITY.md" in names
    assert "docs/SLIDE_DECK.md" in names
    assert "docs/THIRD_PARTY_COMPLIANCE.md" in names
    assert "docs/TRACK3_SCORECARD.md" in names
    assert "docs/SUBMISSION_FORM.md" in names
    assert "deploy/shared-host/compose.prod.yml" in names
    assert "deploy/shared-host/README.md" in names
    assert "deploy/standalone/compose.yml" in names
    assert "deploy/standalone/Caddyfile.example" in names
    assert "deploy/standalone/README.md" in names
    assert "deploy/standalone/yiting.env.example" in names
    assert "deploy/ecs/compose.prod.yml" in names
    assert "infra/alibaba-ecs/README.md" in names
    assert "infra/alibaba-ecs/main.tf" in names
    assert "infra/alibaba-ecs/variables.tf" in names
    assert "infra/alibaba-ecs/outputs.tf" in names
    assert "infra/alibaba-ecs/versions.tf" in names
    assert "scripts/backup_restore_check.py" in names
    assert "scripts/ecs_ops_acceptance.py" in names
    assert "scripts/final_proof_index.py" in names
    assert "scripts/qwen_smoke.py" in names
    assert "scripts/reset_demo.py" in names
    assert "scripts/submission_links.py" in names
    assert "scripts/uptime_monitoring.py" in names
    assert "scripts/smoke.py" in names
    assert "scripts/track3_baseline.py" in names
    assert "scripts/track3_paired_benchmark.py" in names
    assert "evals/track3_paired_scenarios.json" in names
    assert "SUBMISSION_MANIFEST.json" in names
    assert "artifacts/docker-image-smoke.json" in names

    assert ".env" not in names
    assert not any("/node_modules/" in f"/{name}/" for name in names)
    assert not any("/.next/" in f"/{name}/" for name in names)
    assert not any(name.endswith((".db", ".db-shm", ".db-wal", ".pyc")) for name in names)
    assert "deploy/.DS_Store" not in names

    for slug in [
        "lin-xun",
        "chen-ming",
        "zhou-shen",
        "han-ce",
        "lu-xing",
        "wen-lu",
        "song-shu",
    ]:
        assert f"dashboard/public/agents/{slug}.png" in names
    for old_slug in [
        "triage",
        "diagnosis",
        "safety",
        "commander",
        "operator",
        "recorder",
        "scribe",
    ]:
        assert f"dashboard/public/agents/{old_slug}.png" not in names
    assert "dashboard/public/agents/maya.png" not in names
    assert "dashboard/public/agents/atlas.png" not in names
    assert "dashboard/public/agents/quill.png" not in names
    assert "dashboard/public/next.svg" not in names
    assert "dashboard/public/vercel.svg" not in names
    assert "artifacts/deployment-verification.json" in names
    assert "artifacts/local-debug.json" not in names


def test_submission_archive_manifest_records_commit(tmp_path):
    output = tmp_path / "yiting-source.zip"
    build_submission_archive(output, allow_dirty=True)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("SUBMISSION_MANIFEST.json"))

    assert manifest["project"] == "YITING"
    assert manifest["primary_track"] == "Track 3: Agent Society"
    assert manifest["track3_proof_summary"]["primary_track"] == "Track 3: Agent Society"
    assert set(manifest["track3_proof_summary"]["required_showcase"]) == {
        "distinct_capabilities",
        "task_decomposition",
        "dialogue_and_negotiation",
        "disagreement_resolution",
        "hero_evidence_standard",
        "execution_conflict_resolution",
        "measurable_efficiency_gain",
    }
    track3_summary = json.dumps(manifest["track3_proof_summary"])
    assert "/agent-skills" in track3_summary
    assert "inspectable MCP-style skill contracts" in track3_summary
    assert "Qwen Cloud use" in track3_summary
    assert "Track 3 proof categories" in track3_summary
    assert "judge demo cues" in track3_summary
    assert "/evidence/{incident_id}" in track3_summary
    assert "/stats/runsummary" in track3_summary
    assert "higher task success" in track3_summary
    assert "lower unsupported-claim" in track3_summary
    assert "better quality per token" in track3_summary
    assert "speed_improvement_claimed=false" in track3_summary
    assert "speedup_factor > 1" in track3_summary
    assert "disagreement_events > 0" in track3_summary
    assert "matched same-family run IDs include the hero incident" in track3_summary
    assert "within that same family comparison" in track3_summary
    assert "artifacts/track3-baseline.json" in track3_summary
    assert "artifacts/track3-paired-benchmark.json" in track3_summary
    assert "scripts/track3_paired_benchmark.py" in track3_summary
    assert "same fixed scenarios" in track3_summary
    assert "does not claim speed improvement" in track3_summary
    distinct = manifest["track3_proof_summary"]["required_showcase"]["distinct_capabilities"]
    assert distinct["required_fields"] == [
        "tool_name",
        "input_schema",
        "output_schema",
        "qwen_cloud_use",
        "track3_requirement",
        "judge_demo_cue",
        "deterministic_guardrail",
        "evidence_artifact",
    ]
    assert isinstance(manifest["working_tree_clean"], bool)
    assert manifest["file_count"] > 50
    assert manifest["git_commit"]
    assert "node_modules" in manifest["excludes"]
    assert manifest["proof_artifacts"]["innovation_ai_creativity"] == [
        "shared/skill_registry.py",
        "docs/JUDGE_PACKET.md",
        "docs/JUDGING_RUBRIC.md",
        "docs/TRACK3_SCORECARD.md",
    ]
    for artifacts in manifest["proof_artifacts"].values():
        for artifact in artifacts:
            if artifact.startswith("/"):
                continue
            assert artifact in names
    assert "scripts/track3_baseline.py" in manifest["proof_artifacts"]["problem_value_impact"]
    assert "scripts/track3_paired_benchmark.py" in manifest["proof_artifacts"]["problem_value_impact"]
    assert "evals/track3_paired_scenarios.json" in manifest["proof_artifacts"]["problem_value_impact"]
    assert "docs/ADOPTION_ROADMAP.md" in manifest["proof_artifacts"]["problem_value_impact"]
    assert "docs/BASELINE_MEASUREMENT.md" in manifest["proof_artifacts"]["problem_value_impact"]
    assert "docs/TRACK3_SCORECARD.md" in manifest["proof_artifacts"]["problem_value_impact"]
    assert manifest["proof_artifacts"]["blog_post_prize"] == ["docs/BLOG_POST.md"]
    assert (
        "docs/ENGINEERING_PROOF.md"
        in manifest["proof_artifacts"]["technical_depth"]
    )
    assert "Dockerfile" in manifest["proof_artifacts"]["technical_depth"]
    assert "docker/entrypoint.sh" in manifest["proof_artifacts"]["technical_depth"]
    assert "infra/alibaba-ecs/main.tf" in manifest["proof_artifacts"]["technical_depth"]
    assert "infra/alibaba-ecs/README.md" in manifest["proof_artifacts"]["technical_depth"]
    assert "deploy/shared-host/compose.prod.yml" in manifest["proof_artifacts"]["technical_depth"]
    assert "deploy/ecs/compose.prod.yml" in manifest["proof_artifacts"]["technical_depth"]
    assert (
        "docs/FINAL_SUBMISSION_CHECKLIST.md"
        in manifest["proof_artifacts"]["presentation_documentation"]
    )
    assert "docs/JUDGE_TESTING.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/SECURITY.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "deploy/shared-host/README.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "deploy/standalone/README.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/SUBMISSION_FORM.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/SLIDE_DECK.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/PUBLIC_JUDGE_MODE.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/PUBLIC_REPOSITORY.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/INSTALL_AND_RUN.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "docs/TRACK3_SCORECARD.md" in manifest["proof_artifacts"]["presentation_documentation"]
    assert "scripts/uptime_monitoring.py" in manifest["proof_artifacts"]["technical_depth"]
    assert "artifacts/live/ecs-ops-acceptance.json" in manifest["track3_proof_summary"]["judge_routes"]
    assert manifest["final_proof_command"].startswith("make submission-proof")

    assert "HERO_INCIDENT_ID=..." in manifest["final_proof_command"]
    assert "BASELINE_INCIDENT_FAMILY=..." in manifest["final_proof_command"]
    assert manifest["generated_proof_artifacts"] == [
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
    assert manifest["final_submission_checklist"] == [
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
    assert manifest["final_hour_order"] == [
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
        (
            "Run app-scoped Compose restarts, verify both apps recover with persisted state/evidence/logs, "
            "and review artifacts/live/app-restart-resilience.json."
        ),
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
    hero_standard = manifest["track3_proof_summary"]["required_showcase"]["hero_evidence_standard"]
    assert "EXECUTED" in hero_standard["claim"]
    assert "ActionReceipt" in hero_standard["claim"]
    assert "scripts/final_proof_index.py" in hero_standard["evidence"]
    assert "scripts/verify_deployment.py" in hero_standard["evidence"]


def test_submission_packager_refuses_dirty_source_without_explicit_override(monkeypatch):
    monkeypatch.setattr(package_submission, "_git_worktree_clean", lambda: False)

    with pytest.raises(PackageError, match="Refusing to package a dirty working tree"):
        package_submission._require_clean_source()

    package_submission._require_clean_source(allow_dirty=True)


def test_submission_archive_text_has_no_removed_providers_or_stale_hosts(tmp_path):
    output = tmp_path / "yiting-source.zip"
    build_submission_archive(output, allow_dirty=True)

    forbidden = [
        "aim" + "lapi",
        "feather" + "less",
        "lab" + "lab",
        "zhan" + "lue" + "shi",
        "b" + "and of agents",
        "app." + "b" + "and.ai",
        "b" + "and_api_key",
        "open" + "router",
        "deep" + "seek",
        "anth" + "ropic",
        "clau" + "de",
        "gem" + "ini",
        "google" + " ai",
        "or" + "acle",
        "war" + "room",
        "129." + "80.",
    ]
    offenders: list[str] = []
    term_allowlist: dict[str, set[str]] = {}
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
            if suffix not in PACKAGE_TEXT_SUFFIXES and name not in {"Caddyfile", "LICENSE", "Makefile"}:
                continue
            text = archive.read(name).decode("utf-8", errors="ignore").lower()
            for term in forbidden:
                if term in term_allowlist.get(name, set()):
                    continue
                if term in text:
                    offenders.append(f"{name} contains {term!r}")

    assert offenders == []


def test_submission_archive_text_has_no_local_absolute_paths(tmp_path):
    output = tmp_path / "yiting-source.zip"
    build_submission_archive(output, allow_dirty=True)

    local_markers = {
        str(ROOT),
        str(ROOT.parent),
        "/" + "/".join(ROOT.parts[1:3]) + "/",
        "Documents" + "/" + "lab" + "lab2",
        ROOT.parent.parent.name + "/" + "Track 4  Qwen",
    }
    offenders: list[str] = []
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if any(marker in name for marker in local_markers):
                offenders.append(f"{name}: archive path contains local marker")
                continue
            suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
            if suffix not in PACKAGE_TEXT_SUFFIXES and name not in {"Caddyfile", "LICENSE", "Makefile"}:
                continue
            text = archive.read(name).decode("utf-8", errors="ignore")
            for marker in local_markers:
                if marker in text:
                    offenders.append(f"{name}: contains {marker!r}")

    assert offenders == []


def test_package_text_scan_rejects_credential_shaped_values(tmp_path):
    token = "sk-" + "a" * 40
    path = tmp_path / "debug.txt"
    path.write_text(f"dashscope_key={token}\n", encoding="utf-8")

    assert "credential-pattern" in _scan_text_file(path)


def test_package_text_scan_rejects_local_absolute_paths(tmp_path):
    local_path = "/" + "Users" + "/" + "sample-user" + "/" + "project" + "/" + ".env"
    path = tmp_path / "debug.txt"
    path.write_text(f"local env backup: {local_path}\n", encoding="utf-8")

    assert "local-absolute-path" in _scan_text_file(path)


def test_package_text_scan_rejects_stale_public_submission_terms(tmp_path):
    path = tmp_path / "debug.txt"
    path.write_text("stale source folder: " + "lab" + "lab2\n", encoding="utf-8")

    assert "stale-hackathon" in _scan_text_file(path)

    readme_matches = _scan_text_file(ROOT / "README.md")

    assert "stale-origin-name" not in readme_matches
    assert "stale-host" not in readme_matches

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import final_proof_index


def _qwen() -> dict:
    return {
        "project": "YITING",
        "proof_type": "qwen-cloud-smoke",
        "passed": True,
        "model": "openai/qwen3.7-plus",
    }


def _baseline() -> dict:
    return {
        "project": "YITING",
        "proof_type": "track3-manual-baseline",
        "schema_version": 2,
        "baseline": {
            "incident_family": "suspicious deploy",
            "measured_seconds": 240,
        },
        "yiting": {
            "comparison_scope": "same-family runsummary runs",
            "matched_run_count": 1,
            "matched_incident_ids": ["INC-HERO-123"],
            "total_handoffs": 12,
            "disagreement_events": 2,
            "human_interventions": 1,
            "recovery_verified_count": 1,
        },
        "speedup_factor": 3.0,
        "track3_requirements_checked": {
            "distinct_role_handoffs": True,
            "disagreement_or_revision": True,
            "human_intervention": True,
            "recovery_verification": True,
            "measured_speedup_over_baseline": True,
        },
    }


def _deployment() -> dict:
    return {
        "project": "YITING",
        "proof_type": "alibaba-ecs-deployment-verification",
        "passed": True,
        "targets": {
            "public_url": "https://demo.yiting.ai",
            "incident_id": "INC-HERO-123",
            "require_speedup": True,
            "require_public_read_only": True,
        },
        "checks": [
            {"name": "public evidence chain", "ok": True, "detail": "chain_valid=true"},
            {"name": "public chaos disabled", "ok": True, "detail": "HTTP 403 disabled"},
        ],
    }


def _evidence() -> dict:
    return {
        "incident_id": "INC-HERO-123",
        "state": "EXECUTED",
        "incident_family": "suspicious deploy",
        "chain_valid": True,
        "cards": [
            {"card_type": "AlertCard"},
            {"card_type": "TriageDecision"},
            {"card_type": "Assessment"},
            {"card_type": "Verdict"},
            {"card_type": "ResponsePlan"},
            {"card_type": "StructuredApproval"},
            {"card_type": "ActionReceipt"},
        ],
        "collaboration": {
            "role_sequence": [
                "recorder",
                "triage",
                "diagnosis",
                "safety_reviewer",
                "commander",
                "human_gateway",
                "operator",
            ],
            "handoff_count": 6,
            "challenge_count": 1,
            "human_decision_count": 1,
            "human_decisions": [
                {"sequence": 6, "decision": "APPROVED", "reason": "human approved"}
            ],
            "authorization_path": "StructuredApproval",
            "execution_conflict_control": {
                "exact_match": True,
            },
        },
    }


def _backup_restore() -> dict:
    return {
        "format": "yiting-backup-restore-v1",
        "project": "YITING",
        "artifact_class": "live_backup_restore",
        "submission_evidence": True,
        "verified_live": True,
        "backup_dir_name": "20260621T000000Z",
        "passed": True,
        "backups": [
            {
                "label": "gateway",
                "backup_name": "gateway.sqlite",
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "restore": {"ok": True, "integrity": "ok", "table_count": 3},
                "passed": True,
            },
            {
                "label": "victim",
                "backup_name": "victim.sqlite",
                "size_bytes": 1024,
                "sha256": "b" * 64,
                "restore": {"ok": True, "integrity": "ok", "table_count": 1},
                "passed": True,
            },
        ],
        "note": "Same-VM backups protect logical/container state, not total ECS host loss unless copied off-host.",
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_final_proof_index_writes_markdown_and_uses_saved_evidence(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, _evidence())
    output = artifacts / "final-proof-index.md"

    result = final_proof_index.build_final_proof_index(
        public_url="https://demo.yiting.ai",
        hero_incident_id="INC-HERO-123",
        artifact_dir=artifacts,
        hero_evidence_json=hero_evidence,
        output_md=output,
        fetch_evidence=False,
    )

    assert result == output
    text = output.read_text(encoding="utf-8")
    assert "YITING Final Proof Index" in text
    assert "Track 3: Agent Society" in text
    assert "INC-HERO-123" in text
    assert "EXECUTED" in text
    assert "Hero incident family" in text
    assert "suspicious deploy" in text
    assert "Qwen smoke" in text
    assert "3.0x" in text
    assert "Paired quality benchmark" in text
    assert "Hosted timing speedup" in text
    assert "Backup restore proof" in text
    assert "Backup labels" in text
    assert "gateway, victim" in text
    assert "Baseline matched incident IDs" in text
    assert "INC-HERO-123" in text
    assert "Required Track 3 Showcase" in text
    assert "Task decomposition and handoffs" in text
    assert "Execution conflict resolution" in text
    assert "Weighted Judge Score Map" in text
    assert "Innovation & AI Creativity — 30%" in text
    assert "Technical Depth & Engineering — 30%" in text
    assert "Problem Value & Impact — 25%" in text
    assert "Presentation & Documentation — 15%" in text
    assert "Stage One viability" in text
    assert "Blog Post Prize" in text
    assert "Reviewer Cross-Checks" in text
    assert "Track 3 is primary" in text
    assert "Live Qwen smoke passed: True" in text
    assert "MCP-style registry and review manifest" in text
    assert "not a network MCP server" in text
    assert "chain_valid=True" in text
    assert "measured same-family baseline" in text
    assert "does not claim speed" in text
    assert "Public read-only judge mode required: True" in text
    assert "Exact-envelope execution" in text
    assert "Persistence safety" in text
    assert "backup-restore.json proves gateway and victim SQLite backups" in text
    assert "Public chaos disabled check" in text
    assert "Submission Requirement Cross-Checks" in text
    assert "Installability" in text
    assert "Public open-source repository" in text
    assert "Alibaba Cloud proof" in text
    assert "Architecture diagram" in text
    assert "Demo media compliance" in text
    assert "Final submission runbook" in text
    assert "artifacts/hero-evidence.json" in text
    assert "artifacts/live/backup-restore.json" in text
    assert "artifacts/track3-paired-benchmark.json" in text
    assert "dist/yiting-submission-source.zip" in text
    assert "docs/INSTALL_AND_RUN.md" in text
    assert "docs/PUBLIC_REPOSITORY.md" in text
    assert "docs/ARCHITECTURE.md" in text
    assert "docs/ALIBABA_CLOUD_PROOF.md" in text
    assert "docs/THIRD_PARTY_COMPLIANCE.md" in text
    assert "docs/FINAL_SUBMISSION_CHECKLIST.md" in text


def test_build_final_proof_index_rejects_weak_artifacts(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    weak_baseline = _baseline()
    weak_baseline["speedup_factor"] = 1.0
    _write_json(artifacts / "track3-baseline.json", weak_baseline)
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, _evidence())

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    assert "speedup_factor > 1" in str(exc.value)


def test_build_final_proof_index_rejects_baseline_not_bound_to_hero(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    weak_baseline = _baseline()
    weak_baseline["yiting"]["matched_incident_ids"] = ["INC-OTHER"]
    _write_json(artifacts / "track3-baseline.json", weak_baseline)
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, _evidence())

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    assert "matched runs must include the hero incident" in str(exc.value)


def test_build_final_proof_index_rejects_hero_baseline_family_mismatch(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    weak_evidence = _evidence()
    weak_evidence["incident_family"] = "certificate expiry"
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, weak_evidence)

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    assert "incident_family must match" in str(exc.value)


def test_build_final_proof_index_rejects_evidence_missing_core_roles(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    weak_evidence = _evidence()
    weak_evidence["collaboration"]["role_sequence"] = [
        "recorder",
        "triage",
        "diagnosis",
        "safety_reviewer",
        "observer",
        "auditor",
    ]
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, weak_evidence)

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    assert "collaboration.role_sequence missing roles" in str(exc.value)
    assert "commander" in str(exc.value)
    assert "operator" in str(exc.value)


def test_build_final_proof_index_rejects_mismatched_or_unexecuted_hero(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    weak_evidence = _evidence()
    weak_evidence["incident_id"] = "INC-OTHER"
    weak_evidence["state"] = "APPROVED"
    weak_evidence["cards"] = weak_evidence["cards"][:-1]
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, weak_evidence)

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    error = str(exc.value)
    assert "incident_id must match" in error
    assert "final state must be EXECUTED" in error
    assert "ActionReceipt" in error


def test_build_final_proof_index_rejects_hero_without_disagreement(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    weak_evidence = _evidence()
    weak_evidence["collaboration"]["challenge_count"] = 0
    weak_evidence["collaboration"]["human_decisions"] = [
        {"sequence": 6, "decision": "APPROVED", "reason": "approved only"}
    ]
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, weak_evidence)

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    assert "Verdict(CHALLENGE)" in str(exc.value)
    assert "StructuredApproval(REJECTED)" in str(exc.value)


def test_build_final_proof_index_rejects_weak_backup_restore_artifact(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    weak_backup = _backup_restore()
    weak_backup["verified_live"] = False
    weak_backup["backups"][1]["restore"]["ok"] = False
    _write_json(artifacts / "live" / "backup-restore.json", weak_backup)
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, _evidence())

    with pytest.raises(final_proof_index.FinalProofError) as exc:
        final_proof_index.build_final_proof_index(
            public_url="https://demo.yiting.ai",
            hero_incident_id="INC-HERO-123",
            artifact_dir=artifacts,
            hero_evidence_json=hero_evidence,
            output_md=artifacts / "final-proof-index.md",
            fetch_evidence=False,
        )

    error = str(exc.value)
    assert "verified live submission evidence" in error
    assert "victim backup restore must pass" in error


def test_build_final_proof_index_accepts_human_rejection_as_hero_disagreement(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_json(artifacts / "qwen-smoke.json", _qwen())
    _write_json(artifacts / "track3-baseline.json", _baseline())
    _write_json(artifacts / "deployment-verification.json", _deployment())
    _write_json(artifacts / "live" / "backup-restore.json", _backup_restore())
    evidence = _evidence()
    evidence["collaboration"]["challenge_count"] = 0
    evidence["collaboration"]["human_decision_count"] = 2
    evidence["collaboration"]["human_decisions"] = [
        {"sequence": 6, "decision": "REJECTED", "reason": "use circuit breaker"},
        {"sequence": 8, "decision": "APPROVED", "reason": "approved revision"},
    ]
    hero_evidence = artifacts / "hero-evidence.json"
    _write_json(hero_evidence, evidence)
    output = artifacts / "final-proof-index.md"

    final_proof_index.build_final_proof_index(
        public_url="https://demo.yiting.ai",
        hero_incident_id="INC-HERO-123",
        artifact_dir=artifacts,
        hero_evidence_json=hero_evidence,
        output_md=output,
        fetch_evidence=False,
    )

    text = output.read_text(encoding="utf-8")
    assert "Hero human decisions" in text
    assert "| Hero human decisions | 2 |" in text

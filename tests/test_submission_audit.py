from __future__ import annotations

import json
import shutil
import zipfile

from scripts import submission_audit
from scripts.package_submission import TRACK3_PROOF_SUMMARY
from scripts.submission_audit import run_audit


def _remove_pytest_runtime_caches() -> None:
    for path in submission_audit.ROOT.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)


def test_submission_audit_requires_judge_and_blog_artifacts():
    _remove_pytest_runtime_caches()

    results = {result.name: result for result in run_audit()}

    assert results["open-source license"].ok is True
    assert results["open-source license"].detail == "LICENSE detected as MIT"
    assert results["architecture diagram doc"].ok is True
    assert (
        results["architecture diagram doc"].detail
        == "docs/ARCHITECTURE.md covers Qwen, backend, database, and frontend connections"
    )
    assert results["Alibaba Cloud proof material"].ok is True
    assert (
        results["Alibaba Cloud proof material"].detail
        == "docs and code links prove Qwen Cloud API use plus Alibaba ECS deployment verification"
    )
    assert results["Alibaba deployment proof doc"].ok is True
    assert results["Alibaba deployment proof doc"].detail == "docs/ALIBABA_DEPLOYMENT_PROOF.md"
    assert results["Alibaba ECS IaC README"].ok is True
    assert results["Alibaba ECS IaC README"].detail == "infra/alibaba-ecs/README.md"
    assert results["Alibaba ECS IaC main"].ok is True
    assert results["Alibaba ECS IaC main"].detail == "infra/alibaba-ecs/main.tf"
    assert results["ECS VM Compose deployment profiles"].ok is True
    assert (
        results["ECS VM Compose deployment profiles"].detail
        == "Docker, standalone, shared-host, ECS, judge, and security deployment material present with YITING-only boundaries"
    )
    assert results["judging rubric material"].ok is True
    assert (
        results["judging rubric material"].detail
        == "rubric docs map Stage One and all weighted criteria to concrete Track 3 evidence"
    )
    assert results["impact and adoption material"].ok is True
    assert (
        results["impact and adoption material"].detail
        == "roadmap and blog draft prove real-world value, productization path, community potential, and optional blog narrative"
    )
    assert results["public repository material"].ok is True
    assert (
        results["public repository material"].detail
        == "repo guide, license, ignore rules, README, CI, and run docs cover public open-source publication"
    )
    assert results["submission text description"].ok is True
    assert (
        results["submission text description"].detail
        == "form packet and README explain features, functionality, Track 3 fit, and built-with stack"
    )
    assert results["demo media compliance"].ok is True
    assert (
        results["demo media compliance"].detail
        == "demo docs enforce under-3-minute public video and permitted media/platform rules"
    )
    assert results["third-party compliance material"].ok is True
    assert (
        results["third-party compliance material"].detail
        == "docs cover authorized Qwen/Alibaba use, declared dependencies, synthetic data, media hygiene, and judge-mode cost controls"
    )
    assert results["install and run material"].ok is True
    assert (
        results["install and run material"].detail
        == "docs and manifests cover locked install, local verification, hosted deployment, and source packaging"
    )
    assert results["judge packet"].ok is True
    assert results["judge packet"].detail == "docs/JUDGE_PACKET.md"
    assert results["baseline measurement worksheet"].ok is True
    assert results["baseline measurement worksheet"].detail == "docs/BASELINE_MEASUREMENT.md"
    assert results["Track 3 paired benchmark runner"].ok is True
    assert results["Track 3 paired benchmark runner"].detail == "scripts/track3_paired_benchmark.py"
    assert results["backup restore check script"].ok is True
    assert results["backup restore check script"].detail == "scripts/backup_restore_check.py"
    assert results["ECS operations acceptance script"].ok is True
    assert results["ECS operations acceptance script"].detail == "scripts/ecs_ops_acceptance.py"
    assert results["public submission links script"].ok is True
    assert results["public submission links script"].detail == "scripts/submission_links.py"
    assert results["uptime monitoring proof helper"].ok is True
    assert results["uptime monitoring proof helper"].detail == "scripts/uptime_monitoring.py"
    assert results["Track 3 paired benchmark dataset"].ok is True
    assert results["Track 3 paired benchmark dataset"].detail == "evals/track3_paired_scenarios.json"
    assert results["engineering proof matrix"].ok is True
    assert results["engineering proof matrix"].detail == "docs/ENGINEERING_PROOF.md"
    assert results["slide deck source"].ok is True
    assert results["slide deck source"].detail == "docs/SLIDE_DECK.md"
    assert results["public judge mode safety doc"].ok is True
    assert results["public judge mode safety doc"].detail == "docs/PUBLIC_JUDGE_MODE.md"
    assert results["judge testing guide"].ok is True
    assert results["judge testing guide"].detail == "docs/JUDGE_TESTING.md"
    assert results["credential pattern scan"].ok is True
    assert results["credential pattern scan"].detail == "no credential-shaped secrets in text files"
    assert results["local absolute path scan"].ok is True
    assert results["local absolute path scan"].detail == "no local absolute paths in text files"
    assert results["stale generated file scan"].ok is True
    assert results["stale generated file scan"].detail == "no stale generated files in release tree"
    assert results["stale public text scan"].ok is True
    assert results["stale public text scan"].detail == "no stale origin or provider text in release tree"
    assert results["security guide"].ok is True
    assert results["security guide"].detail == "docs/SECURITY.md"
    assert results["gateway rate-limit middleware"].ok is True
    assert results["gateway rate-limit middleware"].detail == "gateway/rate_limit.py"
    assert results["shared-host Compose profile"].ok is True
    assert results["shared-host Compose profile"].detail == "deploy/shared-host/compose.prod.yml"
    assert results["standalone Compose profile"].ok is True
    assert results["standalone Compose profile"].detail == "deploy/standalone/compose.yml"
    assert results["ECS Compose profile"].ok is True
    assert results["ECS Compose profile"].detail == "deploy/ecs/compose.prod.yml"
    assert results["Track 3 submission choice locked"].ok is True
    assert results["Track 3 submission choice locked"].detail == "Track 3 form choice is explicit"
    assert results["Track 3 baseline proof helper"].ok is True
    assert results["Track 3 baseline proof helper"].detail == "scripts/track3_baseline.py"
    assert results["Track 3 paired benchmark artifacts"].ok is True
    assert results["Track 3 paired benchmark artifacts"].detail == "valid paired benchmark proof"
    assert results["judge packet hero evidence finalized"].ok is False
    assert results["judge packet hero evidence finalized"].final_required is True
    assert "Pending final hosted hero run" in results["judge packet hero evidence finalized"].detail
    assert results["submission form public links finalized"].ok is False
    assert results["submission form public links finalized"].final_required is True
    assert "https://youtu.be/<video-id>" in results["submission form public links finalized"].detail
    assert "https://<deployment-domain>" not in results["submission form public links finalized"].detail
    assert "https://youtu.be/<deployment-proof-video-id>" in results["submission form public links finalized"].detail
    assert results["Qwen Cloud smoke artifact finalized"].final_required is True
    assert results["Docker image smoke artifact"].ok is True
    assert results["Docker image smoke artifact"].detail == "valid Docker image smoke proof"
    assert results["Track 3 baseline artifact finalized"].final_required is True
    assert results["deployment verification artifact finalized"].final_required is True
    assert results["hero evidence artifact finalized"].final_required is True
    assert results["final proof index finalized"].final_required is True
    assert results["public submission links artifact finalized"].final_required is True
    assert results["uptime monitoring artifact finalized"].final_required is True
    assert results["source package finalized"].final_required is True


def test_open_source_license_check_requires_detectable_mit_text(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_open_source_license()

    assert result.ok is False
    assert result.detail == "LICENSE missing"

    (tmp_path / "LICENSE").write_text("All rights reserved\n", encoding="utf-8")

    result = submission_audit._check_open_source_license()

    assert result.ok is False
    assert "not detectable as MIT" in result.detail

    (tmp_path / "LICENSE").write_text(
        "\n".join([
            "MIT License",
            "",
            "Permission is hereby granted, free of charge, to any person obtaining a copy",
            "THE SOFTWARE IS PROVIDED \"AS IS\"",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_open_source_license()

    assert result.ok is True
    assert result.detail == "LICENSE detected as MIT"


def test_architecture_diagram_check_requires_qwen_backend_database_frontend(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_architecture_diagram()

    assert result.ok is False
    assert result.detail == "docs/ARCHITECTURE.md missing"

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")

    result = submission_audit._check_architecture_diagram()

    assert result.ok is False
    assert "missing diagram requirement" in result.detail
    assert "```mermaid" in result.detail

    (docs / "ARCHITECTURE.md").write_text(
        "\n".join([
            "# Architecture",
            "```mermaid",
            "flowchart LR",
            "subgraph Alibaba[\"Alibaba Cloud ECS\"]",
            "Dashboard[\"Dashboard\"]",
            "Gateway[\"Gateway\"]",
            "DB[(\"SQLite\")]",
            "Triage[\"Triage\"]",
            "end",
            "Qwen[\"Alibaba Cloud Model Studio\"]",
            "Dashboard --> Gateway",
            "Gateway --> DB",
            "Triage --> Qwen",
            "```",
            "Qwen Cloud connection",
            "Backend connection",
            "Database connection",
            "Frontend connection",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_architecture_diagram()

    assert result.ok is True
    assert result.detail == "docs/ARCHITECTURE.md covers Qwen, backend, database, and frontend connections"


def test_track3_paired_benchmark_audit_requires_quality_per_token_gain(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    summary = {
        "project": "YITING",
        "proof_type": "track3-paired-reproducible-benchmark",
        "schema_version": 1,
        "dataset_id": "yiting-track3-paired-v1",
        "rubric_version": "track3-agent-society-rubric-v1",
        "scenario_count": 20,
        "paired_runs_per_scenario": 3,
        "fairness_controls": {
            "same_input_scenarios": True,
            "same_declared_rubric": True,
            "same_model_tier": True,
            "token_normalized_reporting": True,
            "manual_removal_of_failed_cases": False,
        },
        "model_control": {"same_model_for_single_agent_and_society": True},
        "variants": {
            "single_agent": {
                "success_rate": 0.4,
                "mean_score": 0.6,
                "risks_detected": 20,
                "unsupported_claims": 6,
                "quality_per_1k_tokens": 1.2,
            },
            "full_yiting_society": {
                "success_rate": 0.8,
                "mean_score": 0.9,
                "risks_detected": 40,
                "unsupported_claims": 0,
                "quality_per_1k_tokens": 1.1,
            },
        },
        "comparison": {
            "higher_task_success": True,
            "better_mean_score": True,
            "lower_unsupported_claim_rate": True,
            "more_risks_detected": True,
            "better_quality_per_token": False,
            "speed_improvement_claimed": False,
        },
        "claims_not_made": ["speed improvement"],
    }
    rows = []
    for scenario_index in range(1, 21):
        for run_index in range(1, 4):
            input_hash = f"{scenario_index:064x}"[-64:]
            for variant in ("single_agent", "full_yiting_society"):
                rows.append(
                    {
                        "dataset_id": "yiting-track3-paired-v1",
                        "rubric_version": "track3-agent-society-rubric-v1",
                        "scenario_id": f"T3-{scenario_index:03}",
                        "run_index": run_index,
                        "variant": variant,
                        "input_hash": input_hash,
                        "model_identity": "qwen3.7-plus rolling alias",
                        "same_model_as_pair": True,
                    }
                )
    (artifacts / "track3-paired-benchmark.json").write_text(json.dumps(summary), encoding="utf-8")
    (artifacts / "track3-paired-benchmark-raw.json").write_text(
        json.dumps({"rows": rows}),
        encoding="utf-8",
    )
    (artifacts / "track3-paired-benchmark.csv").write_text(
        "scenario_id,run_index,variant,input_hash,model_identity\n"
        "T3-001,1,single_agent,"
        + "1".zfill(64)
        + ",qwen3.7-plus rolling alias\n"
        "T3-001,1,full_yiting_society,"
        + "1".zfill(64)
        + ",qwen3.7-plus rolling alias\n",
        encoding="utf-8",
    )

    result = submission_audit._check_track3_paired_benchmark_artifacts()

    assert result.ok is False
    assert "society quality_per_1k_tokens must exceed single_agent" in result.detail
    assert "comparison.better_quality_per_token must be true" in result.detail

    summary["variants"]["full_yiting_society"]["quality_per_1k_tokens"] = 1.4
    summary["comparison"]["better_quality_per_token"] = True
    (artifacts / "track3-paired-benchmark.json").write_text(json.dumps(summary), encoding="utf-8")

    result = submission_audit._check_track3_paired_benchmark_artifacts()

    assert result.ok is True
    assert result.detail == "valid paired benchmark proof"


def test_alibaba_cloud_proof_material_requires_docs_and_code_links(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_alibaba_cloud_proof_material()

    assert result.ok is False
    assert "missing required proof file" in result.detail
    assert "docs/ALIBABA_CLOUD_PROOF.md" in result.detail

    for rel_path in [
        "docs/ALIBABA_DEPLOYMENT_PROOF.md",
        "docs/ALIBABA_CLOUD_PROOF.md",
        "infra/alibaba-ecs/README.md",
        "infra/alibaba-ecs/main.tf",
        "infra/alibaba-ecs/variables.tf",
        "infra/alibaba-ecs/outputs.tf",
        "infra/alibaba-ecs/versions.tf",
        "shared/config.py",
        "shared/qwen_reasoning.py",
        "scripts/qwen_smoke.py",
        "scripts/verify_deployment.py",
        "deploy/alibaba-ecs/README.md",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_alibaba_cloud_proof_material()

    assert result.ok is False
    assert "Qwen Cloud / Alibaba Cloud Model Studio" in result.detail
    assert "QWEN_DEFAULT_BASE_URL" in result.detail

    (tmp_path / "docs" / "ALIBABA_DEPLOYMENT_PROOF.md").write_text(
        "\n".join([
            "infra/alibaba-ecs/",
            "Manual ECS provisioning is allowed",
            "Terraform",
            "parity table",
            "deploy/shared-host/compose.prod.yml",
            "scripts/qwen_smoke.py",
            "scripts/verify_deployment.py",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ALIBABA_CLOUD_PROOF.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "infra" / "alibaba-ecs" / "README.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "infra" / "alibaba-ecs" / "main.tf").write_text(
        "\n".join([
            'resource "alicloud_instance" "judging" {}',
            'resource "alicloud_security_group" "judging" {}',
            'port_range        = "80/80"',
            'port_range        = "443/443"',
            'port_range        = "22/22"',
            "var.ssh_source_cidr",
            "cloud_essd",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "shared" / "config.py").write_text(
        "\n".join([
            "Alibaba Cloud Model Studio",
            "QWEN_DEFAULT_BASE_URL = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'",
            "DASHSCOPE_API_KEY",
            "QWEN_BASE_URL",
            "def get_qwen_api_key(): pass",
            "def get_qwen_base_url(): pass",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "qwen_smoke.py").write_text(
        "\n".join([
            "qwen-cloud-smoke",
            '"provider": "qwen"',
            "capability_matrix",
            "structured_output",
            "response_id",
            "get_qwen_base_url",
            "Qwen smoke passed",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "verify_deployment.py").write_text(
        "\n".join([
            "alibaba-ecs-deployment-verification",
            "Alibaba Cloud ECS",
            "require_public_read_only",
            "require_speedup",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "deploy" / "alibaba-ecs" / "README.md").write_text(
        "\n".join([
            "Alibaba Cloud ECS",
            "DASHSCOPE_API_KEY",
            "Qwen/DashScope",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_alibaba_cloud_proof_material()

    assert result.ok is True
    assert result.detail == "docs and code links prove Qwen Cloud API use plus Alibaba ECS deployment verification"


def test_judging_rubric_material_requires_stage_one_weighted_criteria_and_track3_proof(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_judging_rubric_material()

    assert result.ok is False
    assert "docs/JUDGING_RUBRIC.md" in result.detail

    for rel_path in [
        "docs/JUDGING_RUBRIC.md",
        "docs/TRACK3_SCORECARD.md",
        "docs/SUBMISSION.md",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_judging_rubric_material()

    assert result.ok is False
    assert "Stage One: Baseline Viability" in result.detail
    assert "Agents with distinct capabilities" in result.detail

    (tmp_path / "docs" / "JUDGING_RUBRIC.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "TRACK3_SCORECARD.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "SUBMISSION.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )

    result = submission_audit._check_judging_rubric_material()

    assert result.ok is True
    assert (
        result.detail
        == "rubric docs map Stage One and all weighted criteria to concrete Track 3 evidence"
    )


def test_impact_and_adoption_material_requires_roadmap_blog_and_problem_value(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_impact_and_adoption_material()

    assert result.ok is False
    assert "docs/ADOPTION_ROADMAP.md" in result.detail

    for rel_path in [
        "docs/ADOPTION_ROADMAP.md",
        "docs/BLOG_POST.md",
        "docs/JUDGING_RUBRIC.md",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_impact_and_adoption_material()

    assert result.ok is False
    assert "governed incident-response control plane" in result.detail
    assert "Potential Impact In Concrete Terms" in result.detail

    (tmp_path / "docs" / "ADOPTION_ROADMAP.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "BLOG_POST.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "JUDGING_RUBRIC.md").write_text(
        "\n".join([
            "Problem Value & Impact — 25%",
            "Real-world relevance",
            "Authentic business pain",
            "Product potential",
            "Scalable adoption",
            "Trust story",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_impact_and_adoption_material()

    assert result.ok is True
    assert (
        result.detail
        == "roadmap and blog draft prove real-world value, productization path, community potential, and optional blog narrative"
    )


def test_public_repository_material_requires_publication_guide_license_ci_and_ignores(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_public_repository_material()

    assert result.ok is False
    assert "docs/PUBLIC_REPOSITORY.md" in result.detail

    for rel_path in [
        "docs/PUBLIC_REPOSITORY.md",
        "README.md",
        "LICENSE",
        ".gitignore",
        ".github/workflows/ci.yml",
        "docs/INSTALL_AND_RUN.md",
        "deploy/alibaba-ecs/README.md",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_public_repository_material()

    assert result.ok is False
    assert "Visibility: public" in result.detail
    assert "uv lock --check" in result.detail

    (tmp_path / "docs" / "PUBLIC_REPOSITORY.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "\n".join([
            "YITING",
            "Track 3: Agent Society",
            "docs/INSTALL_AND_RUN.md",
            "docs/PUBLIC_REPOSITORY.md",
            "## License",
            "MIT",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text(
        "\n".join([
            "MIT License",
            "Permission is hereby granted, free of charge",
        ]),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "\n".join([
            ".env",
            "*.db",
            "*.db-shm",
            "*.db-wal",
            "node_modules/",
            ".next/",
            "artifacts/*",
            "!artifacts/live/",
            "!artifacts/qwen-smoke.json",
            "!artifacts/track3-baseline.json",
            "!artifacts/track3-paired-benchmark.json",
            "!artifacts/track3-paired-benchmark-raw.json",
            "!artifacts/track3-paired-benchmark.csv",
            "!artifacts/deployment-verification.json",
            "!artifacts/hero-evidence.json",
            "!artifacts/final-proof-index.md",
            "!artifacts/live/uptime-monitoring.json",
            "!artifacts/live/submission-links.json",
        ]),
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "\n".join([
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
        encoding="utf-8",
    )

    result = submission_audit._check_public_repository_material()

    assert result.ok is True
    assert (
        result.detail
        == "repo guide, license, ignore rules, README, CI, and run docs cover public open-source publication"
    )


def test_submission_text_description_requires_features_track_and_stack(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_submission_text_description()

    assert result.ok is False
    assert "docs/SUBMISSION_FORM.md" in result.detail

    for rel_path in [
        "docs/SUBMISSION_FORM.md",
        "docs/SUBMISSION.md",
        "README.md",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_submission_text_description()

    assert result.ok is False
    assert "## Project Name" in result.detail
    assert "## Text Description" in result.detail

    (tmp_path / "docs" / "SUBMISSION_FORM.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "SUBMISSION.md").write_text(
        "\n".join([
            "## Text Description",
            "Suggested submission description:",
            "Qwen-backed agents triage alerts",
            "human gate for high-risk actions",
            "SHA-256 linked evidence chain",
            "Gateway owns state transitions",
            "## Rubric Mapping",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "\n".join([
            "Evidence-bound incident council",
            "Track 3: Agent Society",
            "Three-Way Human Gate",
            "Application of Technology",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_submission_text_description()

    assert result.ok is True
    assert (
        result.detail
        == "form packet and README explain features, functionality, Track 3 fit, and built-with stack"
    )


def test_demo_media_compliance_requires_video_rules_and_supported_hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_demo_media_compliance()

    assert result.ok is False
    assert "missing required demo/compliance file" in result.detail
    assert "docs/DEMO_SCRIPT.md" in result.detail

    for rel_path in [
        "docs/DEMO_SCRIPT.md",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "scripts/finalize_submission.py",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_demo_media_compliance()

    assert result.ok is False
    assert "Target length: under 3 minutes" in result.detail
    assert "video URL must be YouTube, Vimeo, or Facebook Video" in result.detail

    (tmp_path / "docs" / "DEMO_SCRIPT.md").write_text(
        "\n".join([
            "Target length: under 3 minutes",
            "three-minute mark",
            "2:55 as the hard edit target",
            "project UI, proof artifacts, and your own narration",
            "Do not add copyrighted music, unrelated third-party logos, stock footage, or external media",
            "Must-Capture Judge Shots",
            "Video contains no copyrighted music",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "THIRD_PARTY_COMPLIANCE.md").write_text(
        "\n".join([
            "The final demo video should be a screen recording of the project UI and proof artifacts only",
            "Do not add copyrighted music, unrelated third-party logos, or external media",
            "Incident data is synthetic or webhook-shaped sandbox telemetry",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "finalize_submission.py").write_text(
        "\n".join([
            "YouTube/Vimeo/Facebook Video",
            "video URL must be YouTube, Vimeo, or Facebook Video",
            "deployment-proof video URL",
            "youtube.com",
            "vimeo.com",
            "facebook.com",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_demo_media_compliance()

    assert result.ok is True
    assert result.detail == "demo docs enforce under-3-minute public video and permitted media/platform rules"


def test_third_party_compliance_material_requires_authorization_dependency_and_safety_notes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_third_party_compliance_material()

    assert result.ok is False
    assert "docs/THIRD_PARTY_COMPLIANCE.md" in result.detail

    for rel_path in [
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "docs/ALIBABA_CLOUD_PROOF.md",
        "docs/PUBLIC_JUDGE_MODE.md",
        ".env.example",
        "deploy/alibaba-ecs/yiting.env.example",
        "pyproject.toml",
        "dashboard/package.json",
        "LICENSE",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_third_party_compliance_material()

    assert result.ok is False
    assert "third-party SDKs, APIs, data, assets, or media" in result.detail
    assert "DASHSCOPE_API_KEY" in result.detail

    (tmp_path / "docs" / "THIRD_PARTY_COMPLIANCE.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ALIBABA_CLOUD_PROOF.md").write_text(
        "\n".join([
            "Qwen Cloud / Alibaba Cloud Model Studio",
            "Alibaba Cloud ECS",
            "DASHSCOPE_API_KEY",
            "QWEN_API_KEY",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "PUBLIC_JUDGE_MODE.md").write_text(
        "\n".join([
            "read-only",
            "HTTP `403`",
            "YITING_LIVE_CHAOS",
        ]),
        encoding="utf-8",
    )
    env_text = "\n".join([
        "DASHSCOPE_API_KEY",
        "QWEN_BASE_URL",
        "YITING treats DASHSCOPE_API_KEY as the primary model credential",
        "QWEN_API_KEY is accepted only as a backward-compatible alias",
    ])
    (tmp_path / ".env.example").write_text(env_text, encoding="utf-8")
    (tmp_path / "deploy" / "alibaba-ecs" / "yiting.env.example").write_text(env_text, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "fastapi",
            "httpx",
            "litellm",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "dashboard" / "package.json").write_text(
        "\n".join([
            '"next"',
            '"react"',
            '"react-dom"',
        ]),
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text(
        "\n".join([
            "MIT License",
            "Permission is hereby granted, free of charge",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_third_party_compliance_material()

    assert result.ok is True
    assert (
        result.detail
        == "docs cover authorized Qwen/Alibaba use, declared dependencies, synthetic data, media hygiene, and judge-mode cost controls"
    )


def test_install_and_run_material_requires_reproducible_commands_and_manifests(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_install_and_run_material()

    assert result.ok is False
    assert "docs/INSTALL_AND_RUN.md" in result.detail

    for rel_path in [
        "docs/INSTALL_AND_RUN.md",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "dashboard/package.json",
        "Makefile",
        "scripts/package_submission.py",
    ]:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    result = submission_audit._check_install_and_run_material()

    assert result.ok is False
    assert "uv sync --locked" in result.detail
    assert '"build": "next build"' in result.detail

    (tmp_path / "docs" / "INSTALL_AND_RUN.md").write_text(
        "\n".join([
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
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "\n".join([
            "docs/INSTALL_AND_RUN.md",
            "uv sync",
            "make dev",
            "DASHSCOPE_API_KEY",
            "deploy/alibaba-ecs/",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "yiting"',
            "requires-python",
            "dependencies = [",
            "[dependency-groups]",
            "pytest",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        "\n".join([
            "version = 1",
            "requires-python = \">=3.12\"",
            "[[package]]",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "dashboard" / "package.json").write_text(
        "\n".join([
            '{"scripts": {"build": "next build"},',
            '"dependencies": {"next": "16.2.9", "react": "19.2.4"}}',
        ]),
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        "\n".join([
            "dev:",
            "test:",
            "dashboard-build:",
            "local-certify:",
            "submission-package:",
            "submission-proof:",
            "submission-ready:",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "package_submission.py").write_text(
        "\n".join([
            "yiting-submission-source.zip",
            "SUBMISSION_MANIFEST.json",
            "EXCLUDED_DIRS",
            "TRACK3_PROOF_SUMMARY",
        ]),
        encoding="utf-8",
    )

    result = submission_audit._check_install_and_run_material()

    assert result.ok is True
    assert (
        result.detail
        == "docs and manifests cover locked install, local verification, hosted deployment, and source packaging"
    )


def test_baseline_artifact_check_requires_same_family_track3_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    good = {
        "project": "YITING",
        "proof_type": "track3-manual-baseline",
        "schema_version": 2,
        "baseline": {
            "label": "One-person incident response rehearsal",
            "incident_family": "suspicious deploy",
            "measured_seconds": 240,
            "source_requirement": "Measured outside YITING with stopwatch notes.",
        },
        "comparison_method": {
            "formula": "baseline.measured_seconds / yiting.avg_total_resolution_seconds",
            "fairness_rule": "Compare the same incident family and the same terminal criterion.",
            "terminal_criterion": "Terminal incident state with recovery verification when an action executes.",
            "hosted_verifier": "scripts/verify_deployment.py --require-speedup",
        },
        "yiting": {
            "avg_total_resolution_seconds": 80,
            "comparison_scope": "same-family runsummary runs",
            "matched_run_count": 1,
            "matched_incident_ids": ["INC-SUSPICIOUS-1"],
            "incidents_measured": 1,
            "total_handoffs": 6,
            "disagreement_events": 1,
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
    (artifacts / "track3-baseline.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_track3_baseline_artifact()

    assert result.ok is True
    assert result.detail == "valid baseline proof"

    good["baseline"]["incident_family"] = "same incident family as the hosted hero run"
    (artifacts / "track3-baseline.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_track3_baseline_artifact()

    assert result.ok is False
    assert "incident_family" in result.detail

    good["baseline"]["incident_family"] = "suspicious deploy"
    good["yiting"]["matched_run_count"] = 0
    (artifacts / "track3-baseline.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_track3_baseline_artifact()

    assert result.ok is False
    assert "matched_run_count" in result.detail

    good["yiting"]["matched_run_count"] = 1
    good["comparison_method"]["terminal_criterion"] = "same stopping point"
    (artifacts / "track3-baseline.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_track3_baseline_artifact()

    assert result.ok is False
    assert "terminal_criterion" in result.detail

    good["comparison_method"]["terminal_criterion"] = (
        "Terminal incident state with recovery verification when an action executes."
    )
    good["yiting"]["disagreement_events"] = 0
    (artifacts / "track3-baseline.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_track3_baseline_artifact()

    assert result.ok is False
    assert "disagreement_events" in result.detail


def test_qwen_smoke_artifact_check_requires_passed_qwen_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    good = {
        "project": "YITING",
        "proof_type": "qwen-cloud-smoke",
        "artifact_class": "live_qwen_smoke",
        "submission_evidence": True,
        "verified_live": True,
        "schema_version": 1,
        "passed": True,
        "provider": "qwen",
        "base_url": "https://dashscope.example.test/v1",
        "model": "openai/qwen3.7-plus",
        "capability_matrix": {
            "openai/qwen3.7-plus": {
                "chat": "required",
                "structured_output": "required",
                "tools": "not_used",
            }
        },
        "checks": {
            "commander": {
                "ok": True,
                "role": "commander",
                "provider": "qwen",
                "requested_model": "openai/qwen3.7-plus",
                "returned_model": "qwen3.7-plus",
                "response_id": "chatcmpl-yiting-smoke",
                "provider_request_id": "dashscope-request-yiting",
                "latency_ms": 120,
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
                "capabilities": {
                    "chat": "required",
                    "structured_output": "required",
                    "tools": "not_used",
                },
            }
        },
        "response": {
            "ok": True,
            "provider": "qwen",
            "response_id": "chatcmpl-yiting-smoke",
            "provider_request_id": "dashscope-request-yiting",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
    }
    (artifacts / "qwen-smoke.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_qwen_smoke_artifact()

    assert result.ok is True
    assert result.detail == "valid Qwen smoke proof"

    good["passed"] = False
    (artifacts / "qwen-smoke.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_qwen_smoke_artifact()

    assert result.ok is False
    assert "passed must be true" in result.detail

    good["passed"] = True
    del good["checks"]["commander"]["usage"]["total_tokens"]
    (artifacts / "qwen-smoke.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_qwen_smoke_artifact()

    assert result.ok is False
    assert "usage.total_tokens" in result.detail

    good["checks"]["commander"]["usage"]["total_tokens"] = 0
    good["response"]["usage"]["total_tokens"] = 0
    (artifacts / "qwen-smoke.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_qwen_smoke_artifact()

    assert result.ok is False
    assert "usage.total_tokens must be a positive integer" in result.detail

    good["checks"]["commander"]["usage"]["total_tokens"] = 15
    good["response"]["usage"]["total_tokens"] = 15
    good["checks"]["commander"]["capabilities"]["structured_output"] = "not_assumed"
    (artifacts / "qwen-smoke.json").write_text(json.dumps(good), encoding="utf-8")

    result = submission_audit._check_qwen_smoke_artifact()

    assert result.ok is False
    assert "capabilities.structured_output must be required" in result.detail


def test_docker_image_smoke_artifact_check_requires_fail_closed_images(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = {
        "format": "yiting-docker-image-smoke-v1",
        "project": "YITING",
        "passed": True,
        "checks": {
            "gateway": {
                "ok": True,
                "health_status": 200,
                "ready_status": 200,
                "qwen_required": False,
            },
            "victim": {
                "ok": True,
                "status_code": 200,
                "source": "live_synthetic_telemetry",
            },
            "dashboard": {
                "ok": True,
                "status_code": 200,
                "base_path": "/dashboard",
            },
            "production_negative": {
                "ok": True,
                "status_code": 503,
                "qwen_required": True,
                "qwen_ready": False,
                "errors": [
                    "DASHSCOPE_API_KEY is required",
                    "QWEN_BASE_URL must be set explicitly",
                ],
            },
        },
    }
    (artifacts / "docker-image-smoke.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_docker_image_smoke_artifact()

    assert result.ok is True
    assert result.detail == "valid Docker image smoke proof"

    payload["checks"]["production_negative"]["status_code"] = 200
    (artifacts / "docker-image-smoke.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_docker_image_smoke_artifact()

    assert result.ok is False
    assert "checks.production_negative.status_code must be 503" in result.detail

    payload["checks"]["production_negative"]["status_code"] = 503
    payload["checks"]["production_negative"]["errors"] = []
    (artifacts / "docker-image-smoke.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_docker_image_smoke_artifact()

    assert result.ok is False
    assert "DASHSCOPE_API_KEY is required" in result.detail


def test_deployment_verification_check_requires_passed_speedup_public_run(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = {
        "project": "YITING",
        "proof_type": "alibaba-ecs-deployment-verification",
        "primary_track": "Track 3: Agent Society",
        "track3_proof_summary": TRACK3_PROOF_SUMMARY,
        "passed": True,
        "targets": {
            "public_url": "https://demo.example.com",
            "incident_id": "INC-HERO",
            "require_speedup": True,
            "require_public_read_only": True,
        },
        "checks": [{"name": "public evidence chain", "ok": True}],
    }
    (artifacts / "deployment-verification.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_deployment_verification_artifact()

    assert result.ok is True
    assert result.detail == "valid deployment verification"

    payload["targets"]["require_speedup"] = False
    (artifacts / "deployment-verification.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_deployment_verification_artifact()

    assert result.ok is False
    assert "require_speedup" in result.detail

    payload["targets"]["require_speedup"] = True
    payload["track3_proof_summary"] = {}
    (artifacts / "deployment-verification.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_deployment_verification_artifact()

    assert result.ok is False
    assert "track3_proof_summary" in result.detail

    payload["track3_proof_summary"] = TRACK3_PROOF_SUMMARY
    payload["targets"]["require_public_read_only"] = False
    (artifacts / "deployment-verification.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_deployment_verification_artifact()

    assert result.ok is False
    assert "require_public_read_only" in result.detail


def test_ecs_ops_acceptance_check_requires_immutable_images_and_vm_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    live_dir = tmp_path / "artifacts" / "live"
    live_dir.mkdir(parents=True)
    payload = {
        "format": "shared-ecs-ops-acceptance-v1",
        "passed": True,
        "checks": [
            {"name": "disk use below 80%: /opt/apps", "ok": True, "detail": "used=40.0%"},
            {
                "name": "container memory below 75% of limit after warm-up",
                "ok": True,
                "detail": "all containers below threshold",
            },
            *[
                {"name": check_name, "ok": True, "detail": "accepted"}
                for check_name in submission_audit.REQUIRED_ECS_OPS_CHECKS
            ],
        ],
    }
    (live_dir / "ecs-ops-acceptance.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_ecs_ops_acceptance_artifact()

    assert result.ok is True
    assert result.detail == "valid ECS operations acceptance proof"

    payload["checks"] = [
        check
        for check in payload["checks"]
        if check["name"] != "production images are pinned by immutable digest"
    ]
    (live_dir / "ecs-ops-acceptance.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_ecs_ops_acceptance_artifact()

    assert result.ok is False
    assert "missing passing check: production images are pinned by immutable digest" in result.detail


def test_submission_links_artifact_requires_reachable_public_links(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_submission_links_artifact()

    assert result.ok is False
    assert result.final_required is True
    assert "artifacts/live/submission-links.json missing" in result.detail

    live_dir = tmp_path / "artifacts" / "live"
    live_dir.mkdir(parents=True)
    payload = {
        "artifact_class": "public_submission_links",
        "submission_evidence": True,
        "verified_live": True,
        "repository_url": "https://github.com/example-owner/yiting",
        "live_application_url": "https://yiting.exampleapp.dev",
        "demo_video_url": "https://youtu.be/yitingDemo123",
        "deployment_proof_video_url": "https://vimeo.com/987654321",
        "reachability_checked_at": "2026-06-21T00:00:00+00:00",
        "public_reachability": {
            "repository_url": {
                "url": "https://github.com/example-owner/yiting",
                "final_url": "https://github.com/example-owner/yiting",
                "status_code": 200,
                "passed": True,
            },
            "live_application_url": {
                "url": "https://yiting.exampleapp.dev",
                "final_url": "https://yiting.exampleapp.dev",
                "status_code": 200,
                "passed": True,
            },
            "demo_video_url": {
                "url": "https://youtu.be/yitingDemo123",
                "final_url": "https://youtu.be/yitingDemo123",
                "status_code": 200,
                "passed": True,
            },
            "deployment_proof_video_url": {
                "url": "https://vimeo.com/987654321",
                "final_url": "https://vimeo.com/987654321",
                "status_code": 200,
                "passed": True,
            },
        },
    }
    (live_dir / "submission-links.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_submission_links_artifact()

    assert result.ok is True
    assert result.detail == "valid public submission link reachability proof"

    payload["public_reachability"]["demo_video_url"]["status_code"] = 403
    (live_dir / "submission-links.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_submission_links_artifact()

    assert result.ok is False
    assert "public_reachability.demo_video_url.status_code must be successful" in result.detail


def test_uptime_monitoring_artifact_requires_yiting_public_monitor(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_uptime_monitoring_artifact()

    assert result.ok is False
    assert result.final_required is True
    assert "artifacts/live/uptime-monitoring.json missing" in result.detail

    live_dir = tmp_path / "artifacts" / "live"
    live_dir.mkdir(parents=True)
    payload = {
        "format": "uptime-monitoring-v1",
        "artifact_class": "external_uptime_monitoring",
        "submission_evidence": True,
        "verified_live": True,
        "provider": "Better Stack",
        "monitors": [
            {
                "app": "yiting",
                "target_url": "https://yiting-qwen-demo.dev",
                "monitor_url": "https://status.qwen-demo.dev/yiting",
                "enabled": True,
                "interval_seconds": 60,
            },
        ],
    }
    (live_dir / "uptime-monitoring.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_uptime_monitoring_artifact()

    assert result.ok is True
    assert result.detail == "valid uptime monitoring proof"

    payload["monitors"].clear()
    (live_dir / "uptime-monitoring.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_uptime_monitoring_artifact()

    assert result.ok is False
    assert "missing yiting monitor" in result.detail


def test_app_restart_resilience_artifact_requires_persisted_apps(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_app_restart_resilience_artifact()

    assert result.ok is False
    assert result.final_required is True
    assert "artifacts/live/app-restart-resilience.json missing" in result.detail

    live_dir = tmp_path / "artifacts" / "live"
    live_dir.mkdir(parents=True)
    payload = {
        "format": "shared-ecs-app-restart-resilience-v1",
        "artifact_class": "live_app_restart_resilience",
        "submission_evidence": True,
        "verified_live": True,
        "restart_scope": "app-scoped Docker Compose service restart",
        "host_rebooted": False,
        "apps": [
            {
                "app": "yiting",
                "url": "https://yiting-qwen-demo.dev",
                "healthy_after_restart": True,
                "state_persisted": True,
                "evidence_persisted": True,
                "logs_persisted": True,
            },
            {
                "app": "cotenant",
                "url": "https://cotenant-qwen-demo.dev",
                "healthy_after_restart": True,
                "state_persisted": True,
                "evidence_persisted": True,
                "logs_persisted": True,
            },
        ],
    }
    (live_dir / "app-restart-resilience.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_app_restart_resilience_artifact()

    assert result.ok is True
    assert result.detail == "valid app restart resilience proof"

    payload["host_rebooted"] = True
    payload["apps"][0]["logs_persisted"] = False
    (live_dir / "app-restart-resilience.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_app_restart_resilience_artifact()

    assert result.ok is False
    assert "host_rebooted must be false" in result.detail
    assert "yiting: logs_persisted must be true" in result.detail


def test_backup_restore_artifact_requires_live_gateway_and_victim_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)

    result = submission_audit._check_backup_restore_artifact()

    assert result.ok is False
    assert result.final_required is True
    assert "artifacts/live/backup-restore.json missing" in result.detail

    live_dir = tmp_path / "artifacts" / "live"
    live_dir.mkdir(parents=True)
    payload = {
        "format": "yiting-backup-restore-v1",
        "project": "YITING",
        "artifact_class": "live_backup_restore",
        "submission_evidence": True,
        "verified_live": True,
        "generated_at": "2026-06-21T00:00:00+00:00",
        "backup_dir_name": "20260621T000000Z",
        "passed": True,
        "backups": [
            {
                "label": "gateway",
                "source_name": "yiting.db",
                "backup_name": "gateway.sqlite",
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "restore": {"ok": True, "integrity": "ok", "table_count": 3},
                "passed": True,
            },
            {
                "label": "victim",
                "source_name": "heal_idempotency.db",
                "backup_name": "victim.sqlite",
                "size_bytes": 1024,
                "sha256": "b" * 64,
                "restore": {"ok": True, "integrity": "ok", "table_count": 1},
                "passed": True,
            },
        ],
        "note": "Same-VM backups protect logical/container state, not total ECS host loss unless copied off-host.",
    }
    (live_dir / "backup-restore.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_backup_restore_artifact()

    assert result.ok is True
    assert result.detail == "valid backup restore proof"

    payload["verified_live"] = False
    payload["backups"][1]["restore"]["ok"] = False
    payload["backups"][0]["sha256"] = "bad"
    payload["note"] = "local copy"
    (live_dir / "backup-restore.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_backup_restore_artifact()

    assert result.ok is False
    assert "verified live submission evidence" in result.detail
    assert "victim.restore.ok must be true" in result.detail
    assert "gateway.sha256 must be a 64-character digest" in result.detail
    assert "same-VM backup limitation must be disclosed" in result.detail


def test_hero_evidence_check_requires_valid_chain_and_exact_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = {
        "incident_id": "INC-HERO",
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
                "operator",
            ],
            "handoff_count": 5,
            "challenge_count": 1,
            "human_decision_count": 1,
            "human_decisions": [
                {"sequence": 6, "decision": "APPROVED", "reason": "human approved"}
            ],
            "authorization_path": "StructuredApproval",
            "execution_conflict_control": {"exact_match": True},
        },
    }
    (artifacts / "hero-evidence.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_hero_evidence_artifact()

    assert result.ok is True
    assert result.detail == "valid hero evidence"

    payload["collaboration"]["execution_conflict_control"]["exact_match"] = False
    (artifacts / "hero-evidence.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_hero_evidence_artifact()

    assert result.ok is False
    assert "exact_match" in result.detail

    payload["collaboration"]["execution_conflict_control"]["exact_match"] = True
    payload["collaboration"]["challenge_count"] = 0
    payload["collaboration"]["human_decisions"] = [
        {"sequence": 6, "decision": "APPROVED", "reason": "approved only"}
    ]
    (artifacts / "hero-evidence.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_hero_evidence_artifact()

    assert result.ok is False
    assert "StructuredApproval(REJECTED)" in result.detail

    payload["collaboration"]["challenge_count"] = 1
    payload["collaboration"]["human_decisions"] = [
        {"sequence": 6, "decision": "APPROVED", "reason": "human approved"}
    ]
    payload["incident_family"] = ""
    (artifacts / "hero-evidence.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_hero_evidence_artifact()

    assert result.ok is False
    assert "incident_family" in result.detail

    payload["incident_id"] = ""
    payload["incident_family"] = "suspicious deploy"
    payload["state"] = "APPROVED"
    payload["cards"] = payload["cards"][:-1]
    payload["collaboration"]["challenge_count"] = 1
    (artifacts / "hero-evidence.json").write_text(json.dumps(payload), encoding="utf-8")

    result = submission_audit._check_hero_evidence_artifact()

    assert result.ok is False
    assert "incident_id" in result.detail
    assert "state must be EXECUTED" in result.detail
    assert "ActionReceipt" in result.detail


def test_final_proof_index_check_requires_judge_facing_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    good = """
# YITING Final Proof Index

Track 3: Agent Society
Hero incident
Qwen smoke
Paired quality benchmark
Hosted timing speedup
Backup restore proof
Required Track 3 Showcase
Task decomposition and handoffs
Execution conflict resolution
Measured quality and timing proof
Public read-only required
Public chaos disabled check
Evidence chain valid
Weighted Judge Score Map
Innovation & AI Creativity — 30%
Technical Depth & Engineering — 30%
Problem Value & Impact — 25%
Presentation & Documentation — 15%
Reviewer Cross-Checks
Track 3 is primary
Live Qwen smoke passed
MCP-style registry and review manifest
not a network MCP server
measured same-family baseline
does not claim speed
Public read-only judge mode required
Exact-envelope execution
Persistence safety
Submission Requirement Cross-Checks
Installability
Public open-source repository
Alibaba Cloud proof
Architecture diagram
Demo media compliance
Final submission runbook
artifacts/track3-paired-benchmark.json
artifacts/live/backup-restore.json
artifacts/hero-evidence.json
dist/yiting-submission-source.zip
docs/INSTALL_AND_RUN.md
docs/PUBLIC_REPOSITORY.md
docs/ARCHITECTURE.md
docs/ALIBABA_CLOUD_PROOF.md
docs/THIRD_PARTY_COMPLIANCE.md
docs/FINAL_SUBMISSION_CHECKLIST.md
"""
    (artifacts / "final-proof-index.md").write_text(good, encoding="utf-8")

    result = submission_audit._check_final_proof_index_artifact()

    assert result.ok is True
    assert result.detail == "valid final proof index"

    (artifacts / "final-proof-index.md").write_text("# incomplete\n", encoding="utf-8")

    result = submission_audit._check_final_proof_index_artifact()

    assert result.ok is False
    assert "YITING Final Proof Index" in result.detail


def test_source_package_check_requires_current_clean_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    monkeypatch.setattr(submission_audit, "_git_commit", lambda: "abc123")
    monkeypatch.setattr(submission_audit, "_git_worktree_clean", lambda: True)
    dist = tmp_path / "dist"
    dist.mkdir()
    package = dist / "yiting-submission-source.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "SUBMISSION_MANIFEST.json",
            json.dumps({
                "git_commit": "abc123",
                "working_tree_clean": True,
                "track3_proof_summary": TRACK3_PROOF_SUMMARY,
            }),
        )

    result = submission_audit._check_source_package_artifact()

    assert result.ok is True
    assert result.detail == "current clean source package"

    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "SUBMISSION_MANIFEST.json",
            json.dumps({
                "git_commit": "abc123",
                "working_tree_clean": False,
                "track3_proof_summary": TRACK3_PROOF_SUMMARY,
            }),
        )

    result = submission_audit._check_source_package_artifact()

    assert result.ok is False
    assert "dirty working tree" in result.detail

    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "SUBMISSION_MANIFEST.json",
            json.dumps({"git_commit": "abc123", "working_tree_clean": True}),
        )

    result = submission_audit._check_source_package_artifact()

    assert result.ok is False
    assert "missing track3_proof_summary" in result.detail


def test_credential_pattern_scan_rejects_secret_shaped_values(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    token = "LTAI" + "a" * 16
    (tmp_path / "debug.md").write_text(f"temporary key: {token}\n", encoding="utf-8")

    result = submission_audit._check_secret_patterns()

    assert result.ok is False
    assert "debug.md" in result.detail

    (tmp_path / "debug.md").write_text("DASHSCOPE_API_KEY=replace-with-live-key\n", encoding="utf-8")

    result = submission_audit._check_secret_patterns()

    assert result.ok is True
    assert result.detail == "no credential-shaped secrets in text files"


def test_local_absolute_path_scan_rejects_developer_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    local_path = "/" + "Users" + "/" + "sample-user" + "/" + "project" + "/" + ".env"
    (tmp_path / "debug.md").write_text(f"local backup: {local_path}\n", encoding="utf-8")

    result = submission_audit._check_local_absolute_paths()

    assert result.ok is False
    assert "debug.md" in result.detail

    (tmp_path / "debug.md").write_text(
        "/opt/apps/yiting/secrets/yiting.env\n",
        encoding="utf-8",
    )

    result = submission_audit._check_local_absolute_paths()

    assert result.ok is True
    assert result.detail == "no local absolute paths in text files"


def test_stale_generated_file_scan_rejects_platform_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    stale_file = deploy_dir / ".DS_Store"
    stale_file.write_bytes(b"local finder metadata")
    pycache = tmp_path / "app" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "api.cpython-313.pyc").write_bytes(b"bytecode")

    result = submission_audit._check_stale_generated_paths()

    assert result.ok is False
    assert "deploy/.DS_Store" in result.detail
    assert "__pycache__" not in result.detail
    assert ".pyc" not in result.detail

    stale_file.unlink()

    result = submission_audit._check_stale_generated_paths()

    assert result.ok is True
    assert result.detail == "no stale generated files in release tree"


def test_stale_public_text_scan_rejects_stale_submission_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(submission_audit, "ROOT", tmp_path)
    path = tmp_path / "docs" / "debug.md"
    path.parent.mkdir(parents=True)
    path.write_text("stale source folder: " + "lab" + "lab2\n", encoding="utf-8")

    result = submission_audit._check_stale_public_text()

    assert result.ok is False
    assert "docs/debug.md contains stale-hackathon" in result.detail

    path.write_text("YITING Track 3 Agent Society\n", encoding="utf-8")

    result = submission_audit._check_stale_public_text()

    assert result.ok is True
    assert result.detail == "no stale origin or provider text in release tree"

    path.write_text("The public README should not mention Zhan" + "Lue" + "Shi.\n", encoding="utf-8")

    result = submission_audit._check_stale_public_text()

    assert result.ok is False
    assert "docs/debug.md contains stale-origin-name" in result.detail

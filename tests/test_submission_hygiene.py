"""Submission hygiene checks for the Qwen/Alibaba edition."""
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".playwright-cli",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    ".next",
    "node_modules",
    "dist",
    "output",
}
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".service",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yml",
    ".yaml",
}


def _project_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.endswith((".db", ".db-shm", ".db-wal")):
            continue
        if path.name == "test_submission_hygiene.py":
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Caddyfile", "LICENSE", "Makefile", ".gitignore"}:
            continue
        yield path


def test_final_proof_artifacts_are_commit_visible_but_scratch_artifacts_are_ignored():
    final_artifacts = [
        "artifacts/qwen-smoke.json",
        "artifacts/track3-baseline.json",
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
    ]
    ignored = subprocess.run(
        ["git", "check-ignore", *final_artifacts],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert ignored.returncode == 1
    assert ignored.stdout == ""

    scratch = subprocess.run(
        ["git", "check-ignore", "artifacts/local-scratch.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert scratch.returncode == 0
    assert "artifacts/local-scratch.json" in scratch.stdout


def test_public_final_proof_docs_list_all_live_operations_artifacts():
    required_live_artifacts = [
        "artifacts/live/backup-restore.json",
        "artifacts/live/ecs-ops-acceptance.json",
        "artifacts/live/app-restart-resilience.json",
        "artifacts/live/uptime-monitoring.json",
        "artifacts/live/submission-links.json",
    ]
    public_docs = [
        ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "docs" / "SUBMISSION_FORM.md",
    ]

    missing: list[str] = []
    for path in public_docs:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for artifact in required_live_artifacts:
            if artifact not in text:
                missing.append(f"{path.relative_to(ROOT)} missing {artifact}")

    assert missing == []


def test_submission_sources_do_not_reference_removed_providers_or_old_demo_host():
    forbidden = [
        "b" + "and",
        "aim" + "l",
        "feather" + "less",
        "app." + "b" + "and",
        "129." + "80",
        "or" + "acle",
        "war" + "room",
        "lang" + "graph",
        "crew" + "ai",
        "pydantic" + "ai",
        "google " + "adk",
    ]
    term_allowlist: dict[str, set[str]] = {}
    offenders: list[str] = []
    for path in _project_text_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in forbidden:
            if term in term_allowlist.get(rel, set()):
                continue
            if term in text:
                offenders.append(f"{rel} contains {term!r}")
    assert offenders == []


def test_public_wording_does_not_claim_rebuild_or_from_scratch_story():
    forbidden = [
        "from " + "scratch",
        "re" + "build",
        "re" + "built",
        "re-" + "built",
        "previous " + "hackathon",
    ]
    public_files = [
        ROOT / "README.md",
        ROOT / "landing" / "index.html",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "JUDGE_PACKET.md",
        ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md",
        ROOT / "docs" / "COMPLETION_AUDIT.md",
        ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "docs" / "DEMO_SCRIPT.md",
        ROOT / "deploy" / "alibaba-ecs" / "README.md",
    ]
    offenders: list[str] = []
    for path in public_files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in forbidden:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {term!r}")
    assert offenders == []


def test_public_pages_do_not_link_to_placeholder_repository():
    placeholder_links = [
        "github.com/" + "yiting-ai/yiting",
        "github.com/" + "<",
        "github.com/" + "your",
    ]
    public_files = [
        ROOT / "README.md",
        ROOT / "landing" / "index.html",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "JUDGE_PACKET.md",
        ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md",
        ROOT / "docs" / "COMPLETION_AUDIT.md",
        ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "docs" / "DEMO_SCRIPT.md",
        ROOT / "deploy" / "alibaba-ecs" / "README.md",
    ]
    offenders: list[str] = []
    for path in public_files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for link in placeholder_links:
            if link in text:
                offenders.append(f"{path.relative_to(ROOT)} contains placeholder repo link {link!r}")
    assert offenders == []


def test_public_submission_docs_do_not_name_wrong_platform():
    checked_paths = [
        ROOT / "README.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "docs" / "SUBMISSION_FORM.md",
        ROOT / "docs" / "JUDGE_PACKET.md",
        ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md",
        ROOT / "scripts" / "submission_audit.py",
    ]
    offenders: list[str] = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if "devpost" in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_public_state_machine_terms_match_gateway_states():
    """Prevent stale demo-era state names from leaking into public proof."""
    checked_paths = [
        ROOT / "README.md",
        ROOT / "docs" / "ARCHITECTURE.md",
        ROOT / "docs" / "JUDGE_PACKET.md",
        ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md",
        ROOT / "docs" / "TRACK3_SCORECARD.md",
        ROOT / "dashboard" / "app" / "_components" / "YitingApp.js",
    ]
    offenders: list[str] = []
    for path in checked_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "SUPPRESSED_TRIAGE" in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_manual_demo_scripts_do_not_carry_stale_submission_wording():
    demo_scripts = [
        ROOT / "scripts" / "human_demo.py",
        ROOT / "scripts" / "closure_run.py",
        ROOT / "scripts" / "three_way_demo.py",
    ]
    forbidden = [
        "https://your-yiting-domain.example.com",
        "gate_b_trigger.py",
        "Council certification",
    ]
    offenders: list[str] = []
    for path in demo_scripts:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in forbidden:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {term!r}")
    assert offenders == []


def test_dashboard_uses_role_named_agent_assets():
    dashboard = ROOT / "dashboard" / "app" / "_components" / "YitingApp.js"
    text = dashboard.read_text(encoding="utf-8", errors="ignore")
    stale_assets = [
        "atlas.png",
        "elias.png",
        "forge.png",
        "ledger.png",
        "maya.png",
        "quill.png",
        "vera.png",
    ]
    offenders = [asset for asset in stale_assets if asset in text]
    assert offenders == []

    unused_default_assets = [
        ROOT / "dashboard" / "public" / "next.svg",
        ROOT / "dashboard" / "public" / "vercel.svg",
        ROOT / "dashboard" / "public" / "globe.svg",
        ROOT / "dashboard" / "public" / "window.svg",
        ROOT / "dashboard" / "public" / "file.svg",
    ]
    assert [str(path.relative_to(ROOT)) for path in unused_default_assets if path.exists()] == []


def test_dashboard_surfaces_same_family_baseline_proof():
    dashboard = ROOT / "dashboard" / "app" / "_components" / "YitingApp.js"
    text = dashboard.read_text(encoding="utf-8", errors="ignore")

    for phrase in [
        "Incident family",
        "incident_family",
        "alert_service",
        "same-family YITING runs",
        "Baseline proof uses same-family runs",
        "BASELINE_INCIDENT_FAMILY",
    ]:
        assert phrase in text


def test_public_readme_keeps_qwen_model_layer_wording_native():
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    public_model_phrases = [
        "OpenAI-compatible API",
        "LangChain client + Qwen",
        "Local room + LangChain client",
    ]
    offenders = [phrase for phrase in public_model_phrases if phrase in readme]
    assert offenders == []


def test_readme_surfaces_final_track3_proof_command():
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(readme.split())

    for phrase in [
        "Final Proof Before Submission",
        "make submission-proof",
        "HERO_INCIDENT_ID",
        "collaboration.role_sequence",
        "collaboration.execution_conflict_control.exact_match",
        "one disagreement event",
        "Safety Reviewer challenge or human rejection/revision",
        "one human intervention",
        "recovery verification",
        "speedup_factor > 1",
    ]:
        assert phrase in normalized


def test_readme_documentation_index_surfaces_final_judge_artifacts():
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(readme.split())

    for phrase in [
        "docs/SLIDE_DECK.md",
        "eight-slide presentation source",
        "docs/BASELINE_MEASUREMENT.md",
        "same-family baseline worksheet",
        "docs/PUBLIC_JUDGE_MODE.md",
        "read-only public judging mode",
        "docs/ADOPTION_ROADMAP.md",
        "productization, extension points, and open-source community potential",
    ]:
        assert phrase in normalized


def test_architecture_doc_names_engineering_invariants_and_failure_modes():
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(architecture.split())

    for phrase in [
        "Diagram reading guide",
        "Qwen Cloud connection",
        "Backend connection",
        "Database connection",
        "Frontend connection",
        "Human connection",
        "Alibaba Cloud Model Studio / Qwen",
        "Caddy routes public traffic to the Gateway API",
        "Gateway writes the SQLite evidence store",
        "dashboard is served through Caddy and reads Gateway APIs",
        "Engineering Invariants",
        "Cards are immutable after sealing",
        "Human approval is nonce-bound",
        "Execution is exact-envelope only",
        "Recovery is verified before certification",
        "Duplicate execution is suppressed durably",
        "Publication is verified",
        "Public judging can be read-only",
        "Failure behavior",
        "deterministic state, authorization, replay, publication, and recovery controls",
    ]:
        assert phrase in normalized


def test_engineering_proof_matrix_maps_mechanisms_to_code_and_tests():
    proof = (ROOT / "docs" / "ENGINEERING_PROOF.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(proof.split())

    for phrase in [
        "Engineering Proof Matrix",
        "Core Mechanisms",
        "Performance And Cost Controls",
        "Failure-Mode Posture",
        "Canonical evidence sealing",
        "Gateway-owned state machine",
        "Nonce-bound human authority",
        "Exact-envelope execution",
        "Durable duplicate suppression",
        "Replay and stale-message control",
        "Challenge and revision loops",
        "Bounded suppression learning",
        "Publication verification and outbox checks",
        "Clean submission packaging",
        "Code",
        "Verification",
        "tests/test_state_paths.py",
        "scripts/verify_deployment.py",
        "/evidence/{incident_id}",
        "/stats/runsummary",
    ]:
        assert phrase in normalized


def test_judging_and_blog_artifacts_cover_score_criteria():
    rubric = (ROOT / "docs" / "JUDGING_RUBRIC.md").read_text(encoding="utf-8", errors="ignore")
    blog = (ROOT / "docs" / "BLOG_POST.md").read_text(encoding="utf-8", errors="ignore")

    for phrase in [
        "Stage One",
        "Innovation & AI Creativity",
        "Technical Depth & Engineering",
        "Problem Value & Impact",
        "Presentation & Documentation",
        "Qwen Cloud",
        "Alibaba Cloud",
        "Track 3",
        "Agent Society",
        "/agent-skills",
        "Custom agent skills",
        "MCP-style",
        "not a network MCP server",
        "Qwen Cloud use",
        "Track 3 proof category",
        "judge demo cue",
        "track3_baseline.py",
        "--require-speedup",
        "docs/SUBMISSION_FORM.md",
        "docs/FINAL_SUBMISSION_CHECKLIST.md",
        "artifacts/qwen-smoke.json",
        "artifacts/final-proof-index.md",
    ]:
        assert phrase in rubric

    for phrase in [
        "Qwen-powered agent society",
        "Track 3",
        "custom agent skill",
        "MCP-style review manifest",
        "not a network MCP server",
        "input schemas",
        "output schemas",
        "Qwen Cloud use",
        "Track 3 proof",
        "judge demo cue",
        "/agent-skills",
        "/stats/runsummary",
        "Alibaba Cloud",
        "human decision",
        "evidence chain",
        "SHA-256",
        "single-agent baseline",
        "speedup_factor > 1",
        "make submission-proof",
        "artifacts/qwen-smoke.json",
        "scripts/track3_baseline.py",
        "Impact Beyond The Demo",
        "Potential Impact In Concrete Terms",
        "coordination tax",
        "Faster safe recovery",
        "Fewer unsafe automations",
        "Lower false-alarm cost",
        "Audit-ready operations",
        "paired quality gains",
        "optional measured baseline speed",
        "What Qwen Does And What It Does Not Do",
        "Qwen does not own authority",
        "deterministic Gateway code",
        "Why An Agent Society Beats A Single Agent",
        "Single-agent risk",
        "Agent-society control",
        "role separation reduces blast radius",
        "measured baseline keeps the efficiency claim honest",
        "Reader Verification Checklist",
        "open control plane for governed agent societies",
        "collaboration.execution_conflict_control.exact_match",
        "Verdict(CHALLENGE)",
        "StructuredApproval(REJECTED)",
        "Publish-Ready Social Snippets",
        "LinkedIn / Blog Teaser",
        "X / Short Post",
        "Judge-Facing One Sentence",
        "paired benchmark",
        "Hosted timing is measured separately",
    ]:
        assert phrase in blog


def test_submission_form_has_copy_paste_track3_fields():
    form = (ROOT / "docs" / "SUBMISSION_FORM.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(form.split())

    for phrase in [
        "Project Name",
        "Tagline",
        "Primary Track",
        "Track 3: Agent Society",
        "Select Track 3 in the form",
        "Do not choose Track 4 as the primary category",
        "Track Choice Note",
        "secondary Track 4 fit",
        "agent society itself",
        "exact approved-action boundary",
        "Short Description",
        "Long Description",
        "What Makes It Track 3",
        "What Is Novel",
        "governed agent society",
        "deterministic authority boundaries",
        "Qwen prompt boundary",
        "Qwen Cloud use",
        "Track 3 proof category",
        "judge demo cue",
        "Disagreement is operational",
        "Execution conflict resolution is deterministic",
        "The efficiency claim is split honestly",
        "scripts/verify_deployment.py --require-speedup",
        "uses Qwen for judgment, a Gateway for authority, and a hash chain for proof",
        "MCP-style",
        "review manifest",
        "Built With",
        "Public Links To Fill In",
        "Alibaba Cloud Deployment Proof Code Links",
        "Primary code proof",
        "shared/config.py",
        "scripts/qwen_smoke.py",
        "scripts/verify_deployment.py",
        "deploy/alibaba-ecs/README.md",
        "Final Proof Command",
        "HERO_INCIDENT_ID",
        "BASELINE_INCIDENT_FAMILY",
        "same-family tagged",
        "incident_family",
        "speedup_factor > 1",
        "single-agent baseline",
        "same-family hosted baseline",
        "Blog Post Prize",
    ]:
        assert phrase in normalized


def test_third_party_compliance_doc_covers_submission_rules():
    compliance = (ROOT / "docs" / "THIRD_PARTY_COMPLIANCE.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(compliance.split())

    for phrase in [
        "Third-Party Compliance Notes",
        "Qwen Cloud / Alibaba Cloud Model Studio",
        "entrant-provided `DASHSCOPE_API_KEY`",
        "no model key is committed",
        "Python dependencies are declared in `pyproject.toml`",
        "dashboard dependencies are declared in `dashboard/package.json`",
        "Incident data is synthetic or webhook-shaped sandbox telemetry",
        "Do not add copyrighted music",
        "unrelated third-party logos",
        "Public judge mode exposes read-only dashboard",
        "Paid or mutating actions are disabled or rejected",
    ]:
        assert phrase in normalized


def test_readme_leads_with_track3_positioning():
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(readme.split())

    for phrase in [
        "Primary Track",
        "Track 3: Agent Society",
        "choose Track 3: Agent Society",
        "secondary outcome, not the selected track",
        "Track 4 outcome",
        "strongest judging proof is the society itself",
        "specialized agents divide work",
        "Safety Reviewer can challenge Diagnosis",
        "humans can reject Commander",
        "Operator resolves execution conflicts",
        "/agent-skills",
        "/evidence/{incident_id}",
        "/stats/runsummary",
        "Hosted timing is measured separately",
        "Qwen Cloud use",
        "Track 3 proof category",
        "judge demo cue",
        "docs/THIRD_PARTY_COMPLIANCE.md",
    ]:
        assert phrase in normalized


def test_track3_doc_explains_why_track3_is_primary_over_track4():
    track3 = (ROOT / "docs" / "TRACK3_AGENT_SOCIETY.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(track3.split())

    for phrase in [
        "Track Choice",
        "valid Track 4 angle",
        "Track 3 is still the stronger primary submission",
        "coordinated society",
        "Why This Is More Than A Starter Idea",
        "Multi-agent debate",
        "Cooperative swarm",
        "Autonomous workflow",
        "Demo-only simulation",
    ]:
        assert phrase in normalized


def test_landing_page_surfaces_judge_packet_and_score_weights():
    landing = (ROOT / "landing" / "index.html").read_text(encoding="utf-8", errors="ignore")

    for phrase in [
        'id="judging"',
        'id="track3-proof"',
        "Track 3 Proof Matrix",
        "Distinct role contracts",
        "Sealed challenge loop",
        "Human revision loop",
            "Paired quality gains",
        "StructuredApproval(REJECTED)",
        "Judge Packet",
        "Innovation & AI Creativity",
        "Technical Depth",
        "Problem Value",
        "Presentation",
        "30%",
        "25%",
        "15%",
        "Track 3: Qwen Cloud Agent Society",
        "Track 3 proof points",
        "Role Contracts",
        "MCP-style custom skill contracts",
        "Qwen Cloud use",
        "Track 3 proof category",
        "judge demo cue",
        "Task division",
        "Disagreement resolution",
        "Exact execution conflict control",
        "Paired quality gains",
        "Verified Replay + Private Chaos",
        "Public judges inspect read-only replay",
        "separate same-family timing proof",
        "docs/JUDGING_RUBRIC.md",
        "docs/JUDGE_PACKET.md",
        "docs/TRACK3_AGENT_SOCIETY.md",
        "docs/TRACK3_SCORECARD.md",
        "docs/ENGINEERING_PROOF.md",
        "docs/ARCHITECTURE.md",
        "docs/BASELINE_MEASUREMENT.md",
        "docs/PUBLIC_JUDGE_MODE.md",
        "docs/ADOPTION_ROADMAP.md",
        "docs/SLIDE_DECK.md",
        "docs/ALIBABA_CLOUD_PROOF.md",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "docs/BLOG_POST.md",
        "docs/SUBMISSION_FORM.md",
        "docs/FINAL_SUBMISSION_CHECKLIST.md",
        "make submission-proof",
        "artifacts/qwen-smoke.json",
            "artifacts/track3-paired-benchmark.json",
        "artifacts/deployment-verification.json",
        "artifacts/hero-evidence.json",
        "artifacts/final-proof-index.md",
        "dist/yiting-submission-source.zip",
    ]:
        assert phrase in landing

    landing_css = (ROOT / "landing" / "style.css").read_text(encoding="utf-8", errors="ignore")
    assert "finalized-proof-links" in landing_css
    assert "track3-proof" in landing_css
    assert "track3-card" in landing_css


def test_judge_packet_has_five_minute_weighted_scoring_route():
    packet = (ROOT / "docs" / "JUDGE_PACKET.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(packet.split())

    for phrase in [
        "Five-Minute Scoring Route",
        "Stage One viability",
        "Innovation & AI Creativity — 30%",
        "Technical Depth & Engineering — 30%",
        "Problem Value & Impact — 25%",
        "Presentation & Documentation — 15%",
        "Blog Post Prize",
        "Track 3 quick score",
        "Track Choice In One Sentence",
        "evaluated as Track 3: Agent Society",
        "Track 4 outcome",
        "judged behavior is the collaboration itself",
        "Judge Objection Quick Answers",
        "Is this really Track 3, not Track 4?",
        "Is `/agent-skills` a real MCP server?",
        "not a network MCP server",
        "Is the demo mocked?",
        "real Qwen smoke proof",
        "Are third-party APIs, SDKs, and media authorized?",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "incident data is synthetic",
        "copyrighted music",
        "Is speedup invented?",
        "same-family measured baseline",
        "Can public visitors burn credits?",
        "Public judge mode is read-only",
        "Can agents execute unsafe or stale actions?",
        "exact-envelope execution",
        "docs/TRACK3_SCORECARD.md",
        "role-specific Qwen prompts",
        "exact-envelope execution conflict control",
        "paired quality gains",
        "measured same-family timing artifact",
        "matched same-family run IDs",
    ]:
        assert phrase in normalized


def test_track3_scorecard_matches_hackathon_requirements():
    scorecard = (ROOT / "docs" / "TRACK3_SCORECARD.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )

    for phrase in [
        "Track 3: Agent Society",
        "Agents with distinct capabilities",
        "Task division and role assignment",
        "Dialogue and negotiation",
        "Execution conflict resolution",
        "Measurable efficiency gain",
        "/agent-skills",
        "/evidence/{incident_id}.collaboration.role_sequence",
        "Verdict(CHALLENGE)",
        "StructuredApproval(REJECTED)",
        "collaboration.execution_conflict_control.exact_match",
        "speedup_factor > 1",
        "artifacts/track3-baseline.json",
        "artifacts/track3-paired-benchmark.json",
        "artifacts/qwen-smoke.json",
        "Why Track 3 Beats Track 4",
    ]:
        assert phrase in scorecard


def test_demo_script_captures_track3_judge_proof_shots():
    demo = (ROOT / "docs" / "DEMO_SCRIPT.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(demo.split())

    for phrase in [
        "Recording Modes",
        "Live Mode",
        "Verified Replay Mode",
        "Do not show a mocked transcript",
        "dashboard-only animation",
        "Live paired benchmark",
        "under 3 minutes",
        "three-minute mark",
        "2:55 as the hard edit target",
        "Final Under-Three-Minute Edit Recipe",
        "one hero incident for depth and one low-risk contrast for breadth",
        "Record only the project UI, proof artifacts, and your own narration",
        "Do not add copyrighted music, unrelated third-party logos, stock footage, or external media",
        "Do not try to show every scenario in full",
        "Distinct Qwen-backed roles",
        "MCP-style registry",
        "Disagreement, negotiation, and revision",
        "Approval And Exact Execution",
        "Human governance and stale-action prevention",
        "Exact-envelope execution and recovery verification",
        "Graduated autonomy",
        "public read-only judge-mode proof",
        "Must-Capture Judge Shots",
        "Scoreboard Overlay",
        "Innovation & AI Creativity — 30%",
        "Technical Depth & Engineering — 30%",
        "Problem Value & Impact — 25%",
        "Presentation & Documentation — 15%",
        "/agent-skills",
        "MCP-style registry",
        "input schema",
        "output schema",
        "Qwen Cloud use",
        "Track 3 proof category",
        "judge demo cue",
        "collaboration.role_sequence",
        "Verdict(CHALLENGE)",
        "StructuredApproval(REJECTED)",
        "ActionReceipt",
        "approved envelope",
        "/stats/runsummary",
        "speedup_factor > 1",
        "--require-speedup",
        "single-agent baseline",
        "MANUAL_BASELINE_SECS",
        "hosted Gateway",
        "MEASURED_SINGLE_AGENT_SECS",
        "make submission-proof",
        "Track 3 disagreement and negotiation",
        "Track 3 measurable efficiency gain",
        "Video contains no copyrighted music",
        "unrelated third-party trademarks",
        "HERO_INCIDENT_ID",
    ]:
        assert phrase in normalized


def test_submission_guide_names_three_minute_video_and_final_order():
    submission = (ROOT / "docs" / "SUBMISSION.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(submission.split())

    for phrase in [
        "Three-Minute Demo Video",
        "public video must be under three minutes",
        "judges are not required to watch beyond the three-minute mark",
        "record the live frontend flow first",
        "switch the hosted dashboard to public read-only judge mode",
        "run hosted proof",
        "only then submit",
    ]:
        assert phrase in normalized


def test_submission_video_platforms_match_hackathon_rules():
    checked_paths = [
        ROOT / "docs" / "COMPLETION_AUDIT.md",
        ROOT / "docs" / "DEMO_SCRIPT.md",
        ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md",
        ROOT / "docs" / "SUBMISSION.md",
        ROOT / "scripts" / "finalize_submission.py",
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in checked_paths
    )

    assert "YouTube" in combined
    assert "Vimeo" in combined
    assert "Facebook Video" in combined
    assert "Youku" not in combined


def test_slide_deck_source_maps_track3_story_to_judge_proof():
    deck = (ROOT / "docs" / "SLIDE_DECK.md").read_text(encoding="utf-8", errors="ignore")
    normalized = " ".join(deck.split())

    for phrase in [
        "YITING Slide Deck Source",
        "Slide 1: Title",
        "Slide 8: Why It Wins Track 3",
        "Track 3",
        "Qwen Agent Society",
        "agent society",
        "Qwen Cloud smoke + Alibaba ECS verifier + Track 3 scorecard",
        "Stage One proof to mention",
        "`artifacts/qwen-smoke.json` proves live Qwen Cloud API access",
        "`artifacts/deployment-verification.json` proves the hosted Alibaba ECS",
        "`docs/TRACK3_SCORECARD.md` maps the demo to the Track 3 requirements",
        "Recorder seals evidence",
        "Safety Reviewer can challenge weak conclusions",
        "Human Gate approves, rejects, or marks false alarm",
        "`Verdict(CHALLENGE)` forces Diagnosis to revise",
        "`StructuredApproval(REJECTED)` forces Commander to revise",
        "Operator executes only the approved envelope",
        "`chain_valid: true`",
        "High-risk incidents produce `StructuredApproval`",
        "Low-risk safe remediation produces `PolicyAuthorization`",
        "`scripts/track3_baseline.py` records a same-family single-agent/manual baseline",
        "`scripts/verify_deployment.py --require-speedup` fails if `speedup_factor`",
        "Do not claim `speedup_factor > 1` until the same-family baseline artifact",
        "Innovation: Qwen-backed roles plus inspectable MCP-style skill contracts",
        "Technical depth: evidence chain, nonce binding, exact-envelope execution",
        "Impact: safer emergency change control",
        "Presentation: public replay, evidence export, demo video, and final proof index",
    ]:
        assert phrase in normalized


def test_baseline_measurement_worksheet_guards_speedup_claim():
    worksheet = (ROOT / "docs" / "BASELINE_MEASUREMENT.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(worksheet.split())

    for phrase in [
        "Track 3 Baseline Measurement Worksheet",
        "speedup_factor = baseline.measured_seconds / yiting.avg_total_resolution_seconds",
        "same-family single-agent or one-person baseline",
        "Use the same family as the hero incident",
        "Do not use placeholders",
        "Keep The Terminal Criterion Fair",
        "final state `EXECUTED`, `ActionReceipt` present, and recovery verified",
        "Stop the timer only when the baseline reaches the same terminal criterion",
        "Do not include YITING's agent chain",
        "Baseline measured seconds",
        "Recovery verification evidence",
        "scripts/track3_baseline.py",
        "The script refuses placeholder families",
        "track3_requirements_checked.disagreement_or_revision",
        "speedup_factor > 1",
    ]:
        assert phrase in normalized


def test_public_judge_mode_doc_explains_cost_control_proof():
    doc = (ROOT / "docs" / "PUBLIC_JUDGE_MODE.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(doc.split())

    for phrase in [
        "Public Judge Mode And Cost Control",
        "frictionless for judges",
        "`/dashboard/` read-only dashboard and verified replay",
        "`/agent-skills` inspectable MCP-style custom skill registry",
        "`/evidence/{incident_id}` public evidence export",
        "live chaos triggers",
        "any route that can start paid model calls",
        "YITING_LIVE_CHAOS",
            "returns HTTP `403` before contacting the Gateway",
            "The approval UI remains protected separately",
            "export NEXT_PUBLIC_YITING_MODE=judge",
            "If rebuilding from a private registry, set exact immutable digest refs before compose.",
            "docker compose -p yiting -f deploy/shared-host/compose.prod.yml up -d dashboard",
            "scripts/verify_deployment.py --require-public-read-only",
            "/dashboard/api/chaos/activate",
        "HTTP `403` check on the chaos endpoint",
    ]:
        assert phrase in normalized


def test_adoption_roadmap_explains_productization_path():
    roadmap = (ROOT / "docs" / "ADOPTION_ROADMAP.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(roadmap.split())

    for phrase in [
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
    ]:
        assert phrase in normalized


def test_final_checklist_names_strict_hero_evidence_requirements():
    checklist = (ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(checklist.split())

    for phrase in [
        "Final-Hour Order",
        "private recording mode",
        "YITING_LIVE_CHAOS=1",
        "NEXT_PUBLIC_YITING_MODE=live",
        "Record the browser dashboard flow",
        "Use only project UI/proof artifacts and your own narration",
        "copyrighted music",
        "unrelated third-party logos",
        "stock footage",
        "Switch the hosted dashboard to public read-only judge mode",
        "Commit finalized public artifacts",
        "push the final commit",
        "collaboration.role_sequence",
        "collaboration.execution_conflict_control.exact_match: true",
        "at least one disagreement event",
        "Safety Reviewer challenge or human rejection/revision",
        "one human intervention",
        "nonzero disagreement events",
        "nonzero human interventions",
        "recovery verification",
        "Do not invent the baseline",
        "one-person or single-agent rehearsal",
        "same incident family as the hero run",
        "docs/BASELINE_MEASUREMENT.md",
        "the terminal criterion, incident family, measured seconds, and saved notes",
        "MEASURED_SINGLE_AGENT_SECS",
        "apples-to-apples",
        "Expected generated or confirmed files",
        "make submission-ready",
        "make submission-package",
        "authorization path",
        "exact execution match",
        "Patch README, the landing page, the judge packet, the submission form, and the install guide",
        "git diff -- README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md",
        "git add README.md landing/index.html docs/JUDGE_PACKET.md docs/SUBMISSION_FORM.md docs/INSTALL_AND_RUN.md",
        "Demo video includes copyrighted music",
        "unrelated third-party trademarks",
    ]:
        assert phrase in normalized


def test_completion_audit_names_form_packet_and_final_checklist():
    audit = (ROOT / "docs" / "COMPLETION_AUDIT.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(audit.split())

    for phrase in [
        "Submission form packet",
        "docs/SUBMISSION_FORM.md",
        "copy-paste title, tagline, descriptions",
        "Final submission checklist",
        "docs/FINAL_SUBMISSION_CHECKLIST.md",
        "day-of-submission runbook",
        "Third-party authorization and media hygiene",
        "docs/THIRD_PARTY_COMPLIANCE.md",
        "--require-speedup",
        "--require-public-read-only",
        "public read-only chaos/mutation rejection proof",
        "Locally satisfied",
    ]:
        assert phrase in normalized


def test_install_and_run_guide_covers_source_package_verification():
    guide = (ROOT / "docs" / "INSTALL_AND_RUN.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(guide.split())

    for phrase in [
        "Install And Run Guide",
        "public repository or the sanitized source package",
        "Python 3.12 or 3.13",
        "Node.js 20 LTS or newer",
        "uv sync --locked",
        "npm ci",
        "npm run build",
        "Local Verification",
        "make test",
        "make dashboard-build",
        "make local-certify",
        "make submission-package",
        "python scripts/submission_audit.py",
        "python scripts/submission_status.py",
        "local certification script run in test mode and do not require a paid model key",
        "make dev",
        "DASHSCOPE_API_KEY only for live Qwen calls",
        "make submission-proof",
        "Public Judge Mode",
        "state-changing chaos actions",
    ]:
        assert phrase in normalized


def test_public_repository_guide_covers_github_publication_requirements():
    guide = (ROOT / "docs" / "PUBLIC_REPOSITORY.md").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    normalized = " ".join(guide.split())

    for phrase in [
        "Public Repository Publication Guide",
        "public, open-source code repository",
        "Visibility: public",
        "License: detected as MIT from the root `LICENSE` file",
        "YITING — Track 3 Agent Society for governed incident response with Qwen",
        "Use the description above verbatim",
        "contains `Track 3 Agent Society` and `Qwen`",
        "alibaba-cloud",
        "agent-society",
        "human-in-the-loop",
        "judge to open the README",
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
    ]:
        assert phrase in normalized


def test_makefile_submission_ready_runs_all_local_readiness_gates():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8", errors="ignore")
    assert "submission-ready" in makefile.splitlines()[0]

    target = makefile.split("submission-ready:", 1)[1].split("\n\n", 1)[0]
    expected_order = [
        "$(MAKE) test",
        "$(MAKE) track3-benchmark",
        "$(MAKE) dashboard-build",
        "$(MAKE) local-certify",
        "$(MAKE) submission-package",
        "$(MAKE) submission-audit",
        "$(MAKE) submission-status",
    ]

    positions = [target.index(command) for command in expected_order]
    assert positions == sorted(positions)

    assert "submission-proof:" in makefile
    assert "HERO_INCIDENT_ID" in makefile
    assert "BASELINE_INCIDENT_FAMILY" in makefile
    assert "scripts/track3_baseline.py" in makefile
    assert "scripts/track3_paired_benchmark.py" in makefile
    assert "--require-speedup" in makefile
    assert "--require-public-read-only" in makefile


def test_final_proof_bundle_is_consistent_across_public_artifacts():
    bundle_terms = [
        "make submission-proof",
        "artifacts/qwen-smoke.json",
        "artifacts/track3-baseline.json",
        "artifacts/track3-paired-benchmark.json",
        "artifacts/deployment-verification.json",
        "BASELINE_INCIDENT_FAMILY",
    ]
    source_package_term = "dist/yiting-submission-source.zip"
    files = {
        "Makefile": ROOT / "Makefile",
        "readme": ROOT / "README.md",
        "landing": ROOT / "landing" / "index.html",
        "judge_packet": ROOT / "docs" / "JUDGE_PACKET.md",
        "completion_audit": ROOT / "docs" / "COMPLETION_AUDIT.md",
        "submission": ROOT / "docs" / "SUBMISSION.md",
        "submission_form": ROOT / "docs" / "SUBMISSION_FORM.md",
        "submission_status": ROOT / "scripts" / "submission_status.py",
        "finalize_submission": ROOT / "scripts" / "finalize_submission.py",
        "package_submission": ROOT / "scripts" / "package_submission.py",
    }

    missing: list[str] = []
    for label, path in files.items():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in bundle_terms:
            if term not in text:
                missing.append(f"{label} missing {term!r}")

    for label in ["landing", "judge_packet", "submission_form", "package_submission"]:
        text = files[label].read_text(encoding="utf-8", errors="ignore")
        if source_package_term not in text:
            missing.append(f"{label} missing {source_package_term!r}")

    for label in [
        "Makefile",
        "judge_packet",
        "completion_audit",
        "submission",
        "submission_status",
        "finalize_submission",
        "package_submission",
    ]:
        text = files[label].read_text(encoding="utf-8", errors="ignore")
        if "HERO_INCIDENT_ID" not in text:
            missing.append(f"{label} missing 'HERO_INCIDENT_ID'")

    assert missing == []


def test_final_proof_index_artifacts_are_documented_for_judges():
    required_files = {
        "landing": ROOT / "landing" / "index.html",
        "judge_packet": ROOT / "docs" / "JUDGE_PACKET.md",
        "submission_form": ROOT / "docs" / "SUBMISSION_FORM.md",
        "final_checklist": ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md",
        "completion_audit": ROOT / "docs" / "COMPLETION_AUDIT.md",
        "submission_status": ROOT / "scripts" / "submission_status.py",
        "finalize_submission": ROOT / "scripts" / "finalize_submission.py",
        "package_submission": ROOT / "scripts" / "package_submission.py",
    }
    missing: list[str] = []
    for label, path in required_files.items():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "artifacts/final-proof-index.md" not in text:
            missing.append(f"{label} missing final proof index")

    for label in ["judge_packet", "submission_form", "final_checklist", "submission_status", "finalize_submission"]:
        text = required_files[label].read_text(encoding="utf-8", errors="ignore")
        if "artifacts/hero-evidence.json" not in text:
            missing.append(f"{label} missing hero evidence artifact")

    assert missing == []


def test_public_judge_mode_requires_server_side_chaos_block():
    required_files = {
        "Makefile": (
            ROOT / "Makefile",
            ["--require-public-read-only"],
        ),
        "deployment guide": (
            ROOT / "deploy" / "alibaba-ecs" / "README.md",
            [
                "--require-public-read-only",
                "YITING_LIVE_CHAOS",
                "--incident-id \"$HERO_INCIDENT_ID\"",
                "--incident-family \"$BASELINE_INCIDENT_FAMILY\"",
                "Set `BASELINE_INCIDENT_FAMILY` to the same family as the",
                "hero incident",
            ],
        ),
        "ECS bootstrap": (
            ROOT / "deploy" / "alibaba-ecs" / "bootstrap.sh",
            ["--incident-id", "HERO_INCIDENT_ID", "make submission-proof", "BASELINE_INCIDENT_FAMILY"],
        ),
        "final checklist": (
            ROOT / "docs" / "FINAL_SUBMISSION_CHECKLIST.md",
            ["--require-public-read-only", "YITING_LIVE_CHAOS"],
        ),
        "demo script": (
            ROOT / "docs" / "DEMO_SCRIPT.md",
            ["--require-public-read-only", "YITING_LIVE_CHAOS"],
        ),
        "deployment verifier": (
            ROOT / "scripts" / "verify_deployment.py",
            ["--require-public-read-only"],
        ),
        "Alibaba proof": (
            ROOT / "docs" / "ALIBABA_CLOUD_PROOF.md",
            ["require_public_read_only"],
        ),
    }
    missing: list[str] = []
    for label, (path, terms) in required_files.items():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in terms:
            if term not in text:
                missing.append(f"{label} missing {term!r}")

    assert missing == []

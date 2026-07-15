from argparse import Namespace
import json
import urllib.error
from unittest.mock import patch

from scripts import verify_deployment


class _FakeTextResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"YITING dashboard"


def test_agent_predicate_enforces_minimum_online_count():
    predicate = verify_deployment._agent_predicate(2)
    ok, detail = predicate([
        {"agent_role": "triage", "online": True},
        {"agent_role": "diagnosis", "online": False},
        {"agent_role": "commander", "online": True},
    ])
    assert ok is True
    assert "2/3 online" in detail


def test_evidence_predicate_requires_valid_chain_and_cards():
    ok, detail = verify_deployment._evidence_predicate(
        {
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
                    "human_gateway",
                    "operator",
                ],
                "handoff_count": 6,
                "challenge_count": 1,
                "human_decision_count": 1,
                "human_decisions": [
                    {"sequence": 6, "decision": "APPROVED", "reason": "approved"}
                ],
                "authorization_path": "StructuredApproval",
                "execution_conflict_control": {
                    "planned_actions": ["rollback_deploy"],
                    "executed_actions": ["rollback_deploy"],
                    "exact_match": True,
                },
            },
        }
    )
    assert ok is True
    assert "cards=7" in detail
    assert "incident_family='suspicious deploy'" in detail
    assert "handoffs=6" in detail

    ok, detail = verify_deployment._evidence_predicate({"chain_valid": False, "cards": []})
    assert ok is False
    assert "chain_valid=False" in detail

    ok, detail = verify_deployment._evidence_predicate({"chain_valid": True, "cards": [{}]})
    assert ok is False
    assert "state must be EXECUTED" in detail

    ok, detail = verify_deployment._evidence_predicate({
        "incident_id": "INC-HERO",
        "state": "EXECUTED",
        "incident_family": "suspicious deploy",
        "chain_valid": True,
        "cards": [{}] * 7,
        "collaboration": {
            "role_sequence": ["recorder", "triage", "diagnosis", "safety_reviewer", "commander", "operator"],
            "handoff_count": 5,
            "challenge_count": 1,
            "human_decision_count": 0,
            "human_decisions": [],
            "authorization_path": "PolicyAuthorization",
            "execution_conflict_control": {"exact_match": False},
        },
    })
    assert ok is False
    assert "ActionReceipt" in detail

    ok, detail = verify_deployment._evidence_predicate({
        "incident_id": "INC-OTHER",
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
            "role_sequence": ["recorder", "triage", "diagnosis", "safety_reviewer", "commander", "operator"],
            "handoff_count": 5,
            "challenge_count": 1,
            "human_decision_count": 0,
            "human_decisions": [],
            "authorization_path": "PolicyAuthorization",
            "execution_conflict_control": {"exact_match": True},
        },
    }, expected_incident_id="INC-HERO")
    assert ok is False
    assert "incident_id mismatch" in detail

    ok, detail = verify_deployment._evidence_predicate({
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
            {"card_type": "PolicyAuthorization"},
            {"card_type": "ActionReceipt"},
        ],
        "collaboration": {
            "role_sequence": ["recorder", "triage", "diagnosis", "safety_reviewer", "commander", "operator"],
            "handoff_count": 5,
            "challenge_count": 1,
            "human_decision_count": 0,
            "human_decisions": [],
            "authorization_path": "PolicyAuthorization",
            "execution_conflict_control": {"exact_match": False},
        },
    })
    assert ok is False
    assert "exact_match must be true" in detail

    ok, detail = verify_deployment._evidence_predicate({
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
            "role_sequence": ["recorder", "triage", "diagnosis", "safety_reviewer", "commander", "human_gateway", "operator"],
            "handoff_count": 6,
            "challenge_count": 0,
            "human_decision_count": 1,
            "human_decisions": [
                {"sequence": 6, "decision": "APPROVED", "reason": "approved only"}
            ],
            "authorization_path": "StructuredApproval",
            "execution_conflict_control": {"exact_match": True},
        },
    })
    assert ok is False
    assert "Track 3 disagreement proof" in detail

    ok, detail = verify_deployment._evidence_predicate({
        "incident_id": "INC-HERO",
        "state": "EXECUTED",
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
            "role_sequence": ["recorder", "triage", "diagnosis", "safety_reviewer", "commander", "human_gateway", "operator"],
            "handoff_count": 6,
            "challenge_count": 1,
            "human_decision_count": 1,
            "human_decisions": [
                {"sequence": 6, "decision": "APPROVED", "reason": "approved"}
            ],
            "authorization_path": "StructuredApproval",
            "execution_conflict_control": {"exact_match": True},
        },
    })
    assert ok is False
    assert "incident_family" in detail


def test_runsummary_predicate_requires_track3_metrics():
    ok, detail = verify_deployment._runsummary_predicate({
        "summary": {
            "avg_agent_processing_secs": 42,
            "avg_total_resolution_secs": 80,
            "total_challenges_issued": 1,
            "total_human_rejections": 0,
            "disagreement_events": 1,
            "total_handoffs": 6,
            "recovery_verified_count": 1,
            "human_interventions": 1,
            "speedup_factor": None,
        },
        "runs": [],
    })
    assert ok is True
    assert "runsummary shape ok" in detail

    ok, detail = verify_deployment._runsummary_predicate({"summary": {}, "runs": []})
    assert ok is False
    assert "missing keys" in detail


def test_runsummary_predicate_can_require_measured_speedup():
    payload = {
        "summary": {
            "avg_agent_processing_secs": 42,
            "avg_total_resolution_secs": 80,
            "total_challenges_issued": 1,
            "total_human_rejections": 0,
            "disagreement_events": 1,
            "total_handoffs": 6,
            "recovery_verified_count": 1,
            "human_interventions": 1,
            "manual_baseline_secs": 240,
            "speedup_factor": 3.0,
        },
        "runs": [{"incident_id": "INC-1"}],
    }

    ok, detail = verify_deployment._runsummary_predicate(
        payload,
        require_speedup=True,
    )
    assert ok is True
    assert "runsummary shape ok" in detail

    payload["summary"]["speedup_factor"] = None
    ok, detail = verify_deployment._runsummary_predicate(
        payload,
        require_speedup=True,
    )
    assert ok is False
    assert "speedup_factor must be > 1" in detail


def test_runsummary_predicate_requires_nonzero_track3_metrics_with_speedup():
    base_payload = {
        "summary": {
            "avg_agent_processing_secs": 42,
            "avg_total_resolution_secs": 80,
            "total_challenges_issued": 1,
            "total_human_rejections": 0,
            "disagreement_events": 1,
            "total_handoffs": 6,
            "recovery_verified_count": 1,
            "human_interventions": 1,
            "manual_baseline_secs": 240,
            "speedup_factor": 3.0,
        },
        "runs": [{"incident_id": "INC-1"}],
    }

    for key in [
        "total_handoffs",
        "recovery_verified_count",
        "human_interventions",
    ]:
        payload = json.loads(json.dumps(base_payload))
        payload["summary"][key] = 0

        ok, detail = verify_deployment._runsummary_predicate(
            payload,
            require_speedup=True,
        )

        assert ok is False
        assert f"{key} must be > 0 for Track 3 proof" in detail

    payload = json.loads(json.dumps(base_payload))
    payload["summary"]["total_challenges_issued"] = 0
    payload["summary"]["total_human_rejections"] = 0
    payload["summary"]["disagreement_events"] = 0

    ok, detail = verify_deployment._runsummary_predicate(
        payload,
        require_speedup=True,
    )

    assert ok is False
    assert "disagreement_events must be > 0" in detail

    payload = json.loads(json.dumps(base_payload))
    payload["summary"]["total_challenges_issued"] = 0
    payload["summary"]["total_human_rejections"] = 1
    payload["summary"]["disagreement_events"] = 1

    ok, detail = verify_deployment._runsummary_predicate(
        payload,
        require_speedup=True,
    )

    assert ok is True


def test_runsummary_success_detail_names_track3_metrics():
    payload = {
        "summary": {
            "avg_agent_processing_secs": 42,
            "avg_total_resolution_secs": 80,
            "total_challenges_issued": 2,
            "total_human_rejections": 1,
            "disagreement_events": 3,
            "total_handoffs": 12,
            "recovery_verified_count": 3,
            "human_interventions": 4,
            "manual_baseline_secs": 240,
            "speedup_factor": 3.0,
        },
        "runs": [{"incident_id": "INC-1"}],
    }

    ok, detail = verify_deployment._runsummary_predicate(
        payload,
        require_speedup=True,
    )

    assert ok is True
    for phrase in [
        "speedup=3.0",
        "handoffs=12",
        "challenges=2",
        "human_rejections=1",
        "disagreement_events=3",
        "human_interventions=4",
        "recovery_verified=3",
    ]:
        assert phrase in detail


def test_run_checks_adds_public_and_evidence_urls():
    json_calls = []
    http_calls = []

    def fake_check(name, url, predicate=None):
        json_calls.append((name, url, predicate))
        return verify_deployment.Check(name, True, "ok")

    def fake_http(name, url, **kwargs):
        http_calls.append((name, url, kwargs))
        return verify_deployment.Check(name, True, "ok")

    args = Namespace(
        gateway_url="http://127.0.0.1:8000/",
        victim_url="http://127.0.0.1:9000/",
        public_url="https://demo.example.com/",
        incident_id="INC-123",
        min_roles=5,
        require_speedup=False,
        require_public_read_only=False,
    )
    with patch.object(verify_deployment, "_check_json", side_effect=fake_check), \
            patch.object(verify_deployment, "_check_http", side_effect=fake_http):
        checks = verify_deployment.run_checks(args)

    urls = [url for _, url, _ in json_calls]
    http_urls = [url for _, url, _ in http_calls]
    assert "http://127.0.0.1:8000/health" in urls
    assert "http://127.0.0.1:8000/ready" in urls
    assert "http://127.0.0.1:8000/stats/runsummary" in urls
    assert "https://demo.example.com/ready" in urls
    assert "https://demo.example.com/stats/runsummary" in urls
    assert "https://demo.example.com/agent-status" in urls
    assert "http://127.0.0.1:8000/evidence/INC-123" in urls
    assert "https://demo.example.com/evidence/INC-123" in urls
    assert "https://demo.example.com/" in http_urls
    assert "https://demo.example.com/dashboard/" in http_urls
    dashboard_call = next(item for item in http_calls if item[1].endswith("/dashboard/"))
    assert dashboard_call[2]["acceptable_statuses"] == {200}
    assert "basic_auth" not in dashboard_call[2]
    assert dashboard_call[2]["contains"] == "YITING"
    assert len(checks) == len(json_calls) + len(http_calls)


def test_run_checks_requires_public_dashboard_without_credentials():
    http_calls = []

    def fake_check(name, url, predicate=None):
        return verify_deployment.Check(name, True, "ok")

    def fake_http(name, url, **kwargs):
        http_calls.append((name, url, kwargs))
        return verify_deployment.Check(name, True, "ok")

    args = Namespace(
        gateway_url="http://127.0.0.1:8000/",
        victim_url="http://127.0.0.1:9000/",
        public_url="https://demo.example.com/",
        incident_id="",
        min_roles=5,
        require_speedup=False,
        require_public_read_only=False,
    )
    with patch.object(verify_deployment, "_check_json", side_effect=fake_check), \
            patch.object(verify_deployment, "_check_http", side_effect=fake_http):
        verify_deployment.run_checks(args)

    dashboard_call = next(item for item in http_calls if item[1].endswith("/dashboard/"))
    assert dashboard_call[2]["acceptable_statuses"] == {200}
    assert "basic_auth" not in dashboard_call[2]
    assert dashboard_call[2]["contains"] == "YITING"


def test_build_report_is_sanitized_and_records_check_results():
    args = Namespace(
        gateway_url="http://127.0.0.1:8000/",
        victim_url="http://127.0.0.1:9000/",
        public_url="https://demo.example.com/",
        incident_id="INC-123",
        min_roles=5,
        require_speedup=True,
        require_public_read_only=True,
    )
    checks = [
        verify_deployment.Check("landing", True, "HTTP 200"),
        verify_deployment.Check("agents", False, "4/5 online"),
    ]

    report = verify_deployment.build_report(args, checks)
    encoded = json.dumps(report)

    assert report["project"] == "YITING"
    assert report["proof_type"] == "alibaba-ecs-deployment-verification"
    assert report["schema_version"] == 1
    assert report["primary_track"] == "Track 3: Agent Society"
    assert report["track3_proof_summary"]["primary_track"] == "Track 3: Agent Society"
    assert set(report["track3_proof_summary"]["required_showcase"]) >= {
        "distinct_capabilities",
        "task_decomposition",
        "dialogue_and_negotiation",
        "disagreement_resolution",
        "execution_conflict_resolution",
        "measurable_efficiency_gain",
    }
    assert report["submission_artifacts"] == {
        "judge_packet": "docs/JUDGE_PACKET.md",
        "submission_form": "docs/SUBMISSION_FORM.md",
        "final_checklist": "docs/FINAL_SUBMISSION_CHECKLIST.md",
        "blog_post_prize": "docs/BLOG_POST.md",
        "source_package": "dist/yiting-submission-source.zip",
        "qwen_smoke_proof": "artifacts/qwen-smoke.json",
        "baseline_proof": "artifacts/track3-baseline.json",
        "hero_evidence": "artifacts/hero-evidence.json",
        "final_proof_index": "artifacts/final-proof-index.md",
    }
    assert report["final_proof_command"].startswith("make submission-proof")
    assert "HERO_INCIDENT_ID=..." in report["final_proof_command"]
    assert "BASELINE_INCIDENT_FAMILY=..." in report["final_proof_command"]
    assert [item["criterion"] for item in report["rubric_proof"]] == [
        "Stage One viability",
        "Innovation & AI Creativity",
        "Technical Depth & Engineering",
        "Problem Value & Impact",
        "Presentation & Documentation",
    ]
    assert "nonzero handoffs, disagreement events, human interventions, and recovery verification" in encoded
    assert report["passed"] is False
    assert set(report["targets"].keys()) == {
        "gateway_url",
        "incident_id",
        "min_roles",
        "public_url",
        "require_public_read_only",
        "require_speedup",
        "victim_url",
    }
    assert report["targets"]["public_url"] == "https://demo.example.com"
    assert report["targets"]["require_speedup"] is True
    assert report["targets"]["require_public_read_only"] is True
    assert report["checks"][1]["ok"] is False
    for forbidden in [
        "dashboard_user",
        "dashboard_password",
        "api_key",
        "secret",
        "bearer",
    ]:
        assert forbidden not in encoded.lower()


def test_run_checks_can_require_public_read_only_mode():
    json_calls = []
    http_calls = []
    read_only_calls = []

    def fake_check(name, url, predicate=None):
        json_calls.append((name, url, predicate))
        return verify_deployment.Check(name, True, "ok")

    def fake_http(name, url, **kwargs):
        http_calls.append((name, url, kwargs))
        return verify_deployment.Check(name, True, "ok")

    def fake_read_only(public_url):
        read_only_calls.append(public_url)
        return verify_deployment.Check("public chaos disabled", True, "HTTP 403 disabled")

    args = Namespace(
        gateway_url="http://127.0.0.1:8000/",
        victim_url="http://127.0.0.1:9000/",
        public_url="https://demo.example.com/",
        incident_id="",
        min_roles=5,
        require_speedup=True,
        require_public_read_only=True,
    )
    with patch.object(verify_deployment, "_check_json", side_effect=fake_check), \
            patch.object(verify_deployment, "_check_http", side_effect=fake_http), \
            patch.object(verify_deployment, "_check_public_chaos_disabled", side_effect=fake_read_only):
        checks = verify_deployment.run_checks(args)

    assert read_only_calls == ["https://demo.example.com"]
    assert checks[-1].name == "public chaos disabled"


def test_public_chaos_disabled_check_expects_app_level_403():
    with patch.object(verify_deployment, "_post_json", return_value=(403, {"error": "Live chaos actions are disabled for this deployment."})):
        check = verify_deployment._check_public_chaos_disabled("https://demo.example.com")

    assert check.ok is True
    assert check.detail == "HTTP 403 disabled"

    with patch.object(verify_deployment, "_post_json", return_value=(200, {"incident_id": "INC-PAID"})):
        check = verify_deployment._check_public_chaos_disabled("https://demo.example.com")

    assert check.ok is False
    assert "expected HTTP 403" in check.detail

    with patch.object(verify_deployment, "_post_json", return_value=(401, "Unauthorized")):
        check = verify_deployment._check_public_chaos_disabled("https://demo.example.com")

    assert check.ok is False
    assert "dashboard is still auth-gated" in check.detail


def test_urlopen_text_follows_http_308_redirect():
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        del timeout
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                308,
                "Permanent Redirect",
                {"Location": "/dashboard"},
                None,
            )
        return _FakeTextResponse()

    with patch.object(verify_deployment.urllib.request, "urlopen", side_effect=fake_urlopen):
        status, body = verify_deployment._urlopen_text("https://demo.example.com/dashboard/")

    assert status == 200
    assert body == "YITING dashboard"
    assert calls == ["https://demo.example.com/dashboard/", "https://demo.example.com/dashboard"]


def test_write_report_creates_json_file(tmp_path):
    output = tmp_path / "proof" / "deployment.json"
    verify_deployment.write_report(output, {"project": "YITING", "passed": True})

    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True

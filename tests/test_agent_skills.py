"""Tests for the public custom agent skill registry."""
from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app import create_app
from shared.skill_registry import list_agent_skills, skill_manifest, skill_roles

ROOT = Path(__file__).resolve().parents[1]


def test_skill_registry_covers_every_public_agent_role():
    skills = list_agent_skills()
    roles = skill_roles()

    assert len(skills) == 7
    assert roles == [
        "triage",
        "diagnosis",
        "safety_reviewer",
        "commander",
        "operator",
        "recorder",
        "scribe",
    ]
    assert len({skill["skill_id"] for skill in skills}) == len(skills)


def test_skill_registry_has_scoreable_contract_fields():
    for skill in list_agent_skills():
        assert skill["agent_name"]
        assert skill["skill_name"]
        assert skill["qwen_model"]
        assert skill["tool_name"].startswith(f"yiting.{skill['role']}.")
        assert skill["input_contract"]
        assert skill["output_contract"]
        assert skill["input_schema"]["type"] == "object"
        assert "payload" in skill["input_schema"]["properties"]
        assert skill["output_schema"]["properties"]["card_type"]["const"] == skill["evidence_artifact"]
        assert skill["prompt_contract"]
        assert skill["deterministic_guardrail"]
        assert skill["evidence_artifact"]
        assert skill["qwen_cloud_use"]
        assert skill["track3_requirement"]
        assert skill["judge_demo_cue"]


def test_skill_manifest_is_mcp_style_and_track3_scored():
    manifest = skill_manifest()

    assert manifest["manifest_version"] == "yiting.agent-skill-manifest.v1"
    assert manifest["style"] == "MCP-style tool contract manifest"
    assert "not a network MCP server" in manifest["mcp_disclaimer"]
    assert "Qwen prompt boundaries" in manifest["mcp_disclaimer"]
    assert manifest["primary_track"] == "Track 3: Agent Society"
    assert manifest["evidence_endpoints"]["skill_registry"] == "/agent-skills"
    assert manifest["track3_claims"]["disagreement_resolution"].startswith("Verdict(CHALLENGE)")
    assert manifest["skills"][0]["tool_name"] == "yiting.triage.signal_routing"
    assert manifest["skills"][0]["qwen_cloud_use"].startswith("Qwen Flash")
    assert manifest["skills"][2]["track3_requirement"] == "Disagreement resolution"


def test_agent_skills_endpoint_returns_registry():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.get("/agent-skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest_version"] == "yiting.agent-skill-manifest.v1"
    assert payload["style"] == "MCP-style tool contract manifest"
    assert "not a network MCP server" in payload["mcp_disclaimer"]
    assert payload["total_skills"] == 7
    assert payload["roles"] == skill_roles()
    assert payload["skills"][0]["skill_id"] == "signal-routing"
    assert payload["skills"][0]["tool_name"] == "yiting.triage.signal_routing"
    assert payload["skills"][0]["input_contract"] == "AlertCard plus source fingerprint and severity hints."
    assert payload["skills"][0]["output_contract"] == "One TriageDecision: route, suppress, or escalate."
    assert payload["skills"][0]["track3_requirement"] == "Task division and role assignment"
    assert "evidence timeline" in payload["skills"][0]["judge_demo_cue"]
    assert payload["skills"][-1]["evidence_artifact"] == "Postmortem"


def test_dashboard_fetches_and_renders_skill_registry():
    dashboard = ROOT / "dashboard" / "app" / "_components" / "YitingApp.js"
    text = dashboard.read_text(encoding="utf-8")

    assert 'api("/agent-skills")' in text
    assert "Custom agent skills" in text
    assert "MCP-style tool" in text
    assert "deterministic MCP-style contracts" in text
    assert "Review manifest, not a network MCP server" in text
    assert "skill-manifest-note" in text
    assert "Input contract" in text
    assert "Output contract" in text
    assert "Qwen Cloud use" in text
    assert "Track 3 proof" in text
    assert "skill-demo-cue" in text
    assert "deterministic_guardrail" in text


def test_decision_payload_schemas_are_field_level_typed_contracts():
    """Judges querying /agent-skills or MCP tools/list must see the real
    Pydantic field schema of each sealed card, not a bare object with prose."""
    for skill in list_agent_skills():
        payload_schema = skill["output_schema"]["properties"]["decision_payload"]
        assert payload_schema.get("properties"), (
            f"{skill['skill_id']} decision_payload must expose field-level schema"
        )
        # The prose contract is retained alongside the typed fields.
        assert payload_schema.get("description") == skill["output_contract"]


def test_decision_payload_schema_matches_card_model_fields():
    skills = {skill["skill_id"]: skill for skill in list_agent_skills()}
    assessment_props = skills["evidence-fusion"]["output_schema"]["properties"][
        "decision_payload"
    ]["properties"]
    for field in ("severity", "root_cause_hypothesis", "evidence_strength", "recommended_action"):
        assert field in assessment_props
    verdict_props = skills["independent-challenge"]["output_schema"]["properties"][
        "decision_payload"
    ]["properties"]
    for field in ("decision", "reasoning", "agrees_with_diagnosis", "challenge_request"):
        assert field in verdict_props

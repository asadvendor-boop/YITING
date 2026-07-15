"""Custom agent skill registry for the YITING submission.

This is intentionally deterministic metadata: it lets the Gateway, dashboard,
tests, and documentation point to the same first-class list of project-specific
agent skills without requiring paid model calls.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import (
    ActionReceipt,
    AlertCard,
    Assessment,
    Postmortem,
    ResponsePlan,
    TriageDecision,
    Verdict,
)
from .personas import PERSONAS

# Evidence artifact -> the actual Pydantic card model that seals it. The skill
# manifest embeds each model's real JSON schema so /agent-skills and MCP
# tools/list expose field-level typed contracts, not just prose descriptions.
CARD_PAYLOAD_MODELS = {
    "AlertCard": AlertCard,
    "TriageDecision": TriageDecision,
    "Assessment": Assessment,
    "Verdict": Verdict,
    "ResponsePlan": ResponsePlan,
    "ActionReceipt": ActionReceipt,
    "Postmortem": Postmortem,
}


def _payload_schema(evidence_artifact: str, description: str) -> dict[str, Any]:
    """Field-level JSON schema for a card payload, prose contract retained."""
    model = CARD_PAYLOAD_MODELS.get(evidence_artifact)
    if model is None:
        return {"type": "object", "description": description}
    schema = model.model_json_schema()
    schema["description"] = description
    return schema


@dataclass(frozen=True)
class AgentSkill:
    role: str
    agent_name: str
    persona_title: str
    skill_id: str
    skill_name: str
    category: str
    qwen_model: str
    input_contract: str
    output_contract: str
    tool_name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    prompt_contract: str
    deterministic_guardrail: str
    evidence_artifact: str
    qwen_cloud_use: str
    track3_requirement: str
    judge_demo_cue: str


def _skill(
    role: str,
    skill_id: str,
    skill_name: str,
    category: str,
    qwen_model: str,
    input_contract: str,
    output_contract: str,
    prompt_contract: str,
    deterministic_guardrail: str,
    evidence_artifact: str,
    qwen_cloud_use: str,
    track3_requirement: str,
    judge_demo_cue: str,
) -> AgentSkill:
    persona = PERSONAS[role]
    tool_name = f"yiting.{role}.{skill_id.replace('-', '_')}"
    return AgentSkill(
        role=role,
        agent_name=persona.full_name,
        persona_title=persona.title,
        skill_id=skill_id,
        skill_name=skill_name,
        category=category,
        qwen_model=qwen_model,
        input_contract=input_contract,
        output_contract=output_contract,
        tool_name=tool_name,
        input_schema={
            "type": "object",
            "title": f"{skill_name} input",
            "required": ["incident_id", "previous_card_hash", "payload"],
            "properties": {
                "incident_id": {"type": "string"},
                "previous_card_hash": {"type": "string"},
                "payload": {"type": "object", "description": input_contract},
            },
        },
        output_schema={
            "type": "object",
            "title": f"{skill_name} output",
            "required": ["card_type", "card_hash", "decision_payload"],
            "properties": {
                "card_type": {"type": "string", "const": evidence_artifact},
                "card_hash": {"type": "string"},
                "decision_payload": _payload_schema(evidence_artifact, output_contract),
            },
        },
        prompt_contract=prompt_contract,
        deterministic_guardrail=deterministic_guardrail,
        evidence_artifact=evidence_artifact,
        qwen_cloud_use=qwen_cloud_use,
        track3_requirement=track3_requirement,
        judge_demo_cue=judge_demo_cue,
    )


AGENT_SKILLS: tuple[AgentSkill, ...] = (
    _skill(
        "triage",
        "signal-routing",
        "Signal routing and suppression check",
        "intake",
        "Qwen Flash",
        "AlertCard plus source fingerprint and severity hints.",
        "One TriageDecision: route, suppress, or escalate.",
        "Classify signal validity, noise risk, and the next responsible role.",
        "P1 and security-relevant signals bypass suppression and always route.",
        "TriageDecision",
        "Qwen Flash provides alert-classification reasoning behind a deterministic routing schema.",
        "Task division and role assignment",
        "Show the first handoff from Recorder to Triage in the evidence timeline.",
    ),
    _skill(
        "diagnosis",
        "evidence-fusion",
        "Evidence fusion and root-cause assessment",
        "analysis",
        "Qwen Plus",
        "TriageDecision plus four evidence-source snapshots.",
        "One Assessment with severity, hypothesis, evidence strength, and action hint.",
        "Fuse four evidence sources into severity, hypothesis, and proposed action.",
        "Challenge redelivery forces a fresh revision and clears cached tool context.",
        "Assessment",
        "Qwen Plus fuses four evidence snapshots into a bounded Assessment payload.",
        "Specialized evidence analysis",
        "Open an Assessment card and point to the cited error, deploy, metrics, and health evidence.",
    ),
    _skill(
        "safety_reviewer",
        "independent-challenge",
        "Independent challenge review",
        "governance",
        "Qwen Plus",
        "Assessment with evidence summary and revision context.",
        "One Verdict: CONFIRM, CHALLENGE, FALSE_ALARM, or NEEDS_HUMAN.",
        "Confirm, challenge, escalate, or close the assessment with explicit reasoning.",
        "A challenge is sealed as a Verdict and returns the incident to Diagnosis.",
        "Verdict",
        "Qwen Plus performs independent review and explains confirm/challenge decisions.",
        "Disagreement resolution",
        "Show a Verdict(CHALLENGE) followed by Assessment(revision=2).",
    ),
    _skill(
        "commander",
        "runbook-planning",
        "Runbook planning and approval routing",
        "planning",
        "Qwen Plus",
        "Confirmed Verdict, Assessment, runbook policy, and rejection history.",
        "One ResponsePlan with nonce-bound exact action envelopes.",
        "Select a safe runbook and produce exact action envelopes for the incident.",
        "Severity policy and human rejection history bound the allowed runbooks.",
        "ResponsePlan",
        "Qwen Plus proposes the runbook and exact envelope, then policy code narrows unsafe choices.",
        "Negotiated planning",
        "Show a human rejection forcing Commander to issue a revised ResponsePlan.",
    ),
    _skill(
        "operator",
        "exact-envelope-execution",
        "Exact-envelope execution and recovery verification",
        "execution",
        "Qwen Flash",
        "Consumed authorization plus sealed ResponsePlan envelopes.",
        "One ActionReceipt with execution result and recovery verification.",
        "Execute only the approved envelope and verify recovery before receipt.",
        "Any target, parameter, count, or action mismatch is rejected before side effects.",
        "ActionReceipt",
        "Qwen Flash narrates execution intent, but the exact-envelope checker owns side effects.",
        "Execution conflict resolution",
        "Show that ActionReceipt matches the approved envelope and recovery is verified.",
    ),
    _skill(
        "recorder",
        "evidence-sealing",
        "Evidence sealing and state transition",
        "control-plane",
        "Deterministic Gateway",
        "Prepared cards, idempotency keys, nonces, and publication receipts.",
        "Canonical card rows, state transitions, evidence exports, and room messages.",
        "Normalize cards, enforce state transitions, and publish the incident-room trail.",
        "SHA-256 card hashes, nonce binding, and publication verification are owned by the Gateway.",
        "AlertCard",
        "Deterministic control-plane skill; no model call is needed to seal authority.",
        "Shared memory and audit substrate",
        "Show /evidence/{incident_id} recomputing the card chain.",
    ),
    _skill(
        "scribe",
        "postmortem-enrichment",
        "Postmortem enrichment",
        "summary",
        "Qwen Cloud",
        "Terminal evidence chain and ActionReceipt summary.",
        "Optional postmortem narrative that cannot authorize or execute.",
        "Turn the final evidence chain into a concise post-incident narrative.",
        "The scribe never authorizes or executes remediation; it is summary-only.",
        "Postmortem",
        "Optional Qwen Cloud narrative layer over terminal evidence.",
        "Post-resolution collaboration",
        "Mention as optional enrichment after ActionReceipt, not as an authority boundary.",
    ),
)


def list_agent_skills() -> list[dict[str, Any]]:
    return [asdict(skill) for skill in AGENT_SKILLS]


def skill_roles() -> list[str]:
    return [skill.role for skill in AGENT_SKILLS]


def skill_manifest() -> dict[str, Any]:
    """Return the public, MCP-style skill manifest for judges and dashboard.

    This manifest route is not a network MCP server. It is an inspectable
    tool-contract manifest that uses the same core idea: named tools,
    input/output schemas, deterministic guardrails, and evidence artifacts.
    The same contracts are served by the real read-only MCP server at /mcp
    (gateway/mcp.py).
    """
    skills = list_agent_skills()
    return {
        "project": "YITING",
        "manifest_version": "yiting.agent-skill-manifest.v1",
        "style": "MCP-style tool contract manifest",
        "mcp_disclaimer": (
            "Inspectable MCP-style tool contracts; this manifest route is itself "
            "not a network MCP server. The same contracts ARE served by the real "
            "read-only MCP server at /mcp (JSON-RPC 2.0: initialize, tools/list, "
            "tools/call), which exposes stable tool names, schemas, Qwen prompt "
            "boundaries, guardrails, and evidence artifacts for judge review."
        ),
        "primary_track": "Track 3: Agent Society",
        "total_skills": len(skills),
        "roles": skill_roles(),
        "evidence_endpoints": {
            "skill_registry": "/agent-skills",
            "mcp_server": "/mcp",
            "evidence_chain": "/evidence/{incident_id}",
            "run_summary": "/stats/runsummary",
        },
        "track3_claims": {
            "distinct_capabilities": "Each role exposes one named tool contract and one evidence artifact.",
            "task_decomposition": "Role-owned cards form the incident handoff sequence.",
            "disagreement_resolution": "Verdict(CHALLENGE) and StructuredApproval(REJECTED) force revisions.",
            "execution_conflict_resolution": "Operator output must exactly match the authorized envelope.",
            "measurable_efficiency": "Run summary plus baseline artifact report speedup_factor.",
        },
        "skills": skills,
    }

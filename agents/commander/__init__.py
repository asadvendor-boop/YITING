"""YITING Commander Agent — local incident-room runtime + Qwen.

Selects runbook, creates ResponsePlan with typed structured output,
manages human approval flow with nonce-based challenge-response.

Architecture:
  - CommanderPreprocessor: validates Verdict(CONFIRM) from Safety Reviewer,
    extracts linked Assessment, stores trusted per-incident context
  - Deterministic runbook selection based on root_cause and severity
  - Deterministic risk_level: P1/P2 or destructive actions → high risk
  - submit_response_plan handler: typed async function used by local runtime
  - HIGH risk: nonce-based challenge → recruits human + Operator
  - LOW risk: PolicyAuthorization → recruits Operator only

Tool contract (local runtime):
  - typed async handler with Pydantic validation
  - Qwen supplies advisory reasoning, deterministic policy selects runbook/risk

Honest claims:
  - "Deterministic risk_level": from severity + action type, not LLM
  - "Deterministic runbook selection": keyword match on root_cause, not LLM
  - "has_seal_fields": structural pre-filter, not cryptographic proof
  - "Qwen-backed": Qwen improves plan reasoning when credentials are set
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from shared.approval import (
    compute_action_hash,
    compute_plan_hash,
    requires_human_approval,
)
from shared.card_intake import (
    derive_idempotency_key,
    extract_sealed_card,
    has_seal_fields,
)
from shared.config import (
    ACTIVE_INCIDENTS,
    MODELS,
    get_agent_api_key,
)
from shared.models import (
    ExecutionEnvelope,
    ResponsePlan,
    Verdict,
)
from shared.context_restore import (
    fetch_confirmed_cards,
    rejection_already_revised,
    should_skip_terminal_incident,
    verdict_already_planned,
)
from shared.replay_guard import should_skip_stale_card, should_skip_stale_chatter
from shared.incident_room import IncidentRoomClient
from shared.submission_client import SubmissionClient, SubmissionError, format_card_message
from shared.local_room_runtime import LocalDefaultPreprocessor, LocalRoomAgent
from shared.qwen_reasoning import ask_qwen_json, bounded_text
from shared.supervisor import run_with_supervisor

AgentToolsProtocol = Any
logger = logging.getLogger("yiting.commander")

# Gateway URL for SubmissionClient and nonce API
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

# Nonce expiry duration
NONCE_EXPIRY_MINUTES = int(os.getenv("NONCE_EXPIRY_MINUTES", "10"))

# PolicyAuthorization expiry duration
POLICY_AUTH_EXPIRY_MINUTES = int(os.getenv("POLICY_AUTH_EXPIRY_MINUTES", "30"))


# ---------------------------------------------------------------------------
# Runbook definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunbookDef:
    """Definition of a standard runbook with default envelopes."""
    id: str
    name: str
    description: str
    default_envelopes: list[dict]
    destructive: bool = False
    min_risk_level: str = "low"  # Minimum risk level for this runbook


RUNBOOKS: dict[str, RunbookDef] = {
    "RB-001": RunbookDef(
        id="RB-001",
        name="Service restart",
        description="Restart the affected service with health checks",
        min_risk_level="medium",  # Restarts can cause brief downtime
        default_envelopes=[
            {
                "action_id": "restart_service",
                "target": "{service}",
                "parameters": {"grace_period_seconds": 30, "health_check": True},
                "timeout_seconds": 120,
                "rollback_action": None,
            },
        ],
    ),
    "RB-002": RunbookDef(
        id="RB-002",
        name="Scale up replicas",
        description="Horizontally scale the service to handle increased load",
        default_envelopes=[
            {
                "action_id": "scale_up",
                "target": "{service}",
                "parameters": {"direction": "up", "increment": 2, "max_replicas": 10},
                "timeout_seconds": 180,
                "rollback_action": "scale_down",
            },
        ],
    ),
    "RB-003": RunbookDef(
        id="RB-003",
        name="Rollback deployment",
        description="Rollback to the previous known-good deployment",
        destructive=True,
        min_risk_level="high",  # Destructive: rollback requires human approval
        default_envelopes=[
            {
                "action_id": "rollback_deploy",
                "target": "{service}",
                "parameters": {"to_revision": "previous", "strategy": "rolling"},
                "timeout_seconds": 300,
                "rollback_action": None,
            },
        ],
    ),
    "RB-004": RunbookDef(
        id="RB-004",
        name="Enable circuit breaker",
        description="Enable circuit breaker to isolate failing dependency",
        default_envelopes=[
            {
                "action_id": "enable_circuit_breaker",
                "target": "{service}",
                "parameters": {"threshold": 5, "timeout_seconds": 60, "half_open_requests": 3},
                "timeout_seconds": 60,
                "rollback_action": "disable_circuit_breaker",
            },
        ],
    ),
    "RB-005": RunbookDef(
        id="RB-005",
        name="DNS failover",
        description="Failover DNS to standby region",
        destructive=True,
        min_risk_level="high",  # Destructive: DNS failover requires human approval
        default_envelopes=[
            {
                "action_id": "dns_failover",
                "target": "{service}",
                "parameters": {"failover_region": "standby", "ttl_seconds": 60},
                "timeout_seconds": 300,
                "rollback_action": "dns_failback",
            },
        ],
    ),
    "RB-006": RunbookDef(
        id="RB-006",
        name="Emergency maintenance page",
        description="Serve static maintenance page while incident is being resolved",
        default_envelopes=[
            {
                "action_id": "enable_maintenance_page",
                "target": "{service}",
                "parameters": {"message": "We are currently performing maintenance. Please try again shortly."},
                "timeout_seconds": 30,
                "rollback_action": "disable_maintenance_page",
            },
        ],
    ),
}

# Destructive action IDs that force high risk
DESTRUCTIVE_ACTIONS = frozenset({
    "rollback_deploy",
    "dns_failover",
    "dns_failback",
    "scale_down",
    "terminate_instance",
    "modify_security_group",
    "delete_resource",
    "modify_database",
    "revoke_credentials",
})


# ---------------------------------------------------------------------------
# Runbook selection — deterministic keyword matching, NOT LLM
# ---------------------------------------------------------------------------

def select_runbook(root_cause: str, severity: str, recommended_action: str) -> str:
    """Select the best runbook based on root cause, severity, and recommended action.

    Deterministic: keyword-based matching on root_cause and recommended_action.
    Severity guard: P3/P4 incidents NEVER select destructive runbooks (RB-003, RB-005).
    Falls back to severity-based defaults if no keyword matches.
    """
    combined = (root_cause + " " + recommended_action).lower()
    is_low_severity = severity in ("P3", "P4")

    # Check for specific patterns. Rollback needs rollback INTENT or an
    # explicitly bad deploy — a mere mention of "deployment" is not a
    # remediation signal.
    if any(kw in combined for kw in ("rollback", "revert", "bad deploy",
                                     "faulty deploy", "suspicious deploy")):
        if is_low_severity:
            # P3/P4: deploy-related but low severity → circuit breaker, not rollback
            return "RB-004"
        return "RB-003"
    if any(kw in combined for kw in ("dns", "failover", "region", "standby")):
        if is_low_severity:
            # P3/P4: DNS issues but low severity → maintenance page, not failover
            return "RB-006"
        return "RB-005"
    # A leaking process must be restarted, not scaled: scaling multiplies
    # leaking replicas. Leak evidence plus restart intent outranks an
    # incidental scale mention.
    if (any(kw in combined for kw in ("memory leak", "heap", "oom"))
            and any(kw in combined for kw in ("restart", "recycle"))):
        return "RB-001"
    # Capacity remediation outranks circuit breaking when both are described:
    # scaling addresses saturation root causes; a breaker only mitigates.
    if any(kw in combined for kw in ("scale", "replica", "capacity", "load",
                                     "traffic", "saturation")):
        return "RB-002"
    # Circuit breaker requires explicit breaker intent or a described failing
    # dependency — bare "dependency"/"upstream" narration is not enough.
    if any(kw in combined for kw in ("circuit breaker", "circuit-breaker",
                                     "cascading failure", "failing dependency",
                                     "dependency timeout", "upstream outage",
                                     "upstream failure")):
        return "RB-004"
    if any(kw in combined for kw in ("maintenance", "maintenance page", "outage page")):
        return "RB-006"
    if any(kw in combined for kw in ("restart", "crash", "oom", "memory leak", "hung")):
        return "RB-001"

    # Severity-based fallback
    if severity in ("P1", "P2"):
        return "RB-003"  # High severity → rollback is safest default
    return "RB-001"  # Default to service restart


# ---------------------------------------------------------------------------
# Risk level determination — deterministic, NOT LLM
# ---------------------------------------------------------------------------

def determine_risk_level(
    severity: str,
    envelopes: list[ExecutionEnvelope],
) -> str:
    """Determine risk level from severity and action types.

    Deterministic rules:
    - P1 or P2 severity → high
    - Any destructive action → high
    - Everything else → low
    """
    # Severity-based
    if severity in ("P1", "P2"):
        return "high"

    # Action-based: check for destructive actions
    for env in envelopes:
        if env.action_id in DESTRUCTIVE_ACTIONS:
            return "high"

    return "low"


# ---------------------------------------------------------------------------
# Trusted per-incident context (populated by preprocessor, consumed by tools)
# ---------------------------------------------------------------------------

@dataclass
class CommanderContext:
    """Trusted context for an incident, populated by the preprocessor.

    Tool callbacks read from this — never from LLM-supplied values
    for sensitive fields (room_id, room_message_id, etc.).
    """
    incident_id: str
    room_id: str
    room_message_id: str
    source_card_hash: str
    verdict_raw: dict
    assessment_raw: dict
    severity: str            # From Assessment
    root_cause: str          # From Assessment
    recommended_action: str  # From Assessment
    blast_radius: list[str]
    created_at: float = field(default_factory=time.time)
    submitted: bool = False
    plan_revision: int = 1
    revision_instructions: str = ""
    rejected_runbook: str = ""  # Runbook ID from the rejected plan (to avoid repeating it)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Module-level trusted context store, keyed by incident_id
_trusted_context: dict[str, CommanderContext] = {}

# Rooms where Commander has already published its sealed ResponsePlan.
# Non-card messages from agents in these rooms are silently consumed
# (deterministic anti-chatter-loop — not just a prompt instruction).
_handoff_rooms: set[str] = set()

# Recorder agent ID — used to validate StructuredApproval(REJECTED) sender
_RECORDER_AGENT_ID = os.getenv("RECORDER_AGENT_ID", "")


# ---------------------------------------------------------------------------
# Human revision support — constrained runbook parsing + policy validation
# ---------------------------------------------------------------------------

# Explicit keyword → runbook mapping (deliberately small, not semantic free-for-all)
_HUMAN_RUNBOOK_CONSTRAINTS: dict[str, str] = {
    "circuit breaker": "RB-004",
    "circuit-breaker": "RB-004",
    "rollback": "RB-003",
    "roll back": "RB-003",
    "rate limit": "RB-005",  # Maps to DNS failover for demo; adjust as needed
    "rate-limit": "RB-005",
    "scale up": "RB-002",
    "scale out": "RB-002",
    "restart": "RB-001",
    "maintenance page": "RB-006",
    "maintenance": "RB-006",
    "dns failover": "RB-005",
}

# Allowed runbooks per severity (deterministic policy guard)
_ALLOWED_RUNBOOKS_BY_SEVERITY: dict[str, set[str]] = {
    "P1": {"RB-001", "RB-002", "RB-003", "RB-004", "RB-005", "RB-006"},  # All allowed for P1
    "P2": {"RB-001", "RB-002", "RB-003", "RB-004", "RB-005", "RB-006"},  # All allowed for P2
    "P3": {"RB-001", "RB-002", "RB-004", "RB-006"},  # No destructive (RB-003, RB-005) for P3
    "P4": {"RB-001", "RB-002", "RB-004", "RB-006"},  # No destructive for P4
}


def parse_human_runbook_constraint(
    instructions: str,
    *,
    rejected_runbook: str = "",
) -> str:
    """Parse human revision instructions for a recognized runbook constraint.

    Resolves 'X instead of Y' patterns to X (not Y).
    Excludes the rejected runbook to prevent v2 == v1.

    Returns: runbook ID (e.g. 'RB-004') or '' if no match.
    """
    instructions_lower = instructions.lower()

    # Find all matching runbooks, ordered by position in the string
    matches: list[tuple[int, str]] = []
    for keyword, rb_id in _HUMAN_RUNBOOK_CONSTRAINTS.items():
        pos = instructions_lower.find(keyword)
        if pos >= 0:
            matches.append((pos, rb_id))

    if not matches:
        return ""

    # Sort by position — first mention is the desired runbook
    matches.sort(key=lambda x: x[0])

    # If 'instead of' pattern, the first keyword before 'instead' is what they want
    instead_pos = instructions_lower.find("instead")
    if instead_pos >= 0:
        # Take the first match BEFORE 'instead' — that's the desired runbook
        before_instead = [(pos, rb) for pos, rb in matches if pos < instead_pos]
        if before_instead:
            desired = before_instead[0][1]
            if desired != rejected_runbook:
                return desired
            # They asked for the same one they rejected — skip
            return ""

    # No 'instead of' pattern — take first match that isn't the rejected one
    for _, rb_id in matches:
        if rb_id != rejected_runbook:
            return rb_id

    return ""


def get_allowed_runbooks(severity: str) -> set[str]:
    """Return the set of allowed runbook IDs for a given severity level."""
    return _ALLOWED_RUNBOOKS_BY_SEVERITY.get(severity, {"RB-001"})


# ---------------------------------------------------------------------------
# Local runtime handler — submit_response_plan
#
# Kept with the same signature to preserve existing typed-call tests.
# Remaining params become tool input schema via type annotations.
# Tool name = function.__name__ → "submit_response_plan"
# ---------------------------------------------------------------------------

class SubmitResponsePlan(BaseModel):
    """Submit a response plan for an incident.

    MUST be called after receiving a CONFIRM Verdict. The plan will be
    submitted to Gateway and published to the incident room. Risk level and approval
    requirements are determined deterministically by the system.
    """
    incident_id: str = Field(description="The incident identifier")
    runbook: str = Field(
        description=(
            "Runbook ID to apply. One of: RB-001 (restart), RB-002 (scale up), "
            "RB-003 (rollback), RB-004 (circuit breaker), RB-005 (DNS failover), "
            "RB-006 (maintenance page)"
        ),
    )
    target_service: str = Field(
        description="The target service name for the action (e.g., 'payment-service')",
    )
    reasoning: str = Field(
        description="Brief explanation of why this runbook was selected",
    )
    additional_parameters: dict = Field(
        default_factory=dict,
        description="Optional extra parameters to merge into the envelope",
    )


async def submit_response_plan(
    ctx: Any,
    incident_id: str,
    runbook: str,
    target_service: str,
    reasoning: str,
    additional_parameters: dict | None = None,
) -> str:
    """Submit a response plan for an incident.

    MUST be called after receiving a CONFIRM Verdict. The plan will be
    submitted to Gateway and published to the incident room. Risk level and approval
    requirements are determined deterministically by the system.

    Args:
        ctx: Compatibility context retained for typed-call tests.
        incident_id: The incident identifier.
        runbook: Runbook ID to apply. One of: RB-001 (restart), RB-002 (scale up),
            RB-003 (rollback), RB-004 (circuit breaker), RB-005 (DNS failover),
            RB-006 (maintenance page).
        target_service: The target service name for the action (e.g., 'payment-service').
        reasoning: Brief explanation of why this runbook was selected.
        additional_parameters: Optional extra parameters to merge into the envelope.
    """
    # Construct validated Pydantic model from type-annotated params
    plan_input = SubmitResponsePlan(
        incident_id=incident_id,
        runbook=runbook,
        target_service=target_service,
        reasoning=reasoning,
        additional_parameters=additional_parameters or {},
    )
    # Delegate to existing handler logic
    return await handle_submit_response_plan(plan_input)

async def handle_submit_response_plan(input: SubmitResponsePlan) -> str:
    """Submit a ResponsePlan. Deterministic code owns risk + approval flow.

    This callback:
    1. Validates incident_id in trusted context
    2. Validates runbook ID
    3. Builds ExecutionEnvelopes from runbook template + target service
    4. Determines risk_level deterministically
    5. Creates ResponsePlan card
    6. Runs prepare → recruit Operator → publish → confirm saga
    7. For HIGH risk: generates nonce, recruits human approvers, posts challenge
    8. For LOW risk: requests PolicyAuthorization from Gateway
    """
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return f"Error: unknown incident {input.incident_id}. Cannot submit plan."

    async with ctx.lock:
        if ctx.submitted:
            return f"ResponsePlan already submitted for {input.incident_id}."

        # --- Revision-aware, deterministic-policy-validated runbook selection ---
        # The LLM suggests a runbook, but the system makes the final call
        # based on trusted Assessment context. When revising, human instructions
        # can constrain the runbook (if policy-allowed), but deterministic
        # policy still validates the final choice.
        if ctx.revision_instructions:
            # Human-constrained revision: parse instructions for runbook constraint
            constrained = parse_human_runbook_constraint(
                ctx.revision_instructions,
                rejected_runbook=ctx.rejected_runbook,
            )
            if constrained and constrained in get_allowed_runbooks(ctx.severity):
                actual_runbook = constrained
                logger.info(
                    f"[commander] Revision runbook: human constraint → {actual_runbook} "
                    f"(rejected: {ctx.rejected_runbook})"
                )
            else:
                # Fall back to deterministic but try to avoid the rejected runbook
                deterministic_runbook = select_runbook(
                    root_cause=ctx.root_cause,
                    severity=ctx.severity,
                    recommended_action=ctx.recommended_action,
                )
                actual_runbook = deterministic_runbook
                if actual_runbook == ctx.rejected_runbook:
                    # Deterministic picked the same one — try alternatives
                    allowed = get_allowed_runbooks(ctx.severity) - {ctx.rejected_runbook}
                    if allowed:
                        # Pick the first non-rejected allowed runbook
                        actual_runbook = sorted(allowed)[0]
                        logger.info(
                            f"[commander] Avoiding rejected runbook {ctx.rejected_runbook} "
                            f"→ using {actual_runbook}"
                        )
                logger.info(
                    f"[commander] Revision runbook fallback: {actual_runbook} "
                    f"(human constraint: {constrained!r}, rejected: {ctx.rejected_runbook})"
                )
        else:
            # First submission — pure deterministic runbook selection
            deterministic_runbook = select_runbook(
                root_cause=ctx.root_cause,
                severity=ctx.severity,
                recommended_action=ctx.recommended_action,
            )
            if deterministic_runbook != input.runbook:
                logger.info(
                    f"[commander] Runbook override: LLM suggested {input.runbook}, "
                    f"deterministic selection chose {deterministic_runbook} "
                    f"(severity={ctx.severity}, root_cause='{ctx.root_cause[:60]}...')"
                )
            actual_runbook = deterministic_runbook

        # --- Validate runbook ---
        runbook_def = RUNBOOKS.get(actual_runbook)
        if runbook_def is None:
            valid_ids = ", ".join(sorted(RUNBOOKS.keys()))
            return (
                f"Error: unknown runbook '{actual_runbook}'. "
                f"Valid runbook IDs: {valid_ids}"
            )


        # --- Build ExecutionEnvelopes from runbook template ---
        envelopes: list[ExecutionEnvelope] = []
        for tmpl in runbook_def.default_envelopes:
            env = ExecutionEnvelope(
                action_id=tmpl["action_id"],
                target=input.target_service,
                parameters={
                    **tmpl.get("parameters", {}),
                    **input.additional_parameters,
                },
                timeout_seconds=tmpl.get("timeout_seconds", 300),
                rollback_action=tmpl.get("rollback_action"),
            )
            envelopes.append(env)

        # --- Deterministic risk level ---
        # Apply runbook's minimum risk floor BEFORE determine_risk_level.
        # This prevents the LLM from choosing a low risk for destructive runbooks.
        risk_level = determine_risk_level(ctx.severity, envelopes)

        # Enforce runbook-level risk floor
        _RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        runbook_min = runbook_def.min_risk_level
        if _RISK_ORDER.get(risk_level, 0) < _RISK_ORDER.get(runbook_min, 0):
            logger.info(
                f"[commander] Risk floor applied: {risk_level} → {runbook_min} "
                f"(runbook {runbook_def.id} requires min {runbook_min})"
            )
            risk_level = runbook_min

        # --- Deterministic human approval requirement ---
        envelope_dicts = [e.model_dump() for e in envelopes]
        needs_human = requires_human_approval(risk_level, envelope_dicts)

        # --- Build ResponsePlan ---
        plan = ResponsePlan(
            incident_id=input.incident_id,
            runbook=actual_runbook,  # type: ignore[arg-type]
            envelopes=envelopes,
            risk_level=risk_level,  # type: ignore[arg-type]
            requires_human_approval=needs_human,
            revision=ctx.plan_revision,
        )

        # --- Compute hashes for approval binding ---
        plan_dict = plan.model_dump(mode="json")
        plan_hash = compute_plan_hash(plan_dict)
        action_hash = compute_action_hash(envelope_dicts)

        # --- SubmissionClient saga: prepare → publish → confirm ---
        try:
            submission_key = os.getenv(
                "COMMANDER_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            idem_key = derive_idempotency_key(
                "commander", ctx.room_message_id, ctx.source_card_hash,
            )

            async with SubmissionClient(
                gateway_url=GATEWAY_URL,
                agent_key=submission_key,
            ) as sc:
                # 1. Prepare — with state retry for publish-before-confirm race
                STATE_RETRY_DELAYS = [0.5, 1.0, 2.0, 3.0]
                prepared = None
                for attempt, delay in enumerate(STATE_RETRY_DELAYS):
                    try:
                        prepared = await sc.prepare(plan, idempotency_key=idem_key)
                        break
                    except SubmissionError as e:
                        if e.status_code == 409 and attempt < len(STATE_RETRY_DELAYS) - 1:
                            logger.warning(
                                f"[commander] prepare() got 409 on attempt "
                                f"{attempt + 1}/{len(STATE_RETRY_DELAYS)}. "
                                f"Waiting {delay}s for upstream confirm..."
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise

                if prepared is None:
                    raise RuntimeError("[commander] prepare() failed after all retries")

                publish_room = prepared.room_id or ctx.room_id
                sealed_message = format_card_message(prepared.sealed_card)

                # 2. Recruit Operator and publish sealed ResponsePlan into
                # Gateway-owned incident room.
                room_client = IncidentRoomClient(
                    gateway_url=GATEWAY_URL,
                    agent_key=submission_key,
                    sender_id=os.getenv("COMMANDER_AGENT_ID", "commander"),
                    sender_role="commander",
                    timeout=15.0,
                )
                try:
                    operator_id = os.getenv("OPERATOR_AGENT_ID", "")
                    if not operator_id:
                        raise RuntimeError(
                            "[commander] Cannot recruit: OPERATOR_AGENT_ID not configured."
                        )

                    await room_client.add_participant(
                        publish_room,
                        operator_id,
                        role="operator",
                        display_name="Operator",
                    )
                    logger.info(
                        f"[commander] Recruited Operator {operator_id[:12]}... "
                        f"into incident room {publish_room[:12]}..."
                    )

                    plan_message_id = await room_client.post_message(
                        publish_room,
                        sealed_message,
                        mentions=[operator_id],
                        metadata={
                            "publisher": "commander",
                            "card_hash": prepared.card_hash,
                        },
                    )

                finally:
                    await room_client.aclose()

                # 3. Confirm (REVIEWED → PLANNED) — BEFORE branch
                confirm = await sc.confirm(
                    submission_id=prepared.submission_id,
                    incident_id=prepared.incident_id,
                    card_hash=prepared.card_hash,
                    message_id=plan_message_id,
                    room_id=publish_room,
                )

                logger.info(
                    f"[commander] ResponsePlan confirmed: "
                    f"incident={input.incident_id}, risk={risk_level}, "
                    f"runbook={actual_runbook}, state={confirm.new_state}"
                )

                # 4. Branch: high-risk (nonce challenge) or low-risk (PolicyAuth)
                if needs_human:
                    # =========================================
                    # HIGH RISK: Nonce-based approval challenge
                    # =========================================
                    await _high_risk_flow(
                        ctx=ctx,
                        plan=plan,
                        plan_hash=plan_hash,
                        action_hash=action_hash,
                        envelope_dicts=envelope_dicts,
                        publish_room=publish_room,
                        operator_id=operator_id,
                        submission_key=submission_key,
                    )
                else:
                    # =========================================
                    # LOW RISK: PolicyAuthorization
                    # =========================================
                    await _low_risk_flow(
                        ctx=ctx,
                        plan=plan,
                        plan_hash=plan_hash,
                        action_hash=action_hash,
                        envelope_dicts=envelope_dicts,
                        publish_room=publish_room,
                        operator_id=operator_id,
                        submission_key=submission_key,
                        sc=sc,
                    )

            ctx.submitted = True
            # Mark room for post-handoff silence (anti-chatter-loop).
            _handoff_rooms.add(ctx.room_id)
            logger.info(
                f"[commander] Marked room {ctx.room_id[:12]}... for "
                f"post-handoff silence (incident {input.incident_id})"
            )
            risk_desc = "HIGH (approval challenge sent)" if needs_human else "LOW (policy authorized)"
            # Build revision-aware return message (prevents LLM
            # from referencing old runbook in its text response)
            revision_note = ""
            if ctx.revision_instructions:
                revision_note = (
                    f" [REVISION v{ctx.plan_revision}] Human feedback: "
                    f"\"{ctx.revision_instructions[:200]}\". "
                    f"Previous runbook ({ctx.rejected_runbook}) was rejected. "
                    f"System selected {actual_runbook} based on human constraint."
                )

            return (
                f"ResponsePlan submitted for {input.incident_id}. "
                f"Runbook: {runbook_def.name} ({actual_runbook}). "
                f"Risk: {risk_desc}. "
                f"Plan published and confirmed.{revision_note} "
                f"YOUR WORK IS DONE. Do not send any more messages."
            )

        except Exception as exc:
            logger.error(
                "[commander] ResponsePlan submission failed (%s)",
                type(exc).__name__,
            )
            return f"Error submitting response plan ({type(exc).__name__})"


def _target_from_context(ctx: CommanderContext) -> str:
    """Choose a target service from trusted Assessment context."""
    if ctx.blast_radius:
        first = ctx.blast_radius[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    for text in (ctx.root_cause, ctx.recommended_action):
        for service in (
            "payment-service",
            "auth-service",
            "api-gateway",
            "user-service",
            "worker-service",
        ):
            if service in text:
                return service
    return "payment-service"


async def run_local_commander(event) -> None:
    """Run Commander planning without an external adapter after acceptance."""
    payload = getattr(event, "payload", None)
    content = getattr(payload, "content", "") if payload else ""
    card = extract_sealed_card(content)
    if not card:
        return
    if card.get("card_type") == "Verdict" and card.get("decision") == "CONFIRM":
        incident_id = card.get("incident_id", "")
    elif card.get("card_type") == "StructuredApproval" and card.get("decision") == "REJECTED":
        incident_id = card.get("incident_id", "")
    else:
        return

    ctx = _trusted_context.get(incident_id)
    if ctx is None or ctx.submitted:
        return

    runbook = select_runbook(
        root_cause=ctx.root_cause,
        severity=ctx.severity,
        recommended_action=ctx.recommended_action,
    )
    reasoning = (
        "Local Commander selected the safest matching runbook from "
        f"trusted Assessment context (severity={ctx.severity})."
    )
    qwen = await ask_qwen_json(
        role="commander",
        system=(
            "You are Han Ce, the Commander. Explain why the supplied runbook "
            "matches the trusted diagnosis. Do not choose a different runbook "
            "and do not alter the target service."
        ),
        user={
            "incident_id": incident_id,
            "fixed_runbook": runbook,
            "severity": ctx.severity,
            "root_cause": ctx.root_cause,
            "recommended_action": ctx.recommended_action,
            "target_service": _target_from_context(ctx),
            "revision_instructions": ctx.revision_instructions,
            "expected_json_keys": ["reasoning"],
        },
        max_tokens=500,
    )
    if qwen:
        reasoning = bounded_text(qwen.get("reasoning"), max_len=700) or reasoning

    plan = SubmitResponsePlan(
        incident_id=incident_id,
        runbook=runbook,
        target_service=_target_from_context(ctx),
        reasoning=reasoning,
    )
    result = await handle_submit_response_plan(plan)
    logger.info("[commander] Local planning result: %s", result)


# ---------------------------------------------------------------------------
# HIGH RISK flow — nonce-based approval challenge
# ---------------------------------------------------------------------------

async def _high_risk_flow(
    *,
    ctx: CommanderContext,
    plan: ResponsePlan,
    plan_hash: str,
    action_hash: str,
    envelope_dicts: list[dict],
    publish_room: str,
    operator_id: str,
    submission_key: str,
) -> None:
    """Execute high-risk approval challenge flow.

    Called AFTER the shared publish + confirm steps.

    1. Generate nonce
    2. Create nonce in Gateway
    3. Surface approval challenge through Gateway
    4. Post approval challenge message @mentioning human + Operator
    """
    # Create nonce in Gateway — Gateway derives plan_hash/action_hash/plan_revision
    # from the confirmed ResponsePlan. Commander sends only incident_id.
    nonce_body = {
        "incident_id": ctx.incident_id,
    }

    async with httpx.AsyncClient(timeout=20.0) as gw_client:  # Raised from 15s: Gateway retry budget is ~13.5s
        nonce_resp = await gw_client.post(
            f"{GATEWAY_URL}/api/nonce/create",
            json=nonce_body,
            headers={
                "X-Agent-Key": submission_key,
                "Content-Type": "application/json",
            },
        )
        if nonce_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"[commander] Failed to create nonce: "
                f"HTTP {nonce_resp.status_code}"
            )
            
        nonce = nonce_resp.json()["nonce"]
        expiry_iso = nonce_resp.json().get("expiry_iso", "")
        # Use Gateway-authoritative bindings (these are derived from the
        # stored sealed ResponsePlan with seal fields reset, guaranteed
        # consistent with what /authorization/request will verify).
        plan_hash = nonce_resp.json().get("plan_hash", plan_hash)
        action_hash = nonce_resp.json().get("action_hash", action_hash)
        plan_revision_gw = nonce_resp.json().get("plan_revision", ctx.plan_revision)
        # Parse back to datetime for display
        from datetime import datetime, timezone
        try:
            expiry = datetime.fromisoformat(expiry_iso.replace("Z", "+00:00"))
        except Exception:
            expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

    logger.info(
        "[commander] Nonce created by Gateway for %s; plan_hash=%s...",
        ctx.incident_id,
        plan_hash[:12],
    )

    # Human approves via Gateway approval page.
    # Mention Operator only — Operator must wake to process StructuredApproval.
    logger.info(
        f"[commander] Skipping human recruitment — approval via Gateway UI. "
        f"Mentioning Operator only: {operator_id[:12]}..."
    )
    mention_objects = [{"id": operator_id}]

    challenge_payload = {
        "type": "APPROVAL_CHALLENGE",
        "incident_id": ctx.incident_id,
        "plan_hash": plan_hash,
        "action_hash": action_hash,
        # nonce intentionally omitted — not needed in incident room (web approval model)
        "expiry": expiry.isoformat(),
        "plan_revision": plan_revision_gw,
        "mentions": mention_objects,
    }

    challenge_text = (
        f"🔐 **APPROVAL REQUIRED** — High-risk plan for incident `{ctx.incident_id}`\n\n"
        f"Runbook: **{plan.runbook}** — Risk: **{plan.risk_level}**\n"
        f"Actions: {', '.join(e.action_id for e in plan.envelopes)}\n\n"
        f"To approve, open the YITING approval page for `{ctx.incident_id}`.\n"
        f"Nonce expires: {expiry.isoformat()}\n\n"
        f"```json\n{json.dumps(challenge_payload, indent=2)}\n```"
    )

    # Post challenge through Gateway/Recorder so the approval beat is visible
    # in the incident room and Gateway stores the real message ID.
    _CONFIRM_RETRIES = [0.5, 1.0, 2.0]
    confirmed = False
    async with httpx.AsyncClient(timeout=15.0) as gw_client:
        for attempt, delay in enumerate(_CONFIRM_RETRIES):
            try:
                confirm_resp = await gw_client.post(
                    f"{GATEWAY_URL}/api/nonce/challenge-posted",
                    json={
                        "incident_id": ctx.incident_id,
                        "nonce": nonce,
                        "challenge_text": challenge_text,
                    },
                    headers={
                        "X-Agent-Key": submission_key,
                        "Content-Type": "application/json",
                    },
                )
                if confirm_resp.status_code in (200, 201):
                    resp_data = confirm_resp.json()
                    challenge_msg = (
                        resp_data.get("challenge_message_id")
                        or resp_data.get("challenge_message_id", "")
                    )
                    logger.info(
                        "[commander] Challenge posted via Gateway/Recorder: "
                        "status=%s message_id=%s incident=%s",
                        confirm_resp.status_code,
                        challenge_msg,
                        ctx.incident_id,
                    )
                    confirmed = True
                    break
                else:
                    logger.warning(
                        "[commander] Challenge confirm attempt %s/%s failed: "
                        "HTTP %s incident=%s",
                        attempt + 1,
                        len(_CONFIRM_RETRIES),
                        confirm_resp.status_code,
                        ctx.incident_id,
                    )
            except Exception as confirm_err:
                logger.error(
                    "[commander] Challenge confirm attempt %s/%s failed (%s) "
                    "for incident=%s",
                    attempt + 1,
                    len(_CONFIRM_RETRIES),
                    type(confirm_err).__name__,
                    ctx.incident_id,
                )
            if attempt < len(_CONFIRM_RETRIES) - 1:
                await asyncio.sleep(delay)

    if not confirmed:
        raise RuntimeError(
            f"[commander] Failed to post challenge via Gateway/Recorder "
            f"after {len(_CONFIRM_RETRIES)} attempts for incident {ctx.incident_id}. "
            "Approval remains unavailable."
        )

    logger.info(
        "[commander] Approval challenge ready for %s; mentions=1 (Operator only)",
        ctx.incident_id,
    )


# ---------------------------------------------------------------------------
# LOW RISK flow — PolicyAuthorization
# ---------------------------------------------------------------------------

async def _low_risk_flow(
    *,
    ctx: CommanderContext,
    plan: ResponsePlan,
    plan_hash: str,
    action_hash: str,
    envelope_dicts: list[dict],
    publish_room: str,
    operator_id: str,
    submission_key: str,
    sc: SubmissionClient,
) -> None:
    """Execute low-risk PolicyAuthorization flow (Fork B: Gateway-owned).

    Called AFTER the shared publish + confirm steps.

    1. Request PolicyAuthorization from Gateway (Gateway creates + seals it)
    2. Gateway publishes the PolicyAuthorization notification
    """
    # Request PolicyAuthorization from Gateway (Fork B: Gateway-owned)
    # Commander only sends incident_id + plan_hash. Gateway derives
    # risk_level, envelopes, action_hash from the stored ResponsePlan.
    async with httpx.AsyncClient(timeout=15.0) as gw_client:
        auth_resp = await gw_client.post(
            f"{GATEWAY_URL}/api/authorization/request",
            json={
                "incident_id": ctx.incident_id,
                "plan_hash": plan_hash,
            },
            headers={
                "X-Agent-Key": submission_key,
                "Content-Type": "application/json",
            },
        )

        if auth_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"[commander] PolicyAuthorization request failed: "
                f"HTTP {auth_resp.status_code}"
            )

        auth_data = auth_resp.json()
        authorization_id = auth_data["authorization_id"]

    # NOTE: Commander does NOT post a separate PolicyAuthorization notification.
    # Gateway already posted the sealed PolicyAuthorization card via Recorder,
    # mentioning Operator. A second Commander notification would wake Operator
    # twice, creating a duplicate execution context. Gateway's card is the sole
    # trigger for the low-risk Operator path.
    logger.info(
        f"[commander] PolicyAuthorization issued by Gateway for {ctx.incident_id}: "
        f"auth_id={authorization_id[:12]}..."
    )


# ---------------------------------------------------------------------------
# Commander Preprocessor (thin: validate → store context → delegate)
# ---------------------------------------------------------------------------

class CommanderPreprocessor:
    """Thin preprocessor for the Commander agent.

    Intercepts Verdict(CONFIRM) messages from incident room. Validates sender
    (must be Safety Reviewer), checks seal fields, Pydantic-validates,
    rejects non-CONFIRM decisions, extracts linked Assessment from
    message context, stores trusted per-incident context, and delegates
    to the local incident-room runtime for plan creation.

    SDK contract: process(ctx, event, **kwargs) → AgentInput | None
    - Return AgentInput → local runtime invokes the planning callback
    - Return None → event consumed silently
    """

    def __init__(
        self,
        *,
        commander_agent_id: str,
        commander_api_key: str,
    ):
        self._commander_agent_id = commander_agent_id
        self._commander_api_key = commander_api_key
        self._safety_reviewer_id = os.getenv("SAFETY_REVIEWER_AGENT_ID", "")
        self._default_preprocessor = None
        self._boot_epoch = time.time()

    async def _ensure_default(self):
        """Lazily import and create DefaultPreprocessor."""
        if self._default_preprocessor is None:
            self._default_preprocessor = LocalDefaultPreprocessor()

    async def process(self, ctx, event, **kwargs):
        """Process a room event.

        Intercepts Verdict(CONFIRM) → stores context → delegates to adapter.
        Other messages → pass through to default preprocessor.
        """
        await self._ensure_default()

        # Only handle MessageEvents
        event_type = type(event).__name__
        if event_type != "MessageEvent":
            return await self._default_preprocessor.process(ctx, event, **kwargs)

        payload = getattr(event, "payload", None)
        if payload is None:
            return await self._default_preprocessor.process(ctx, event, **kwargs)

        content = getattr(payload, "content", None) or ""
        sender_id = getattr(payload, "sender_id", "") or ""
        sender_type = getattr(payload, "sender_type", "") or ""
        room_id = getattr(event, "room_id", "") or ""
        room_message_id = getattr(payload, "id", "") or ""

        # Ignore own messages
        if sender_id == self._commander_agent_id:
            return None

        # Try to extract a Verdict card
        card_data = extract_sealed_card(content)
        if not card_data:
            # No sealed card — deterministic post-handoff silence.
            # If ResponsePlan was already submitted for this room, silently
            # consume non-card agent messages to prevent chatter loops.
            if room_id and room_id in _handoff_rooms and sender_type == "Agent":
                logger.debug(
                    f"[commander] Post-handoff silence: consuming non-card "
                    f"agent message in room {room_id[:12]}..."
                )
                return None

            # Check freshness for non-sealed chatter
            inserted_at = getattr(payload, "inserted_at", None)
            if should_skip_stale_chatter(str(inserted_at) if inserted_at else None, self._boot_epoch, "commander"):
                return None
            # Preserve human messages (e.g. APPROVE <nonce>)
            return await self._default_preprocessor.process(ctx, event, **kwargs)

        # --- Handle StructuredApproval(REJECTED) — human requests plan revision ---
        if card_data.get("card_type") == "StructuredApproval":
            sa_decision = card_data.get("decision", "")
            if sa_decision == "REJECTED":
                return await self._handle_rejection(
                    card_data=card_data,
                    sender_id=sender_id,
                    sender_type=sender_type,
                    room_id=room_id,
                    room_message_id=room_message_id,
                    event=event,
                    ctx=ctx,
                    kwargs=kwargs,
                )
            # FALSE_ALARM or APPROVED — Commander doesn't act on these
            logger.info(
                f"[commander] Ignoring StructuredApproval({sa_decision}) — "
                f"Commander only acts on REJECTED"
            )
            return None

        if card_data.get("card_type") != "Verdict":
            # Sealed card but not our type — silent consume if has seal fields
            if has_seal_fields(card_data):
                logger.info(
                    f"[commander] Silently consuming unsupported sealed card "
                    f"{card_data.get('card_type', '?')}"
                )
                return None
            # Card-shaped but no seal fields — reject + log
            logger.warning(
                f"[commander] Card-shaped payload missing seal fields "
                f"(type={card_data.get('card_type', '?')}) — rejected"
            )
            return None

        # ----- Sender Validation -----
        if sender_type != "Agent":
            logger.warning(
                f"[commander] REJECTED Verdict from non-agent "
                f"sender_type={sender_type!r}"
            )
            return None

        if not self._safety_reviewer_id:
            logger.error(
                "[commander] REJECTED Verdict: SAFETY_REVIEWER_AGENT_ID not "
                "configured. Cannot verify sender identity."
            )
            return None

        if sender_id != self._safety_reviewer_id:
            logger.warning(
                f"[commander] REJECTED Verdict from untrusted agent "
                f"{sender_id!r} — expected Safety Reviewer "
                f"{self._safety_reviewer_id!r}"
            )
            return None

        # ----- Seal Field Check -----
        if not has_seal_fields(card_data):
            return None

        # ----- Active Incident Allowlist (credit protection) -----
        incident_id_guard = card_data.get("incident_id", "")
        if ACTIVE_INCIDENTS and incident_id_guard not in ACTIVE_INCIDENTS:
            logger.info(f"[commander] Skipping non-active incident {incident_id_guard}")
            return None

        # ----- Stale Card Guard (cost optimization) -----
        card_seq = card_data.get("sequence_number")
        if incident_id_guard and await should_skip_stale_card(incident_id_guard, card_seq, "commander"):
            return None
        if incident_id_guard and await should_skip_terminal_incident(incident_id_guard, role="commander"):
            return None
        confirmed_cards: list[dict] = []
        if incident_id_guard:
            confirmed_cards = await fetch_confirmed_cards(
                incident_id_guard,
                agent_key=os.getenv("COMMANDER_SUBMISSION_KEY", os.getenv("GATEWAY_SECRET", "")),
                role="commander",
            )
            if confirmed_cards and verdict_already_planned(confirmed_cards, card_data):
                logger.info(
                    "[commander] Skipping stale Verdict(CONFIRM) for %s: "
                    "later ResponsePlan already exists",
                    incident_id_guard,
                )
                return None

        # ----- Pydantic Validation -----
        try:
            validated = Verdict(**card_data)
        except Exception as exc:
            logger.warning(
                "[commander] Verdict validation failed (%s)",
                type(exc).__name__,
            )
            return None

        # ----- Only accept CONFIRM verdicts -----
        if validated.decision != "CONFIRM":
            logger.info(
                f"[commander] Ignoring Verdict({validated.decision}) for "
                f"{validated.incident_id} — Commander only acts on CONFIRM"
            )
            return None

        # ----- Reject duplicate -----
        # Restart note: a None context on the CONFIRM path is NOT a stall —
        # the code below re-fetches the Assessment from the Gateway and
        # rebuilds a fresh CommanderContext, so a restarted Commander
        # re-plans. Worst case is a redundant plan the Gateway's state
        # prerequisites reject; _restore_context_from_gateway covers the
        # REJECTED path, which needs the prior plan revision.
        incident_id = validated.incident_id
        existing = _trusted_context.get(incident_id)
        if existing is not None:
            if existing.submitted:
                logger.warning(
                    f"[commander] Redelivered Verdict for already-submitted "
                    f"incident {incident_id} — ignoring"
                )
            else:
                logger.warning(
                    f"[commander] Duplicate Verdict for active incident "
                    f"{incident_id} — ignoring"
                )
            return None

        # ----- Extract linked Assessment from the message context -----
        # The Verdict message typically follows an Assessment in the same room.
        # We search the message content for Assessment data, or fetch it from
        # the Verdict's reasoning + the room's message history.
        # For now, we extract Assessment info from what's available.
        assessment_data = await self._fetch_assessment(
            incident_id=incident_id,
            room_id=room_id,
        )

        if assessment_data is None:
            logger.error(
                f"[commander] Cannot find Assessment for incident "
                f"{incident_id}. Cannot create response plan."
            )
            return None

        # FAIL-CLOSED: severity must be explicitly present and recognized.
        # A missing/unparseable severity must NEVER default to P4, because
        # that silently converts an unknown P1 into low-risk auto-execution.
        severity_raw = assessment_data.get("severity", "")
        # Derive from Assessment schema: Literal["P1", "P2", "P3", "P4"]
        RECOGNIZED_SEVERITIES = {"P1", "P2", "P3", "P4"}
        if not severity_raw or severity_raw not in RECOGNIZED_SEVERITIES:
            logger.error(
                f"[commander] SEVERITY FAIL-CLOSED: Assessment for {incident_id} "
                f"has severity={severity_raw!r} — not in {RECOGNIZED_SEVERITIES}. "
                f"Aborting ResponsePlan creation (cannot determine risk level)."
            )
            return None

        # Store trusted context
        _trusted_context[incident_id] = CommanderContext(
            incident_id=incident_id,
            room_id=room_id,
            room_message_id=room_message_id,
            source_card_hash=card_data.get("card_hash", ""),
            verdict_raw=card_data,
            assessment_raw=assessment_data,
            severity=severity_raw,
            root_cause=assessment_data.get("root_cause_hypothesis", ""),
            recommended_action=assessment_data.get("recommended_action", ""),
            blast_radius=assessment_data.get("blast_radius", []),
        )

        logger.info(
            f"[commander] Accepted Verdict(CONFIRM) for {incident_id}. "
            f"Severity: {severity_raw}, "
            f"Root cause: {assessment_data.get('root_cause_hypothesis', '')[:80]}. "
            f"Context stored. Delegating to local Qwen planning."
        )

        # ----- Delegate to local incident-room runtime -----
        return await self._default_preprocessor.process(ctx, event, **kwargs)

    async def _fetch_assessment(
        self,
        incident_id: str,
        room_id: str,
    ) -> dict | None:
        """Fetch the Assessment card for an incident from Gateway.

        Tries Gateway's incident cards endpoint first. Falls back to
        searching the Gateway-owned incident room history if needed.
        """
        # Try Gateway cards endpoint
        try:
            submission_key = os.getenv(
                "COMMANDER_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GATEWAY_URL}/api/incidents/{incident_id}/cards",
                    headers={
                        "X-Agent-Key": submission_key,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    cards = resp.json()
                    if isinstance(cards, list):
                        card_list = cards
                    elif isinstance(cards, dict):
                        card_list = cards.get("cards", [])
                    else:
                        card_list = []
                    for card in reversed(card_list):
                        if card.get("card_type") == "Assessment":
                            return self._unpack_card(card)
        except Exception as exc:
            logger.warning(
                "[commander] Failed to fetch Assessment from Gateway (%s)",
                type(exc).__name__,
            )

        # Fallback: search incident room history
        try:
            submission_key = os.getenv(
                "COMMANDER_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            room_client = IncidentRoomClient(
                gateway_url=GATEWAY_URL,
                agent_key=submission_key,
                sender_id=self._commander_agent_id,
                sender_role="commander",
                timeout=15.0,
            )
            try:
                messages = await room_client.get_messages(room_id, limit=50)
            finally:
                await room_client.aclose()

            for msg in reversed(messages):
                msg_content = msg.get("content", "")
                card = extract_sealed_card(msg_content)
                if (
                    card
                    and card.get("card_type") == "Assessment"
                    and card.get("incident_id") == incident_id
                ):
                    return self._unpack_card(card)
        except Exception as exc:
            logger.warning(
                "[commander] Failed to search incident room for Assessment (%s)",
                type(exc).__name__,
            )

        return None

    @staticmethod
    def _unpack_card(card: dict) -> dict:
        """Unpack card data into top-level dict fields.

        Gateway exposes card data in different shapes depending on the
        endpoint:
        - ``/incidents/{id}`` → ``card_json`` (JSON string from SQLite)
        - ``/api/incidents/{id}/cards`` → ``data`` (parsed dict)

        This method handles both and merges data fields into the top-level
        dict so callers can access ``card.get("severity")`` directly.
        """
        import json as _json

        # Try both possible keys: 'data' (API) and 'card_json' (raw SQLite)
        card_json_raw = card.get("data") or card.get("card_json")
        if card_json_raw:
            try:
                # card_json may be a JSON string (from SQLite) or already
                # parsed to a dict (from resp.json()).  Handle both.
                if isinstance(card_json_raw, str):
                    data = _json.loads(card_json_raw)
                elif isinstance(card_json_raw, dict):
                    data = card_json_raw
                else:
                    data = {}
                if isinstance(data, dict):
                    # Merge data fields. Overwrite None/empty top-level values
                    # so the real data from card_json wins.
                    for key, value in data.items():
                        if card.get(key) in (None, "", [], {}):
                            card[key] = value
            except (_json.JSONDecodeError, TypeError):
                pass
        return card

    async def _handle_rejection(
        self,
        *,
        card_data: dict,
        sender_id: str,
        sender_type: str,
        room_id: str,
        room_message_id: str,
        event,
        ctx,
        kwargs,
    ):
        """Handle StructuredApproval(REJECTED) — human requests plan revision.

        Validation flow:
        1. Sender must be RECORDER_AGENT_ID (fail-closed)
        2. Seal fields must be present
        3. Active incident allowlist guard
        4. Stale-card guard (sequence_number)
        5. Context must exist (existing or restored from Gateway)
        6. Dedup guard keyed on source_card_hash
        7. Reset context for revision + revision-aware runbook selection
        8. Delegate to local Qwen-assisted planning for revised plan creation
        """
        incident_id = card_data.get("incident_id", "")

        # 1. Sender must be RECORDER_AGENT_ID (sealed cards come from Gateway/Recorder)
        recorder_id = _RECORDER_AGENT_ID
        if sender_type != "Agent":
            logger.warning(
                f"[commander] REJECTED StructuredApproval from non-agent "
                f"sender_type={sender_type!r}"
            )
            return None
        if not recorder_id:
            logger.error(
                "[commander] RECORDER_AGENT_ID not configured — cannot verify "
                "StructuredApproval sender. Rejecting (fail-closed)."
            )
            return None
        if sender_id != recorder_id:
            logger.warning(
                f"[commander] REJECTED StructuredApproval from unauthorized "
                f"agent {sender_id!r} — expected RECORDER {recorder_id!r}"
            )
            return None

        # 2. Seal fields
        if not has_seal_fields(card_data):
            logger.warning(
                f"[commander] StructuredApproval(REJECTED) missing seal fields "
                f"for {incident_id} — rejected"
            )
            return None

        # 3. Active incident allowlist
        if ACTIVE_INCIDENTS and incident_id not in ACTIVE_INCIDENTS:
            logger.info(f"[commander] Skipping non-active incident {incident_id}")
            return None

        # 4. Stale-card guard
        card_seq = card_data.get("sequence_number")
        if incident_id and await should_skip_stale_card(incident_id, card_seq, "commander"):
            return None
        if incident_id and await should_skip_terminal_incident(incident_id, role="commander"):
            return None
        confirmed_cards = []
        if incident_id:
            confirmed_cards = await fetch_confirmed_cards(
                incident_id,
                agent_key=os.getenv("COMMANDER_SUBMISSION_KEY", os.getenv("GATEWAY_SECRET", "")),
                role="commander",
            )
            if confirmed_cards and rejection_already_revised(confirmed_cards, card_data):
                logger.info(
                    "[commander] Skipping stale StructuredApproval(REJECTED) "
                    "for %s: later ResponsePlan revision already exists",
                    incident_id,
                )
                return None

        # 5. Context must exist (or restore from Gateway)
        existing = _trusted_context.get(incident_id)
        if existing is None:
            logger.info(
                f"[commander] No existing context for {incident_id} — "
                f"attempting restore from Gateway"
            )
            restored = await self._restore_context_from_gateway(incident_id, room_id)
            if restored is None:
                logger.error(
                    f"[commander] Cannot restore context for {incident_id} — "
                    f"ignoring rejection"
                )
                return None
            _trusted_context[incident_id] = restored
            existing = restored

        # 6. Dedup guard keyed on source_card_hash (not plan_revision)
        rejection_hash = card_data.get("card_hash", "")
        if existing.source_card_hash == rejection_hash and existing.submitted:
            logger.warning(
                f"[commander] Already processed rejection {rejection_hash[:12]} "
                f"for {incident_id}"
            )
            return None

        # DB fallback: check Gateway for a newer ResponsePlan
        rejected_revision = card_data.get("plan_revision", 1)
        latest_plan = await self._fetch_response_plan(incident_id)
        if latest_plan:
            latest_plan_dict = dict(latest_plan) if not isinstance(latest_plan, dict) else latest_plan
            latest_rev = latest_plan_dict.get("revision", 1)
            if latest_rev > rejected_revision:
                logger.info(
                    f"[commander] ResponsePlan revision {latest_rev} > "
                    f"rejected revision {rejected_revision} — stale rejection, ignoring"
                )
                return None

        # Extract revision instructions from the rejection card
        revision_instructions = card_data.get("reason", "")

        # Determine the rejected runbook from the current plan
        rejected_runbook = ""
        if latest_plan:
            latest_plan_dict = dict(latest_plan) if not isinstance(latest_plan, dict) else latest_plan
            rejected_runbook = latest_plan_dict.get("runbook", "")

        # 7. Reset context for revision
        async with existing.lock:
            # Human-constrained, deterministic-policy-validated runbook selection
            constrained = parse_human_runbook_constraint(
                revision_instructions,
                rejected_runbook=rejected_runbook,
            )
            if constrained and constrained in get_allowed_runbooks(existing.severity):
                new_runbook = constrained
                logger.info(
                    f"[commander] Human constraint parsed: {constrained} "
                    f"(policy-allowed for {existing.severity})"
                )
            else:
                new_runbook = select_runbook(
                    existing.root_cause, existing.severity, existing.recommended_action,
                )
                if constrained:
                    logger.info(
                        f"[commander] Human constraint {constrained!r} not allowed "
                        f"for {existing.severity} — falling back to deterministic: {new_runbook}"
                    )

            existing.submitted = False
            existing.plan_revision += 1
            existing.revision_instructions = revision_instructions
            existing.rejected_runbook = rejected_runbook
            existing.source_card_hash = rejection_hash
            existing.room_message_id = room_message_id

            # Remove room from handoff set so Commander can speak again
            if room_id in _handoff_rooms:
                _handoff_rooms.discard(room_id)

        logger.info(
            f"[commander] Revision requested for {incident_id}: "
            f"v{existing.plan_revision}, instructions: {revision_instructions[:100]!r}, "
            f"suggested runbook: {new_runbook}"
        )

        # 8. Delegate to local Qwen-assisted planning for revised plan creation
        return await self._default_preprocessor.process(ctx, event, **kwargs)

    async def _restore_context_from_gateway(
        self, incident_id: str, room_id: str,
    ) -> "CommanderContext | None":
        """Restore CommanderContext from Gateway cards after restart.

        Populates ALL required fields from the latest confirmed cards:
        - assessment_raw, verdict_raw from latest Assessment + Verdict(CONFIRM)
        - room_message_id and source_card_hash are set to empty strings
          (overwritten by _handle_rejection after restore)
        - plan_revision from latest ResponsePlan
        """
        assessment = await self._fetch_assessment(incident_id, room_id)
        if not assessment:
            return None

        # Fetch latest Verdict(CONFIRM) for verdict_raw
        verdict = await self._fetch_latest_card(incident_id, "Verdict")

        # Fetch ResponsePlan so revision is anchored to what was rejected
        plan_v1 = await self._fetch_response_plan(incident_id)

        severity = assessment.get("severity", "")
        if severity not in {"P1", "P2", "P3", "P4"}:
            return None  # Fail-closed on unrecognized severity

        plan_revision = 1
        if plan_v1:
            plan_v1_dict = dict(plan_v1) if not isinstance(plan_v1, dict) else plan_v1
            plan_revision = plan_v1_dict.get("revision", 1)

        return CommanderContext(
            incident_id=incident_id,
            room_id=room_id,
            room_message_id="",       # Overwritten by _handle_rejection
            source_card_hash="",      # Overwritten by _handle_rejection
            severity=severity,
            root_cause=assessment.get("root_cause_hypothesis", ""),
            recommended_action=assessment.get("recommended_action", ""),
            blast_radius=assessment.get("blast_radius", []),
            verdict_raw=verdict or {},
            assessment_raw=assessment,
            plan_revision=plan_revision,
        )

    async def _fetch_response_plan(self, incident_id: str) -> dict | None:
        """Fetch the latest confirmed ResponsePlan from Gateway."""
        try:
            submission_key = os.getenv(
                "COMMANDER_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GATEWAY_URL}/api/incidents/{incident_id}/cards",
                    headers={
                        "X-Agent-Key": submission_key,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    cards = resp.json()
                    card_list = cards if isinstance(cards, list) else cards.get("cards", [])
                    for card in reversed(card_list):
                        if card.get("card_type") == "ResponsePlan":
                            return self._unpack_card(card)
        except Exception as exc:
            logger.warning(
                "[commander] Failed to fetch ResponsePlan (%s)",
                type(exc).__name__,
            )
        return None

    async def _fetch_latest_card(self, incident_id: str, card_type: str) -> dict | None:
        """Fetch the latest confirmed card of a given type from Gateway."""
        try:
            submission_key = os.getenv(
                "COMMANDER_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GATEWAY_URL}/api/incidents/{incident_id}/cards",
                    headers={
                        "X-Agent-Key": submission_key,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    cards = resp.json()
                    card_list = cards if isinstance(cards, list) else cards.get("cards", [])
                    for card in reversed(card_list):
                        if card.get("card_type") == card_type:
                            return self._unpack_card(card)
        except Exception as exc:
            logger.warning(
                "[commander] Failed to fetch %s (%s)",
                card_type,
                type(exc).__name__,
            )
        return None


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

async def create_commander_agent():
    """Create the Commander agent on the Gateway-owned incident-room runtime."""
    config = MODELS["commander"]

    commander_agent_id = os.getenv("COMMANDER_AGENT_ID", "")
    commander_api_key = get_agent_api_key("commander")

    required_vars = {
        "COMMANDER_AGENT_ID": commander_agent_id,
        "SAFETY_REVIEWER_AGENT_ID": os.getenv("SAFETY_REVIEWER_AGENT_ID", ""),
        "OPERATOR_AGENT_ID": os.getenv("OPERATOR_AGENT_ID", ""),
        "COMMANDER_API_KEY": commander_api_key,
        "RECORDER_AGENT_ID": os.getenv("RECORDER_AGENT_ID", ""),
    }
    submission_key = os.getenv(
        "COMMANDER_SUBMISSION_KEY", os.getenv("GATEWAY_SECRET", ""),
    )
    if not submission_key:
        required_vars["COMMANDER_SUBMISSION_KEY or GATEWAY_SECRET"] = ""

    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        raise RuntimeError(
            f"Commander agent cannot start: missing required env vars: "
            f"{', '.join(missing)}. Set them in .env before starting."
        )
    logger.info("[commander] Startup validation passed — all required IDs configured")

    preprocessor = CommanderPreprocessor(
        commander_agent_id=commander_agent_id,
        commander_api_key=commander_api_key,
    )

    return LocalRoomAgent(
        role="commander",
        agent_id=commander_agent_id,
        agent_key=commander_api_key,
        preprocessor=preprocessor,
        on_agent_input=run_local_commander,
        framework="Local Room + Qwen",
        model=config.model,
    )


async def main():
    logging.basicConfig(level=logging.INFO)
    await run_with_supervisor(create_commander_agent, "commander")


if __name__ == "__main__":
    asyncio.run(main())

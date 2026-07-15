"""YITING Diagnosis Agent — local incident-room runtime + Qwen.

Investigates incidents by querying victim-app evidence endpoints via local tools.
Computes evidence_strength via deterministic aggregation of LLM-judged
relevance. Submits sealed Assessment via Gateway.

Architecture:
  - DiagnosisPreprocessor: thin validator (sender, seal, Pydantic, reject suppress)
  - Stores trusted per-incident context for tool callbacks
  - LocalRoomAgent invokes the Qwen-assisted diagnosis callback after acceptance
  - Tools use CustomToolDef: tuple[BaseModel, Callable]
  - Tool names derived by get_custom_tool_name: strips "Input", lowercases
  - submit_assessment callback: deterministic evidence_strength + severity + saga

Tool contract (local runtime):
  - additional_tools: list[CustomToolDef] = list[tuple[type[BaseModel], Callable]]
  - execute_custom_tool: model, func = tool; validated = model.model_validate(args); func(validated)
  - Callbacks receive a VALIDATED PYDANTIC MODEL, not **kwargs
  - Tool names: QueryMetrics → "querymetrics", SubmitAssessment → "submitassessment"

Honest claims:
  - "Qwen-backed": Qwen synthesizes advisory diagnosis text when credentials are set
  - "Deterministic evidence_strength": deterministic aggregation of LLM-judged relevance
  - "Deterministic severity": from impact metrics, not LLM-decided
  - "has_seal_fields": structural pre-filter, not cryptographic proof
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from shared.card_intake import (
    derive_idempotency_key,
    extract_sealed_card,
    has_seal_fields,
)
from shared.config import (
    ACTIVE_INCIDENTS,
    MODELS,
    get_provider_settings,
    get_agent_api_key,
)
from shared.context_restore import (
    challenge_already_answered,
    count_challenge_verdicts,
    fetch_confirmed_cards,
    latest_card_of_type,
    should_skip_terminal_incident,
)
from shared.evidence import compute_evidence_strength
from shared.models import Assessment, TriageDecision, Verdict
from shared.incident_room import IncidentRoomClient
from shared.replay_guard import should_skip_stale_card, should_skip_stale_chatter
from shared.submission_client import SubmissionClient, SubmissionError, format_card_message
from shared.local_room_runtime import LocalDefaultPreprocessor, LocalRoomAgent
from shared.qwen_reasoning import ask_qwen_json, bounded_text
from shared.supervisor import run_with_supervisor

logger = logging.getLogger("yiting.diagnosis")

# Gateway URL for SubmissionClient
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")

# Victim app URL for evidence queries
VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://localhost:9000")


# ---------------------------------------------------------------------------
# Trusted per-incident context (populated by preprocessor, consumed by tools)
# ---------------------------------------------------------------------------

@dataclass
class IncidentContext:
    """Trusted context for an incident, populated by the preprocessor.

    Tool callbacks read from this — never from model-supplied values
    for sensitive fields (room_id, room_message_id, etc.).
    """
    incident_id: str
    alert_id: str
    room_id: str
    room_message_id: str
    source_card_hash: str
    triage_decision_raw: dict
    # room message created_at for freshness (if available), else receipt time
    alert_timestamp: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    # Tool results cached here (source-of-truth for anomaly_detected)
    tool_results: dict[str, dict] = field(default_factory=dict)
    tools_completed: set[str] = field(default_factory=set)
    submitted: bool = False
    revision: int = 1
    challenge_request: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Module-level trusted context store, keyed by incident_id
_trusted_context: dict[str, IncidentContext] = {}

# Rooms where Diagnosis has already published its sealed Assessment.
# Non-card messages in these rooms are silently consumed (anti-chatter-loop).
_handoff_rooms: set[str] = set()

# Shared httpx client for victim-app queries (avoid per-call leaks)
_http_client: httpx.AsyncClient | None = None

# Required evidence tools before submission — ALL four sources must be queried.
# metrics: needed for severity derivation (error_rate, latency_p99)
# sentry: error logs for root cause
# deploys: temporal correlation
# uptime: uptime_pct for P1 threshold
# Prompt instructions are NOT deterministic enforcement — this is.
REQUIRED_TOOLS = frozenset({"metrics", "sentry", "deploys", "uptime"})


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create shared httpx client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


# ---------------------------------------------------------------------------
# Severity derivation — from IMPACT metrics, NOT evidence confidence
# ---------------------------------------------------------------------------

def derive_severity(
    metrics: dict,
    uptime: dict,
) -> str:
    """Derive severity from impact signals, NOT evidence_strength.

    Evidence strength = "How strongly is the hypothesis supported?"
    Severity = "How damaging is the incident?"

    Source: tool-cached results from victim-app, not LLM-judged.

    Args:
        metrics: From ctx.tool_results["metrics"] (victim-app /api/v1/metrics)
        uptime: From ctx.tool_results["uptime"] (victim-app /api/v1/uptime)
    """
    error_rate = metrics.get("error_rate", 0.0)
    p99_latency_ms = metrics.get("latency_p99", 0)
    uptime_pct = uptime.get("uptime_percentage", 100.0)

    if error_rate >= 25.0 or uptime_pct < 95.0:
        return "P1"  # Major outage
    elif error_rate >= 10.0 or p99_latency_ms >= 5000:
        return "P2"  # Significant degradation
    elif error_rate >= 2.0 or p99_latency_ms >= 2000:
        return "P3"  # Minor degradation
    else:
        return "P4"  # Informational


# ---------------------------------------------------------------------------
# Tool Input Models (Pydantic) — local-runtime CustomToolDef contract
#
# local-runtime derives tool names via get_custom_tool_name:
#   strips "Input" suffix, lowercases → QueryMetrics → "querymetrics"
# Callbacks receive VALIDATED PYDANTIC MODEL, not **kwargs.
# ---------------------------------------------------------------------------

class QueryMetrics(BaseModel):
    """Query system metrics for an incident from the monitored service."""
    incident_id: str = Field(description="The incident identifier to query metrics for")


class QueryErrors(BaseModel):
    """Query recent error logs for an incident from the monitored service."""
    incident_id: str = Field(description="The incident identifier to query errors for")


class QueryDeploys(BaseModel):
    """Query recent deployment history for an incident."""
    incident_id: str = Field(description="The incident identifier to query deploys for")


class QueryUptime(BaseModel):
    """Query uptime/availability data for an incident."""
    incident_id: str = Field(description="The incident identifier to query uptime for")


class SubmitAssessment(BaseModel):
    """Submit the final diagnostic assessment for an incident.

    MUST be called after querying evidence tools. The assessment will be
    submitted to Gateway and published to the incident room.
    """
    incident_id: str = Field(description="The incident identifier")
    root_cause_hypothesis: str = Field(description="Root cause analysis")
    recommended_action: str = Field(description="Recommended remediation")
    blast_radius: list[str] = Field(description="List of affected systems/services")
    sentry_relevance: float = Field(ge=0.0, le=1.0, description="Error signal relevance (0.0-1.0)")
    metrics_relevance: float = Field(ge=0.0, le=1.0, description="Metric signal relevance (0.0-1.0)")
    deploys_relevance: float = Field(ge=0.0, le=1.0, description="Deploy signal relevance (0.0-1.0)")
    uptime_relevance: float = Field(ge=0.0, le=1.0, description="Uptime signal relevance (0.0-1.0)")


# ---------------------------------------------------------------------------
# Tool Callbacks — receive validated Pydantic model (NOT **kwargs)
# ---------------------------------------------------------------------------

async def handle_query_metrics(input: QueryMetrics) -> str:
    """Query metrics from victim-app. Caches result in trusted context."""
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return json.dumps({"error": f"Unknown incident: {input.incident_id}"})

    try:
        client = await _get_http_client()
        resp = await client.get(
            f"{VICTIM_APP_URL}/api/v1/metrics",
            params={"incident_id": input.incident_id},
        )
        resp.raise_for_status()
        data = resp.json()

        async with ctx.lock:
            ctx.tool_results["metrics"] = data
            ctx.tools_completed.add("metrics")

        logger.info(
            f"[diagnosis] querymetrics for {input.incident_id}: "
            f"error_rate={data.get('error_rate')}, anomaly={data.get('anomaly_detected')}"
        )
        return json.dumps(data)
    except Exception as exc:
        logger.error(
            "[diagnosis] querymetrics failed for %s (%s)",
            input.incident_id,
            type(exc).__name__,
        )
        return json.dumps({
            "error": f"metrics query failed ({type(exc).__name__})",
            "anomaly_detected": False,
        })


async def handle_query_errors(input: QueryErrors) -> str:
    """Query errors from victim-app. Caches result under 'sentry' key."""
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return json.dumps({"error": f"Unknown incident: {input.incident_id}"})

    try:
        client = await _get_http_client()
        resp = await client.get(
            f"{VICTIM_APP_URL}/api/v1/errors/recent",
            params={"incident_id": input.incident_id},
        )
        resp.raise_for_status()
        data = resp.json()

        # Cache under "sentry" key to match shared/evidence.py SOURCES
        async with ctx.lock:
            ctx.tool_results["sentry"] = data
            ctx.tools_completed.add("sentry")

        logger.info(
            f"[diagnosis] queryerrors for {input.incident_id}: "
            f"anomaly={data.get('anomaly_detected')}"
        )
        return json.dumps(data)
    except Exception as exc:
        logger.error(
            "[diagnosis] queryerrors failed for %s (%s)",
            input.incident_id,
            type(exc).__name__,
        )
        return json.dumps({
            "error": f"error-source query failed ({type(exc).__name__})",
            "anomaly_detected": False,
        })


async def handle_query_deploys(input: QueryDeploys) -> str:
    """Query deploys from victim-app. Caches result in trusted context."""
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return json.dumps({"error": f"Unknown incident: {input.incident_id}"})

    try:
        client = await _get_http_client()
        resp = await client.get(
            f"{VICTIM_APP_URL}/api/v1/deploys/recent",
            params={"incident_id": input.incident_id},
        )
        resp.raise_for_status()
        data = resp.json()

        async with ctx.lock:
            ctx.tool_results["deploys"] = data
            ctx.tools_completed.add("deploys")

        logger.info(
            f"[diagnosis] querydeploys for {input.incident_id}: "
            f"anomaly={data.get('anomaly_detected')}"
        )
        return json.dumps(data)
    except Exception as exc:
        logger.error(
            "[diagnosis] querydeploys failed for %s (%s)",
            input.incident_id,
            type(exc).__name__,
        )
        return json.dumps({
            "error": f"deploy query failed ({type(exc).__name__})",
            "anomaly_detected": False,
        })


async def handle_query_uptime(input: QueryUptime) -> str:
    """Query uptime from victim-app. Caches result in trusted context."""
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return json.dumps({"error": f"Unknown incident: {input.incident_id}"})

    try:
        client = await _get_http_client()
        resp = await client.get(
            f"{VICTIM_APP_URL}/api/v1/uptime",
            params={"incident_id": input.incident_id},
        )
        resp.raise_for_status()
        data = resp.json()

        async with ctx.lock:
            ctx.tool_results["uptime"] = data
            ctx.tools_completed.add("uptime")

        logger.info(
            f"[diagnosis] queryuptime for {input.incident_id}: "
            f"uptime={data.get('uptime_percentage')}%, anomaly={data.get('anomaly_detected')}"
        )
        return json.dumps(data)
    except Exception as exc:
        logger.error(
            "[diagnosis] queryuptime failed for %s (%s)",
            input.incident_id,
            type(exc).__name__,
        )
        return json.dumps({
            "error": f"uptime query failed ({type(exc).__name__})",
            "anomaly_detected": False,
        })


async def handle_submit_assessment(input: SubmitAssessment) -> str:
    """Submit the final Assessment. Deterministic code owns scoring + saga.

    This callback:
    1. Validates incident_id in trusted context
    2. Requires at least metrics in tools_completed (for severity)
    3. Reads anomaly_detected from tool-cached results (NOT from Qwen)
    4. Uses Qwen-supplied relevance_scores only
    5. Computes evidence_strength via shared/evidence.py
    6. Derives severity from impact metrics
    7. Runs prepare → recruit → publish @mention → confirm saga
    """
    ctx = _trusted_context.get(input.incident_id)
    if ctx is None:
        return f"Error: unknown incident {input.incident_id}. Cannot submit assessment."

    async with ctx.lock:
        if ctx.submitted:
            # _handle_challenge() resets submitted=False before re-investigation,
            # so this guard only blocks true duplicates (not challenge re-entries).
            return f"Assessment already submitted for {input.incident_id}."

        # --- Require at least metrics (needed for severity) ---
        missing = REQUIRED_TOOLS - ctx.tools_completed
        if missing:
            return (
                f"Error: required evidence tools not yet called: {missing}. "
                f"Query them first before submitting assessment."
            )

        # --- Build signals from tool-cached results (NOT from Qwen) ---
        signals: dict[str, Any] = {}
        relevance_map = {
            "sentry": input.sentry_relevance,
            "metrics": input.metrics_relevance,
            "deploys": input.deploys_relevance,
            "uptime": input.uptime_relevance,
        }
        for source_key in ("sentry", "metrics", "deploys", "uptime"):
            tool_data = ctx.tool_results.get(source_key, {})
            signals[source_key] = {
                "anomaly_detected": tool_data.get("anomaly_detected", False),
                "relevance_score": max(0.0, min(1.0, relevance_map[source_key])),
            }

        # Temporal correlation from deploy data
        deploys_data = ctx.tool_results.get("deploys", {})
        # deploy_to_error_gap_minutes lives inside deploys[0], not top-level
        gap = deploys_data.get("deploy_to_error_gap_minutes")
        if gap is None:
            deploys_list = deploys_data.get("deploys", [])
            if deploys_list and isinstance(deploys_list, list):
                gap = deploys_list[0].get("deploy_to_error_gap_minutes")
        if gap is not None:
            signals["deploy_to_error_gap_minutes"] = gap

        # Freshness from room message timestamp (when TriageDecision was posted),
        # NOT Diagnosis receipt time. Falls back to receipt time if unavailable.
        freshness = (time.time() - ctx.alert_timestamp) / 60.0
        signals["freshness_minutes"] = freshness

        # --- Deterministic evidence_strength ---
        evidence_strength = compute_evidence_strength(
            signals, input.root_cause_hypothesis,
        )

        # --- Deterministic severity from IMPACT metrics ---
        # uptime from ctx.tool_results["uptime"], NOT from metrics
        metrics_data = ctx.tool_results.get("metrics", {})
        uptime_data = ctx.tool_results.get("uptime", {})
        severity = derive_severity(metrics_data, uptime_data)

        # --- Build Assessment card ---
        assessment = Assessment(
            incident_id=input.incident_id,
            severity=severity,
            evidence_strength=round(evidence_strength, 4),
            blast_radius=input.blast_radius or [],
            root_cause_hypothesis=input.root_cause_hypothesis,
            recommended_action=input.recommended_action,
            revision=ctx.revision,
            evidence={
                "signals": {
                    k: v for k, v in signals.items()
                    if isinstance(v, dict)
                },
                "tools_completed": sorted(ctx.tools_completed),
                "relevance_scores": {
                    "sentry": input.sentry_relevance,
                    "metrics": input.metrics_relevance,
                    "deploys": input.deploys_relevance,
                    "uptime": input.uptime_relevance,
                },
                "temporal_gap_minutes": gap,
                "freshness_minutes": round(freshness, 1),
                "challenge_response": ctx.challenge_request,
            },
        )

        # --- SubmissionClient saga ---
        try:
            submission_key = os.getenv("DIAGNOSIS_SUBMISSION_KEY", "")
            idem_key = derive_idempotency_key(
                "diagnosis", ctx.room_message_id, ctx.source_card_hash,
            )

            async with SubmissionClient(
                gateway_url=GATEWAY_URL,
                agent_key=submission_key,
            ) as sc:
                # 1. Prepare — with bounded state retry for publish-before-confirm race.
                # Triage flow: prepare → recruit Diagnosis → publish → confirm.
                # Diagnosis can receive the published TriageDecision BEFORE Triage
                # calls confirm(), so Gateway may still be at DETECTED (not TRIAGED).
                # Gateway returns 409 ("wrong state") → we retry with backoff.
                STATE_RETRY_DELAYS = [0.5, 1.0, 2.0, 3.0]  # max wait ~3.5s (last delay unused)
                prepared = None
                for attempt, delay in enumerate(STATE_RETRY_DELAYS):
                    try:
                        prepared = await sc.prepare(assessment, idempotency_key=idem_key)
                        break  # Success
                    except SubmissionError as e:
                        if e.status_code == 409 and attempt < len(STATE_RETRY_DELAYS) - 1:
                            logger.warning(
                                f"[diagnosis] prepare() got 409 (state race) on attempt "
                                f"{attempt + 1}/{len(STATE_RETRY_DELAYS)}. Waiting {delay}s "
                                f"for Triage to confirm TRIAGED..."
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise  # Non-409 or final attempt → propagate

                if prepared is None:
                    raise RuntimeError("[diagnosis] prepare() failed after all retries")

                publish_room = prepared.room_id or ctx.room_id
                sealed_message = format_card_message(prepared.sealed_card)

                # 2. Recruit Safety Reviewer BEFORE publishing
                reviewer_id = os.getenv("SAFETY_REVIEWER_AGENT_ID", "")
                if not reviewer_id:
                    raise RuntimeError(
                        "[diagnosis] Cannot recruit: SAFETY_REVIEWER_AGENT_ID "
                        "not configured."
                    )

                room_client = IncidentRoomClient(
                    sender_id=os.getenv("DIAGNOSIS_AGENT_ID", "diagnosis"),
                    sender_role="diagnosis",
                )

                try:
                    await room_client.add_participant(
                        publish_room,
                        reviewer_id,
                        role="safety_reviewer",
                        display_name="Safety Reviewer",
                    )
                    logger.info(
                        f"[diagnosis] Recruited Safety Reviewer "
                        f"{reviewer_id[:12]}... into room {publish_room[:12]}..."
                    )

                    # 3. Publish Assessment @mentioning Safety Reviewer
                    message_id = await room_client.post_message(
                        publish_room,
                        sealed_message,
                        mentions=[reviewer_id],
                        metadata={
                            "publisher": "diagnosis",
                            "card_hash": prepared.card_hash,
                        },
                    )
                finally:
                    await room_client.aclose()

                # 4. Confirm (TRIAGED → ASSESSED)
                confirm = await sc.confirm(
                    submission_id=prepared.submission_id,
                    incident_id=prepared.incident_id,
                    card_hash=prepared.card_hash,
                    message_id=message_id,
                    room_id=publish_room,
                )

                logger.info(
                    f"[diagnosis] Assessment confirmed: "
                    f"incident={input.incident_id}, severity={severity}, "
                    f"evidence_strength={evidence_strength:.3f}, "
                    f"state={confirm.new_state}"
                )

            ctx.submitted = True
            # Mark room for post-handoff silence (anti-chatter-loop).
            _handoff_rooms.add(ctx.room_id)
            logger.info(
                f"[diagnosis] Marked room {ctx.room_id[:12]}... for "
                f"post-handoff silence (incident {input.incident_id})"
            )
            return (
                f"Assessment submitted successfully for {input.incident_id}. "
                f"Severity: {severity}, Evidence Strength: {evidence_strength:.2f}. "
                f"Safety Reviewer has been recruited and will review. "
                f"YOUR WORK IS DONE — do NOT reply, do NOT explain, do NOT "
                f"send any follow-up message. STOP NOW."
            )

        except Exception as exc:
            logger.error(
                "[diagnosis] Assessment submission failed (%s)",
                type(exc).__name__,
            )
            return f"Error submitting assessment ({type(exc).__name__})"


def _root_cause_from_evidence(ctx: IncidentContext) -> tuple[str, str, list[str]]:
    """Build a compact diagnosis from trusted evidence tool results."""
    metrics = ctx.tool_results.get("metrics", {})
    errors = ctx.tool_results.get("sentry", {})
    deploys = ctx.tool_results.get("deploys", {})
    uptime = ctx.tool_results.get("uptime", {})

    service = (
        metrics.get("service")
        or errors.get("service")
        or deploys.get("service")
        or uptime.get("service")
        or "affected-service"
    )
    parts: list[str] = []
    if deploys.get("anomaly_detected"):
        deploy_bits = ["recent deploy correlation"]
        deploy_blob = json.dumps(deploys, default=str).lower()
        for key in ("deployer", "version", "service"):
            value = deploys.get(key)
            if value:
                deploy_bits.append(f"{key}={value}")
        if "dependen" in deploy_blob:
            deploy_bits.append("release includes dependency version changes")
        if "review" in deploy_blob:
            deploy_bits.append("review status flagged")
        parts.append(" ".join(deploy_bits))
    if errors.get("anomaly_detected"):
        error_bits = ["error spike"]
        error_blob = json.dumps(errors, default=str).lower()
        for signal, phrase in (("timeout", "timeout signatures in the error stream"),
                               ("null", "null-reference failures in the error stream")):
            if signal in error_blob:
                error_bits.append(phrase)
        parts.append(" ".join(error_bits))
    if metrics.get("anomaly_detected"):
        # Document the salient verified signals by name so the sealed
        # assessment records what was actually observed, not just a summary.
        signal_bits = []
        for key in ("error_rate", "latency_p99", "saturation_percentage",
                    "rate_limit_utilization", "slow_query_p99",
                    "db_pool_utilization", "waiting_requests",
                    "long_running_queries", "heap_utilization",
                    "heap_growth_mb_per_minute", "gc_pause_p99_ms",
                    "certificate_hours_remaining", "failed_requests",
                    "queued_requests"):
            value = metrics.get(key)
            if value not in (None, "", 0, 0.0):
                signal_bits.append(f"{key}={value}")
        parts.append("metric anomaly " + " ".join(signal_bits or ["detected"]))
    if uptime.get("anomaly_detected"):
        parts.append(f"availability degradation uptime={uptime.get('uptime_percentage', '?')}")
    if not parts:
        parts.append("no strong anomaly across the four evidence sources")

    root_cause = f"{service}: " + "; ".join(parts)
    # Branch on structured evidence signals, never on substrings of the
    # composed text above: "latency_p99=" appears in every metric-anomaly
    # string regardless of fault family, so text matching misroutes.
    saturation = any(
        float(metrics.get(key) or 0) >= threshold
        for key, threshold in (
            ("saturation_percentage", 80.0),
            ("rate_limit_utilization", 90.0),
            ("db_pool_utilization", 90.0),
        )
    )
    leaking = (
        float(metrics.get("heap_utilization") or 0) >= 85.0
        or float(metrics.get("gc_pause_p99_ms") or 0) >= 500.0
    )
    recommended_action = "Use the least-risk remediation matching the verified root cause."
    if deploys.get("anomaly_detected"):
        recommended_action = "Rollback or revise the correlated deployment."
    elif metrics.get("anomaly_detected") and leaking:
        recommended_action = (
            "Restart the affected service to clear the leaking process, then "
            "monitor heap growth."
        )
    elif metrics.get("anomaly_detected") and saturation:
        recommended_action = "Scale up replicas/capacity to relieve the measured saturation."
    elif errors.get("anomaly_detected"):
        recommended_action = (
            "Restart the affected service and verify error rates recover; add "
            "replicas if queued traffic stays above capacity."
        )
    elif uptime.get("anomaly_detected"):
        recommended_action = "Restore service health and verify availability."

    blast_radius = [service]
    return root_cause[:600], recommended_action[:400], blast_radius


def _relevance_from_tool(data: dict) -> float:
    return 0.9 if data.get("anomaly_detected") else 0.25


async def run_local_diagnosis(event) -> None:
    """Run Diagnosis without an external adapter after preprocessor acceptance."""
    payload = getattr(event, "payload", None)
    content = getattr(payload, "content", "") if payload else ""
    card = extract_sealed_card(content)
    if not card:
        return
    card_type = card.get("card_type")
    if card_type == "TriageDecision":
        incident_id = card.get("incident_id", "")
    elif card_type == "Verdict" and card.get("decision") == "CHALLENGE":
        incident_id = card.get("incident_id", "")
    else:
        return

    ctx = _trusted_context.get(incident_id)
    if ctx is None or ctx.submitted:
        return

    await handle_query_metrics(QueryMetrics(incident_id=incident_id))
    await handle_query_errors(QueryErrors(incident_id=incident_id))
    await handle_query_deploys(QueryDeploys(incident_id=incident_id))
    await handle_query_uptime(QueryUptime(incident_id=incident_id))

    root_cause, recommended_action, blast_radius = _root_cause_from_evidence(ctx)
    qwen = await ask_qwen_json(
        role="diagnosis",
        system=(
            "You are Chen Ming, the Diagnosis agent. Synthesize the trusted "
            "evidence into a concise root-cause hypothesis and recommended "
            "remediation. Name the primary failing signal the tool_results "
            "actually show (deploy correlation, capacity saturation, memory "
            "leak, error spike, expiry) instead of a generic dependency "
            "narrative; never attribute failure to an upstream or downstream "
            "dependency unless the evidence explicitly shows one failing. "
            "When the alert's own remediation hint is consistent with the "
            "evidence, prefer it. Do not invent evidence and do not decide "
            "severity."
        ),
        user={
            "incident_id": incident_id,
            "challenge_request": ctx.challenge_request,
            "tool_results": ctx.tool_results,
            "deterministic_baseline": {
                "root_cause_hypothesis": root_cause,
                "recommended_action": recommended_action,
                "blast_radius": blast_radius,
            },
            "expected_json_keys": [
                "root_cause_hypothesis",
                "recommended_action",
                "blast_radius",
            ],
        },
    )
    if qwen:
        root_cause = bounded_text(qwen.get("root_cause_hypothesis"), max_len=600) or root_cause
        recommended_action = (
            bounded_text(qwen.get("recommended_action"), max_len=400)
            or recommended_action
        )
        if isinstance(qwen.get("blast_radius"), list):
            qwen_radius = [
                item.strip()[:80]
                for item in qwen["blast_radius"]
                if isinstance(item, str) and item.strip()
            ]
            if qwen_radius:
                blast_radius = qwen_radius[:5]
    assessment = SubmitAssessment(
        incident_id=incident_id,
        root_cause_hypothesis=root_cause,
        recommended_action=recommended_action,
        blast_radius=blast_radius,
        sentry_relevance=_relevance_from_tool(ctx.tool_results.get("sentry", {})),
        metrics_relevance=_relevance_from_tool(ctx.tool_results.get("metrics", {})),
        deploys_relevance=_relevance_from_tool(ctx.tool_results.get("deploys", {})),
        uptime_relevance=_relevance_from_tool(ctx.tool_results.get("uptime", {})),
    )
    result = await handle_submit_assessment(assessment)
    logger.info("[diagnosis] Local diagnosis result: %s", result)


# ---------------------------------------------------------------------------
# Diagnosis Preprocessor (thin: validate → store context → delegate)
# ---------------------------------------------------------------------------

class DiagnosisPreprocessor:
    """Thin preprocessor for the Diagnosis agent.

    Intercepts TriageDecision(route) messages from incident room. Validates sender
    (must be Triage), checks seal fields, Pydantic-validates, rejects
    suppress decisions, stores trusted per-incident context, and delegates
    to the local runtime for tool orchestration.

    SDK contract: process(ctx, event, **kwargs) → AgentInput | None
    - Return AgentInput → local runtime invokes the diagnosis callback
    - Return None → event consumed silently
    """

    def __init__(
        self,
        *,
        diagnosis_agent_id: str,
        diagnosis_api_key: str,
    ):
        self._diagnosis_agent_id = diagnosis_agent_id
        self._diagnosis_api_key = diagnosis_api_key
        self._triage_agent_id = os.getenv("TRIAGE_AGENT_ID", "")
        self._safety_reviewer_agent_id = os.getenv("SAFETY_REVIEWER_AGENT_ID", "")
        self._default_preprocessor = None
        self._boot_epoch = time.time()

    async def _ensure_default(self):
        """Lazily import and create DefaultPreprocessor."""
        if self._default_preprocessor is None:
            self._default_preprocessor = LocalDefaultPreprocessor()

    async def process(self, ctx, event, **kwargs):
        """Process a room event.

        Intercepts TriageDecision(route) → stores context → delegates to adapter.
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

        # room_id lives on the EVENT, not the payload (incident room 1.0)
        room_id = getattr(event, "room_id", "") or ""

        # room message ID for idempotency derivation
        room_message_id = getattr(payload, "id", "") or ""

        # Ignore own messages
        if sender_id == self._diagnosis_agent_id:
            return None

        # Try to extract a TriageDecision
        card_data = extract_sealed_card(content)
        if not card_data:
            # No sealed card — post-handoff silence check.
            # If Assessment was already submitted for this room, silently
            # consume non-card messages to prevent chatter loops.
            if room_id and room_id in _handoff_rooms:
                logger.debug(
                    f"[diagnosis] Post-handoff silence: consuming non-card "
                    f"message in room {room_id[:12]}..."
                )
                return None

            # Check freshness for non-sealed chatter
            inserted_at = getattr(payload, "inserted_at", None)
            if should_skip_stale_chatter(str(inserted_at) if inserted_at else None, self._boot_epoch, "diagnosis"):
                return None
            return await self._default_preprocessor.process(ctx, event, **kwargs)

        card_type = card_data.get("card_type")

        # ---- Handle Verdict(CHALLENGE) from Safety Reviewer ----
        if card_type == "Verdict":
            return await self._handle_challenge(
                card_data, sender_id, sender_type, room_id,
                room_message_id, ctx, event, **kwargs,
            )

        if card_type != "TriageDecision":
            # Not a TriageDecision or Verdict — silent consume if sealed
            if has_seal_fields(card_data):
                logger.info(
                    f"[diagnosis] Silently consuming unsupported sealed "
                    f"card {card_type} for routing"
                )
                return None
            # Card-shaped but no seal fields — reject + log
            if card_type:
                logger.warning(
                    f"[diagnosis] Card-shaped payload missing seal fields "
                    f"(type={card_type}) — rejected"
                )
                return None
            # Non-card content — pass through
            return await self._default_preprocessor.process(ctx, event, **kwargs)

        # ----- Sender Validation -----
        if sender_type != "Agent":
            logger.warning(
                f"[diagnosis] REJECTED TriageDecision from non-agent "
                f"sender_type={sender_type!r}"
            )
            return None

        if not self._triage_agent_id:
            logger.error(
                "[diagnosis] REJECTED TriageDecision: TRIAGE_AGENT_ID not configured. "
                "Cannot verify sender identity."
            )
            return None

        if sender_id != self._triage_agent_id:
            logger.warning(
                f"[diagnosis] REJECTED TriageDecision from untrusted agent "
                f"{sender_id!r} — expected Triage {self._triage_agent_id!r}"
            )
            return None

        # ----- Seal Field Check -----
        if not has_seal_fields(card_data):
            return None

        # ----- Active Incident Allowlist (credit protection) -----
        incident_id_for_guard = card_data.get("incident_id", "")
        if ACTIVE_INCIDENTS and incident_id_for_guard not in ACTIVE_INCIDENTS:
            logger.info(f"[diagnosis] Skipping non-active incident {incident_id_for_guard}")
            return None

        # ----- Stale Card Guard (cost optimization) -----
        card_seq = card_data.get("sequence_number")
        if incident_id_for_guard and await should_skip_stale_card(incident_id_for_guard, card_seq, "diagnosis"):
            return None
        if incident_id_for_guard and await should_skip_terminal_incident(incident_id_for_guard, role="diagnosis"):
            return None

        # ----- Pydantic Validation -----
        try:
            validated = TriageDecision(**card_data)
        except Exception as exc:
            logger.warning(
                "[diagnosis] TriageDecision validation failed (%s)",
                type(exc).__name__,
            )
            return None

        # ----- Reject suppress (defense-in-depth) -----
        if validated.decision == "suppress":
            logger.info(
                f"[diagnosis] Ignoring TriageDecision(suppress) for "
                f"{validated.incident_id}"
            )
            return None

        # ----- Reject duplicate (active OR already submitted) -----
        # Challenge re-entry is handled by _handle_challenge() which receives
        # Verdict(CHALLENGE) via the card-type router, not this TriageDecision path.
        incident_id = validated.incident_id
        existing = _trusted_context.get(incident_id)
        if existing is not None:
            if existing.submitted:
                logger.warning(
                    f"[diagnosis] Redelivered TriageDecision for already-submitted "
                    f"incident {incident_id} — ignoring (prevents duplicate Assessment)"
                )
            else:
                logger.warning(
                    f"[diagnosis] Duplicate TriageDecision for active incident "
                    f"{incident_id} — ignoring"
                )
            return None

        # ------------------------------------------------------------------
        # CHALLENGE re-entry: If the incoming message is a Verdict(CHALLENGE)
        # from Safety Reviewer, reset context for re-investigation.
        # ------------------------------------------------------------------
        # (This block is never reached for TriageDecisions — it's a fallback
        # for when the card_type check above redirects to the Verdict handler.)
        # The actual CHALLENGE handler is below, after the TriageDecision path.

        # Extract room message timestamp for freshness calculation.
        # Local room payloads use inserted_at: str (ISO 8601), not created_at.
        msg_inserted_at = getattr(payload, "inserted_at", None)
        if msg_inserted_at is not None:
            try:
                # inserted_at is an ISO 8601 string (e.g. "2026-06-13T14:00:00Z")
                # Python 3.11+ fromisoformat handles Z suffix natively.
                alert_ts = datetime.fromisoformat(str(msg_inserted_at)).timestamp()
            except (ValueError, TypeError):
                alert_ts = time.time()
        else:
            alert_ts = time.time()

        _trusted_context[incident_id] = IncidentContext(
            incident_id=incident_id,
            alert_id=validated.alert_id,
            room_id=room_id,
            room_message_id=room_message_id,
            source_card_hash=card_data.get("card_hash", ""),
            triage_decision_raw=card_data,
            alert_timestamp=alert_ts,
        )

        logger.info(
            f"[diagnosis] Accepted TriageDecision(route) for {incident_id}. "
        f"Context stored. Delegating to local Qwen investigation."
        )

        # ----- Delegate to local incident-room runtime -----
        return await self._default_preprocessor.process(ctx, event, **kwargs)

    async def _handle_challenge(
        self, card_data: dict, sender_id: str, sender_type: str,
        room_id: str, room_message_id: str, ctx, event, **kwargs,
    ):
        """Handle Verdict(CHALLENGE) from Safety Reviewer.

        Validates sender, checks that an Assessment was previously submitted,
        resets tool results, increments revision, and re-delegates locally
        for re-investigation.
        """
        # Sender validation: only Safety Reviewer may CHALLENGE (fail-closed)
        if sender_type != "Agent":
            logger.warning(
                f"[diagnosis] REJECTED Verdict from non-agent "
                f"sender_type={sender_type!r}"
            )
            return None

        if not self._safety_reviewer_agent_id:
            logger.warning(
                "[diagnosis] REJECTED CHALLENGE — SAFETY_REVIEWER_AGENT_ID "
                "not configured. Fail-closed: cannot verify sender."
            )
            return None

        if sender_id != self._safety_reviewer_agent_id:
            logger.warning(
                f"[diagnosis] REJECTED Verdict from untrusted agent "
                f"{sender_id!r} — expected Safety Reviewer "
                f"{self._safety_reviewer_agent_id!r}"
            )
            return None

        # Pydantic validation
        try:
            verdict = Verdict(**card_data)
        except Exception as exc:
            logger.warning(
                "[diagnosis] Verdict validation failed (%s)",
                type(exc).__name__,
            )
            return None

        # Only process CHALLENGE decisions
        if verdict.decision != "CHALLENGE":
            logger.info(
                f"[diagnosis] Received Verdict({verdict.decision}) for "
                f"{verdict.incident_id} — not a CHALLENGE, ignoring"
            )
            return None

        incident_id = verdict.incident_id

        # ----- Active Incident Allowlist (credit protection) -----
        if ACTIVE_INCIDENTS and incident_id not in ACTIVE_INCIDENTS:
            logger.info(f"[diagnosis] Skipping CHALLENGE for non-active incident {incident_id}")
            return None

        if await should_skip_terminal_incident(incident_id, role="diagnosis"):
            return None

        submission_key = os.getenv(
            "DIAGNOSIS_SUBMISSION_KEY",
            os.getenv("GATEWAY_SECRET", ""),
        )
        confirmed_cards = await fetch_confirmed_cards(
            incident_id, agent_key=submission_key, role="diagnosis",
        )
        if confirmed_cards and challenge_already_answered(confirmed_cards, card_data):
            logger.info(
                "[diagnosis] Skipping stale CHALLENGE for %s: later Assessment "
                "revision already answers it",
                incident_id,
            )
            return None

        existing = _trusted_context.get(incident_id)

        # After a process restart the in-memory context is gone even though the
        # sealed room ledger still holds the Assessment. Rebuild from the
        # Gateway instead of dropping the CHALLENGE, which would strand the
        # room in CHALLENGED with no path forward.
        if existing is None:
            existing = await self._restore_context_from_gateway(
                incident_id, room_id, cards=confirmed_cards,
            )
            if existing is not None:
                _trusted_context[incident_id] = existing

        # CHALLENGE requires a prior submitted Assessment
        if existing is None or not existing.submitted:
            logger.warning(
                f"[diagnosis] CHALLENGE for {incident_id} but no "
                f"submitted Assessment exists — ignoring"
            )
            return None

        # Reset context for re-investigation
        async with existing.lock:
            existing.submitted = False
            existing.tool_results.clear()
            existing.tools_completed.clear()
            existing.revision += 1
            existing.challenge_request = verdict.challenge_request
            existing.room_message_id = room_message_id
            existing.source_card_hash = card_data.get("card_hash", "")

        logger.info(
            f"[diagnosis] CHALLENGE accepted for {incident_id} "
            f"(revision {existing.revision}). "
            f"Challenge: {verdict.challenge_request or 'no specific request'}. "
            f"Re-investigating."
        )

        # Re-delegate for local Qwen-assisted re-investigation
        return await self._default_preprocessor.process(ctx, event, **kwargs)

    async def _restore_context_from_gateway(
        self, incident_id: str, room_id: str, *, cards: list[dict] | None = None,
    ) -> "IncidentContext | None":
        """Rebuild IncidentContext from sealed Gateway cards after a restart.

        Mirrors the Commander restore pattern. The revision is derived from the
        count of sealed CHALLENGE Verdicts — never re-defaulted — so the
        challenge budget survives the restart. Fail-closed: no sealed
        Assessment means there is nothing to re-investigate.
        """
        if cards is None:
            submission_key = os.getenv(
                "DIAGNOSIS_SUBMISSION_KEY",
                os.getenv("GATEWAY_SECRET", ""),
            )
            cards = await fetch_confirmed_cards(
                incident_id, agent_key=submission_key, role="diagnosis",
            )
        if not cards:
            return None
        triage = latest_card_of_type(cards, "TriageDecision")
        assessment = latest_card_of_type(cards, "Assessment")
        if triage is None or assessment is None:
            return None
        challenge_count = count_challenge_verdicts(cards)
        context = IncidentContext(
            incident_id=incident_id,
            alert_id=str(triage.get("alert_id", "")),
            room_id=room_id,
            room_message_id="",       # Overwritten by _handle_challenge
            source_card_hash="",      # Overwritten by _handle_challenge
            triage_decision_raw=triage,
            # The sealed challenge that triggered this restore is already in
            # the ledger, so the pre-reset revision equals the challenge count;
            # _handle_challenge increments it for the re-investigation.
            revision=max(1, challenge_count),
            submitted=True,
        )
        logger.info(
            f"[diagnosis] Restored context for {incident_id} from Gateway "
            f"ledger (revision={context.revision}, "
            f"sealed_challenges={challenge_count})"
        )
        return context


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

async def create_diagnosis_agent():
    """Create the Diagnosis agent on the Gateway-owned incident-room runtime."""
    # Validate inexpensive configuration before starting the local runtime.
    # This makes deployment errors fail immediately and keeps startup
    # validation tests from initializing provider runtimes unnecessarily.
    diagnosis_agent_id = os.getenv("DIAGNOSIS_AGENT_ID", "")
    diagnosis_api_key = get_agent_api_key("diagnosis")
    required_vars = {
        "DIAGNOSIS_AGENT_ID": diagnosis_agent_id,
        "TRIAGE_AGENT_ID": os.getenv("TRIAGE_AGENT_ID", ""),
        "DIAGNOSIS_SUBMISSION_KEY": os.getenv("DIAGNOSIS_SUBMISSION_KEY", ""),
        "SAFETY_REVIEWER_AGENT_ID": os.getenv("SAFETY_REVIEWER_AGENT_ID", ""),
        "DIAGNOSIS_API_KEY": diagnosis_api_key,
        "DASHSCOPE_API_KEY": get_provider_settings()["qwen"]["api_key"],
        "VICTIM_APP_URL": VICTIM_APP_URL,
    }
    missing = [name for name, value in required_vars.items() if not value]
    if missing:
        raise RuntimeError(
            "Diagnosis agent cannot start: missing required env vars: "
            f"{', '.join(missing)}. Set them in .env before starting."
        )
    logger.info("[diagnosis] Startup validation passed — all required IDs configured")

    config = MODELS["diagnosis"]
    preprocessor = DiagnosisPreprocessor(
        diagnosis_agent_id=diagnosis_agent_id,
        diagnosis_api_key=diagnosis_api_key,
    )

    agent = LocalRoomAgent(
        role="diagnosis",
        agent_id=diagnosis_agent_id,
        agent_key=diagnosis_api_key,
        preprocessor=preprocessor,
        on_agent_input=run_local_diagnosis,
        framework="Local Room + Qwen",
        model=config.model,
    )

    return agent


async def main():
    logging.basicConfig(level=logging.INFO)
    await run_with_supervisor(create_diagnosis_agent, "diagnosis")


if __name__ == "__main__":
    asyncio.run(main())

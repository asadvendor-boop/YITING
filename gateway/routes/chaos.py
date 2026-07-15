"""YITING Gateway — controlled full-pipeline chaos routes.

Every supported scenario follows the same path:
  victim-app break endpoint → Recorder incident room → sealed AlertCard → agents

POST /chaos/trigger accepts an optional ``scenario_type`` (default ``deploy``).
POST /chaos/reset restores victim telemetry and removes local demo records.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .chaos_cleanup import remove_demo_incidents
from shared.config import qwen_readiness_status

router = APIRouter()
logger = logging.getLogger("gateway.chaos")

VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://127.0.0.1:9000")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
RECORDER_SUBMISSION_KEY = os.getenv("RECORDER_SUBMISSION_KEY", "")
TRIAGE_AGENT_ID = os.getenv("TRIAGE_AGENT_ID", "")
YITING_OPERATOR_TOKEN = os.getenv("YITING_OPERATOR_TOKEN", "")

SCENARIO_ENDPOINTS: dict[str, str] = {
    "deploy": "/admin/break/deploy",
    "sentry": "/admin/break/sentry",
    "latency": "/admin/break/latency",
    "db": "/admin/break/db",
    "memory": "/admin/break/memory",
    "cert": "/admin/break/cert",
}

_SCENARIO_ROOM_LABELS = {
    "deploy": "Suspicious Deploy Detected",
    "sentry": "Sentry Error Spike Detected",
    "latency": "Latency Degradation Detected",
    "db": "Database Pool Exhaustion Detected",
    "memory": "Memory Pressure Detected",
    "cert": "Certificate Expiry Warning",
}
_SOURCE_VALUES = frozenset({"sentry", "github_deploy", "uptime", "metrics"})
_SEVERITY_VALUES = frozenset({"P1", "P2", "P3", "P4", "unknown"})

# Preserve the existing single-trigger lock and 30-second cooldown.
_trigger_lock = asyncio.Lock()
_last_trigger_time: float = 0.0
_COOLDOWN_SECONDS = 30.0


class ChaosTriggerRequest(BaseModel):
    scenario_type: str = "deploy"


def _operator_error(request: Request) -> JSONResponse | None:
    """Require an explicit operator token for demo mutations."""
    if not YITING_OPERATOR_TOKEN:
        return JSONResponse(
            {"success": False, "error": "YITING_OPERATOR_TOKEN is not configured"},
            status_code=503,
        )
    supplied = request.headers.get("x-operator-token", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if not hmac.compare_digest(supplied, YITING_OPERATOR_TOKEN):
        return JSONResponse(
            {"success": False, "error": "Valid operator token is required"},
            status_code=401,
        )
    return None


def _deploy_alert_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt the deploy response without changing its behavior."""
    deploy = payload.get("deploy") or {}
    service = str(deploy.get("service") or "payment-service")
    version = str(deploy.get("version") or "unknown")
    deployer = str(deploy.get("deployer") or "unknown")
    return {
        "alert_type": "suspicious_deploy",
        "source": "github_deploy",
        "title": f"Suspicious deploy: {service} v{version} by {deployer}",
        "severity": "critical",
        "preliminary_severity": "P2",
        "service": service,
        "security_relevant": True,
        "fingerprint": f"sha256:deploy-{service}-{deployer}",
        "raw_payload": deploy,
    }


def _validate_alert_payload(
    scenario_type: str,
    victim_payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    incident_id = str(victim_payload.get("incident_id") or "").strip()
    if not incident_id:
        raise ValueError("victim response did not include incident_id")

    alert = victim_payload.get("alert")
    if not isinstance(alert, dict):
        if scenario_type != "deploy":
            raise ValueError("victim response did not include alert payload")
        alert = _deploy_alert_payload(victim_payload)

    source = str(alert.get("source") or "")
    preliminary_severity = str(alert.get("preliminary_severity") or "unknown")
    raw_payload = alert.get("raw_payload")
    if source not in _SOURCE_VALUES:
        raise ValueError("victim response included unsupported alert source")
    if preliminary_severity not in _SEVERITY_VALUES:
        raise ValueError("victim response included unsupported preliminary severity")
    if not isinstance(raw_payload, dict):
        raise ValueError("victim response raw_payload must be an object")
    if not str(alert.get("title") or "").strip():
        raise ValueError("victim response did not include alert title")
    return incident_id, alert


@router.post("/chaos/trigger")
async def chaos_trigger(
    request: Request,
    body: ChaosTriggerRequest | None = None,
):
    """Activate one scenario and seed the complete incident room agent pipeline."""
    global _last_trigger_time
    if error := _operator_error(request):
        return error

    qwen = qwen_readiness_status()
    if qwen["required"] and not qwen["ready"]:
        return JSONResponse(
            {
                "success": False,
                "error": "Live Qwen readiness failed; workflow start refused",
                "qwen": qwen,
            },
            status_code=503,
        )

    from agents.recorder import Recorder
    from shared.models import AlertCard
    from shared.submission_client import SubmissionClient, format_card_message

    scenario_type = (body.scenario_type if body else "deploy").strip().lower()
    endpoint = SCENARIO_ENDPOINTS.get(scenario_type)
    if endpoint is None:
        return JSONResponse(
            {
                "success": False,
                "error": (
                    f"Unknown scenario_type: {scenario_type}. Allowed: "
                    f"{', '.join(SCENARIO_ENDPOINTS)}"
                ),
            },
            status_code=400,
        )

    if not TRIAGE_AGENT_ID:
        return JSONResponse(
            {"success": False, "error": "TRIAGE_AGENT_ID not configured"},
            status_code=503,
        )
    if _trigger_lock.locked():
        return JSONResponse(
            {"success": False, "error": "A chaos trigger is already in progress"},
            status_code=429,
        )

    now = time.monotonic()
    if now - _last_trigger_time < _COOLDOWN_SECONDS:
        remaining = max(1, int(_COOLDOWN_SECONDS - (now - _last_trigger_time)))
        return JSONResponse(
            {"success": False, "error": f"Cooldown active — retry in {remaining}s"},
            status_code=429,
        )

    recorder = None
    victim_broken = False
    incident_id = ""

    async with _trigger_lock:
        try:
            requested_incident_id = f"INC-CHAOS-{uuid.uuid4().hex[:6].upper()}"
            async with httpx.AsyncClient(timeout=10.0) as http:
                response = await http.post(
                    f"{VICTIM_APP_URL}{endpoint}",
                    json={"incident_id": requested_incident_id},
                )
                response.raise_for_status()
                victim_payload = response.json()

            if not isinstance(victim_payload, dict):
                raise ValueError("victim response was not a JSON object")
            incident_id, alert_payload = _validate_alert_payload(
                scenario_type, victim_payload
            )

            # Cooldown starts only after victim activation succeeds, preserving
            # the proven suspicious-deploy behavior.
            _last_trigger_time = time.monotonic()
            victim_broken = True

            alert = AlertCard(
                alert_id=incident_id,
                source=alert_payload["source"],
                timestamp=datetime.now(timezone.utc),
                title=str(alert_payload["title"]),
                raw_payload=alert_payload["raw_payload"],
                fingerprint=str(
                    alert_payload.get("fingerprint")
                    or f"sha256:chaos-{scenario_type}-{incident_id}"
                ),
                preliminary_severity=alert_payload["preliminary_severity"],
                security_relevant=bool(
                    alert_payload.get("security_relevant", False)
                ),
            )

            async with SubmissionClient(
                GATEWAY_URL, agent_key=RECORDER_SUBMISSION_KEY
            ) as submission:
                prepared = await submission.prepare(
                    alert, idempotency_key=str(uuid.uuid4())
                )

                recorder = Recorder()
                room_title = (
                    f"🔴 {prepared.incident_id} — {_SCENARIO_ROOM_LABELS[scenario_type]}"
                )
                room_id = await recorder.create_room(
                    room_title,
                    incident_id=prepared.incident_id,
                )
                await recorder.add_participant(room_id, TRIAGE_AGENT_ID)

                message_id = await recorder.post_message(
                    room_id,
                    format_card_message(prepared.sealed_card),
                    [TRIAGE_AGENT_ID],
                )
                confirmed = await submission.confirm(
                    submission_id=prepared.submission_id,
                    incident_id=prepared.incident_id,
                    card_hash=prepared.card_hash,
                    message_id=message_id,
                    room_id=room_id,
                )

            return {
                "success": True,
                "scenario_type": scenario_type,
                "alert_type": alert_payload.get("alert_type"),
                "service": alert_payload.get("service"),
                "severity": alert_payload.get("severity"),
                "incident_id": prepared.incident_id,
                "room_id": room_id,
                "state": confirmed.new_state,
                "card_hash": prepared.card_hash[:24] + "...",
            }

        except Exception as exc:
            logger.error(
                "Chaos trigger failed for scenario=%s (%s)",
                scenario_type,
                type(exc).__name__,
            )
            if victim_broken and incident_id:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as http:
                        await http.post(
                            f"{VICTIM_APP_URL}/admin/scenario/{incident_id}/reset"
                        )
                except Exception as compensation_exc:
                    logger.warning(
                        "Chaos compensation failed (%s)",
                        type(compensation_exc).__name__,
                    )
            return JSONResponse(
                {"success": False, "error": "Chaos trigger failed — check server logs"},
                status_code=502,
            )
        finally:
            if recorder is not None:
                try:
                    await recorder.client.aclose()
                except Exception:
                    pass


@router.post("/chaos/reset")
async def chaos_reset(request: Request):
    """Reset victim telemetry and clear only local synthetic incident data."""
    if error := _operator_error(request):
        return error
    async with _trigger_lock:
        try:
            # Victim first: if reset fails, retain Gateway rows so an active
            # anomaly cannot disappear from the dashboard as an orphan.
            async with httpx.AsyncClient(timeout=10.0) as http:
                response = await http.post(
                    f"{VICTIM_APP_URL}/admin/scenario/reset-all"
                )
                response.raise_for_status()
                victim_result = response.json()

            cleanup = remove_demo_incidents(request.app.state.db)
            return {
                "success": True,
                "status": "reset",
                "victim_scenarios_cleared": (
                    victim_result.get("cleared", 0)
                    if isinstance(victim_result, dict)
                    else 0
                ),
                **cleanup,
            }
        except Exception as exc:
            logger.error("Chaos reset failed (%s)", type(exc).__name__)
            return JSONResponse(
                {"success": False, "error": "Demo reset failed — check server logs"},
                status_code=502,
            )

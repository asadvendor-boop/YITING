"""YITING Gateway — FastAPI application.

Central coordination service that:
- Receives controlled sandbox telemetry and demo incident signals
- Normalizes incident signals into AlertCards
- Creates Gateway-owned incident rooms and routes to agents
- Seals cards with integrity chain (seal-before-send)
- Manages incident state machine
- Provides REST API for dashboard
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import init_db
from .mcp import router as mcp_router
from .rate_limit import RateLimitMiddleware
from shared import qwen_reasoning as qwen_runtime
from shared.config import MODELS, get_qwen_api_key, get_qwen_base_url, qwen_readiness_status

logger = logging.getLogger("yiting.gateway")

# Ensure .env is loaded before any os.getenv calls in routes.
# Without this, bare `uvicorn` never reads .env, and fail-closed
# auth rejects every correctly-keyed request (safe direction,
# but maddening to debug at 2 AM).
try:
    from dotenv import load_dotenv
    load_dotenv()
    # Load approval secrets (only available on prod VM)
    try:
        load_dotenv("/etc/yiting/approval.env", override=False)
    except Exception:
        pass
except ImportError:
    pass  # python-dotenv not installed — env vars must be set externally


def _family_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = (
        " ".join(value.replace("_", " ").replace("-", " ").split())
        .strip()
        .lower()
    )
    return cleaned or None


def _alert_family(card_data: dict) -> tuple[str, str | None]:
    raw_payload = card_data.get("raw_payload")
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    family = (
        _family_label(raw_payload.get("alert_type"))
        or _family_label(raw_payload.get("scenario"))
        or _family_label(raw_payload.get("metric_name"))
        or _family_label(card_data.get("source"))
        or "unknown"
    )
    service = (
        raw_payload.get("service")
        or raw_payload.get("target_service")
        or raw_payload.get("component")
    )
    return family, str(service).strip() if service else None


def _operator_token_error(request: Request) -> JSONResponse | None:
    token = os.getenv("YITING_OPERATOR_TOKEN", "")
    if not token:
        return JSONResponse(
            {"status": "not_ready", "error": "YITING_OPERATOR_TOKEN is not configured"},
            status_code=503,
        )
    supplied = request.headers.get("x-operator-token", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if not hmac.compare_digest(supplied, token):
        return JSONResponse(
            {"status": "not_ready", "error": "Valid operator token is required"},
            status_code=401,
        )
    return None


def _response_text(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _response_id(response: Any) -> str | None:
    value = getattr(response, "id", None) or getattr(response, "_response_id", None)
    return str(value) if value else None


def _provider_request_id(response: Any) -> str | None:
    value = (
        getattr(response, "_request_id", None)
        or getattr(response, "request_id", None)
        or getattr(response, "x_request_id", None)
    )
    return str(value) if value else None


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    import logging

    db_path = getattr(app.state, "_db_path", None) or os.getenv("GATEWAY_DB_PATH", "yiting.db")
    app.state.db = init_db(db_path)
    csrf = os.getenv("APPROVAL_UI_CSRF_SECRET", "")
    if not csrf:
        logging.getLogger("gateway").warning("APPROVAL_UI_CSRF_SECRET not set — approval UI disabled")
    try:
        yield
    finally:
        app.state.db.close()


def create_app(db_path: str | None = None) -> FastAPI:
    """Factory for creating the Gateway app (used by tests with :memory:)."""
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    cors_origins = ["http://localhost:3000"]
    if public_base_url:
        cors_origins.append(public_base_url)

    new_app = FastAPI(
        title="YITING Gateway",
        description=(
            "Multi-agent incident command gateway. "
            "Coordinates a six-agent core through Gateway-owned incident rooms."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    new_app.state._db_path = db_path

    new_app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Agent-Key", "X-Operator-Token", "X-CSRF-Token"],
    )
    new_app.add_middleware(RateLimitMiddleware)

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @new_app.get("/health")
    async def health():
        """Basic health check."""
        return {"status": "ok", "service": "yiting-gateway"}

    @new_app.get("/ready")
    async def ready():
        """Production readiness check for live Qwen-backed workflows."""
        qwen = qwen_readiness_status()
        status_code = 200 if qwen["ready"] else 503
        return JSONResponse(
            {
                "status": "ready" if qwen["ready"] else "not_ready",
                "service": "yiting-gateway",
                "qwen": qwen,
            },
            status_code=status_code,
        )

    @new_app.get("/ready/qwen-live")
    async def qwen_live_ready(request: Request):
        """Operator-protected live Qwen probe for hosted proof.

        This endpoint is intentionally separate from /ready so container
        healthchecks do not spend Qwen tokens. It proves invalid credentials or
        unsupported model settings fail closed during judge smoke tests.
        """
        if error := _operator_token_error(request):
            return error

        qwen = qwen_readiness_status()
        if not qwen["ready"]:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "service": "yiting-gateway",
                    "qwen": qwen,
                    "live_probe": {"ok": False, "error": "configuration_not_ready"},
                },
                status_code=503,
            )

        if qwen_runtime.acompletion is None:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "service": "yiting-gateway",
                    "qwen": qwen,
                    "live_probe": {"ok": False, "error": "litellm_not_installed"},
                },
                status_code=503,
            )

        model = qwen_runtime.normalize_litellm_model(MODELS["operator"].model)
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                qwen_runtime.acompletion(
                    model=model,
                    api_key=get_qwen_api_key(),
                    api_base=get_qwen_base_url(),
                    messages=[
                        {
                            "role": "system",
                            "content": "Reply with one compact sentence. Do not include secrets.",
                        },
                        {
                            "role": "user",
                            "content": "YITING live Qwen readiness check: say ok.",
                        },
                    ],
                    temperature=0.0,
                    max_tokens=24,
                ),
                timeout=15.0,
            )
            ok = bool(_response_text(response).strip())
            probe = {
                "ok": ok,
                "provider": "qwen",
                "requested_model": model,
                "returned_model": str(getattr(response, "model", "") or model),
                "response_id": _response_id(response),
                "provider_request_id": _provider_request_id(response),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "usage": _usage_dict(response),
            }
        except Exception as exc:
            probe = {
                "ok": False,
                "provider": "qwen",
                "requested_model": model,
                "error_type": type(exc).__name__,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        ready_status = qwen["ready"] and probe["ok"]
        return JSONResponse(
            {
                "status": "ready" if ready_status else "not_ready",
                "service": "yiting-gateway",
                "qwen": qwen,
                "live_probe": probe,
            },
            status_code=200 if ready_status else 503,
        )

    # -----------------------------------------------------------------------
    # Dashboard REST endpoints
    # -----------------------------------------------------------------------

    @new_app.get("/incidents")
    async def list_incidents(state: str | None = None):
        """List all incidents, optionally filtered by state."""
        db = new_app.state.db
        if state:
            rows = db.execute(
                "SELECT * FROM incidents WHERE state=? ORDER BY created_at DESC",
                (state,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM incidents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    @new_app.get("/incidents/{incident_id}")
    async def get_incident(incident_id: str):
        """Get incident details including card chain."""
        from fastapi import HTTPException

        db = new_app.state.db
        incident = db.execute(
            "SELECT * FROM incidents WHERE incident_id=?",
            (incident_id,),
        ).fetchone()
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        cards = db.execute(
            "SELECT * FROM cards WHERE incident_id=? ORDER BY sequence_number ASC",
            (incident_id,),
        ).fetchall()

        return {
            "incident": dict(incident),
            "cards": [dict(c) for c in cards],
            "card_count": len(cards),
        }

    @new_app.get("/evidence/{incident_id}")
    async def get_evidence_public(incident_id: str):
        """Public evidence export: judges can verify the tamper-evident chain.

        This route is intentionally unauthenticated, read-only, and designed
        for judges/auditors to inspect the sealed incident evidence. For
        keyed production exports, use /api/export/evidence/{id} instead.
        """
        import json as _json

        from fastapi import HTTPException
        from shared.integrity import verify_chain

        db = new_app.state.db
        incident = db.execute(
            "SELECT * FROM incidents WHERE incident_id=?",
            (incident_id,),
        ).fetchone()
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

        cards = db.execute(
            "SELECT card_json, card_hash, card_type, sequence_number, published_at "
            "FROM cards WHERE incident_id=? ORDER BY sequence_number ASC",
            (incident_id,),
        ).fetchall()

        is_valid, errors = verify_chain(incident_id, db)
        persona_by_card_type = {
            "AlertCard": {
                "key": "wen_lu",
                "name": "Wen Lu",
                "role": "Evidence Recorder",
            },
            "TriageDecision": {
                "key": "lin_xun",
                "name": "Lin Xun",
                "role": "Signal Sentinel",
            },
            "Assessment": {
                "key": "chen_ming",
                "name": "Chen Ming",
                "role": "Diagnostician",
            },
            "Verdict": {
                "key": "zhou_shen",
                "name": "Zhou Shen",
                "role": "Safety Reviewer",
            },
            "ResponsePlan": {
                "key": "han_ce",
                "name": "Han Ce",
                "role": "Incident Strategist",
            },
            "StructuredApproval": {
                "key": "human_judge",
                "name": "Human Judge",
                "role": "Authorized Approver",
            },
            "PolicyAuthorization": {
                "key": "gateway_policy",
                "name": "Gateway Policy",
                "role": "Deterministic Authorization Guard",
            },
            "ActionReceipt": {
                "key": "lu_xing",
                "name": "Lu Xing",
                "role": "Remediation Operator",
            },
            "Postmortem": {
                "key": "scribe",
                "name": "Council Scribe",
                "role": "Incident Memory Archivist",
            },
        }

        public_key_rewrites = {
            "agrees_with_diagnosis": "agrees_with_chen_ming_assessment",
            "diagnosis": "chen_ming_assessment",
            "commander": "han_ce_strategy",
            "operator": "lu_xing_remediation",
            "safety_reviewer": "zhou_shen_review",
            "triage": "lin_xun_intake",
            "recorder": "wen_lu_recording",
            "scribe": "council_scribe",
        }
        public_value_rewrites = {
            "safety_reviewer": "Zhou Shen",
            "diagnosis": "Chen Ming assessment",
            "commander": "Han Ce",
            "operator": "Lu Xing",
            "triage": "Lin Xun",
            "recorder": "Wen Lu",
            "scribe": "Council Scribe",
        }

        def public_evidence_value(value):
            if isinstance(value, dict):
                return {
                    public_key_rewrites.get(key, key): public_evidence_value(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [public_evidence_value(item) for item in value]
            if isinstance(value, str):
                public_value = value
                for old, new in public_value_rewrites.items():
                    public_value = public_value.replace(old, new)
                return public_value
            return value

        parsed_cards = []
        incident_family = "unknown"
        alert_service = None
        for row in cards:
            data = _json.loads(row["card_json"])
            if row["card_type"] == "AlertCard":
                incident_family, alert_service = _alert_family(data)
            persona = persona_by_card_type.get(row["card_type"], {
                "key": "system",
                "name": "YITING Core",
                "role": "Deterministic Control Plane",
            })
            parsed_cards.append({
                "sequence": row["sequence_number"],
                "card_type": row["card_type"],
                "role": persona["key"],
                "agent": persona,
                "hash": row["card_hash"],
                "published": row["published_at"] is not None,
                "data": public_evidence_value(data),
            })
        role_sequence = [card["role"] for card in parsed_cards]
        handoffs = [
            {
                "sequence": current["sequence"],
                "from": previous["role"],
                "to": current["role"],
                "card_type": current["card_type"],
            }
            for previous, current in zip(parsed_cards, parsed_cards[1:])
            if previous["role"] != current["role"]
        ]
        challenges = [
            {
                "sequence": card["sequence"],
                "challenge_request": card["data"].get("challenge_request"),
            }
            for card in parsed_cards
            if card["card_type"] == "Verdict"
            and card["data"].get("decision") == "CHALLENGE"
        ]
        human_decisions = [
            {
                "sequence": card["sequence"],
                "decision": card["data"].get("decision"),
                "reason": card["data"].get("reason"),
            }
            for card in parsed_cards
            if card["card_type"] == "StructuredApproval"
        ]
        authorization_cards = [
            card for card in parsed_cards
            if card["card_type"] in {"StructuredApproval", "PolicyAuthorization"}
        ]
        response_plans = [
            card for card in parsed_cards if card["card_type"] == "ResponsePlan"
        ]
        action_receipts = [
            card for card in parsed_cards if card["card_type"] == "ActionReceipt"
        ]
        last_plan = response_plans[-1]["data"] if response_plans else {}
        last_receipt = action_receipts[-1]["data"] if action_receipts else {}
        planned_actions = [
            action.get("action_id")
            for action in last_plan.get("envelopes", [])
            if isinstance(action, dict)
        ]
        executed_actions = [
            action.get("action_id")
            for action in last_receipt.get("actions_taken", [])
            if isinstance(action, dict)
        ]

        return {
            "incident_id": incident_id,
            "state": incident["state"],
            "incident_family": incident_family,
            "alert_service": alert_service,
            "total_cards": len(cards),
            "chain_valid": is_valid,
            "chain_errors": errors,
            "collaboration": {
                "role_sequence": role_sequence,
                "handoffs": handoffs,
                "handoff_count": len(handoffs),
                "challenge_count": len(challenges),
                "challenges": challenges,
                "human_decision_count": len(human_decisions),
                "human_decisions": human_decisions,
                "authorization_path": (
                    authorization_cards[-1]["card_type"]
                    if authorization_cards else None
                ),
                "execution_conflict_control": {
                    "planned_actions": planned_actions,
                    "executed_actions": executed_actions,
                    "exact_match": (
                        bool(planned_actions)
                        and planned_actions == executed_actions
                    ),
                },
            },
            "cards": parsed_cards,
        }

    @new_app.get("/stats")
    async def get_stats():
        """Aggregated stats for the dashboard."""
        import json as _json

        db = new_app.state.db
        total = db.execute("SELECT COUNT(*) as cnt FROM incidents").fetchone()["cnt"]
        active = db.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE state NOT IN "
            "('EXECUTED', 'RESOLVED', 'CLOSED_FALSE_ALARM', 'SUPPRESSED')"
        ).fetchone()["cnt"]
        suppressed = db.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE state='SUPPRESSED'"
        ).fetchone()["cnt"]
        resolved = db.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE state IN "
            "('EXECUTED', 'RESOLVED')"
        ).fetchone()["cnt"]

        # ── ROI Counters ──────────────────────────────────────────────────
        # False alarms caught = CLOSED_FALSE_ALARM + SUPPRESSED
        false_alarms = db.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE state IN "
            "('CLOSED_FALSE_ALARM', 'SUPPRESSED')"
        ).fetchone()["cnt"]

        # Challenges issued = Verdict cards with decision='CHALLENGE'
        verdict_rows = db.execute(
            "SELECT card_json FROM cards WHERE card_type='Verdict'"
        ).fetchall()
        challenges = 0
        for row in verdict_rows:
            try:
                data = _json.loads(row["card_json"])
                if data.get("decision") == "CHALLENGE":
                    challenges += 1
            except (ValueError, KeyError):
                pass

        # Human decisions = StructuredApproval cards (APPROVED/REJECTED/FALSE_ALARM)
        human_decisions = db.execute(
            "SELECT COUNT(*) as cnt FROM cards WHERE card_type='StructuredApproval'"
        ).fetchone()["cnt"]

        # Avg resolution time = avg(updated_at - created_at) for EXECUTED incidents
        avg_row = db.execute(
            "SELECT AVG((julianday(updated_at) - julianday(created_at)) * 86400) "
            "as avg_secs FROM incidents WHERE state='EXECUTED'"
        ).fetchone()
        avg_resolution = round(avg_row["avg_secs"]) if avg_row["avg_secs"] else None

        return {
            "total_incidents": total,
            "active_incidents": active,
            "suppressed_incidents": suppressed,
            "resolved_incidents": resolved,
            "false_alarms_caught": false_alarms,
            "challenges_issued": challenges,
            "human_decisions": human_decisions,
            "avg_resolution_secs": avg_resolution,
        }

    # -----------------------------------------------------------------------
    # Agent heartbeat endpoints
    # -----------------------------------------------------------------------

    @new_app.post("/heartbeat")
    async def post_heartbeat(request: Request):
        """Register an agent heartbeat. Authenticated via X-Agent-Key."""
        from .auth import get_role_for_key

        agent_key = request.headers.get("X-Agent-Key", "")
        role_from_key = get_role_for_key(agent_key)
        if not role_from_key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body = await request.json()
        claimed_role = body.get("role", "")

        # Validate against known agent roles (Fix 6: no garbage rows)
        KNOWN_ROLES = {"recorder", "triage", "diagnosis", "safety_reviewer", "commander", "operator", "scribe"}
        if claimed_role not in KNOWN_ROLES:
            return JSONResponse({"error": f"unknown role: {claimed_role}"}, status_code=400)

        # Role/key binding — only gateway key can claim any role
        if role_from_key != "gateway" and role_from_key != claimed_role:
            return JSONResponse({"error": "role/key mismatch"}, status_code=403)

        db = new_app.state.db
        db.execute(
            """INSERT INTO heartbeats (
                   agent_role, agent_id, framework, model,
                   display_name, persona_title, persona_temperament, last_seen
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(agent_role) DO UPDATE SET
                   last_seen = datetime('now'),
                   agent_id = excluded.agent_id,
                   framework = excluded.framework,
                   model = excluded.model,
                   display_name = excluded.display_name,
                   persona_title = excluded.persona_title,
                   persona_temperament = excluded.persona_temperament""",
            (
                claimed_role,
                body.get("agent_id", ""),
                body.get("framework", ""),
                body.get("model", ""),
                body.get("display_name", ""),
                body.get("persona_title", ""),
                body.get("persona_temperament", ""),
            ),
        )
        db.commit()
        return {"status": "ok"}

    @new_app.get("/agent-status")
    async def get_agent_status():
        """Public: agent liveness for dashboard."""
        from datetime import datetime, timezone

        db = new_app.state.db
        rows = db.execute("SELECT * FROM heartbeats").fetchall()
        agents = []
        for r in rows:
            row = dict(r)
            try:
                last = datetime.fromisoformat(row["last_seen"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                diff = (
                    datetime.now(timezone.utc) - last
                ).total_seconds()
                row["online"] = diff < 60
            except Exception:
                row["online"] = False
            agents.append(row)
        return agents

    @new_app.get("/agent-skills")
    async def get_agent_skills():
        """Public: custom agent skill contracts for judges and dashboard."""
        from shared.skill_registry import skill_manifest

        return skill_manifest()

    # -----------------------------------------------------------------------
    # Suppression rule endpoints
    # -----------------------------------------------------------------------

    @new_app.get("/suppression-rules")
    async def get_suppression_rules(fingerprint: str | None = None):
        """Public read: get active, non-exhausted suppression rules."""
        db = new_app.state.db
        base_filter = "active=1 AND suppression_count < max_suppressions"
        if fingerprint:
            rows = db.execute(
                f"SELECT * FROM suppression_rules WHERE fingerprint=? AND {base_filter}",
                (fingerprint,),
            ).fetchall()
        else:
            rows = db.execute(
                f"SELECT * FROM suppression_rules WHERE {base_filter}"
            ).fetchall()
        return [dict(r) for r in rows]

    @new_app.post("/suppression-rules")
    async def create_suppression_rule(request: Request):
        """Create a suppression rule. Safety-reviewer or gateway only."""
        from .auth import get_role_for_key

        agent_key = request.headers.get("X-Agent-Key", "")
        role = get_role_for_key(agent_key)
        if role not in ("safety_reviewer", "gateway"):
            return JSONResponse({"error": "unauthorized"}, status_code=403)

        body = await request.json()
        fingerprint = body.get("fingerprint", "")
        if not fingerprint:
            return JSONResponse(
                {"error": "fingerprint required"}, status_code=400
            )

        db = new_app.state.db
        # Check for existing active rule with same fingerprint
        existing = db.execute(
            "SELECT id FROM suppression_rules WHERE fingerprint=? AND active=1",
            (fingerprint,),
        ).fetchone()
        if existing:
            return JSONResponse(
                {"error": "rule already exists", "rule_id": existing["id"]},
                status_code=409,
            )

        cursor = db.execute(
            """INSERT INTO suppression_rules
               (fingerprint, reason, source_incident_id, created_at, max_suppressions)
               VALUES (?, ?, ?, datetime('now'), 3)""",
            (
                fingerprint,
                body.get("reason", ""),
                body.get("source_incident_id", ""),
            ),
        )
        db.commit()
        return {"rule_id": cursor.lastrowid, "fingerprint": fingerprint, "max": 3}

    @new_app.post("/suppression-rules/{rule_id}/increment")
    async def increment_suppression(rule_id: int, request: Request):
        """Atomic increment. Triage or gateway only. 409 if exhausted."""
        from .auth import get_role_for_key

        agent_key = request.headers.get("X-Agent-Key", "")
        role = get_role_for_key(agent_key)
        if role not in ("triage", "gateway"):
            return JSONResponse({"error": "unauthorized"}, status_code=403)

        db = new_app.state.db
        # Atomic: only increment if active AND within bounds
        cursor = db.execute(
            """UPDATE suppression_rules
               SET suppression_count = suppression_count + 1
               WHERE id=? AND active=1 AND suppression_count < max_suppressions""",
            (rule_id,),
        )
        db.commit()

        if cursor.rowcount == 0:
            return JSONResponse(
                {"error": "rule exhausted or not found"}, status_code=409
            )

        return {"status": "incremented", "rule_id": rule_id}

    # -----------------------------------------------------------------------
    # Card submission routes
    # -----------------------------------------------------------------------
    from .routes.submission import router as submission_router
    new_app.include_router(submission_router, prefix="/api")

    from .routes.nonce import router as nonce_router
    new_app.include_router(nonce_router, prefix="/api")

    from .routes.authorization import router as auth_router
    new_app.include_router(auth_router, prefix="/api")

    from .routes.approve_ui import router as approve_router
    new_app.include_router(approve_router)  # No prefix — /approve/* directly

    from .routes.chaos import router as chaos_router
    new_app.include_router(chaos_router)  # No prefix — /chaos/trigger directly

    from .routes.rooms import router as rooms_router
    new_app.include_router(rooms_router, prefix="/api")

    # NOTE: Scribe/Postmortem/RESOLVED/AuditSeal are roadmap features.
    # The Platform Scribe agent observes the incident room, but its Gateway
    # integration (postmortem sealing, RESOLVED state transition, AuditSeal
    # event) is not yet wired end-to-end through incident-room publication+confirmation.
    # Removed broken /scribe/postmortem endpoint to avoid HTTP 500.
    # See README § Roadmap for planned Scribe integration.

    # -----------------------------------------------------------------------
    # Incident Room Messages (for dashboard viewer)
    # -----------------------------------------------------------------------

    @new_app.get("/room-messages/{incident_id}")
    async def get_room_messages(
        incident_id: str,
        request: Request,
    ):
        """Fetch sanitized incident-room messages for an incident (read-only).

        The endpoint removes sender IDs and active authorization material before
        returning operational messages to the dashboard.  Deployment access
        control remains the reverse proxy's responsibility.
        """
        from fastapi import HTTPException

        db = new_app.state.db
        row = db.execute(
            "SELECT room_id, room_alias_id FROM incidents WHERE incident_id=?",
            (incident_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Incident not found")

        room_id = row["room_id"] or row["room_alias_id"]
        if not room_id:
            return {"incident_id": incident_id, "messages": [], "note": "No incident room for this incident"}

        rows = db.execute(
            """
            SELECT * FROM incident_room_messages
            WHERE incident_id=? OR room_id=?
            ORDER BY id ASC
            """,
            (incident_id, room_id),
        ).fetchall()

        # Format messages for dashboard display
        formatted = []
        for msg in rows:
            sender_role = msg["sender_role"] or ""
            content = msg["content"] or ""

            # Fallback: content heuristics for messages from unknown senders
            if not sender_role:
                if "Verdict" in content or "cross-check" in content:
                    sender_role = "safety"
                elif "Triage" in content or "triage" in content:
                    sender_role = "triage"
                elif "Root Cause" in content or "assessment" in content.lower()[:100]:
                    sender_role = "diagnosis"
                elif "APPROVED" in content or "REJECTED" in content:
                    sender_role = "commander"
                elif "rollback" in content.lower() or "remediation" in content.lower():
                    sender_role = "operator"
                elif "Recorder" in content:
                    sender_role = "recorder"
                elif "Postmortem" in content or "Scribe" in content:
                    sender_role = "scribe"

            # Redact active authorization material before public display.
            import re as _re
            sanitized_content = content
            sanitized_content = _re.sub(
                r'(?i)(nonce["\s:=]+)([A-Z0-9]{6,64}|[0-9a-f-]{36})',
                r'\1[REDACTED]', sanitized_content,
            )
            sanitized_content = _re.sub(
                r'(?i)([?&]nonce=)[^&\s"`]+',
                r'\1[REDACTED]', sanitized_content,
            )
            sanitized_content = _re.sub(
                r'(?i)(authorization[_\s]*id["\s:=]+)[0-9a-f-]{36}',
                r'\1[REDACTED]', sanitized_content,
            )

            formatted.append({
                "id": msg["message_id"],
                "content": sanitized_content,
                "sender_role": sender_role,
                "sender_type": msg["sender_type"] or "Agent",
                "created_at": msg["created_at"],
            })

        return {
            "incident_id": incident_id,
            "room_id": room_id,
            "message_count": len(formatted),
            "messages": formatted,
        }

    # -----------------------------------------------------------------------
    # RunSummary — Hard baseline metrics
    # -----------------------------------------------------------------------

    @new_app.get("/stats/runsummary")
    async def get_runsummary():
        """Compute transparent, per-incident timing and collaboration metrics.

        Only confirmed/published cards participate.  A manual comparison
        baseline is optional and must be supplied through MANUAL_BASELINE_SECS;
        the API never invents or attributes an industry baseline.
        """
        import json as _json
        import os
        from datetime import datetime as _dt

        db = new_app.state.db
        incidents = db.execute(
            "SELECT incident_id, state, created_at, updated_at "
            "FROM incidents WHERE state IN "
            "('EXECUTED', 'RESOLVED', 'CLOSED_FALSE_ALARM') "
            "ORDER BY created_at DESC"
        ).fetchall()

        role_by_card_type = {
            "AlertCard": "recorder",
            "TriageDecision": "triage",
            "Assessment": "diagnosis",
            "Verdict": "safety_reviewer",
            "ResponsePlan": "commander",
            "StructuredApproval": "human_gateway",
            "PolicyAuthorization": "gateway_policy",
            "ActionReceipt": "operator",
            "Postmortem": "scribe",
        }

        runs: list[dict] = []
        total_agent_secs = 0.0
        total_resolution_secs = 0.0
        total_post_plan_secs = 0.0
        agent_secs_count = 0
        resolution_count = 0
        post_plan_count = 0
        total_challenges = 0
        total_handoffs = 0
        total_recovery_verified = 0
        total_human_interventions = 0
        total_human_rejections = 0
        total_plan_revisions = 0
        incidents_challenged = 0
        incidents_revised = 0

        def _seconds_between(start_value: str | None, end_value: str | None):
            if not start_value or not end_value:
                return None
            try:
                start_dt = _dt.fromisoformat(start_value.replace("Z", "+00:00"))
                end_dt = _dt.fromisoformat(end_value.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None
            seconds = (end_dt - start_dt).total_seconds()
            return seconds if seconds >= 0 else None

        for incident in incidents:
            incident_id = incident["incident_id"]
            cards = db.execute(
                "SELECT card_type, card_json, published_at "
                "FROM cards WHERE incident_id=? AND published_at IS NOT NULL "
                "ORDER BY sequence_number ASC",
                (incident_id,),
            ).fetchall()

            alert_time = next(
                (row["published_at"] for row in cards if row["card_type"] == "AlertCard"),
                None,
            )
            plan_time = next(
                (row["published_at"] for row in cards if row["card_type"] == "ResponsePlan"),
                None,
            )
            receipt_time = next(
                (row["published_at"] for row in reversed(cards)
                 if row["card_type"] == "ActionReceipt"),
                None,
            )
            terminal_time = receipt_time or (
                cards[-1]["published_at"] if cards else None
            )

            challenge_count = 0
            human_rejection_count = 0
            incident_family = "unknown"
            alert_service = None
            for row in cards:
                try:
                    card_data = _json.loads(row["card_json"])
                except (TypeError, ValueError):
                    logger.warning(
                        "[runsummary] Invalid %s JSON for incident=%s",
                        row["card_type"],
                        incident_id,
                    )
                    continue
                if row["card_type"] == "AlertCard":
                    incident_family, alert_service = _alert_family(card_data)
                if row["card_type"] == "Verdict":
                    if card_data.get("decision") == "CHALLENGE":
                        challenge_count += 1
                elif row["card_type"] == "StructuredApproval":
                    if card_data.get("decision") == "REJECTED":
                        human_rejection_count += 1

            card_types = [row["card_type"] for row in cards]
            roles = [role_by_card_type.get(card_type, card_type) for card_type in card_types]
            handoff_count = sum(
                1 for previous, current in zip(roles, roles[1:])
                if previous != current
            )
            response_plan_count = card_types.count("ResponsePlan")
            plan_revision_count = max(0, response_plan_count - 1)

            human_auth = db.execute(
                "SELECT 1 FROM authorizations WHERE incident_id=? "
                "AND authorization_type='human_approval' "
                "AND (consumed=1 OR status='CONSUMED') LIMIT 1",
                (incident_id,),
            ).fetchone()
            human_intervention = human_auth is not None
            recovery_verified = receipt_time is not None

            agent_secs = _seconds_between(alert_time, plan_time)
            resolution_secs = _seconds_between(alert_time, terminal_time)
            post_plan_secs = _seconds_between(plan_time, terminal_time)

            runs.append({
                "incident_id": incident_id,
                "state": incident["state"],
                "incident_family": incident_family,
                "alert_service": alert_service,
                "agent_processing_secs": (
                    round(agent_secs) if agent_secs is not None else None
                ),
                "total_resolution_secs": (
                    round(resolution_secs) if resolution_secs is not None else None
                ),
                # Kept for dashboard/API compatibility.  This measures elapsed
                # time after plan publication, not guaranteed human think time.
                "human_review_secs": (
                    round(post_plan_secs) if post_plan_secs is not None else None
                ),
                "post_plan_wait_secs": (
                    round(post_plan_secs) if post_plan_secs is not None else None
                ),
                "card_count": len(cards),
                "card_types": card_types,
                "challenges": challenge_count,
                "human_rejections": human_rejection_count,
                "plan_revisions": plan_revision_count,
                "disagreement_events": challenge_count + human_rejection_count,
                "handoffs": handoff_count,
                "handoff_method": "adjacent published card-role transitions",
                "recovery_verified": recovery_verified,
                "human_intervention": human_intervention,
            })

            if agent_secs is not None:
                total_agent_secs += agent_secs
                agent_secs_count += 1
            if resolution_secs is not None:
                total_resolution_secs += resolution_secs
                resolution_count += 1
            if post_plan_secs is not None:
                total_post_plan_secs += post_plan_secs
                post_plan_count += 1
            total_challenges += challenge_count
            total_handoffs += handoff_count
            total_recovery_verified += int(recovery_verified)
            total_human_interventions += int(human_intervention)
            total_human_rejections += human_rejection_count
            total_plan_revisions += plan_revision_count
            incidents_challenged += int(challenge_count > 0)
            incidents_revised += int(human_rejection_count > 0 or plan_revision_count > 0)

        avg_agent = (
            round(total_agent_secs / agent_secs_count)
            if agent_secs_count else None
        )
        avg_total = (
            round(total_resolution_secs / resolution_count)
            if resolution_count else None
        )
        avg_post_plan = (
            round(total_post_plan_secs / post_plan_count)
            if post_plan_count else None
        )

        baseline_raw = os.getenv("MANUAL_BASELINE_SECS", "").strip()
        baseline_secs = None
        if baseline_raw:
            try:
                parsed_baseline = int(baseline_raw)
                if parsed_baseline > 0:
                    baseline_secs = parsed_baseline
            except ValueError:
                logger.warning("[runsummary] Ignoring invalid MANUAL_BASELINE_SECS")

        # Optional same-family scoping: when BASELINE_INCIDENT_FAMILY is set,
        # the speedup denominator uses only that family's measured runs, so the
        # comparison matches the family the manual baseline was measured on.
        baseline_family = os.getenv("BASELINE_INCIDENT_FAMILY", "").strip() or None
        family_avg_total = None
        family_run_count = 0
        if baseline_family:
            family_secs = [
                run["total_resolution_secs"]
                for run in runs
                if run.get("incident_family") == baseline_family
                and run.get("total_resolution_secs") is not None
            ]
            family_run_count = len(family_secs)
            if family_secs:
                family_avg_total = round(sum(family_secs) / len(family_secs))
        speedup_denominator = (
            family_avg_total if family_avg_total else avg_total
        )

        return {
            "summary": {
                "incidents_measured": resolution_count,
                "avg_agent_processing_secs": avg_agent,
                "avg_total_resolution_secs": avg_total,
                "avg_human_review_secs": avg_post_plan,
                "avg_post_plan_wait_secs": avg_post_plan,
                "manual_baseline_secs": baseline_secs,
                "baseline_source": (
                    "User-configured measured baseline"
                    if baseline_secs is not None else None
                ),
                "baseline_note": (
                    "Comparison is shown only when MANUAL_BASELINE_SECS is explicitly configured."
                ),
                "baseline_incident_family": baseline_family,
                "baseline_family_avg_total_secs": family_avg_total,
                "baseline_family_run_count": family_run_count,
                "speedup_factor": (
                    round(baseline_secs / speedup_denominator, 1)
                    if baseline_secs is not None
                    and speedup_denominator and speedup_denominator > 0
                    else None
                ),
                "total_challenges_issued": total_challenges,
                "incidents_challenged": incidents_challenged,
                "total_human_rejections": total_human_rejections,
                "total_plan_revisions": total_plan_revisions,
                "incidents_revised": incidents_revised,
                "disagreement_events": total_challenges + total_human_rejections,
                "total_handoffs": total_handoffs,
                "handoff_method": "adjacent published card-role transitions",
                "recovery_verified_count": total_recovery_verified,
                # A CHALLENGE is not necessarily an unsafe plan, so this field
                # is intentionally unavailable until an explicit block event is recorded.
                "unsafe_plans_blocked": None,
                "human_interventions": total_human_interventions,
                "human_intervention_method": "consumed human_approval authorizations",
            },
            "runs": runs,
        }

    # Real read-only MCP server over the same skill registry (gateway/mcp.py).
    new_app.include_router(mcp_router)

    return new_app


app = create_app()

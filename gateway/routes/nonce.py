"""YITING Gateway — Nonce Consumption Route.

POST /api/nonce/consume — Atomically validates and consumes a nonce.

This is the REAL authorization boundary. The Operator preprocessor
regex is just triage; this route decides whether execution happens.

Two-layer auth:
    1. Transport: X-Agent-Key must resolve to the "operator" role (same
       key system as card submission). Only the Operator agent may consume.
    2. Semantic: consumed_by must appear in HUMAN_APPROVER_IDS (fail-closed).

Returns:
    200: Nonce valid and consumed — execution may proceed.
    400: Validation failed (missing fields, hash mismatch, expired, etc.)
    409: Nonce already consumed (replay attempt).
    401: Unauthorized — missing/invalid agent key or sender not in allowlist.
    403: Forbidden — valid key but wrong role (not operator).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from gateway.routes.rooms import store_room_message, store_room_participant
from shared.config import HUMAN_APPROVER_IDS

logger = logging.getLogger("yiting.nonce")

router = APIRouter()


# ---------------------------------------------------------------------------
# Transport auth — reuses the submission key system
# ---------------------------------------------------------------------------

def _authenticate_operator(key: str) -> tuple[bool, str]:
    """Verify X-Agent-Key belongs to the 'operator' role.

    Uses the same _load_agent_keys() as card submission.
    Fail-closed: no key / wrong role → rejected.
    """
    if not key:
        return False, "Missing X-Agent-Key header"

    # Import here to avoid circular import at module load
    from gateway.routes.submission import _load_agent_keys

    keys = _load_agent_keys()
    if not keys:
        return False, "No agent keys configured — all requests rejected"

    role = keys.get(key)
    if role is None:
        return False, "Invalid agent key"

    # Only the Operator agent may consume nonces
    if role not in ("operator", "gateway"):
        return False, f"Role '{role}' is not authorized to consume nonces"

    return True, role


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NonceConsumeRequest(BaseModel):
    """Request body for nonce consumption."""
    incident_id: str
    nonce: str
    plan_hash: str
    action_hash: str
    consumed_by: str         # sender_id of the human approver
    room_message_id: str     # Message ID carrying the approval


class NonceConsumeResponse(BaseModel):
    """Response body for nonce consumption."""
    consumed: bool
    reason: str
    authorization_id: str | None = None
    plan_hash: str | None = None
    action_hash: str | None = None
    envelopes: list | None = None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/nonce/consume", response_model=NonceConsumeResponse)
async def consume_nonce(
    body: NonceConsumeRequest,
    request: Request,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    """Atomically validate and consume a nonce.

    The Operator calls this after extracting a nonce from the preprocessor.

    Auth layers (both must pass):
        1. Transport: X-Agent-Key → operator role
        2. Semantic: consumed_by → HUMAN_APPROVER_IDS allowlist

    Rejection reasons (all fail-closed, no consumption on failure):
        - Missing/invalid agent key (401)
        - Wrong role (403)
        - Approver allowlist empty or sender not in it (401)
        - Unknown nonce (400)
        - Nonce invalidated by plan revision (400)
        - Nonce already consumed / replay (409)
        - Plan hash mismatch (400)
        - Action hash mismatch / tampering (400)
        - Nonce expired (400)
    """
    # --- Layer 1: Transport auth ---
    authed, role_or_error = _authenticate_operator(x_agent_key)
    if not authed:
        logger.warning(
            f"[nonce] Transport auth FAILED: {role_or_error}"
        )
        # Distinguish "valid key, wrong role" (403) from "bad key" (401)
        status = 403 if "not authorized" in role_or_error else 401
        raise HTTPException(status_code=status, detail=role_or_error)

    # Approval message ID required for API callers (not for UI)
    if not body.room_message_id.strip():
        raise HTTPException(
            status_code=400,
            detail="room_message_id required and must not be whitespace",
        )

    db = request.app.state.db

    return await _do_consume_nonce(
        incident_id=body.incident_id,
        nonce=body.nonce,
        plan_hash=body.plan_hash,
        action_hash=body.action_hash,
        consumed_by=body.consumed_by,
        room_message_id=body.room_message_id,
        approval_channel="room",
        db=db,
    )


# ---------------------------------------------------------------------------
# Core consume — three branches (called by API route and UI)
# ---------------------------------------------------------------------------

async def _do_consume_nonce(
    *,
    incident_id: str,
    nonce: str,
    plan_hash: str,
    action_hash: str,
    consumed_by: str,
    room_message_id: str,
    approval_channel: str,
    db,
) -> NonceConsumeResponse:
    """Branch router: FRESH → seal+consume, PENDING → resume, PUBLISHED → idempotent."""
    import json

    # Semantic auth (every caller — API and UI both)
    if not HUMAN_APPROVER_IDS:
        raise HTTPException(status_code=401, detail="Approver allowlist not configured")
    if consumed_by not in HUMAN_APPROVER_IDS:
        raise HTTPException(
            status_code=401,
            detail=f"Sender {consumed_by!r} not in approver allowlist",
        )

    # Check for existing authorization
    auth_row = db.execute(
        "SELECT authorization_id, card_hash, status, consumed_by, envelopes_json, nonce "
        "FROM authorizations WHERE incident_id=? AND nonce=? "
        "AND authorization_type='human_approval'",
        (incident_id, nonce),
    ).fetchone()

    if auth_row:
        if auth_row["consumed_by"] != consumed_by:
            raise HTTPException(status_code=403, detail="Approver mismatch")

        status = auth_row["status"]

        # PUBLISHED → idempotent success
        if status == "PUBLISHED":
            inc = db.execute(
                "SELECT state FROM incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
            if inc and inc["state"] in ("APPROVED", "EXECUTED"):
                envelopes = json.loads(auth_row["envelopes_json"] or "[]")
                return NonceConsumeResponse(
                    consumed=True,
                    reason="Idempotent success — already published",
                    authorization_id=auth_row["authorization_id"],
                    envelopes=envelopes,
                )
            raise HTTPException(status_code=409, detail="inconsistent_lifecycle")

        # PENDING → resume incident-room publication
        if status == "PENDING":
            return await _resume_pending(db, incident_id, auth_row)

        # CONSUMED → error
        if status == "CONSUMED":
            raise HTTPException(status_code=409, detail="already_consumed")

        raise HTTPException(status_code=409, detail="inconsistent_lifecycle")

    # FRESH → full seal + consume
    return await _fresh_consume(
        db=db,
        incident_id=incident_id,
        nonce=nonce,
        plan_hash=plan_hash,
        action_hash=action_hash,
        consumed_by=consumed_by,
        room_message_id=room_message_id,
        approval_channel=approval_channel,
    )


async def _fresh_consume(
    *,
    db,
    incident_id: str,
    nonce: str,
    plan_hash: str,
    action_hash: str,
    consumed_by: str,
    room_message_id: str,
    approval_channel: str,
) -> NonceConsumeResponse:
    """FRESH branch: all guards inside atomic transaction."""
    import json
    import uuid
    from datetime import datetime, timedelta, timezone
    from shared.models import StructuredApproval
    from shared.integrity import seal_card_in_transaction
    from shared.card_intake import derive_idempotency_key
    from shared.approval import validate_nonce_only, consume_nonce_only

    now = datetime.now(timezone.utc)
    authorization_id = str(uuid.uuid4())

    db.execute("BEGIN IMMEDIATE")
    try:
        # GUARD 1: state == PLANNED
        inc = db.execute(
            "SELECT state, room_id, room_alias_id FROM incidents WHERE incident_id=?",
            (incident_id,),
        ).fetchone()
        if not inc or inc["state"] != "PLANNED":
            db.execute("ROLLBACK")
            state = inc["state"] if inc else "NOT_FOUND"
            raise HTTPException(
                status_code=409,
                detail=f"Incident state is {state}, expected PLANNED",
            )

        # GUARD 2: room_id exists (from incident, NOT body).
        # ``room_alias_id`` is a compatibility alias during schema cleanup.
        room_id = inc["room_id"] or inc["room_alias_id"] or ""
        if not room_id:
            db.execute("ROLLBACK")
            raise HTTPException(
                status_code=502,
                detail="No incident room for this incident — cannot seal",
            )

        # GUARD 3/4: the approval challenge must be visible in the room and the
        # nonce must match the current plan/action hashes, remain unexpired,
        # unconsumed, and not invalidated.
        valid, reason, nonce_row = validate_nonce_only(
            incident_id=incident_id,
            nonce=nonce,
            plan_hash=plan_hash,
            action_hash=action_hash,
            db=db,
            require_challenge_visibility=True,
        )
        if not valid:
            db.execute("ROLLBACK")
            status_code = 409 if "replay" in reason.lower() else 400
            logger.warning(
                "[nonce] Consumption rejected: %s (incident=%s)",
                reason,
                incident_id,
            )
            raise HTTPException(status_code=status_code, detail=reason)

        # Derive envelopes from confirmed ResponsePlan
        plan_card = db.execute(
            "SELECT card_json FROM cards "
            "WHERE incident_id=? AND card_type='ResponsePlan' "
            "AND published_at IS NOT NULL "
            "ORDER BY sequence_number DESC LIMIT 1",
            (incident_id,),
        ).fetchone()

        envelopes_json = "[]"
        if plan_card:
            try:
                plan_data = json.loads(plan_card["card_json"])
                envelopes_json = json.dumps(plan_data.get("envelopes", []))
            except (json.JSONDecodeError, TypeError):
                pass
        resume_envelopes = json.loads(envelopes_json)

        expiry_str = nonce_row["expiry"] if nonce_row else (
            now + timedelta(minutes=30)
        ).isoformat()
        plan_revision = (
            nonce_row["plan_revision"]
            if nonce_row and "plan_revision" in nonce_row.keys()
            else 1
        )

        # Seal StructuredApproval
        approval_card = StructuredApproval(
            incident_id=incident_id,
            action_id=authorization_id,
            action_hash=action_hash,
            decision="APPROVED",
            approver_id=consumed_by,
            room_message_id=room_message_id,
            room_alias_id=room_id,  # Compatibility model field.
            plan_hash=plan_hash,
            nonce=nonce,
            expiry=datetime.fromisoformat(expiry_str) if isinstance(expiry_str, str) else expiry_str,
            approval_channel=approval_channel,
            plan_revision=plan_revision,
        )

        idem_key = derive_idempotency_key(
            "gateway_approval", incident_id, nonce,
        )

        sealed = seal_card_in_transaction(
            approval_card, incident_id, db,
            idempotency_key=idem_key,
            prepared_by_role="gateway",
        )
        sealed_card_hash = sealed.card_hash

        # Authorization record (PENDING)
        db.execute(
            "INSERT OR IGNORE INTO authorizations "
            "(authorization_id, incident_id, authorization_type, plan_hash, "
            "action_hash, envelopes_json, expiry, created_at, consumed, status, nonce, card_hash, consumed_by) "
            "VALUES (?, ?, 'human_approval', ?, ?, ?, ?, ?, 0, 'PENDING', ?, ?, ?)",
            (authorization_id, incident_id, plan_hash,
             action_hash, envelopes_json, expiry_str,
             now.isoformat(), nonce, sealed_card_hash, consumed_by),
        )

        # Consume nonce
        consume_nonce_only(
            incident_id=incident_id,
            nonce=nonce,
            consumed_by=consumed_by,
            db=db,
        )

        # COMMIT
        db.execute("COMMIT")

    except HTTPException:
        raise
    except Exception as exc:
        db.execute("ROLLBACK")
        logger.error(
            "[nonce] Atomic seal+consume failed (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Nonce consumption failed atomically; nothing was consumed.",
        ) from exc

    # Post-commit: publish + advance
    return await _publish_and_advance(
        db, incident_id, sealed_card_hash, authorization_id, resume_envelopes,
        plan_hash=plan_hash, action_hash=action_hash,
    )


async def _resume_pending(db, incident_id: str, auth_row) -> NonceConsumeResponse:
    """Resume PENDING authorization — revalidate lifecycle, retry room publish.

    NOTE: This revalidation is not transactional, so simultaneous resume
    requests may post duplicate StructuredApproval messages to the room.
    Execution remains single-use: Operator's second consume returns
    409 already_consumed, and the EXECUTED-skip guard catches it.
    This is documented as residual duplicate-publication risk (at-least-once delivery).
    """
    import json

    # 1. Incident state == PLANNED
    inc = db.execute(
        "SELECT state FROM incidents WHERE incident_id=?",
        (incident_id,),
    ).fetchone()
    if not inc or inc["state"] != "PLANNED":
        raise HTTPException(
            status_code=409,
            detail=f"inconsistent_lifecycle: state={inc['state'] if inc else 'MISSING'}",
        )

    # 2. Authorization still PENDING
    if auth_row["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="inconsistent_lifecycle: auth not PENDING")

    # 3. Unpublished sealed card exists
    card_count = db.execute(
        "SELECT COUNT(*) as count FROM cards "
        "WHERE card_hash=? AND card_type='StructuredApproval' AND published_at IS NULL",
        (auth_row["card_hash"],),
    ).fetchone()["count"]
    if card_count != 1:
        raise HTTPException(status_code=409, detail="inconsistent_lifecycle: card missing or published")

    # 4. Nonce consumed and bound — bracket notation (sqlite3.Row has no .get())
    nonce_check = db.execute(
        "SELECT consumed FROM nonces WHERE incident_id=? AND nonce=?",
        (incident_id, auth_row["nonce"]),
    ).fetchone()
    if not nonce_check or not nonce_check["consumed"]:
        raise HTTPException(status_code=409, detail="inconsistent_lifecycle: nonce not consumed")

    # 5. Plan not superseded — latest ResponsePlan hashes must match auth record
    from shared.approval import compute_plan_hash, compute_action_hash, normalize_plan_for_hash
    plan_card = db.execute(
        "SELECT card_json FROM cards "
        "WHERE incident_id=? AND card_type='ResponsePlan' "
        "AND published_at IS NOT NULL "
        "ORDER BY sequence_number DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    if not plan_card:
        raise HTTPException(status_code=409, detail="inconsistent_lifecycle: no confirmed ResponsePlan")

    plan_data = json.loads(plan_card["card_json"])
    current_plan_hash = compute_plan_hash(normalize_plan_for_hash(plan_data))
    current_action_hash = compute_action_hash(plan_data.get("envelopes", []))

    auth_full = db.execute(
        "SELECT plan_hash, action_hash FROM authorizations WHERE authorization_id=?",
        (auth_row["authorization_id"],),
    ).fetchone()
    if auth_full["plan_hash"] != current_plan_hash or auth_full["action_hash"] != current_action_hash:
        raise HTTPException(
            status_code=409,
            detail="inconsistent_lifecycle: plan has been superseded since authorization",
        )

    envelopes = json.loads(auth_row["envelopes_json"] or "[]")

    # NOTE: If room publication succeeds but advance fails, retry will re-post the
    # StructuredApproval. Harmless: Operator's second consume returns 409
    # already_consumed, and the EXECUTED-skip guard catches it.
    return await _publish_and_advance(
        db, incident_id, auth_row["card_hash"], auth_row["authorization_id"], envelopes,
        plan_hash=auth_full["plan_hash"], action_hash=auth_full["action_hash"],
    )


async def _publish_and_advance(
    db,
    incident_id: str,
    sealed_card_hash: str,
    authorization_id: str,
    envelopes: list,
    *,
    plan_hash: str = "",
    action_hash: str = "",
) -> NonceConsumeResponse:
    """Post sealed card to the incident room @Operator, then advance lifecycle."""
    import json
    import os
    from shared.submission_client import format_card_message

    # Mention Operator — must wake to consume authorization.
    # Do NOT mention human — humans can't participate in agent-created rooms.
    operator_id = os.getenv("OPERATOR_AGENT_ID", "")
    if not operator_id:
        raise HTTPException(
            status_code=502,
            detail="OPERATOR_AGENT_ID not configured",
        )
    inc_row = db.execute(
        "SELECT room_id, room_alias_id FROM incidents WHERE incident_id=?",
        (incident_id,),
    ).fetchone()
    room_id = None
    if inc_row:
        room_id = inc_row["room_id"] or inc_row["room_alias_id"]

    if not room_id:
        raise HTTPException(
            status_code=502,
            detail="Cannot publish StructuredApproval: no incident room. "
            "Authorization is PENDING — retry is safe.",
        )

    recorder_agent_id = os.getenv("RECORDER_AGENT_ID", "recorder")

    # ⚠️ INTEGRITY NOTE: card_hash is excluded from card_json during sealing
    # to prevent self-referential hashing. We inject it into the incident-room
    # message COPY only. DB card_json MUST remain hash-free.
    # Any future code that re-hashes received card_json must strip card_hash
    # first, or the hash will always mismatch.
    row = db.execute(
        "SELECT card_json, card_hash FROM cards WHERE card_hash=? AND incident_id=?",
        (sealed_card_hash, incident_id),
    ).fetchone()
    sealed_card_data = json.loads(row["card_json"])
    sealed_card_data["card_hash"] = row["card_hash"]  # Copy only — DB untouched
    sealed_message = format_card_message(sealed_card_data)

    try:
        store_room_participant(
            db,
            room_id,
            operator_id,
            role="operator",
            display_name="Operator",
        )
        message = store_room_message(
            db,
            room_id,
            sealed_message,
            sender_id=recorder_agent_id,
            sender_role="recorder",
            mentions=[operator_id],
            metadata={
                "publisher": "gateway",
                "card_hash": sealed_card_hash,
            },
        )
        message_id = message["message_id"]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[nonce] StructuredApproval room publication failed (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Incident-room publication failed. Authorization remains PENDING.",
        ) from exc

    # Advance lifecycle → APPROVED
    from shared.approval import advance_authorization_lifecycle
    advance_authorization_lifecycle(
        db=db,
        incident_id=incident_id,
        card_hash=sealed_card_hash,
        authorization_id=authorization_id,
        room_message_id=message_id,
        target_incident_state="APPROVED",
    )

    # NOTE: card_json is IMMUTABLE after sealing (card_hash = sha256(card_json)).
    # The real room message ID is already stored in the cards.room_message_id
    # COLUMN by advance_authorization_lifecycle → approval.py:399.
    # card_json.room_message_id keeps the approval source value — this is intended.
    # A judge recomputing the chain will match because they hash card_json as-is.

    logger.info(
        f"[nonce] StructuredApproval published to incident room: "
        f"incident={incident_id}, auth_id={authorization_id[:12]}..., "
        f"state → APPROVED"
    )

    return NonceConsumeResponse(
        consumed=True,
        reason="Nonce valid and consumed",
        authorization_id=authorization_id,
        plan_hash=plan_hash,
        action_hash=action_hash,
        envelopes=envelopes,
    )


# ---------------------------------------------------------------------------
# Nonce creation route (Commander creates approval challenges)
# ---------------------------------------------------------------------------

class NonceCreateRequest(BaseModel):
    """Commander supplies only incident_id.
    
    Gateway derives plan_hash, action_hash, and plan_revision from
    the confirmed (published) ResponsePlan stored in the DB.
    Commander cannot supply or tamper with these bindings.
    """
    incident_id: str


class NonceCreateResponse(BaseModel):
    created: bool
    nonce: str
    incident_id: str
    expiry_iso: str  # ISO 8601 expiry timestamp for Commander to display
    plan_hash: str  # Gateway-authoritative binding
    action_hash: str  # Gateway-authoritative binding
    plan_revision: int  # Gateway-authoritative binding


def _authenticate_commander(key: str) -> tuple[bool, str]:
    """Verify X-Agent-Key belongs to the 'commander' or 'gateway' role."""
    if not key:
        return False, "Missing X-Agent-Key header"

    from gateway.routes.submission import _load_agent_keys

    keys = _load_agent_keys()
    if not keys:
        return False, "No agent keys configured — all requests rejected"

    role = keys.get(key)
    if role is None:
        return False, "Invalid agent key"

    if role not in ("commander", "gateway"):
        return False, f"Role {role!r} is not authorized to create nonces"

    return True, role


@router.post("/nonce/create", response_model=NonceCreateResponse)
async def create_nonce_endpoint(
    body: NonceCreateRequest,
    request: Request,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    """Create a nonce for human approval challenge.

    The Commander calls this after selecting a runbook and building
    a ResponsePlan. The nonce binds the approval to the exact
    plan_hash and action_hash.

    Auth: Only the Commander agent may create nonces.
    """
    authed, role_or_error = _authenticate_commander(x_agent_key)
    if not authed:
        logger.warning(f"[nonce] Create auth FAILED: {role_or_error}")
        status = 403 if "not authorized" in role_or_error else 401
        raise HTTPException(status_code=status, detail=role_or_error)

    db = request.app.state.db
    from datetime import datetime, timedelta, timezone
    from shared.approval import generate_nonce
    import json as _json

    # --- Derive bindings from confirmed ResponsePlan ---
    # Gateway owns these — Commander cannot supply or tamper with them.
    plan_row = db.execute(
        "SELECT card_json FROM cards "
        "WHERE incident_id=? AND card_type='ResponsePlan' "
        "AND published_at IS NOT NULL "
        "ORDER BY sequence_number DESC LIMIT 1",
        (body.incident_id,),
    ).fetchone()

    if not plan_row:
        logger.warning(
            f"[nonce] No confirmed ResponsePlan for incident {body.incident_id} "
            f"— cannot create nonce (fail-closed)"
        )
        raise HTTPException(
            status_code=400,
            detail=f"No confirmed ResponsePlan for incident {body.incident_id}. "
                   "Submit and publish a ResponsePlan first.",
        )

    try:
        plan_data = _json.loads(plan_row["card_json"])
    except (TypeError, ValueError) as exc:
        logger.error(
            "[nonce] Stored ResponsePlan could not be parsed (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Stored ResponsePlan could not be parsed.",
        ) from exc

    # Derive hashes from stored plan (Gateway-authoritative)
    from shared.approval import compute_plan_hash, compute_action_hash, normalize_plan_for_hash
    plan_hash = compute_plan_hash(normalize_plan_for_hash(plan_data))
    action_hash = compute_action_hash(plan_data.get("envelopes", []))
    # ResponsePlan model field is 'revision', not 'plan_revision'
    plan_revision = plan_data.get("revision", 1)

    nonce = generate_nonce()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

    try:
        # Invalidate previous nonces for this incident first.
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "UPDATE nonces SET invalidated=1 WHERE incident_id=? AND consumed=0",
                (body.incident_id,),
            )
            db.execute(
                "INSERT INTO nonces "
                "(incident_id, nonce, plan_hash, action_hash, plan_revision, "
                "expiry, consumed, invalidated) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (body.incident_id, nonce, plan_hash,
                 action_hash, plan_revision, expiry.isoformat()),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

        logger.info(
            "[nonce] Created approval nonce for incident=%s, plan_hash=%s...",
            body.incident_id,
            plan_hash[:12],
        )
        return NonceCreateResponse(
            created=True,
            nonce=nonce,
            incident_id=body.incident_id,
            expiry_iso=expiry.isoformat(),
            plan_hash=plan_hash,
            action_hash=action_hash,
            plan_revision=plan_revision,
        )

    except Exception as exc:
        logger.error("[nonce] Create failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Nonce creation failed due to an internal error.",
        ) from exc


# ---------------------------------------------------------------------------
# Challenge publication confirmation — Commander asks Gateway to post challenge
# ---------------------------------------------------------------------------

class ChallengePostedRequest(BaseModel):
    """Commander sends challenge text; Gateway posts to the incident room."""
    incident_id: str
    nonce: str
    challenge_text: str

    @field_validator("challenge_text")
    @classmethod
    def challenge_text_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("challenge_text must not be empty")
        return v


@router.post("/nonce/challenge-posted")
async def confirm_challenge_posted(
    body: ChallengePostedRequest,
    request: Request,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    """Post the approval challenge to the incident room and record the message ID.

    Lifecycle order (validate-first):
        1. Auth: Only Commander may trigger challenge publication.
        2. Validate: nonce must exist, be active (not consumed/invalidated/expired).
        3. Idempotency: if challenge already posted, return existing ID.
        4. Post: publish challenge to the incident room as Recorder.
        5. Store: real room message ID in nonces table.

    This ensures no challenge message is posted for invalid/consumed nonces.
    Operator mention is derived server-side from OPERATOR_AGENT_ID.
    """
    authed, role_or_error = _authenticate_commander(x_agent_key)
    if not authed:
        logger.warning(f"[nonce] Challenge-posted auth FAILED: {role_or_error}")
        status = 403 if "not authorized" in role_or_error else 401
        raise HTTPException(status_code=status, detail=role_or_error)

    db = request.app.state.db

    # --- STEP 1: Validate nonce exists and is active BEFORE any room post ---
    nonce_row = db.execute(
        "SELECT nonce, consumed, invalidated, expiry, challenge_message_id "
        "FROM nonces WHERE incident_id=? AND nonce=?",
        (body.incident_id, body.nonce),
    ).fetchone()

    if not nonce_row:
        raise HTTPException(
            status_code=404,
            detail=f"No active nonce found for incident={body.incident_id}",
        )

    if nonce_row["consumed"]:
        raise HTTPException(
            status_code=409,
            detail=f"Nonce already consumed for incident={body.incident_id}",
        )

    if nonce_row["invalidated"]:
        raise HTTPException(
            status_code=409,
            detail=f"Nonce invalidated for incident={body.incident_id}",
        )

    # Check expiry
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    try:
        expiry = datetime.fromisoformat(nonce_row["expiry"].replace("Z", "+00:00"))
        if now > expiry:
            raise HTTPException(
                status_code=409,
                detail=f"Nonce expired for incident={body.incident_id}",
            )
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail=f"Malformed nonce expiry for incident={body.incident_id}; rejecting",
        )

    # --- STEP 2: Idempotency — if challenge already posted, return existing ID ---
    existing_id = (nonce_row["challenge_message_id"] or "").strip()
    if existing_id:
        logger.info(
            "[nonce] Challenge already posted for %s; room_message_id=%s...",
            body.incident_id,
            existing_id[:12],
        )
        return {
            "confirmed": True,
            "incident_id": body.incident_id,
            "challenge_message_id": existing_id,
        }

    # --- STEP 3: Look up incident room ---
    inc_row = db.execute(
        "SELECT room_id, room_alias_id FROM incidents WHERE incident_id=?",
        (body.incident_id,),
    ).fetchone()
    room_id = None
    if inc_row:
        room_id = inc_row["room_id"] or inc_row["room_alias_id"]

    if not room_id:
        raise HTTPException(
            status_code=502,
            detail=f"No incident room for incident {body.incident_id}",
        )

    # --- STEP 4: Derive Operator mention server-side (don't trust Commander) ---
    import os
    operator_id = os.getenv("OPERATOR_AGENT_ID", "")
    if not operator_id:
        raise HTTPException(
            status_code=500,
            detail="OPERATOR_AGENT_ID not configured — cannot post challenge with required mention",
        )
    # --- STEP 5: Post challenge as Recorder into the incident room ---
    recorder_agent_id = os.getenv("RECORDER_AGENT_ID", "recorder")
    try:
        store_room_participant(
            db,
            room_id,
            operator_id,
            role="operator",
            display_name="Operator",
        )
        message = store_room_message(
            db,
            room_id,
            body.challenge_text,
            sender_id=recorder_agent_id,
            sender_role="recorder",
            mentions=[operator_id],
            message_type="approval_challenge",
            metadata={
                "publisher": "gateway",
                "nonce": body.nonce,
                "challenge": True,
            },
        )
        challenge_message_id = message["message_id"]
    except Exception as room_err:
        logger.warning(
            "[nonce] Challenge room post failed for incident=%s (%s)",
            body.incident_id,
            type(room_err).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Challenge could not be published to the incident room. "
            "Approval remains unavailable until the challenge is visible.",
        ) from room_err

    logger.info(
        "[nonce] Challenge posted to incident room for incident=%s",
        body.incident_id,
    )

    # --- STEP 6: Store the real challenge message ID ---
    result = db.execute(
        "UPDATE nonces SET challenge_message_id=? "
        "WHERE incident_id=? AND nonce=? AND consumed=0 AND invalidated=0",
        (challenge_message_id, body.incident_id, body.nonce),
    )
    db.execute("COMMIT") if db.in_transaction else None

    if result.rowcount == 0:
        # Race condition: nonce was consumed between our check and update
        logger.warning(
            f"[nonce] Race: nonce consumed between validation and update "
            f"for {body.incident_id}"
        )
        raise HTTPException(
            status_code=409,
            detail="Nonce was consumed during challenge publication (race condition)",
        )

    logger.info(
        "[nonce] Challenge publication confirmed for incident=%s message=%s",
        body.incident_id,
        challenge_message_id,
    )
    return {
        "confirmed": True,
        "incident_id": body.incident_id,
        "challenge_message_id": challenge_message_id,
    }


# ---------------------------------------------------------------------------
# Active nonce query — used by gate_b_trigger to verify challenge posted
# ---------------------------------------------------------------------------

def _authenticate_any_agent(key: str) -> tuple[bool, str]:
    """Verify X-Agent-Key is a valid agent key (any role).

    Used for read-only queries that don't modify state but should
    not be publicly accessible.
    """
    if not key:
        return False, "Missing X-Agent-Key header"

    from gateway.routes.submission import _load_agent_keys

    keys = _load_agent_keys()
    if not keys:
        return False, "No agent keys configured — all requests rejected"

    role = keys.get(key)
    if role is None:
        return False, "Invalid agent key"

    return True, role


@router.get("/nonce/active/{incident_id}")
async def get_active_nonce(
    incident_id: str,
    request: Request,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    """Check whether an active nonce exists for an incident AND the approval
    challenge message was actually recorded.

    Only returns nonces where challenge_message_id is set (i.e., Commander
    confirmed the challenge was posted). This prevents the race where a nonce
    exists but the challenge hasn't been posted to the room yet.

    Auth: requires any valid agent key (defense-in-depth).
    Does NOT return plan_hash/action_hash (approval bindings are not
    exposed — they are visible only to room participants).

    Returns:
        200: Active nonce found with confirmed challenge
        401/403: Unauthorized
        404: No active nonce (or challenge not yet posted)
    """
    authed, role_or_error = _authenticate_any_agent(x_agent_key)
    if not authed:
        logger.warning(f"[nonce] Active query auth FAILED: {role_or_error}")
        status = 403 if "not authorized" in role_or_error else 401
        raise HTTPException(status_code=status, detail=role_or_error)

    db = request.app.state.db
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    row = db.execute(
        "SELECT nonce, expiry "
        "FROM nonces "
        "WHERE incident_id=? AND consumed=0 AND invalidated=0 "
        "AND expiry > ? AND challenge_message_id IS NOT NULL "
        "AND length(trim(challenge_message_id)) > 0 "
        "ORDER BY rowid DESC LIMIT 1",
        (incident_id, now),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No active nonce")

    return {
        "incident_id": incident_id,
        "nonce": row["nonce"],
        "expiry": row["expiry"],
    }

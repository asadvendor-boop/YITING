"""Tests for nonce consumption — the REAL authorization boundary.

Contract tests walked through the actual HTTP route (TestClient),
not by calling internals. Two-layer auth:
    Layer 1: X-Agent-Key → operator role (transport auth)
    Layer 2: consumed_by → HUMAN_APPROVER_IDS allowlist (semantic auth)

Acceptance contract:
    1. Missing nonce → refuse (400)
    2. Replayed/consumed nonce → refuse (409)
    3. Expired nonce → refuse (400)
    4. Invalidated nonce (plan revision) → refuse (400)
    5. Wrong plan hash → refuse (400)
    6. Wrong action hash → refuse (400, tampering fails)
    7. Unauthorized sender → refuse (401)
    8. Valid nonce → consume atomically, bound to action_hash
    9. Missing/invalid X-Agent-Key → refuse (401)
   10. Wrong role X-Agent-Key → refuse (403)
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from gateway.app import create_app
from shared.approval import (
    compute_action_hash,
    compute_plan_hash,
    create_nonce,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SENDER = "human-approver-001"
INCIDENT_ID = "INC-NONCE-TEST"
OPERATOR_KEY = "test-operator-key-abc123"
GATEWAY_SECRET = "test-gateway-secret"
COMMANDER_KEY = "test-commander-key-xyz"
ROOM_MSG_ID = "550e8400-e29b-41d4-a716-446655440001"
ROOM_ID = "room-nonce-test"
OPERATOR_AGENT_ID = "operator-agent-test"
RECORDER_AGENT_ID = "recorder-agent-test"

PLAN = {"action": "scale_down", "target": "web-fleet", "revision": 1}
PLAN_HASH = compute_plan_hash(PLAN)

ENVELOPES = [
    {"action_id": "scale_down", "target": "web-fleet", "params": {"replicas": 2}},
]
ACTION_HASH = compute_action_hash(ENVELOPES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_body(nonce="XXXXXX", plan_hash=None, action_hash=None, **overrides):
    """Build a nonce consumption request body."""
    body = {
        "incident_id": INCIDENT_ID,
        "nonce": nonce,
        "plan_hash": plan_hash or PLAN_HASH,
        "action_hash": action_hash or ACTION_HASH,
        "consumed_by": VALID_SENDER,
        "room_message_id": ROOM_MSG_ID,
    }
    body.update(overrides)
    return body


def _post(client, body, key=OPERATOR_KEY):
    """POST to /api/nonce/consume with auth header."""
    return client.post(
        "/api/nonce/consume",
        json=body,
        headers={"X-Agent-Key": key},
    )


def _seed_incident_and_challenge(db, incident_id=INCIDENT_ID, nonce=None):
    """Seed a PLANNED incident room and mark challenge posted.

    Required by GUARD 1 (state==PLANNED) and GUARD 3 (challenge posted)
    added for the fresh nonce consume path.
    """
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT OR IGNORE INTO incidents "
        "(incident_id, state, severity, created_at, updated_at, room_id, room_alias_id) "
        "VALUES (?, 'PLANNED', 'P2', ?, ?, ?, ?)",
        (incident_id, now, now, ROOM_ID, ROOM_ID),
    )
    db.execute(
        "INSERT OR IGNORE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, 'recorder', ?, ?)",
        (ROOM_ID, incident_id, "Nonce test room", now, now),
    )
    if nonce:
        db.execute(
            "UPDATE nonces SET challenge_message_id='challenge-msg-test' "
            "WHERE incident_id=? AND nonce=?",
            (incident_id, nonce),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_and_db():
    """Create a test app with :memory: DB and agent keys configured."""
    # Configure agent keys via env vars BEFORE app creation
    env_patches = {
        "OPERATOR_SUBMISSION_KEY": OPERATOR_KEY,
        "COMMANDER_SUBMISSION_KEY": COMMANDER_KEY,
        "GATEWAY_SECRET": GATEWAY_SECRET,
        "OPERATOR_AGENT_ID": OPERATOR_AGENT_ID,
        "RECORDER_AGENT_ID": RECORDER_AGENT_ID,
    }
    with patch.dict(os.environ, env_patches):
        app = create_app(db_path=":memory:")
        # Reset the cached keys so they reload with our env vars
        import gateway.routes.submission as sub_mod
        sub_mod._agent_keys = None

        # Manually init the DB in THIS thread (TestClient spawns a new thread)
        import sqlite3
        db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        from gateway.database import SCHEMA
        db.executescript(SCHEMA)
        from gateway.database import _migrate
        _migrate(db)
        app.state.db = db
        app.state._db_path = None
        yield app, db
        # Reset cached keys after test
        sub_mod._agent_keys = None


@pytest.fixture
def client(app_and_db):
    """TestClient with patched allowlist + shared DB + agent keys."""
    app, _ = app_and_db
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def noop_lifespan(app):
        yield
    app.router.lifespan_context = noop_lifespan

    with patch(
        "gateway.routes.nonce.HUMAN_APPROVER_IDS",
        frozenset({VALID_SENDER}),
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def seeded_nonce(app_and_db, client):
    """Create a valid, unexpired nonce in the DB and return (nonce, db, client).

    Also seeds an incident (state=PLANNED) and a confirmed ResponsePlan,
    because the nonce consumption endpoint creates a StructuredApproval card
    (Fork B) which requires these to exist.

    IMPORTANT: PLAN_HASH and ACTION_HASH are derived from the actual
    serialized ResponsePlan model (after normalization), matching what
    the Gateway derives. This ensures resume's plan-superseded check
    uses identical hashes.
    """
    _, db = app_and_db
    now = datetime.now(timezone.utc)

    # Seed incident in PLANNED state
    db.execute(
        "INSERT OR REPLACE INTO incidents "
        "(incident_id, state, severity, created_at, updated_at, room_id, room_alias_id) "
        "VALUES (?, 'PLANNED', 'P2', ?, ?, ?, ?)",
        (INCIDENT_ID, now.isoformat(), now.isoformat(), ROOM_ID, ROOM_ID),
    )
    db.execute(
        "INSERT OR REPLACE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, 'recorder', ?, ?)",
        (ROOM_ID, INCIDENT_ID, "Nonce test room", now.isoformat(), now.isoformat()),
    )

    # Seed a confirmed ResponsePlan card (required for StructuredApproval)
    from shared.models import ResponsePlan, ExecutionEnvelope
    from shared.integrity import seal_card
    from shared.approval import normalize_plan_for_hash
    import json as _json

    rp = ResponsePlan(
        incident_id=INCIDENT_ID,
        runbook="RB-001",
        envelopes=[ExecutionEnvelope(**e) for e in ENVELOPES],
        risk_level="high",
        requires_human_approval=True,
        revision=1,
    )
    sealed = seal_card(rp, INCIDENT_ID, db, prepared_by_role="commander")
    db.execute(
        "UPDATE cards SET published_at=? WHERE card_hash=? AND incident_id=?",
        (now.isoformat(), sealed.card_hash, INCIDENT_ID),
    )

    # Derive hashes from the ACTUAL stored card (matches Gateway's derivation)
    stored_card = db.execute(
        "SELECT card_json FROM cards WHERE card_hash=?", (sealed.card_hash,)
    ).fetchone()
    plan_data = _json.loads(stored_card["card_json"])
    actual_plan_hash = compute_plan_hash(normalize_plan_for_hash(plan_data))
    actual_action_hash = compute_action_hash(plan_data.get("envelopes", []))

    # Create the nonce with ACTUAL hashes
    expiry = now + timedelta(minutes=15)
    nonce = create_nonce(
        incident_id=INCIDENT_ID,
        plan_hash=actual_plan_hash,
        action_hash=actual_action_hash,
        plan_revision=1,
        expiry=expiry,
        db=db,
    )

    # Simulate Commander confirming challenge was posted to the incident room
    # (required by GUARD 3 in _fresh_consume)
    db.execute(
        "UPDATE nonces SET challenge_message_id='challenge-msg-001' "
        "WHERE incident_id=? AND nonce=?",
        (INCIDENT_ID, nonce),
    )

    return nonce, db, client, actual_plan_hash, actual_action_hash


# ===========================================================================
# Test 1: Missing nonce → 400
# ===========================================================================

class TestMissingNonce:
    def test_unknown_nonce_returns_409_no_incident(self, client):
        """No incident seeded → state guard fires first (409, not 400)."""
        resp = _post(client, _make_body())
        assert resp.status_code == 409
        assert "Incident state" in resp.json()["detail"] or "NOT_FOUND" in resp.json()["detail"]


# ===========================================================================
# Test 2: Replayed/consumed nonce → 409
# ===========================================================================

class TestReplayedNonce:
    def test_second_consume_returns_200_idempotent(self, seeded_nonce):
        nonce, _, client, ph, ah = seeded_nonce
        body = _make_body(nonce, plan_hash=ph, action_hash=ah)

        # First consume — should succeed
        resp1 = _post(client, body)
        assert resp1.status_code == 200
        assert resp1.json()["consumed"] is True

        # Second consume — idempotent success
        resp2 = _post(client, body)
        assert resp2.status_code == 200
        assert "idempotent success" in resp2.json()["reason"].lower()

    def test_consumed_status_returns_409(self, seeded_nonce):
        """Historical authorizations mapped to CONSUMED return 409 replay."""
        nonce, db, client, ph, ah = seeded_nonce
        body = _make_body(nonce, plan_hash=ph, action_hash=ah)
        
        _post(client, body)
        # Mutate to CONSUMED
        db.execute("UPDATE authorizations SET status='CONSUMED' WHERE nonce=?", (nonce,))
        
        resp2 = _post(client, body)
        assert resp2.status_code == 409
        assert "already_consumed" in resp2.json()["detail"].lower()


# ===========================================================================
# Test 3: Expired nonce → 400
# ===========================================================================

class TestExpiredNonce:
    def test_expired_nonce_returns_400(self, app_and_db, client):
        _, db = app_and_db
        expiry = datetime.now(timezone.utc) - timedelta(minutes=1)
        nonce = create_nonce(
            incident_id=INCIDENT_ID,
            plan_hash=PLAN_HASH,
            action_hash=ACTION_HASH,
            plan_revision=1,
            expiry=expiry,
            db=db,
        )
        _seed_incident_and_challenge(db, nonce=nonce)
        resp = _post(client, _make_body(nonce))
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()


# ===========================================================================
# Test 4: Invalidated nonce (plan revision) → 400
# ===========================================================================

class TestInvalidatedNonce:
    def test_invalidated_by_revision_returns_400(self, app_and_db, client):
        _, db = app_and_db
        expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

        nonce_v1 = create_nonce(
            incident_id=INCIDENT_ID,
            plan_hash=PLAN_HASH,
            action_hash=ACTION_HASH,
            plan_revision=1,
            expiry=expiry,
            db=db,
        )
        _seed_incident_and_challenge(db, nonce=nonce_v1)

        # Create v2 (invalidates v1)
        _nonce_v2 = create_nonce(
            incident_id=INCIDENT_ID,
            plan_hash=compute_plan_hash({"action": "restart", "revision": 2}),
            action_hash=compute_action_hash([{"action_id": "restart"}]),
            plan_revision=2,
            expiry=expiry,
            db=db,
        )
        _seed_incident_and_challenge(db, nonce=nonce_v1)

        resp = _post(client, _make_body(nonce_v1))
        assert resp.status_code == 400
        assert "invalidated" in resp.json()["detail"].lower()


# ===========================================================================
# Test 5: Wrong plan hash → 400
# ===========================================================================

class TestWrongPlanHash:
    def test_plan_hash_mismatch_returns_400(self, seeded_nonce):
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash="wrong-hash", action_hash=ah))
        assert resp.status_code == 400
        assert "plan hash" in resp.json()["detail"].lower()


# ===========================================================================
# Test 6: Wrong action hash → 400 (TAMPERING FAILS — demo proof #5)
# ===========================================================================

class TestWrongActionHash:
    """Approve actions → modify parameter → execution refused."""

    def test_tampered_envelopes_returns_400(self, seeded_nonce):
        nonce, _, client, ph, ah = seeded_nonce
        tampered = [{"action_id": "scale_down", "target": "web-fleet", "params": {"replicas": 1}}]
        tampered_hash = compute_action_hash(tampered)
        assert tampered_hash != ACTION_HASH

        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=tampered_hash))
        assert resp.status_code == 400
        assert "action hash" in resp.json()["detail"].lower()

    def test_nonce_not_consumed_after_tamper(self, seeded_nonce):
        """Failed tamper → nonce NOT consumed → correct retry succeeds."""
        nonce, _, client, ph, ah = seeded_nonce
        tampered_hash = compute_action_hash([{"action_id": "scale_down", "params": {"replicas": 999}}])
        _post(client, _make_body(nonce, plan_hash=ph, action_hash=tampered_hash))

        # Correct attempt should still work
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))
        assert resp.status_code == 200
        assert resp.json()["consumed"] is True


# ===========================================================================
# Test 7: Unauthorized sender → 401
# ===========================================================================

class TestUnauthorizedSender:
    def test_non_allowlisted_sender_returns_401(self, seeded_nonce):
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah, consumed_by="evil-agent-42"))
        assert resp.status_code == 401
        assert "allowlist" in resp.json()["detail"].lower()

    def test_empty_allowlist_returns_401(self, app_and_db):
        """With empty allowlist, ALL consumption is rejected (fail-closed)."""
        app, _ = app_and_db
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def noop_lifespan(app):
            yield
        app.router.lifespan_context = noop_lifespan

        with patch(
            "gateway.routes.nonce.HUMAN_APPROVER_IDS",
            frozenset(),
        ):
            with TestClient(app) as client:
                resp = _post(client, _make_body())
                assert resp.status_code == 401
                assert "not configured" in resp.json()["detail"].lower()


# ===========================================================================
# Test 8: Valid nonce → consume atomically (happy path)
# ===========================================================================

class TestValidConsumption:
    def test_valid_nonce_consumed(self, seeded_nonce):
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumed"] is True
        assert "consumed" in data["reason"].lower()

    def test_consumed_by_recorded_in_db(self, seeded_nonce):
        """Verify audit trail: consumed_by and consumed_at are set."""
        nonce, db, client, ph, ah = seeded_nonce
        _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))

        row = db.execute(
            "SELECT consumed, consumed_by, consumed_at FROM nonces "
            "WHERE incident_id=? AND nonce=?",
            (INCIDENT_ID, nonce),
        ).fetchone()
        assert row["consumed"] == 1
        assert row["consumed_by"] == VALID_SENDER
        assert row["consumed_at"] is not None


# ===========================================================================
# Test 9: Transport auth — missing/invalid X-Agent-Key → 401
# ===========================================================================

class TestTransportAuth:
    """X-Agent-Key transport auth layer."""

    def test_missing_key_returns_422(self, seeded_nonce):
        """FastAPI requires X-Agent-Key header — missing → 422."""
        nonce, _, client, ph, ah = seeded_nonce
        resp = client.post(
            "/api/nonce/consume",
            json=_make_body(nonce, plan_hash=ph, action_hash=ah),
            # No X-Agent-Key header
        )
        assert resp.status_code == 422  # FastAPI validation error

    def test_invalid_key_returns_401(self, seeded_nonce):
        """Wrong key → 401."""
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah), key="totally-wrong-key")
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_valid_operator_key_succeeds(self, seeded_nonce):
        """Operator key → 200."""
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah), key=OPERATOR_KEY)
        assert resp.status_code == 200

    def test_gateway_secret_key_succeeds(self, seeded_nonce):
        """Gateway shared key (role=gateway) → allowed to consume."""
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah), key=GATEWAY_SECRET)
        assert resp.status_code == 200


# ===========================================================================
# Test 10: Wrong role X-Agent-Key → 403
# ===========================================================================

class TestWrongRoleAuth:
    """Only operator/gateway roles may consume nonces."""

    def test_commander_key_returns_403(self, seeded_nonce):
        """Commander has a valid key but wrong role → 403."""
        nonce, _, client, ph, ah = seeded_nonce
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah), key=COMMANDER_KEY)
        assert resp.status_code == 403
        assert "not authorized" in resp.json()["detail"].lower()


# ===========================================================================
# Test 11: Incident-room Publish Failures & Resumption
# ===========================================================================

class TestRoomFailuresAndLifecycle:
    def test_room_failure_preserves_pending_state(self, seeded_nonce):
        """If room publication fails, auth remains PENDING, incident remains PLANNED."""
        nonce, db, client, ph, ah = seeded_nonce

        with patch("gateway.routes.nonce.store_room_message", side_effect=RuntimeError("room down")):
            resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))
            assert resp.status_code == 502
            assert "room down" not in resp.json()["detail"]
            assert "PENDING" in resp.json()["detail"]

        # Card is sealed and un-published
        card = db.execute("SELECT published_at FROM cards WHERE incident_id=? AND card_type='StructuredApproval'", (INCIDENT_ID,)).fetchone()
        assert card["published_at"] is None

        # Auth is PENDING
        auth = db.execute("SELECT status, consumed_by, nonce FROM authorizations WHERE incident_id=? AND authorization_type='human_approval'", (INCIDENT_ID,)).fetchone()
        assert auth["status"] == "PENDING"
        assert auth["consumed_by"] == VALID_SENDER
        assert auth["nonce"] == nonce

        # Incident is PLANNED
        inc = db.execute("SELECT state FROM incidents WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert inc["state"] == "PLANNED"
        
        # Nonce is consumed
        n = db.execute("SELECT consumed FROM nonces WHERE incident_id=? AND nonce=?", (INCIDENT_ID, nonce)).fetchone()
        assert n["consumed"] == 1

    def test_resume_publication_after_failure(self, seeded_nonce):
        """Retrying after room publication failure resumes publication successfully."""
        nonce, db, client, ph, ah = seeded_nonce

        # 1. Fail first attempt
        with patch("gateway.routes.nonce.store_room_message", side_effect=RuntimeError("room down")):
            _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))

        # 2. Retry succeeds (autouse mock returns 200)
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))
        assert resp.status_code == 200

        # Assert state advanced
        auth = db.execute("SELECT status FROM authorizations WHERE incident_id=? AND authorization_type='human_approval'", (INCIDENT_ID,)).fetchone()
        assert auth["status"] == "PUBLISHED"
        inc = db.execute("SELECT state FROM incidents WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert inc["state"] == "APPROVED"

        # Assert no duplicate cards or auths created
        card_count = db.execute("SELECT COUNT(*) as c FROM cards WHERE incident_id=? AND card_type='StructuredApproval'", (INCIDENT_ID,)).fetchone()["c"]
        assert card_count == 1
        auth_count = db.execute("SELECT COUNT(*) as c FROM authorizations WHERE incident_id=? AND authorization_type='human_approval'", (INCIDENT_ID,)).fetchone()["c"]
        assert auth_count == 1

    def test_mixed_lifecycle_rejected(self, seeded_nonce):
        """If auth is PENDING but incident is already APPROVED (mixed state), fail closed."""
        nonce, db, client, ph, ah = seeded_nonce

        # 1. Fail first attempt to create PENDING auth
        with patch("gateway.routes.nonce.store_room_message", side_effect=RuntimeError("room down")):
            _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))

        # 2. Manually mutate DB to mixed state (incident APPROVED, auth PENDING)
        db.execute("UPDATE incidents SET state='APPROVED' WHERE incident_id=?", (INCIDENT_ID,))

        # 3. Retry should fail closed
        resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))
        assert resp.status_code == 409
        assert "inconsistent_lifecycle" in resp.json()["detail"].lower()

    def test_retry_wrong_approver_rejected(self, seeded_nonce):
        """Retrying a pending nonce with a different approver ID is rejected."""
        nonce, db, client, ph, ah = seeded_nonce

        # 1. Fail first attempt by VALID_SENDER
        with patch("gateway.routes.nonce.store_room_message", side_effect=RuntimeError("room down")):
            _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah))

        # 2. Add a second approver to the allowlist
        with patch("gateway.routes.nonce.HUMAN_APPROVER_IDS", frozenset({VALID_SENDER, "other-approver-002"})):
            # 3. Retry by other approver
            resp = _post(client, _make_body(nonce, plan_hash=ph, action_hash=ah, consumed_by="other-approver-002"))
            assert resp.status_code == 403
            assert "approver mismatch" in resp.json()["detail"].lower()

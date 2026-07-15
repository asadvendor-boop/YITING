"""Tests for POST /api/authorization/request — PolicyAuthorization endpoint.

Drives the REAL HTTP route via TestClient against a real SQLite :memory: DB.
Validates:
    1. Nested transaction crash is fixed (seal_card owns its own transaction)
    2. Risk level derived from stored ResponsePlan, NOT request body
    3. Envelopes/action_hash derived from stored ResponsePlan
    4. plan_hash cross-check is fail-closed
    5. Idempotent replay returns stored authorization_id
    6. State transitions: PLANNED → AUTHORIZED
    7. Auth: only commander role can call
    8. Rejects high-risk plans
    9. Rejects if requires_human_approval=True
"""
from __future__ import annotations

import json
import os
import sqlite3
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.database import SCHEMA, _migrate
from shared.approval import compute_action_hash, compute_plan_hash
from shared.integrity import seal_card
from shared.models import ExecutionEnvelope, ResponsePlan as RPModel


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INCIDENT_ID = "INC-AUTH-TEST-001"
COMMANDER_KEY = "test-commander-key-xyz"
OPERATOR_KEY = "test-operator-key-abc123"
GATEWAY_SECRET = "test-gateway-secret"
ROOM_ID = "room-auth-test-001"
ROOM_ALIAS_ID = ROOM_ID  # Compatibility alias while schema cleanup is pending.
OPERATOR_AGENT_ID = "test-operator-agent-id-001"
RECORDER_API_KEY = "test-recorder-api-key-001"

ENVELOPES = [
    {"action_id": "restart_service", "target": "api-server",
     "parameters": {"grace_period_seconds": 30}, "timeout_seconds": 120},
]
ACTION_HASH = compute_action_hash(ENVELOPES)

# Build a model to get the exact card_json shape (same as what Gateway reads)
_rp_model = RPModel(
    incident_id=INCIDENT_ID,
    runbook="RB-001",
    envelopes=[ExecutionEnvelope(**e) for e in ENVELOPES],
    risk_level="low",
    requires_human_approval=False,
    revision=1,
)
# plan_hash is computed from model_dump(mode='json') — that's what's in card_json
PLAN_DATA = _rp_model.model_dump(mode="json")
PLAN_HASH = compute_plan_hash(PLAN_DATA)

# High-risk plan (model-based so hash matches)
_hr_model = RPModel(
    incident_id=INCIDENT_ID,
    runbook="RB-001",
    envelopes=[ExecutionEnvelope(**e) for e in ENVELOPES],
    risk_level="high",
    requires_human_approval=True,
    revision=1,
)
HIGH_RISK_PLAN = _hr_model.model_dump(mode="json")
HIGH_RISK_PLAN_HASH = compute_plan_hash(HIGH_RISK_PLAN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_body(**overrides):
    body = {
        "incident_id": INCIDENT_ID,
        "plan_hash": PLAN_HASH,
    }
    body.update(overrides)
    return body


def _post(client, body, key=COMMANDER_KEY):
    return client.post(
        "/api/authorization/request",
        json=body,
        headers={"X-Agent-Key": key},
    )


def _seed_incident_and_plan(db, *, state="PLANNED", plan_data=None):
    """Insert incident in given state + confirmed ResponsePlan."""
    now = datetime.now(timezone.utc).isoformat()
    pd = plan_data or PLAN_DATA

    db.execute(
        "INSERT OR REPLACE INTO incidents "
        "(incident_id, state, severity, room_id, room_alias_id, created_at, updated_at) "
        "VALUES (?, ?, 'P2', ?, ?, ?, ?)",
        (INCIDENT_ID, state, ROOM_ID, ROOM_ALIAS_ID, now, now),
    )
    db.execute(
        "INSERT OR REPLACE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, 'recorder', ?, ?)",
        (ROOM_ID, INCIDENT_ID, "Authorization test room", now, now),
    )

    # Create ExecutionEnvelope objects from dict data
    envelope_objs = [
        ExecutionEnvelope(**env) for env in pd.get("envelopes", ENVELOPES)
    ]

    # Create a ResponsePlan card using the model
    rp = RPModel(
        incident_id=INCIDENT_ID,
        runbook="RB-001",
        envelopes=envelope_objs,
        risk_level=pd.get("risk_level", "low"),
        requires_human_approval=pd.get("requires_human_approval", False),
        revision=1,
    )
    sealed = seal_card(rp, INCIDENT_ID, db, prepared_by_role="commander")
    # Confirm the card
    db.execute(
        "UPDATE cards SET published_at=? WHERE card_hash=? AND incident_id=?",
        (now, sealed.card_hash, INCIDENT_ID),
    )
    return sealed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_and_db():
    env_patches = {
        "OPERATOR_SUBMISSION_KEY": OPERATOR_KEY,
        "COMMANDER_SUBMISSION_KEY": COMMANDER_KEY,
        "GATEWAY_SECRET": GATEWAY_SECRET,
        "OPERATOR_AGENT_ID": OPERATOR_AGENT_ID,
        "RECORDER_API_KEY": RECORDER_API_KEY,
    }
    with patch.dict(os.environ, env_patches):
        app = create_app(db_path=":memory:")
        import gateway.routes.submission as sub_mod
        sub_mod._agent_keys = None

        db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        _migrate(db)
        app.state.db = db
        app.state._db_path = None
        yield app, db
        sub_mod._agent_keys = None


@pytest.fixture
def client(app_and_db):
    app, _ = app_and_db
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def noop_lifespan(app):
        yield
    app.router.lifespan_context = noop_lifespan
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded(app_and_db, client):
    """Seed DB with PLANNED incident + confirmed ResponsePlan.
    Publication uses the Gateway-owned incident room."""
    _, db = app_and_db
    _seed_incident_and_plan(db)
    yield client, db


# ---------------------------------------------------------------------------
# Tests: Nested transaction fix (Bug #1 — proven crash)
# ---------------------------------------------------------------------------

class TestNestedTransactionFix:
    """The old code wrapped seal_card in an outer BEGIN IMMEDIATE.
    seal_card also does BEGIN IMMEDIATE → sqlite3.OperationalError.
    These tests prove the crash is fixed."""

    def test_first_call_does_not_crash(self, seeded):
        """POST to /authorization/request should not 500 with
        'cannot start a transaction within a transaction'."""
        client, db = seeded
        resp = _post(client, _make_body())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["authorized"] is True
        assert data["new_state"] == "AUTHORIZED"

    def test_state_actually_advances(self, seeded):
        """After successful auth, incident state must be AUTHORIZED."""
        client, db = seeded
        resp = _post(client, _make_body())
        assert resp.status_code == 200

        row = db.execute(
            "SELECT state FROM incidents WHERE incident_id=?",
            (INCIDENT_ID,),
        ).fetchone()
        assert row["state"] == "AUTHORIZED"

    def test_authorization_record_created(self, seeded):
        """An authorization record must exist for consumption tracking."""
        client, db = seeded
        resp = _post(client, _make_body())
        assert resp.status_code == 200
        data = resp.json()

        auth = db.execute(
            "SELECT * FROM authorizations WHERE authorization_id=?",
            (data["authorization_id"],),
        ).fetchone()
        assert auth is not None
        assert auth["consumed"] == 0
        assert auth["authorization_type"] == "policy"

    def test_card_sealed_into_chain(self, seeded):
        """PolicyAuthorization card must exist in the cards table."""
        client, db = seeded
        resp = _post(client, _make_body())
        assert resp.status_code == 200

        card = db.execute(
            "SELECT * FROM cards WHERE incident_id=? AND card_type='PolicyAuthorization'",
            (INCIDENT_ID,),
        ).fetchone()
        assert card is not None
        assert card["prepared_by_role"] == "gateway"
        assert card["published_at"] is not None  # Auto-confirmed


# ---------------------------------------------------------------------------
# Tests: Risk bypass prevention (Bug #2 — security)
# ---------------------------------------------------------------------------

class TestRiskBypassPrevention:
    """Gateway MUST derive risk from stored ResponsePlan.
    A Commander sending risk_level:'low' for a high-risk plan
    must be rejected."""

    def test_high_risk_plan_rejected(self, app_and_db, client):
        """Plan with risk_level=high → 403 (requires human approval)."""
        _, db = app_and_db
        _seed_incident_and_plan(db, plan_data=HIGH_RISK_PLAN)

        # Commander tries to get PolicyAuth for a high-risk plan
        resp = _post(client, _make_body(plan_hash=HIGH_RISK_PLAN_HASH))
        assert resp.status_code == 403
        assert "high" in resp.json()["detail"].lower()

    def test_requires_human_rejected(self, app_and_db, client):
        """Plan with requires_human_approval=True → 403."""
        _, db = app_and_db
        hr_model = RPModel(
            incident_id=INCIDENT_ID,
            runbook="RB-001",
            envelopes=[ExecutionEnvelope(**e) for e in ENVELOPES],
            risk_level="medium",
            requires_human_approval=True,
            revision=1,
        )
        plan = hr_model.model_dump(mode="json")
        plan_hash = compute_plan_hash(plan)
        _seed_incident_and_plan(db, plan_data=plan)

        resp = _post(client, _make_body(plan_hash=plan_hash))
        assert resp.status_code == 403
        assert "human approval" in resp.json()["detail"].lower()

    def test_envelopes_from_stored_plan(self, seeded):
        """Envelopes in auth record must match stored ResponsePlan,
        not any commander-supplied values."""
        client, db = seeded
        resp = _post(client, _make_body())
        assert resp.status_code == 200

        auth = db.execute(
            "SELECT envelopes_json FROM authorizations WHERE incident_id=?",
            (INCIDENT_ID,),
        ).fetchone()

        stored_envelopes = json.loads(auth["envelopes_json"])
        assert len(stored_envelopes) == len(ENVELOPES)
        # Check that each envelope has the right action_id and target
        for stored, expected in zip(stored_envelopes, ENVELOPES):
            assert stored["action_id"] == expected["action_id"]
            assert stored["target"] == expected["target"]
            assert stored["parameters"] == expected["parameters"]


# ---------------------------------------------------------------------------
# Tests: plan_hash fail-closed
# ---------------------------------------------------------------------------

class TestPlanHashValidation:
    def test_mismatched_hash_rejected(self, seeded):
        """Wrong plan_hash → 400."""
        client, db = seeded
        resp = _post(client, _make_body(plan_hash="wrong-hash-12345"))
        assert resp.status_code == 400
        assert "mismatch" in resp.json()["detail"].lower()

    def test_no_confirmed_plan_rejected(self, app_and_db, client):
        """No confirmed ResponsePlan → 409."""
        _, db = app_and_db
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO incidents (incident_id, state, severity, created_at, updated_at) "
            "VALUES (?, 'PLANNED', 'P2', ?, ?)",
            (INCIDENT_ID, now, now),
        )
        resp = _post(client, _make_body())
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Tests: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_replay_returns_stored_auth_id(self, seeded):
        """Two identical calls → same authorization_id, no crash."""
        client, db = seeded
        resp1 = _post(client, _make_body())
        assert resp1.status_code == 200
        data1 = resp1.json()

        resp2 = _post(client, _make_body())
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data1["authorization_id"] == data2["authorization_id"]
        assert data1["card_hash"] == data2["card_hash"]


# ---------------------------------------------------------------------------
# Tests: Auth / ACL
# ---------------------------------------------------------------------------

class TestACL:
    def test_operator_key_rejected(self, seeded):
        """Operator role cannot request PolicyAuth."""
        client, _ = seeded
        resp = _post(client, _make_body(), key=OPERATOR_KEY)
        assert resp.status_code == 403

    def test_invalid_key_rejected(self, seeded):
        """Unknown key → 401."""
        client, _ = seeded
        resp = _post(client, _make_body(), key="bad-key")
        assert resp.status_code == 401

    def test_missing_key_rejected(self, seeded):
        """No X-Agent-Key header → 422 (FastAPI validation)."""
        client, _ = seeded
        resp = client.post("/api/authorization/request", json=_make_body())
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: State prerequisites
# ---------------------------------------------------------------------------

class TestStatePrerequisites:
    def test_wrong_state_rejected(self, app_and_db, client):
        """Incident not in PLANNED → 409."""
        _, db = app_and_db
        _seed_incident_and_plan(db, state="ASSESSED")
        resp = _post(client, _make_body())
        assert resp.status_code == 409
        assert "state" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests: Incident-Room Publish Failures & Resumption
# ---------------------------------------------------------------------------

class TestRoomPublicationFailuresAndLifecycle:
    def test_room_failure_preserves_pending_state(self, seeded):
        """If room publish fails, auth remains PENDING, incident remains PLANNED."""
        client, db = seeded

        with patch(
            "gateway.routes.authorization.store_room_message",
            side_effect=Exception("room down"),
        ):
            resp = _post(client, _make_body())
            assert resp.status_code == 502
            detail = resp.json()["detail"]
            assert "PENDING" in detail
            assert "room down" not in detail, (
                "Upstream exception bodies must not be exposed to callers"
            )

        # Card is sealed and un-published
        card = db.execute("SELECT published_at FROM cards WHERE incident_id=? AND card_type='PolicyAuthorization'", (INCIDENT_ID,)).fetchone()
        assert card["published_at"] is None

        # Auth is PENDING
        auth = db.execute("SELECT status FROM authorizations WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert auth["status"] == "PENDING"

        # Incident is PLANNED
        inc = db.execute("SELECT state FROM incidents WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert inc["state"] == "PLANNED"

    def test_resume_publication_after_failure(self, seeded):
        """Retrying after room publish failure resumes publication successfully."""
        client, db = seeded

        # 1. Fail first attempt
        with patch(
            "gateway.routes.authorization.store_room_message",
            side_effect=Exception("room down"),
        ):
            _post(client, _make_body())

        # 2. Retry succeeds using the local incident room.
        resp = _post(client, _make_body())
        assert resp.status_code == 200

        # Assert state advanced
        auth = db.execute("SELECT status FROM authorizations WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert auth["status"] == "PUBLISHED"
        inc = db.execute("SELECT state FROM incidents WHERE incident_id=?", (INCIDENT_ID,)).fetchone()
        assert inc["state"] == "AUTHORIZED"

        # Assert no duplicate cards or auths created
        card_count = db.execute("SELECT COUNT(*) as c FROM cards WHERE incident_id=? AND card_type='PolicyAuthorization'", (INCIDENT_ID,)).fetchone()["c"]
        assert card_count == 1
        auth_count = db.execute("SELECT COUNT(*) as c FROM authorizations WHERE incident_id=?", (INCIDENT_ID,)).fetchone()["c"]
        assert auth_count == 1

    def test_mixed_lifecycle_rejected(self, seeded):
        """If auth is PENDING but incident is already AUTHORIZED (mixed state), fail closed."""
        client, db = seeded

        # 1. Fail first attempt to create PENDING auth
        with patch(
            "gateway.routes.authorization.store_room_message",
            side_effect=Exception("room down"),
        ):
            _post(client, _make_body())

        # 2. Manually mutate DB to mixed state (incident AUTHORIZED, auth PENDING)
        db.execute("UPDATE incidents SET state='AUTHORIZED' WHERE incident_id=?", (INCIDENT_ID,))

        # 3. Retry should fail closed
        resp = _post(client, _make_body())
        assert resp.status_code == 409
        assert "expected 'planned'" in resp.json()["detail"].lower()

    def test_unknown_incident_rejected(self, client):
        """Unknown incident → 404."""
        resp = _post(client, _make_body(incident_id="nonexistent"))
        assert resp.status_code == 404

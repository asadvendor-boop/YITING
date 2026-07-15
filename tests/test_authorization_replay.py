"""Regression tests for crash-recovery authorization replay.

The Operator consumes its authorization BEFORE executing envelopes. If the
process crashes between consume and execution, the redelivered authorization
card triggers a re-consume of a now-CONSUMED authorization. The old endpoint
answered 409 for every re-consume, so the restarted Operator could never
rebuild its execution context: the incident stayed authorized-but-unexecuted
forever.

The fix: a re-consume by the SAME consumer role within the validity window is
acknowledged idempotently (200 + identical payload + replayed=true). It grants
no new authority — hash binding and expiry are still enforced, a different
consumer is still refused, and the victim app's already_applied guard keeps
re-execution idempotent.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.database import SCHEMA, _migrate
from shared.approval import compute_action_hash, compute_plan_hash
from shared.integrity import seal_card
from shared.models import ExecutionEnvelope, ResponsePlan as RPModel

INCIDENT_ID = "INC-REPLAY-TEST-001"
AUTH_ID = "auth-replay-test-001"
COMMANDER_KEY = "test-commander-key-xyz"
OPERATOR_KEY = "test-operator-key-abc123"
GATEWAY_SECRET = "test-gateway-secret"
ROOM_ID = "room-replay-test-001"

ENVELOPES = [
    {"action_id": "restart_service", "target": "api-server",
     "parameters": {"grace_period_seconds": 30}, "timeout_seconds": 120},
]

_rp_model = RPModel(
    incident_id=INCIDENT_ID,
    runbook="RB-001",
    envelopes=[ExecutionEnvelope(**e) for e in ENVELOPES],
    risk_level="low",
    requires_human_approval=False,
    revision=1,
)
PLAN_DATA = _rp_model.model_dump(mode="json")
PLAN_HASH = compute_plan_hash(PLAN_DATA)
# The endpoint recomputes the action hash from the SEALED plan's envelopes
# (full model dump, defaults included) — mirror that exactly.
SEALED_ENVELOPES = PLAN_DATA["envelopes"]
ACTION_HASH = compute_action_hash(SEALED_ENVELOPES)


@pytest.fixture
def app_and_db():
    env_patches = {
        "OPERATOR_SUBMISSION_KEY": OPERATOR_KEY,
        "COMMANDER_SUBMISSION_KEY": COMMANDER_KEY,
        "GATEWAY_SECRET": GATEWAY_SECRET,
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


def _seed_incident_plan_and_auth(
    db,
    *,
    status: str = "PUBLISHED",
    consumed_by: str | None = None,
    expiry: datetime | None = None,
    auth_plan_hash: str = PLAN_HASH,
):
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    expiry_iso = (expiry or (now + timedelta(minutes=10))).isoformat()

    db.execute(
        "INSERT OR REPLACE INTO incidents "
        "(incident_id, state, severity, room_id, room_alias_id, created_at, updated_at) "
        "VALUES (?, 'AUTHORIZED', 'P2', ?, ?, ?, ?)",
        (INCIDENT_ID, ROOM_ID, ROOM_ID, now_iso, now_iso),
    )
    db.execute(
        "INSERT OR REPLACE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, 'Replay test room', 'recorder', ?, ?)",
        (ROOM_ID, INCIDENT_ID, now_iso, now_iso),
    )
    sealed = seal_card(_rp_model, INCIDENT_ID, db, prepared_by_role="commander")
    db.execute(
        "UPDATE cards SET published_at=? WHERE card_hash=? AND incident_id=?",
        (now_iso, sealed.card_hash, INCIDENT_ID),
    )
    db.execute(
        "INSERT OR REPLACE INTO authorizations "
        "(authorization_id, incident_id, authorization_type, plan_hash, action_hash, "
        " envelopes_json, expiry, consumed, consumed_at, consumed_by, status) "
        "VALUES (?, ?, 'policy', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            AUTH_ID,
            INCIDENT_ID,
            auth_plan_hash,
            ACTION_HASH,
            json.dumps(SEALED_ENVELOPES),
            expiry_iso,
            1 if status == "CONSUMED" else 0,
            now_iso if status == "CONSUMED" else None,
            consumed_by,
            status,
        ),
    )


def _consume(client, key=OPERATOR_KEY):
    return client.post(
        f"/api/authorization/{AUTH_ID}/consume",
        json={"incident_id": INCIDENT_ID},
        headers={"X-Agent-Key": key},
    )


class TestOperatorReplayRecovery:
    def test_same_operator_replay_is_idempotent(self, app_and_db, client):
        """Consume, then simulate the restarted Operator re-consuming."""
        _, db = app_and_db
        _seed_incident_plan_and_auth(db)

        first = _consume(client)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["replayed"] is False
        assert body["envelopes"] == SEALED_ENVELOPES

        # Crash happens here: execution context lost. The redelivered card
        # makes the restarted Operator consume again with the same key.
        replay = _consume(client)
        assert replay.status_code == 200, replay.text
        replay_body = replay.json()
        assert replay_body["replayed"] is True
        assert replay_body["envelopes"] == SEALED_ENVELOPES
        assert replay_body["plan_hash"] == body["plan_hash"]
        assert replay_body["action_hash"] == body["action_hash"]

        # The authorization was consumed exactly once.
        row = db.execute(
            "SELECT status, consumed, consumed_by FROM authorizations "
            "WHERE authorization_id=?",
            (AUTH_ID,),
        ).fetchone()
        assert row["status"] == "CONSUMED"
        assert row["consumed"] == 1
        assert row["consumed_by"] == "operator"

    def test_different_consumer_replay_is_refused(self, app_and_db, client):
        """A consumer with a different role cannot piggyback on the replay path."""
        _, db = app_and_db
        _seed_incident_plan_and_auth(db)

        assert _consume(client).status_code == 200

        other = _consume(client, key=GATEWAY_SECRET)  # role 'gateway'
        assert other.status_code == 409
        assert "already_consumed" in other.json()["detail"]

    def test_expired_authorization_replay_is_refused(self, app_and_db, client):
        """The replay window closes with the authorization's own expiry."""
        _, db = app_and_db
        _seed_incident_plan_and_auth(
            db,
            status="CONSUMED",
            consumed_by="operator",
            expiry=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        replay = _consume(client)
        assert replay.status_code == 410

    def test_replay_still_hash_bound(self, app_and_db, client):
        """A replay is refused if the stored plan no longer matches the grant."""
        _, db = app_and_db
        _seed_incident_plan_and_auth(
            db,
            status="CONSUMED",
            consumed_by="operator",
            auth_plan_hash="tampered-" + PLAN_HASH[:32],
        )

        replay = _consume(client)
        assert replay.status_code == 409
        assert "plan_hash mismatch" in replay.json()["detail"]

    def test_pending_authorization_still_pending(self, app_and_db, client):
        """The replay path does not weaken the PENDING gate."""
        _, db = app_and_db
        _seed_incident_plan_and_auth(db, status="PENDING")

        resp = _consume(client)
        assert resp.status_code == 409
        assert "authorization_pending" in resp.json()["detail"]

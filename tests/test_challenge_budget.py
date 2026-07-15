"""Tests for the Gateway-side persistent challenge budget.

The Safety Reviewer self-caps at 2 challenges, but that counter lives in
process memory. The sealed room ledger is the durable budget: the Gateway
refuses a third CHALLENGE Verdict at prepare time, so no agent restart or
misbehaving client can drive unlimited CHALLENGED->ASSESSED cycles.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.database import SCHEMA, _migrate
from shared.integrity import seal_card
from shared.models import Verdict

INCIDENT_ID = "INC-BUDGET-TEST-001"
SAFETY_KEY = "test-safety-reviewer-key-001"
GATEWAY_SECRET = "test-gateway-secret"
ROOM_ID = "room-budget-test-001"


@pytest.fixture
def app_and_db():
    env_patches = {
        "SAFETY_REVIEWER_SUBMISSION_KEY": SAFETY_KEY,
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


def _seed_incident(db, *, state="ASSESSED", sealed_challenges=0):
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT OR REPLACE INTO incidents "
        "(incident_id, state, severity, room_id, room_alias_id, created_at, updated_at) "
        "VALUES (?, ?, 'P2', ?, ?, ?, ?)",
        (INCIDENT_ID, state, ROOM_ID, ROOM_ID, now, now),
    )
    db.execute(
        "INSERT OR REPLACE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, 'Budget test room', 'recorder', ?, ?)",
        (ROOM_ID, INCIDENT_ID, now, now),
    )
    for index in range(sealed_challenges):
        verdict = Verdict(
            incident_id=INCIDENT_ID,
            decision="CHALLENGE",
            reasoning=f"Sealed challenge {index + 1}",
            agrees_with_diagnosis=False,
            challenge_request=f"Re-check source {index + 1}",
        )
        sealed = seal_card(verdict, INCIDENT_ID, db, prepared_by_role="safety_reviewer")
        db.execute(
            "UPDATE cards SET published_at=? WHERE card_hash=? AND incident_id=?",
            (now, sealed.card_hash, INCIDENT_ID),
        )


def _prepare_challenge(client, reasoning="Fresh challenge"):
    return client.post(
        "/api/prepare/Verdict",
        json={
            "incident_id": INCIDENT_ID,
            "decision": "CHALLENGE",
            "reasoning": reasoning,
            "agrees_with_diagnosis": False,
            "challenge_request": "Provide stronger evidence",
        },
        headers={"X-Agent-Key": SAFETY_KEY},
    )


class TestPersistentChallengeBudget:
    def test_challenges_within_budget_are_accepted(self, app_and_db, client):
        _, db = app_and_db
        _seed_incident(db, sealed_challenges=1)

        resp = _prepare_challenge(client)
        assert resp.status_code == 200, resp.text

    def test_third_challenge_is_refused_at_the_gateway(self, app_and_db, client):
        _, db = app_and_db
        _seed_incident(db, sealed_challenges=2)

        resp = _prepare_challenge(client)
        assert resp.status_code == 409
        assert "Challenge budget exhausted" in resp.json()["detail"]

    def test_needs_human_escape_hatch_stays_open(self, app_and_db, client):
        """When the budget is exhausted the escalation path must still work."""
        _, db = app_and_db
        _seed_incident(db, sealed_challenges=2)

        resp = client.post(
            "/api/prepare/Verdict",
            json={
                "incident_id": INCIDENT_ID,
                "decision": "NEEDS_HUMAN",
                "reasoning": "Budget exhausted; escalating to a human.",
                "agrees_with_diagnosis": False,
            },
            headers={"X-Agent-Key": SAFETY_KEY},
        )
        assert resp.status_code == 200, resp.text

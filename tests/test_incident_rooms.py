"""Tests for Gateway-owned incident rooms.

These tests pin the local collaboration substrate that replaces the external
room service in the Alibaba/Qwen fork. They deliberately exercise the HTTP
routes instead of direct helper calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from gateway.auth import _reset_for_testing
from shared.integrity import seal_card
from shared.models import (
    ActionReceipt,
    AlertCard,
    Assessment,
    ExecutionEnvelope,
    ResponsePlan,
    StructuredApproval,
    TriageDecision,
    Verdict,
)


@pytest.fixture
def room_client(tmp_path, monkeypatch):
    import sqlite3

    _reset_for_testing()
    monkeypatch.setenv("YITING_TEST_MODE", "true")
    monkeypatch.setenv("RECORDER_SUBMISSION_KEY", "recorder-key")
    monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "triage-key")
    monkeypatch.setenv("GATEWAY_SECRET", "gateway-key")

    from gateway.app import create_app
    from gateway.database import SCHEMA, _migrate

    app = create_app()
    db = sqlite3.connect(
        str(tmp_path / "rooms.db"),
        isolation_level=None,
        check_same_thread=False,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    app.state.db = db

    client = TestClient(app)
    yield client, app

    db.close()
    _reset_for_testing()


def _insert_incident(app, incident_id: str = "INC-ROOM-001") -> None:
    now = datetime.now(timezone.utc).isoformat()
    app.state.db.execute(
        """
        INSERT INTO incidents (incident_id, state, severity, created_at, updated_at)
        VALUES (?, 'DETECTED', 'P3', ?, ?)
        """,
        (incident_id, now, now),
    )


def _seal_and_publish(app, incident_id: str, card, role: str):
    sealed = seal_card(card, incident_id, app.state.db, prepared_by_role=role)
    app.state.db.execute(
        "UPDATE cards SET published_at=?, room_message_id=? WHERE card_hash=?",
        (
            datetime.now(timezone.utc).isoformat(),
            f"msg-{sealed.sequence_number}",
            sealed.card_hash,
        ),
    )
    return sealed


class TestIncidentRooms:
    def test_create_room_requires_agent_key(self, room_client):
        client, _app = room_client

        resp = client.post(
            "/api/rooms",
            json={"title": "P3 Incident", "incident_id": "INC-NOAUTH"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid_agent_key"

    def test_create_room_updates_incident_room_aliases(self, room_client):
        client, app = room_client
        _insert_incident(app)

        resp = client.post(
            "/api/rooms",
            json={"title": "P3 Incident", "incident_id": "INC-ROOM-001"},
            headers={"X-Agent-Key": "recorder-key"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["room_id"].startswith("room-")

        incident = app.state.db.execute(
            "SELECT room_id, room_alias_id FROM incidents WHERE incident_id='INC-ROOM-001'"
        ).fetchone()
        assert incident["room_id"] == data["room_id"]
        # Temporary compatibility alias while remaining publish paths are moved.
        assert incident["room_alias_id"] == data["room_id"]

    def test_create_room_for_same_incident_is_idempotent(self, room_client):
        client, _app = room_client
        _insert_incident(_app)

        first = client.post(
            "/api/rooms",
            json={"title": "Original Title", "incident_id": "INC-ROOM-001"},
            headers={"X-Agent-Key": "recorder-key"},
        )
        second = client.post(
            "/api/rooms",
            json={"title": "Retry Title", "incident_id": "INC-ROOM-001"},
            headers={"X-Agent-Key": "recorder-key"},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == "already_exists"
        assert second.json()["room_id"] == first.json()["room_id"]

    def test_participants_and_messages_are_persisted(self, room_client):
        client, app = room_client
        _insert_incident(app)
        room_id = client.post(
            "/api/rooms",
            json={"title": "Room With Messages", "incident_id": "INC-ROOM-001"},
            headers={"X-Agent-Key": "recorder-key"},
        ).json()["room_id"]

        participant = client.post(
            f"/api/rooms/{room_id}/participants",
            json={
                "participant_id": "agent-triage",
                "role": "triage",
                "display_name": "Li Wei",
            },
            headers={"X-Agent-Key": "recorder-key"},
        )
        assert participant.status_code == 200
        assert participant.json()["participant"]["role"] == "triage"

        message = client.post(
            f"/api/rooms/{room_id}/messages",
            json={
                "content": "Assessment ready [source: metrics]",
                "sender_id": "agent-triage",
                "sender_role": "triage",
                "mentions": ["diagnosis"],
                "message_type": "card",
                "metadata": {"card_type": "TriageDecision"},
            },
            headers={"X-Agent-Key": "triage-key"},
        )
        assert message.status_code == 200
        assert message.json()["message_id"].startswith("msg-")

        listed = client.get(
            f"/api/rooms/{room_id}/messages",
            headers={"X-Agent-Key": "recorder-key"},
        )
        assert listed.status_code == 200
        assert listed.json()["message_count"] == 1
        assert listed.json()["messages"][0]["metadata"]["card_type"] == "TriageDecision"

    def test_dashboard_room_messages_are_sanitized(self, room_client):
        client, app = room_client
        _insert_incident(app)
        room_id = client.post(
            "/api/rooms",
            json={"title": "Public Room View", "incident_id": "INC-ROOM-001"},
            headers={"X-Agent-Key": "recorder-key"},
        ).json()["room_id"]

        raw_auth_id = "550e8400-e29b-41d4-a716-446655440000"
        client.post(
            f"/api/rooms/{room_id}/messages",
            json={
                "content": (
                    f'Approve nonce="ABC123" '
                    f"authorization_id={raw_auth_id} "
                    "https://example.test/approve?nonce=SECRET123"
                ),
                "sender_id": "agent-recorder",
                "sender_role": "recorder",
            },
            headers={"X-Agent-Key": "recorder-key"},
        )

        public = client.get("/room-messages/INC-ROOM-001")

        assert public.status_code == 200
        content = public.json()["messages"][0]["content"]
        assert "ABC123" not in content
        assert "SECRET123" not in content
        assert raw_auth_id not in content
        assert "[REDACTED]" in content

    def test_evidence_export_includes_track3_collaboration_analysis(self, room_client):
        client, app = room_client
        incident_id = "INC-COLLAB-001"
        _insert_incident(app, incident_id)
        now = datetime.now(timezone.utc)
        envelope = ExecutionEnvelope(
            action_id="restart_service",
            target="checkout",
            parameters={"replicas": 2},
        )

        _seal_and_publish(
            app,
            incident_id,
            AlertCard(
                alert_id="alert-1",
                source="metrics",
                timestamp=now,
                title="Checkout error spike",
                raw_payload={"metric_name": "checkout_errors", "service": "checkout"},
                fingerprint="fp-collab",
                preliminary_severity="P2",
            ),
            "recorder",
        )
        _seal_and_publish(
            app,
            incident_id,
            TriageDecision(
                incident_id=incident_id,
                alert_id="alert-1",
                decision="route",
                reasoning="Route to Diagnosis.",
            ),
            "triage",
        )
        _seal_and_publish(
            app,
            incident_id,
            Assessment(
                incident_id=incident_id,
                severity="P2",
                evidence_strength=0.5,
                root_cause_hypothesis="Checkout dependency regression.",
                recommended_action="Restart checkout.",
            ),
            "diagnosis",
        )
        _seal_and_publish(
            app,
            incident_id,
            Verdict(
                incident_id=incident_id,
                decision="CHALLENGE",
                reasoning="Evidence strength is weak.",
                agrees_with_diagnosis=False,
                challenge_request="Re-check deploy and metrics.",
            ),
            "safety_reviewer",
        )
        _seal_and_publish(
            app,
            incident_id,
            Assessment(
                incident_id=incident_id,
                severity="P2",
                evidence_strength=0.9,
                root_cause_hypothesis="Checkout dependency regression confirmed.",
                recommended_action="Restart checkout.",
                revision=2,
            ),
            "diagnosis",
        )
        _seal_and_publish(
            app,
            incident_id,
            ResponsePlan(
                incident_id=incident_id,
                runbook="RB-001",
                envelopes=[envelope],
                risk_level="high",
                requires_human_approval=True,
            ),
            "commander",
        )
        _seal_and_publish(
            app,
            incident_id,
            StructuredApproval(
                incident_id=incident_id,
                action_id="restart_service",
                action_hash="action-hash",
                decision="APPROVED",
                approver_id="human-1",
                plan_hash="plan-hash",
                nonce="ABC123",
                expiry=now + timedelta(minutes=5),
                approval_channel="gateway_ui",
            ),
            "human_gateway",
        )
        _seal_and_publish(
            app,
            incident_id,
            ActionReceipt(
                incident_id=incident_id,
                authorization_type="human_approval",
                authorization_id="auth-1",
                actions_taken=[{"action_id": "restart_service", "target": "checkout"}],
                resolution_summary="Checkout recovered.",
            ),
            "operator",
        )

        resp = client.get(f"/evidence/{incident_id}")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["chain_valid"] is True
        assert payload["incident_family"] == "checkout errors"
        assert payload["alert_service"] == "checkout"
        collaboration = payload["collaboration"]
        assert collaboration["handoff_count"] >= 7
        assert collaboration["challenge_count"] == 1
        assert collaboration["challenges"][0]["sequence"] == 4
        assert collaboration["human_decision_count"] == 1
        assert collaboration["human_decisions"][0]["decision"] == "APPROVED"
        assert collaboration["authorization_path"] == "StructuredApproval"
        assert collaboration["execution_conflict_control"] == {
            "planned_actions": ["restart_service"],
            "executed_actions": ["restart_service"],
            "exact_match": True,
        }
        assert payload["cards"][0]["role"] == "wen_lu"
        assert payload["cards"][-1]["role"] == "lu_xing"


@pytest.fixture
def production_room_client(tmp_path, monkeypatch):
    """Gateway app in production-mode verification, but with local test DB."""
    import sqlite3

    _reset_for_testing()
    monkeypatch.delenv("YITING_TEST_MODE", raising=False)
    monkeypatch.setenv("RECORDER_SUBMISSION_KEY", "recorder-key")
    monkeypatch.setenv("GATEWAY_SECRET", "gateway-key")

    import gateway.routes.submission as submission
    from gateway.app import create_app
    from gateway.database import SCHEMA, _migrate

    submission._agent_keys = None
    app = create_app()
    db = sqlite3.connect(
        str(tmp_path / "production-rooms.db"),
        isolation_level=None,
        check_same_thread=False,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    app.state.db = db

    client = TestClient(app)
    yield client, app

    db.close()
    submission._agent_keys = None
    _reset_for_testing()


class TestRoomBackedConfirm:
    def test_confirm_verifies_local_room_message_in_production_mode(
        self,
        production_room_client,
    ):
        client, app = production_room_client

        from shared.models import AlertCard

        now = datetime.now(timezone.utc)
        alert = AlertCard(
            alert_id="INC-CONFIRM-ROOM",
            source="metrics",
            timestamp=now,
            title="Room-backed confirm",
            raw_payload={"metric_name": "error_rate"},
            fingerprint="fp-room-confirm",
            preliminary_severity="P3",
        )

        prepared = client.post(
            "/api/prepare/AlertCard",
            json=alert.model_dump(mode="json"),
            headers={
                "X-Agent-Key": "recorder-key",
                "X-Idempotency-Key": "room-confirm-idem",
            },
        )
        assert prepared.status_code == 200
        prepared_data = prepared.json()

        room = client.post(
            "/api/rooms",
            json={"title": "Confirm Room", "incident_id": "INC-CONFIRM-ROOM"},
            headers={"X-Agent-Key": "recorder-key"},
        )
        assert room.status_code == 200
        room_id = room.json()["room_id"]

        message = client.post(
            f"/api/rooms/{room_id}/messages",
            json={
                "content": f"sealed card hash {prepared_data['card_hash']}",
                "sender_id": "recorder-agent",
                "sender_role": "recorder",
                "metadata": {"card_hash": prepared_data["card_hash"]},
            },
            headers={"X-Agent-Key": "recorder-key"},
        )
        assert message.status_code == 200
        message_id = message.json()["message_id"]

        confirmed = client.post(
            "/api/confirm",
            json={
                "submission_id": prepared_data["submission_id"],
                "incident_id": "INC-CONFIRM-ROOM",
                "card_hash": prepared_data["card_hash"],
                "message_id": message_id,
                "room_id": room_id,
            },
            headers={"X-Agent-Key": "recorder-key"},
        )

        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
        assert confirmed.json()["message_id"] == message_id
        card = app.state.db.execute(
            "SELECT published_at, room_message_id FROM cards WHERE card_hash=?",
            (prepared_data["card_hash"],),
        ).fetchone()
        assert card["published_at"] is not None
        assert card["room_message_id"] == message_id

    def test_confirm_rejects_room_message_for_different_card(
        self,
        production_room_client,
    ):
        client, _app = production_room_client

        from shared.models import AlertCard

        now = datetime.now(timezone.utc)
        alert = AlertCard(
            alert_id="INC-CONFIRM-BAD-HASH",
            source="metrics",
            timestamp=now,
            title="Bad hash confirm",
            raw_payload={"metric_name": "latency"},
            fingerprint="fp-room-bad-hash",
            preliminary_severity="P3",
        )

        prepared = client.post(
            "/api/prepare/AlertCard",
            json=alert.model_dump(mode="json"),
            headers={
                "X-Agent-Key": "recorder-key",
                "X-Idempotency-Key": "bad-hash-idem",
            },
        ).json()
        room_id = client.post(
            "/api/rooms",
            json={"title": "Bad Hash Room", "incident_id": "INC-CONFIRM-BAD-HASH"},
            headers={"X-Agent-Key": "recorder-key"},
        ).json()["room_id"]
        message_id = client.post(
            f"/api/rooms/{room_id}/messages",
            json={
                "content": "sealed card hash not-this-card",
                "sender_role": "recorder",
                "metadata": {"card_hash": "not-this-card"},
            },
            headers={"X-Agent-Key": "recorder-key"},
        ).json()["message_id"]

        confirmed = client.post(
            "/api/confirm",
            json={
                "submission_id": prepared["submission_id"],
                "incident_id": "INC-CONFIRM-BAD-HASH",
                "card_hash": prepared["card_hash"],
                "message_id": message_id,
                "room_id": room_id,
            },
            headers={"X-Agent-Key": "recorder-key"},
        )

        assert confirmed.status_code == 409
        assert "different sealed card" in confirmed.json()["detail"]

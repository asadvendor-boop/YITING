"""Council R6 regression tests for the production code paths patched here.

These tests deliberately exercise the real functions and HTTP routes rather
than duplicating their algorithms in test-only helpers.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def production_gateway(monkeypatch):
    """Gateway client with production confirmation verification enabled."""
    import sqlite3
    from gateway.app import create_app
    from gateway.database import SCHEMA, _migrate
    import gateway.routes.submission as submission

    monkeypatch.setenv("YITING_TEST_MODE", "false")
    monkeypatch.setenv("GATEWAY_SECRET", "r6-gateway-secret")
    monkeypatch.setenv("RECORDER_AGENT_ID", "recorder-id")
    monkeypatch.setenv("RECORDER_API_KEY", "recorder-room-key")
    submission._agent_keys = None

    app = create_app(db_path=":memory:")
    db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    app.state.db = db

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    with TestClient(app) as client:
        yield client, app.state.db
    submission._agent_keys = None


def _prepare_alert(client: TestClient, alert_id: str):
    response = client.post(
        "/api/prepare/AlertCard",
        headers={
            "X-Agent-Key": "r6-gateway-secret",
            "X-Idempotency-Key": f"idem-{alert_id}",
        },
        json={
            "alert_id": alert_id,
            "source": "metrics",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "title": "R6 verification alert",
            "raw_payload": {"signal": "test"},
            "fingerprint": f"fp-{alert_id}",
            "preliminary_severity": "P2",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestConfirmPublicationLookup:
    def test_production_confirm_verifies_room_message(self, production_gateway):
        client, db = production_gateway
        prepared = _prepare_alert(client, "INC-R6-CONFIRM")
        message_id = "msg-550e8400-e29b-41d4-a716-446655440100"
        now = datetime.now(timezone.utc).isoformat()

        db.execute(
            "INSERT INTO incident_rooms "
            "(room_id, incident_id, title, created_by, created_at, updated_at) "
            "VALUES ('room-r6', ?, 'R6 confirm room', 'recorder', ?, ?)",
            (prepared["incident_id"], now, now),
        )
        db.execute(
            "UPDATE incidents SET room_id='room-r6', room_alias_id='room-r6' "
            "WHERE incident_id=?",
            (prepared["incident_id"],),
        )
        db.execute(
            "INSERT INTO incident_room_messages "
            "(message_id, room_id, incident_id, sender_id, sender_role, sender_type, "
            "content, mentions_json, message_type, metadata_json, created_at, inserted_at) "
            "VALUES (?, 'room-r6', ?, 'recorder-id', 'recorder', 'Agent', "
            "?, '[]', 'message', ?, ?, ?)",
            (
                message_id,
                prepared["incident_id"],
                f"sealed card\ncard_hash: {prepared['card_hash']}",
                json.dumps({"card_hash": prepared["card_hash"]}),
                now,
                now,
            ),
        )
        response = client.post(
            "/api/confirm",
            headers={"X-Agent-Key": "r6-gateway-secret"},
            json={
                "submission_id": prepared["submission_id"],
                "incident_id": prepared["incident_id"],
                "card_hash": prepared["card_hash"],
                "message_id": message_id,
                "room_id": "room-r6",
            },
        )

        assert response.status_code == 200, response.text
        row = db.execute(
            "SELECT published_at, room_message_id FROM cards WHERE card_hash=?",
            (prepared["card_hash"],),
        ).fetchone()
        assert row["published_at"] is not None
        assert row["room_message_id"] == message_id

    def test_missing_room_message_does_not_publish_card(self, production_gateway):
        client, db = production_gateway
        prepared = _prepare_alert(client, "INC-R6-REJECT")
        message_id = "msg-550e8400-e29b-41d4-a716-446655440101"
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO incident_rooms "
            "(room_id, incident_id, title, created_by, created_at, updated_at) "
            "VALUES ('room-r6', ?, 'R6 missing room', 'recorder', ?, ?)",
            (prepared["incident_id"], now, now),
        )
        db.execute(
            "UPDATE incidents SET room_id='room-r6', room_alias_id='room-r6' "
            "WHERE incident_id=?",
            (prepared["incident_id"],),
        )
        response = client.post(
            "/api/confirm",
            headers={"X-Agent-Key": "r6-gateway-secret"},
            json={
                "submission_id": prepared["submission_id"],
                "incident_id": prepared["incident_id"],
                "card_hash": prepared["card_hash"],
                "message_id": message_id,
                "room_id": "room-r6",
            },
        )

        assert response.status_code == 409
        row = db.execute(
            "SELECT published_at, room_message_id FROM cards WHERE card_hash=?",
            (prepared["card_hash"],),
        ).fetchone()
        assert row["published_at"] is None
        assert row["room_message_id"] is None


class TestOperatorExactExecution:
    @pytest.fixture(autouse=True)
    def clear_contexts(self):
        from agents.operator import _execution_contexts
        _execution_contexts.clear()
        yield
        _execution_contexts.clear()

    def _context(self, incident_id: str, envelopes: list[dict]):
        from agents.operator import ExecutionContext, _execution_contexts

        context = ExecutionContext(
            incident_id=incident_id,
            authorization_type="human_approval",
            authorization_id="auth-r6",
            plan_hash="plan-r6",
            action_hash="action-r6",
            envelopes=envelopes,
            room_id="room-r6",
        )
        _execution_contexts[incident_id] = context
        return context

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_is_blocked_before_side_effect(self):
        from agents.operator import execute_remediation

        self._context("INC-R6-CONCURRENT", [{
            "action_id": "restart_service",
            "target": "api",
            "parameters": {},
        }])
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def perform(**kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return {
                "action_id": kwargs["action_id"],
                "target": kwargs["target"],
                "parameters": kwargs["parameters"],
                "status": "success",
                "duration_seconds": 0.01,
            }

        with patch("agents.operator._perform_remediation_action", side_effect=perform):
            first_task = asyncio.create_task(execute_remediation(
                "INC-R6-CONCURRENT", "restart_service", "api", "{}"
            ))
            await entered.wait()
            second = json.loads(await execute_remediation(
                "INC-R6-CONCURRENT", "restart_service", "api", "{}"
            ))
            release.set()
            first = json.loads(await first_task)

        assert first["status"] == "success"
        assert "error" in second
        assert calls == 1

    @pytest.mark.asyncio
    async def test_distinct_approved_parameters_remain_distinct(self):
        from agents.operator import execute_remediation

        context = self._context("INC-R6-PARAMS", [
            {"action_id": "scale_up", "target": "api", "parameters": {"replicas": 3}},
            {"action_id": "scale_up", "target": "api", "parameters": {"replicas": 5}},
        ])

        async def perform(**kwargs):
            return {
                "action_id": kwargs["action_id"],
                "target": kwargs["target"],
                "parameters": kwargs["parameters"],
                "status": "success",
                "duration_seconds": 0.01,
            }

        with patch("agents.operator._perform_remediation_action", side_effect=perform):
            first = json.loads(await execute_remediation(
                "INC-R6-PARAMS", "scale_up", "api", '{"replicas": 3}'
            ))
            second = json.loads(await execute_remediation(
                "INC-R6-PARAMS", "scale_up", "api", '{"replicas": 5}'
            ))

        assert first["status"] == "success"
        assert second["status"] == "success"
        assert [action["parameters"] for action in context.actions_taken] == [
            {"replicas": 3}, {"replicas": 5}
        ]

    @pytest.mark.asyncio
    async def test_receipt_counter_checks_real_production_function(self):
        from agents.operator import submit_action_receipt

        context = self._context("INC-R6-COUNTER", [{
            "action_id": "restart_service",
            "target": "api",
            "parameters": {},
        }])
        context.actions_taken = [
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
        ]

        result = json.loads(await submit_action_receipt(
            "INC-R6-COUNTER", "should not be accepted"
        ))
        assert "Exact-envelope mismatch" in result["error"]


@pytest.fixture
def read_only_gateway(monkeypatch):
    import sqlite3
    from gateway.app import create_app
    from gateway.database import SCHEMA, _migrate

    app = create_app(db_path=":memory:")
    db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    app.state.db = db

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    with TestClient(app) as client:
        yield client, app.state.db


class TestJudgeFacingSanitizationAndMetrics:
    def test_room_messages_redacts_active_approval_material(
        self, read_only_gateway, monkeypatch
    ):
        client, db = read_only_gateway
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO incidents "
            "(incident_id, state, severity, room_id, room_alias_id, created_at, updated_at) "
            "VALUES (?, 'PLANNED', 'P1', 'room-r6', 'room-r6', ?, ?)",
            ("INC-R6-ROOM", now, now),
        )
        db.execute(
            "INSERT INTO incident_rooms "
            "(room_id, incident_id, title, created_by, created_at, updated_at) "
            "VALUES ('room-r6', 'INC-R6-ROOM', 'R6 room', 'recorder', ?, ?)",
            (now, now),
        )

        auth_id = "550e8400-e29b-41d4-a716-446655440999"

        db.execute(
            "INSERT INTO incident_room_messages "
            "(message_id, room_id, incident_id, sender_id, sender_role, sender_type, "
            "content, mentions_json, message_type, metadata_json, created_at, inserted_at) "
            "VALUES ('m1', 'room-r6', 'INC-R6-ROOM', 'unknown', 'operator', 'Agent', "
            "?, '[]', 'message', '{}', ?, ?)",
            (
                "APPROVE nonce: ABC123 "
                "https://example.test/approve?nonce=ZXCV99&incident=x "
                f"authorization_id: {auth_id}",
                now,
                now,
            ),
        )

        response = client.get("/room-messages/INC-R6-ROOM")
        assert response.status_code == 200, response.text
        content = response.json()["messages"][0]["content"]
        assert "ABC123" not in content
        assert "ZXCV99" not in content
        assert auth_id not in content
        assert content.count("[REDACTED]") == 3

    def test_runsummary_uses_confirmed_cards_and_no_invented_baseline(
        self, read_only_gateway, monkeypatch
    ):
        client, db = read_only_gateway
        monkeypatch.delenv("MANUAL_BASELINE_SECS", raising=False)
        base = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)
        incident_id = "INC-R6-SUMMARY"
        db.execute(
            "INSERT INTO incidents "
            "(incident_id, state, severity, room_alias_id, created_at, updated_at) "
            "VALUES (?, 'EXECUTED', 'P1', 'room-r6', ?, ?)",
            (incident_id, base.isoformat(), (base + timedelta(minutes=5)).isoformat()),
        )
        cards = [
            (
                1,
                "AlertCard",
                {
                    "source": "github_deploy",
                    "raw_payload": {
                        "alert_type": "suspicious_deploy",
                        "service": "payment-service",
                    },
                },
                0,
            ),
            (2, "TriageDecision", {}, 30),
            (3, "Assessment", {}, 60),
            (4, "Verdict", {"decision": "CHALLENGE"}, 90),
            (5, "Assessment", {}, 120),
            (6, "Verdict", {"decision": "CONFIRM"}, 150),
            (7, "ResponsePlan", {}, 180),
            (8, "ActionReceipt", {}, 300),
        ]
        for sequence, card_type, payload, seconds in cards:
            timestamp = (base + timedelta(seconds=seconds)).isoformat()
            db.execute(
                "INSERT INTO cards "
                "(incident_id, sequence_number, card_type, card_hash, card_json, "
                "idempotency_key, prepared_by_role, request_fp, created_at, "
                "published_at, room_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    incident_id,
                    sequence,
                    card_type,
                    f"hash-{sequence}",
                    json.dumps(payload),
                    f"idem-{sequence}",
                    "gateway",
                    f"fp-{sequence}",
                    timestamp,
                    timestamp,
                    f"msg-{sequence}",
                ),
            )
        db.execute(
            "INSERT INTO authorizations "
            "(authorization_id, incident_id, authorization_type, plan_hash, "
            "action_hash, expiry, consumed, status) "
            "VALUES ('auth-r6', ?, 'human_approval', 'p', 'a', ?, 1, 'CONSUMED')",
            (incident_id, (base + timedelta(hours=1)).isoformat()),
        )

        response = client.get("/stats/runsummary")
        assert response.status_code == 200, response.text
        data = response.json()
        summary = data["summary"]
        run = data["runs"][0]
        assert summary["manual_baseline_secs"] is None
        assert summary["speedup_factor"] is None
        assert run["incident_family"] == "suspicious deploy"
        assert run["alert_service"] == "payment-service"
        assert run["challenges"] == 1
        assert run["recovery_verified"] is True
        assert run["human_intervention"] is True
        assert run["agent_processing_secs"] == 180
        assert run["total_resolution_secs"] == 300

    def test_runsummary_family_scoped_speedup_with_baseline_family(
        self, read_only_gateway, monkeypatch
    ):
        """BASELINE_INCIDENT_FAMILY scopes the speedup denominator to that
        family's runs while the cross-family averages stay untouched."""
        client, db = read_only_gateway
        monkeypatch.setenv("MANUAL_BASELINE_SECS", "501")
        base = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)

        def _insert_incident(incident_id, alert_type, plan_secs, receipt_secs):
            db.execute(
                "INSERT INTO incidents "
                "(incident_id, state, severity, room_alias_id, created_at, updated_at) "
                "VALUES (?, 'EXECUTED', 'P1', 'room-fam', ?, ?)",
                (
                    incident_id,
                    base.isoformat(),
                    (base + timedelta(seconds=receipt_secs)).isoformat(),
                ),
            )
            cards = [
                (
                    1,
                    "AlertCard",
                    {
                        "source": "telemetry",
                        "raw_payload": {
                            "alert_type": alert_type,
                            "service": "payment-service",
                        },
                    },
                    0,
                ),
                (2, "ResponsePlan", {}, plan_secs),
                (3, "ActionReceipt", {}, receipt_secs),
            ]
            for sequence, card_type, payload, seconds in cards:
                timestamp = (base + timedelta(seconds=seconds)).isoformat()
                db.execute(
                    "INSERT INTO cards "
                    "(incident_id, sequence_number, card_type, card_hash, card_json, "
                    "idempotency_key, prepared_by_role, request_fp, created_at, "
                    "published_at, room_message_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        incident_id,
                        sequence,
                        card_type,
                        f"hash-{incident_id}-{sequence}",
                        json.dumps(payload),
                        f"idem-{incident_id}-{sequence}",
                        "gateway",
                        f"fp-{incident_id}-{sequence}",
                        timestamp,
                        timestamp,
                        f"msg-{incident_id}-{sequence}",
                    ),
                )

        _insert_incident("INC-FAM-MET", "metrics", 100, 200)
        _insert_incident("INC-FAM-DEP", "suspicious_deploy", 50, 100)

        # Family scoping on: speedup uses only the metrics-family average.
        monkeypatch.setenv("BASELINE_INCIDENT_FAMILY", "metrics")
        data = client.get("/stats/runsummary").json()
        summary = data["summary"]
        assert summary["avg_total_resolution_secs"] == 150  # global, unchanged
        assert summary["baseline_incident_family"] == "metrics"
        assert summary["baseline_family_avg_total_secs"] == 200
        assert summary["baseline_family_run_count"] == 1
        assert summary["speedup_factor"] == round(501 / 200, 1)

        # Family scoping off: prior behavior — global average denominator.
        monkeypatch.delenv("BASELINE_INCIDENT_FAMILY", raising=False)
        data = client.get("/stats/runsummary").json()
        summary = data["summary"]
        assert summary["baseline_incident_family"] is None
        assert summary["baseline_family_avg_total_secs"] is None
        assert summary["speedup_factor"] == round(501 / 150, 1)

# ═══════════════════════════════════════════════════════════════
# R6.1 — Live-integration regression tests (canary findings)
# ═══════════════════════════════════════════════════════════════


class TestScribeRoomPayload:
    """Regression test: Scribe invite uses the Gateway-owned incident room."""

    def test_scribe_invite_uses_incident_room_client(self):
        """Verify the Operator no longer posts Scribe invites through external REST."""
        import pathlib

        operator_init = (
            pathlib.Path(__file__).parent.parent
            / "agents" / "operator" / "__init__.py"
        )
        source = operator_init.read_text()
        # Extract the Scribe invite section
        scribe_section = source[source.index("Invite Scribe"):]
        scribe_section = scribe_section[:scribe_section.index("Clean up context")]

        assert "IncidentRoomClient" in scribe_section
        assert "/agent/chats" not in scribe_section
        assert 'message_type="postmortem_request"' in scribe_section

    def test_action_receipt_publish_uses_incident_room_client(self):
        """ActionReceipt publication should use the local room transport."""
        import pathlib

        operator_init = (
            pathlib.Path(__file__).parent.parent
            / "agents" / "operator" / "__init__.py"
        )
        source = operator_init.read_text()
        receipt_section = source[source.index("# 2. Publish to the Gateway-owned incident room"):]
        receipt_section = receipt_section[:receipt_section.index("# 3. Confirm")]

        assert "IncidentRoomClient" in receipt_section
        assert "post_message" in receipt_section
        assert "/agent/chats" not in receipt_section


class TestApprovalEnvVarDocumentation:
    """Regression test: all approval UI env vars must be in .env.example.

    Root cause: the approval UI requires five env vars. If they are not
    documented in .env.example, deployment produces hard-to-debug 403 errors.
    """

    def test_env_example_has_approval_vars(self):
        """All APPROVAL_* env vars must be documented in .env.example."""
        import pathlib

        env_example = pathlib.Path(__file__).parent.parent / ".env.example"
        if not env_example.exists():
            pytest.skip(".env.example not found")

        content = env_example.read_text()
        required_vars = [
            "APPROVAL_PROXY_SECRET",
            "APPROVAL_UI_USER",
            "APPROVAL_UI_BCRYPT_HASH",
            "APPROVAL_UI_APPROVER_ID",
            "APPROVAL_UI_CSRF_SECRET",
        ]
        for var in required_vars:
            assert var in content, (
                f"{var} missing from .env.example — "
                f"required for three-layer approval auth. See R6.1 fix."
            )

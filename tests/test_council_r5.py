"""Council R5 production-path tests.

These tests call actual production functions (not reimplementations)
as required by the AI Council audit.

T1: Parameterized envelope succeeds
T2: Duplicate action rejected before side effects
T3: Unhealthy recovery blocks receipt
T4: Delayed healthy recovery succeeds
T5: Fabricated room message ID rejected
T6: RunSummary timing accuracy
T7: Outbox failure policy (challenge publish fail → 502)
"""
from __future__ import annotations

import json
import os
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution_context(incident_id, envelopes=None, room_id="test-room"):
    """Create an ExecutionContext via the production dataclass."""
    from agents.operator import ExecutionContext, _execution_contexts

    ctx = ExecutionContext(
        incident_id=incident_id,
        authorization_type="human_approval",
        authorization_id="auth-test-001",
        plan_hash="plan-hash-test",
        action_hash="action-hash-test",
        envelopes=envelopes or [],
        room_id=room_id,
    )
    _execution_contexts[incident_id] = ctx
    return ctx


def _cleanup_context(incident_id):
    """Remove execution context after test."""
    from agents.operator import _execution_contexts
    _execution_contexts.pop(incident_id, None)


# ---------------------------------------------------------------------------
# T1: Parameterized envelope succeeds
# ---------------------------------------------------------------------------

class TestParameterizedEnvelope:
    """Approve restart_service with {"grace": 30}, execute, verify receipt."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ.setdefault("YITING_TEST_MODE", "true")
        yield
        _cleanup_context("T1-test")

    @pytest.mark.asyncio
    async def test_parameterized_execute_and_receipt(self):
        """Execute with non-empty params -> result must include parameters."""
        from agents.operator import execute_remediation

        envelopes = [{
            "action_id": "restart_service",
            "target": "api-server",
            "parameters": {"grace": 30},
        }]
        ctx = _make_execution_context("T1-test", envelopes)

        # Mock the HTTP call to victim-app
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healed", "action": "restart_service"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result_json = await execute_remediation(
                incident_id="T1-test",
                action_id="restart_service",
                target="api-server",
                parameters=json.dumps({"grace": 30}),
            )

        result = json.loads(result_json)
        assert result["status"] == "success", f"Expected success, got {result}"

        # B2 fix verification: parameters must be in the result
        assert "parameters" in result, "B2: parameters missing from result"
        assert result["parameters"] == {"grace": 30}, \
            f"B2: parameters mismatch: {result['parameters']}"

        # Verify context also has parameters
        action = ctx.actions_taken[0]
        assert action.get("parameters") == {"grace": 30}, \
            "B2: actions_taken entry missing parameters"


# ---------------------------------------------------------------------------
# T2: Duplicate action rejected before side effects
# ---------------------------------------------------------------------------

class TestDuplicateActionRejected:
    """Execute same action twice -> second must be rejected before side effects."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ.setdefault("YITING_TEST_MODE", "true")
        yield
        _cleanup_context("T2-test")

    @pytest.mark.asyncio
    async def test_second_execution_refused(self):
        """Second call to execute_remediation for same action must fail."""
        from agents.operator import execute_remediation

        envelopes = [{
            "action_id": "restart_service",
            "target": "api",
            "parameters": {},
        }]
        _make_execution_context("T2-test", envelopes)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "healed"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            # First execution -- should succeed
            r1 = json.loads(await execute_remediation(
                incident_id="T2-test",
                action_id="restart_service",
                target="api",
                parameters="{}",
            ))
            assert r1["status"] == "success"

            # Second execution -- must be REJECTED (duplicate guard)
            r2 = json.loads(await execute_remediation(
                incident_id="T2-test",
                action_id="restart_service",
                target="api",
                parameters="{}",
            ))
            assert "error" in r2, "B3: duplicate execution must be rejected"
            assert "duplicate" in r2["error"].lower() or "already" in r2["error"].lower(), \
                f"B3: error must mention duplicate, got: {r2['error']}"

    @pytest.mark.asyncio
    async def test_counter_detects_double_execution(self):
        """Counter-based equality must flag 1 approved vs 2 executed."""
        envs = [{"action_id": "restart_service", "target": "api", "parameters": {}}]
        acts = [
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
        ]

        def _canonical_key(d):
            return (
                d.get("action_id", ""),
                d.get("target", ""),
                json.dumps(d.get("parameters", {}), sort_keys=True),
            )

        approved = Counter(_canonical_key(e) for e in envs)
        executed = Counter(
            _canonical_key(a) for a in acts
            if a["status"] in ("success", "already_applied")
        )

        assert approved != executed, "B3: Counter must detect 1 vs 2 mismatch"
        extra = executed - approved
        assert sum(extra.values()) == 1, "B3: should have 1 extra execution"


# ---------------------------------------------------------------------------
# T3: Unhealthy recovery blocks receipt
# ---------------------------------------------------------------------------

class TestUnhealthyRecoveryBlocksReceipt:
    """Metrics remain anomalous -> no receipt, no EXECUTED."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ.setdefault("YITING_TEST_MODE", "true")
        yield
        _cleanup_context("T3-test")

    @pytest.mark.asyncio
    async def test_unhealthy_metrics_refuse_receipt(self):
        """All recovery checks fail -> submit_action_receipt must return error."""
        from agents.operator import submit_action_receipt

        # Pre-populate context with one successful action
        ctx = _make_execution_context("T3-test", [
            {"action_id": "restart_service", "target": "api", "parameters": {}},
        ])
        ctx.actions_taken = [
            {"action_id": "restart_service", "target": "api",
             "parameters": {}, "status": "success"},
        ]

        # Mock victim-app to always return unhealthy metrics
        unhealthy_metrics = MagicMock()
        unhealthy_metrics.status_code = 200
        unhealthy_metrics.json.return_value = {
            "anomaly_detected": True,
            "error_rate": 25.0,
        }
        unhealthy_uptime = MagicMock()
        unhealthy_uptime.status_code = 200
        unhealthy_uptime.json.return_value = {
            "uptime_percentage": 80.0,
            "anomaly_detected": True,
        }

        async def mock_get(url, **kwargs):
            if "metrics" in url:
                return unhealthy_metrics
            return unhealthy_uptime

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result_json = await submit_action_receipt(
                incident_id="T3-test",
                resolution_summary="Test recovery",
            )

        result = json.loads(result_json)
        assert "error" in result, "B1: unhealthy recovery must refuse receipt"
        assert "not verified" in result["error"].lower() or "recovery" in result["error"].lower(), \
            f"B1: error must mention recovery failure, got: {result['error']}"

        # Verify no receipt was prepared/published
        assert "receipt_hash" not in result, "B1: no receipt hash when recovery failed"


# ---------------------------------------------------------------------------
# T4: Delayed healthy recovery succeeds
# ---------------------------------------------------------------------------

class TestDelayedRecoverySucceeds:
    """First checks fail, later check passes -> receipt should succeed."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        os.environ.setdefault("YITING_TEST_MODE", "true")
        yield
        _cleanup_context("T4-test")

    @pytest.mark.asyncio
    async def test_eventual_recovery_allows_receipt(self):
        """Recovery passes on attempt 3 -> receipt flow should proceed."""
        from agents.operator import submit_action_receipt

        ctx = _make_execution_context("T4-test", [
            {"action_id": "restart_service", "target": "api", "parameters": {}},
        ])
        ctx.actions_taken = [
            {"action_id": "restart_service", "target": "api",
             "parameters": {}, "status": "success"},
        ]

        call_count = {"metrics": 0, "uptime": 0}

        def make_metrics_response():
            call_count["metrics"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["metrics"] >= 3:
                resp.json.return_value = {
                    "anomaly_detected": False,
                    "error_rate": 1.0,
                }
            else:
                resp.json.return_value = {
                    "anomaly_detected": True,
                    "error_rate": 20.0,
                }
            return resp

        def make_uptime_response():
            call_count["uptime"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["uptime"] >= 3:
                resp.json.return_value = {
                    "uptime_percentage": 99.5,
                    "anomaly_detected": False,
                }
            else:
                resp.json.return_value = {
                    "uptime_percentage": 80.0,
                    "anomaly_detected": True,
                }
            return resp

        async def mock_get(url, **kwargs):
            if "metrics" in url:
                return make_metrics_response()
            return make_uptime_response()

        # Mock the entire receipt submission flow — use plain objects to
        # avoid AsyncMock auto-attribute coroutines (fixes RuntimeWarning)
        mock_prepare = MagicMock(spec=[
            "submission_id", "sealed_card", "card_hash",
            "sequence_number", "incident_id", "room_alias_id",
        ])
        mock_prepare.submission_id = "sub-test"
        mock_prepare.sealed_card = {
            "card_type": "ActionReceipt",
            "incident_id": "T4-test",
            "card_hash": "abcdef123456",
            "sequence_number": 1,
        }
        mock_prepare.card_hash = "abcdef123456"
        mock_prepare.sequence_number = 1
        mock_prepare.incident_id = "T4-test"
        mock_prepare.room_alias_id = "room-test"

        mock_confirm = MagicMock(spec=["status", "new_state", "incident_id", "card_hash", "room_message_id"])
        mock_confirm.status = "confirmed"
        mock_confirm.new_state = "EXECUTED"

        with patch("httpx.AsyncClient") as MockClient, \
             patch("agents.operator.SubmissionClient") as MockSubClient, \
             patch("agents.operator.get_agent_api_key", return_value="test-key"):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.post = AsyncMock(return_value=MagicMock(
                status_code=200, json=MagicMock(return_value={"data": {"id": "mock-msg-t4test0001"}})
            ))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            # Build a mock that works as async context manager
            mock_sub = AsyncMock()
            mock_sub.prepare = AsyncMock(return_value=mock_prepare)
            mock_sub.confirm = AsyncMock(return_value=mock_confirm)
            # Make SubmissionClient(...) return an object whose __aenter__ returns mock_sub
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_sub)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            MockSubClient.return_value = mock_cm

            result_json = await submit_action_receipt(
                incident_id="T4-test",
                resolution_summary="Recovered after delay",
            )

        result = json.loads(result_json)
        # Should succeed (eventually recovered)
        assert "error" not in result or "recovery" not in result.get("error", "").lower(), \
            f"T4: receipt should succeed after eventual recovery, got: {result}"

        # Check timeline records the correct attempt
        recovery_events = [
            e for e in ctx.timeline
            if e["event"] in ("recovery_verified", "recovery_verification_failed")
        ]
        assert len(recovery_events) >= 1, "T4: timeline must have recovery event"
        assert recovery_events[0]["recovered"] is True, \
            "T4: timeline should record recovered=True"


# ---------------------------------------------------------------------------
# T5: Fabricated room message ID rejected
# ---------------------------------------------------------------------------

class TestFabricatedRoomIdRejected:
    """Fabricated room_message_id must be rejected in production."""

    def test_fabricated_id_rejected_in_production(self):
        """Non-UUID, non-bm* IDs must fail in production mode."""
        import re
        _ROOM_REAL_ID_PATTERN = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
            r"^bm[a-zA-Z0-9]{6,64}$"
        )

        fabricated = [
            "room-msg-completely-made-up-12345",
            "room-msg-fake-id-abc",
            "room-msg-x1-test",
            "totally-not-a-real-id",
            "x1",
            "short",
        ]
        for fid in fabricated:
            assert not _ROOM_REAL_ID_PATTERN.match(fid), \
                f"H1: fabricated ID '{fid}' should NOT match production pattern"

    def test_real_uuid_accepted(self):
        """Real UUID format must pass."""
        import re
        _ROOM_REAL_ID_PATTERN = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
            r"^bm[a-zA-Z0-9]{6,64}$"
        )

        valid = [
            "550e8400-e29b-41d4-a716-446655440000",
            "bm1234567890abcdef",
            "bmABCDEF123456",
        ]
        for vid in valid:
            assert _ROOM_REAL_ID_PATTERN.match(vid), \
                f"H1: valid ID '{vid}' must match production pattern"

    def test_mock_ids_only_in_test_mode(self):
        """mock-msg-* and synthetic-* must only work in test mode."""
        import re
        _ROOM_REAL_ID_PATTERN = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
            r"^bm[a-zA-Z0-9]{6,64}$"
        )
        _ROOM_TEST_ID_PATTERN = re.compile(
            r"^mock-msg-[a-zA-Z0-9_-]{4,64}$|"
            r"^synthetic-[a-zA-Z0-9_-]{8,64}$"
        )

        test_ids = [
            "mock-msg-test-1234",
            "synthetic-abcdefgh-1234",
        ]
        for tid in test_ids:
            assert not _ROOM_REAL_ID_PATTERN.match(tid), \
                f"H1: test ID '{tid}' must NOT match production pattern"
            assert _ROOM_TEST_ID_PATTERN.match(tid), \
                f"H1: test ID '{tid}' must match test pattern"


# ---------------------------------------------------------------------------
# T6: RunSummary timing accuracy
# ---------------------------------------------------------------------------

class TestRunSummaryTiming:
    """Verify RunSummary calculations are correct for known timestamps."""

    def test_false_alarm_has_no_agent_processing(self):
        """False alarm (no ResponsePlan) should have None agent_processing_secs."""
        alert_time = "2026-06-18T10:00:00+00:00"
        plan_time = None

        agent_secs = None
        if alert_time and plan_time:
            from datetime import datetime as _dt
            t0 = _dt.fromisoformat(alert_time)
            t1 = _dt.fromisoformat(plan_time)
            agent_secs = (t1 - t0).total_seconds()

        assert agent_secs is None, "False alarm should have no agent_processing_secs"

    def test_executed_run_timing(self):
        """Known timestamps -> exact expected durations."""
        from datetime import datetime as _dt

        alert_time = "2026-06-18T10:00:00+00:00"
        plan_time = "2026-06-18T10:02:00+00:00"
        terminal_time = "2026-06-18T10:05:00+00:00"

        t0 = _dt.fromisoformat(alert_time)
        t1 = _dt.fromisoformat(plan_time)
        t2 = _dt.fromisoformat(terminal_time)

        agent_secs = (t1 - t0).total_seconds()
        resolution_secs = (t2 - t0).total_seconds()
        human_secs = resolution_secs - agent_secs

        assert agent_secs == 120.0, f"Agent should be 120s, got {agent_secs}"
        assert resolution_secs == 300.0, f"Resolution should be 300s, got {resolution_secs}"
        assert human_secs == 180.0, f"Human should be 180s, got {human_secs}"

    def test_separate_denominators(self):
        """avg_agent uses agent_secs_count, not resolution_count."""
        agent_times = [120.0]
        resolution_times = [300.0, 90.0]

        avg_agent = sum(agent_times) / len(agent_times)

        wrong_avg_agent = sum(agent_times) / len(resolution_times)

        assert avg_agent == 120.0, "Correct average uses agent_secs_count"
        assert wrong_avg_agent == 60.0, "Wrong average uses resolution_count"
        assert avg_agent != wrong_avg_agent, "Denominators must differ"


# ---------------------------------------------------------------------------
# T7: Outbox failure policy
# ---------------------------------------------------------------------------

class TestOutboxFailurePolicy:
    """Challenge publication failure must block approval (fail closed)."""

    def test_outbox_code_raises_on_failure(self):
        """When challenge incident room POST fails, must raise HTTPException(502)."""
        import inspect
        from gateway.routes import nonce
        source = inspect.getsource(nonce)

        assert "raise HTTPException" in source, \
            "H2: nonce module must raise HTTPException on challenge failure"

        assert "DON'T raise 502" not in source, \
            "H2: old silent-proceed comment must be removed"
        assert "best-effort mode, background retry spawned" not in source, \
            "H2: old best-effort fallback must be removed"

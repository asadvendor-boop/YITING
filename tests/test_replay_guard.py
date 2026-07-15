"""Behavioral tests for replay guard + durable duplicate suppression.

29+ tests covering:
- §1: Durable duplicate suppression at victim-app /heal (required fields, 422, concurrency)
- §2: Replay guard (should_skip_stale_card + should_skip_stale_chatter)
- §3: Operator preprocessor nonce match + EXECUTED opt
- §4: Silent consume of unsupported sealed cards
- §5: Slack suppression on already_applied

Runs locally and on the deployment VM. No external dependencies beyond the project.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure yiting root is importable
YITING_ROOT = str(Path(__file__).parent.parent)
if YITING_ROOT not in sys.path:
    sys.path.insert(0, YITING_ROOT)

from shared.replay_guard import should_skip_stale_card, should_skip_stale_chatter


def _run_async(coro):
    """Run an async coroutine in a fresh event loop (avoids pytest-asyncio conflicts)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ==========================================================================
# §1: Durable Duplicate Suppression — victim-app /heal
# ==========================================================================

class TestHealIdempotency(unittest.TestCase):
    """Tests for victim-app durable duplicate suppression via SQLite."""

    @classmethod
    def setUpClass(cls):
        """Import app module with a temp SQLite DB to avoid test pollution."""
        cls._tmp_dir = tempfile.mkdtemp()
        cls._db_path = os.path.join(cls._tmp_dir, "test_heal.db")
        os.environ["HEAL_IDEMPOTENCY_DB"] = cls._db_path

        # Force reimport of victim-app/app.py with temp DB
        victim_app_dir = str(Path(__file__).parent.parent / "victim-app")
        if victim_app_dir not in sys.path:
            sys.path.insert(0, victim_app_dir)

        # Remove cached module if re-importing
        for mod_name in list(sys.modules.keys()):
            if mod_name == "app" or mod_name.startswith("app."):
                del sys.modules[mod_name]

        import app as victim_app
        cls.victim_app = victim_app

        from fastapi.testclient import TestClient
        cls.client = TestClient(victim_app.app)

    def setUp(self):
        """Reset idempotency DB and scenarios before each test."""
        self.victim_app._scenarios.clear()
        # Clear the SQLite DB
        self.victim_app._idem_db.execute("DELETE FROM applied_actions")
        self.victim_app._idem_db.commit()

    def _make_heal_body(self, incident_id, **overrides):
        """Build a valid heal body with defaults."""
        body = {
            "incident_id": incident_id,
            "action": "rollback_deploy",
            "target": "payment-service",
            "parameters": {"version": "v2.14.2"},
            "action_hash": "default_hash",
        }
        body.update(overrides)
        return body

    # Test 1: Bare POST /heal (no body) returns 422
    def test_01_bare_heal_returns_422(self):
        """Bare POST /heal with no JSON body returns 422 (required fields)."""
        resp = self.client.post("/admin/scenario/INC-001/heal")
        self.assertEqual(resp.status_code, 422)

    # Test 2: /heal with all required fields returns healed on first call
    def test_02_idempotent_first_call_heals(self):
        """First /heal with valid body returns healed."""
        self.client.post("/admin/scenario/INC-002/activate", params={"tier": "severe"})
        resp = self.client.post("/admin/scenario/INC-002/heal",
                                json=self._make_heal_body("INC-002"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healed")

    # Test 3: Duplicate call returns already_applied
    def test_03_duplicate_returns_already_applied(self):
        """Second identical /heal returns already_applied."""
        self.client.post("/admin/scenario/INC-003/activate", params={"tier": "severe"})
        body = self._make_heal_body("INC-003", action_hash="abc123")
        self.client.post("/admin/scenario/INC-003/heal", json=body)
        resp2 = self.client.post("/admin/scenario/INC-003/heal", json=body)
        self.assertEqual(resp2.json()["status"], "already_applied")

    # Test 4: Different action_hash is NOT a duplicate
    def test_04_different_hash_not_duplicate(self):
        """Different action_hash produces a fresh heal."""
        self.client.post("/admin/scenario/INC-004/activate", params={"tier": "severe"})
        body1 = self._make_heal_body("INC-004", action_hash="hash_A")
        body2 = self._make_heal_body("INC-004", action_hash="hash_B")
        self.client.post("/admin/scenario/INC-004/heal", json=body1)
        # Re-activate so second heal has something to do
        self.client.post("/admin/scenario/INC-004/activate", params={"tier": "severe"})
        resp2 = self.client.post("/admin/scenario/INC-004/heal", json=body2)
        self.assertEqual(resp2.json()["status"], "healed")

    # Test 5: Empty action_hash returns 422 (not bypass)
    def test_05_empty_action_hash_returns_422(self):
        """Empty action_hash string returns 422 — no idempotency bypass."""
        resp = self.client.post("/admin/scenario/INC-005/heal", json={
            "incident_id": "INC-005",
            "action": "rollback_deploy",
            "target": "payment-service",
            "action_hash": "",
        })
        self.assertEqual(resp.status_code, 422)

    # Test 6: Same action_hash different incident is NOT duplicate
    def test_06_same_hash_different_incident(self):
        """Same action_hash across different incidents are independent."""
        self.client.post("/admin/scenario/INC-006A/activate", params={"tier": "severe"})
        self.client.post("/admin/scenario/INC-006B/activate", params={"tier": "severe"})
        body_a = self._make_heal_body("INC-006A", action_hash="shared_hash")
        body_b = self._make_heal_body("INC-006B", action_hash="shared_hash")
        resp1 = self.client.post("/admin/scenario/INC-006A/heal", json=body_a)
        resp2 = self.client.post("/admin/scenario/INC-006B/heal", json=body_b)
        self.assertEqual(resp1.json()["status"], "healed")
        self.assertEqual(resp2.json()["status"], "healed")

    # Test 7: Real concurrent duplicate — exactly one mutation
    def test_07_concurrent_duplicate_one_mutation(self):
        """Two truly concurrent requests: exactly one applies the _scenarios mutation."""
        self.client.post("/admin/scenario/INC-007/activate", params={"tier": "severe"})
        body = self._make_heal_body("INC-007", action_hash="concurrent_hash")

        # Count SQLite rows before
        rows_before = self.victim_app._idem_db.execute(
            "SELECT COUNT(*) FROM applied_actions WHERE incident_id='INC-007'"
        ).fetchone()[0]

        # Fire two concurrent requests via ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self.client.post, "/admin/scenario/INC-007/heal", json=body)
            f2 = pool.submit(self.client.post, "/admin/scenario/INC-007/heal", json=body)
            r1, r2 = f1.result(), f2.result()

        statuses = {r1.json()["status"], r2.json()["status"]}
        self.assertEqual(statuses, {"healed", "already_applied"})

        # Count SQLite rows after — exactly one INSERT must have occurred
        rows_after = self.victim_app._idem_db.execute(
            "SELECT COUNT(*) FROM applied_actions WHERE incident_id='INC-007'"
        ).fetchone()[0]
        self.assertEqual(rows_after - rows_before, 1, "Exactly one mutation (INSERT) must occur")

    # Test 8: Durable across restart — reload module, retry via HTTP
    def test_08_durable_across_restart(self):
        """Idempotency record survives app module reload (simulated restart)."""
        body = self._make_heal_body("INC-008", action_hash="restart_hash")
        self.client.post("/admin/scenario/INC-008/activate", params={"tier": "severe"})
        resp1 = self.client.post("/admin/scenario/INC-008/heal", json=body)
        self.assertEqual(resp1.json()["status"], "healed")

        # Simulate restart: remove module, reimport, create new TestClient
        for mod_name in list(sys.modules.keys()):
            if mod_name == "app" or mod_name.startswith("app."):
                del sys.modules[mod_name]

        import app as fresh_app
        from fastapi.testclient import TestClient
        fresh_client = TestClient(fresh_app.app)

        # Retry — must get already_applied from the durable SQLite record
        resp2 = fresh_client.post("/admin/scenario/INC-008/heal", json=body)
        self.assertEqual(resp2.json()["status"], "already_applied")

        # Restore the original module reference for subsequent tests
        self.__class__.victim_app = fresh_app
        self.__class__.client = fresh_client

    # Test 9: Execution key uses full SHA-256
    def test_09_execution_key_full_sha256(self):
        """Execution key is a valid 64-char hex SHA-256 digest."""
        from app import _execution_key
        key = _execution_key("INC-009", "hash1", "rollback", "svc", {"v": "1"})
        self.assertEqual(len(key), 64)
        int(key, 16)  # Must be valid hex

    # Test 10: Canonical JSON produces deterministic keys
    def test_10_deterministic_execution_key(self):
        """Same inputs always produce the same execution key."""
        from app import _execution_key
        params = {"version": "v2.14.2", "region": "us-east-1"}
        k1 = _execution_key("INC-010", "h1", "rollback", "svc", params)
        k2 = _execution_key("INC-010", "h1", "rollback", "svc", params)
        self.assertEqual(k1, k2)

    # Test 11: Different parameter order produces same key (sort_keys)
    def test_11_param_order_invariant(self):
        """Parameter key order doesn't affect execution key."""
        from app import _execution_key
        k1 = _execution_key("INC-011", "h", "a", "t", {"b": 2, "a": 1})
        k2 = _execution_key("INC-011", "h", "a", "t", {"a": 1, "b": 2})
        self.assertEqual(k1, k2)

    # Test 12: Missing action_hash field returns 422
    def test_12_missing_action_hash_422(self):
        """Request body missing action_hash returns 422."""
        resp = self.client.post("/admin/scenario/INC-012/heal", json={
            "incident_id": "INC-012",
            "action": "rollback",
            "target": "svc",
        })
        self.assertEqual(resp.status_code, 422)

    # Test 13: Whitespace-only action_hash returns 422
    def test_13_whitespace_action_hash_422(self):
        """Whitespace-only action_hash returns 422."""
        resp = self.client.post("/admin/scenario/INC-013/heal", json={
            "incident_id": "INC-013",
            "action": "rollback",
            "target": "svc",
            "action_hash": "   ",
        })
        self.assertEqual(resp.status_code, 422)

    # Test 14: /reset endpoint works for test cleanup
    def test_14_reset_endpoint_works(self):
        """The separate /reset endpoint clears scenarios without idempotency."""
        self.client.post("/admin/scenario/INC-014/activate", params={"tier": "severe"})
        resp = self.client.post("/admin/scenario/INC-014/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "reset")
        # Verify metrics show healthy
        metrics = self.client.get("/api/v1/metrics", params={"incident_id": "INC-014"}).json()
        self.assertFalse(metrics["anomaly_detected"])


# ==========================================================================
# §2: Replay Guard — should_skip_stale_card + should_skip_stale_chatter
# ==========================================================================

class TestReplayGuard(unittest.TestCase):
    """Tests for shared/replay_guard.py functions."""

    # Test 15: Stale chatter — old message skipped
    def test_15_stale_chatter_old_message(self):
        """Message older than boot_epoch - 60s is skipped."""
        boot = time.time()
        old_ts = datetime.fromtimestamp(boot - 120, tz=timezone.utc).isoformat()
        self.assertTrue(should_skip_stale_chatter(old_ts, boot, "test"))

    # Test 16: Recent chatter passes
    def test_16_recent_chatter_passes(self):
        """Message within 60s of boot is NOT skipped."""
        boot = time.time()
        recent_ts = datetime.fromtimestamp(boot - 30, tz=timezone.utc).isoformat()
        self.assertFalse(should_skip_stale_chatter(recent_ts, boot, "test"))

    # Test 17: None inserted_at passes (fail-open)
    def test_17_none_inserted_at_passes(self):
        """None inserted_at is NOT skipped (fail-open)."""
        self.assertFalse(should_skip_stale_chatter(None, time.time(), "test"))

    # Test 18: Malformed timestamp passes (fail-open)
    def test_18_malformed_timestamp_passes(self):
        """Malformed timestamp string is NOT skipped (fail-open)."""
        self.assertFalse(
            should_skip_stale_chatter("not-a-timestamp", time.time(), "test")
        )

    # Test 19: Stale card — higher seq skipped
    def test_19_stale_card_higher_seq(self):
        """Card with lower seq than published max is skipped."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "cards": [
                {"sequence_number": 1, "published_at": "2024-01-01"},
                {"sequence_number": 3, "published_at": "2024-01-01"},
            ]
        }
        with patch("shared.replay_guard.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = _run_async(
                should_skip_stale_card("INC-TEST", 2, "test")
            )
            self.assertTrue(result)

    # Test 20: Same seq passes (own confirm)
    def test_20_same_seq_passes(self):
        """Card with same seq as published max is NOT skipped."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "cards": [
                {"sequence_number": 1, "published_at": "2024-01-01"},
                {"sequence_number": 3, "published_at": "2024-01-01"},
            ]
        }
        with patch("shared.replay_guard.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = _run_async(
                should_skip_stale_card("INC-TEST", 3, "test")
            )
            self.assertFalse(result)

    # Test 21: No seq fails open
    def test_21_no_seq_fails_open(self):
        """None sequence_number is NOT skipped (fail-open)."""
        result = _run_async(
            should_skip_stale_card("INC-TEST", None, "test")
        )
        self.assertFalse(result)

    # Test 22: Gateway error fails open
    def test_22_gateway_error_fails_open(self):
        """If Gateway returns non-200, should_skip_stale_card fails open."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("shared.replay_guard.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = _run_async(
                should_skip_stale_card("INC-TEST", 1, "test")
            )
            self.assertFalse(result)

    # Test 23: Network exception fails open
    def test_23_network_exception_fails_open(self):
        """Network exception in stale card check fails open."""
        with patch("shared.replay_guard.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("conn refused"))
            mock_client_cls.return_value = mock_client

            result = _run_async(
                should_skip_stale_card("INC-TEST", 1, "test")
            )
            self.assertFalse(result)


# ==========================================================================
# §3: Operator Preprocessor — nonce parse + nonce match
# ==========================================================================

class TestOperatorNonceParsing(unittest.TestCase):
    """Tests for Operator _parse_challenge nonce extraction."""

    @classmethod
    def setUpClass(cls):
        from agents.operator import OperatorPreprocessor
        cls.preprocessor = OperatorPreprocessor()

    # Test 24: JSON challenge extracts nonce
    def test_24_json_challenge_nonce(self):
        """JSON challenge extracts all 4 fields including nonce."""
        msg = json.dumps({
            "type": "approval_challenge",
            "incident_id": "INC-001",
            "plan_hash": "plan123",
            "action_hash": "action456",
            "nonce": "K7V3NW",
        })
        result = self.preprocessor._parse_challenge(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["nonce"], "K7V3NW")
        self.assertEqual(result["incident_id"], "INC-001")

    # Test 25: Key-value challenge extracts nonce
    def test_25_kv_challenge_nonce(self):
        """Key-value format challenge extracts nonce."""
        msg = """incident_id: INC-002
plan_hash: plan789
action_hash: action012
nonce: XY9ABC"""
        result = self.preprocessor._parse_challenge(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result["nonce"], "XY9ABC")

    # Test 26: Missing nonce returns None
    def test_26_missing_nonce_returns_none(self):
        """Challenge missing nonce returns None (all 4 fields required)."""
        msg = json.dumps({
            "type": "approval_challenge",
            "incident_id": "INC-003",
            "plan_hash": "plan123",
            "action_hash": "action456",
        })
        result = self.preprocessor._parse_challenge(msg)
        self.assertIsNone(result)


# ==========================================================================
# §4: Silent Consume — card_intake utility
# ==========================================================================

class TestSilentConsume(unittest.TestCase):
    """Tests for card_intake has_seal_fields used in silent consume."""

    # Test 27: has_seal_fields True for full card
    def test_27_has_seal_fields_full(self):
        """Card with card_hash + sequence_number passes has_seal_fields."""
        from shared.card_intake import has_seal_fields
        card = {
            "card_type": "Assessment",
            "card_hash": "sha256:abc123",
            "sequence_number": 3,
        }
        self.assertTrue(has_seal_fields(card))

    # Test 28: has_seal_fields False for missing card_hash
    def test_28_missing_card_hash(self):
        """Card without card_hash fails has_seal_fields."""
        from shared.card_intake import has_seal_fields
        card = {"card_type": "Assessment", "sequence_number": 3}
        self.assertFalse(has_seal_fields(card))

    # Test 29: has_seal_fields False for missing sequence_number
    def test_29_missing_sequence_number(self):
        """Card without sequence_number fails has_seal_fields."""
        from shared.card_intake import has_seal_fields
        card = {"card_type": "Assessment", "card_hash": "sha256:abc123"}
        self.assertFalse(has_seal_fields(card))


# ==========================================================================
# §5: Slack Suppression on already_applied
# ==========================================================================

class TestSlackSuppression(unittest.TestCase):
    """Tests that Slack notification is NOT sent on already_applied."""

    # Test 30: Duplicate remediation does not send Slack
    def test_30_no_slack_on_already_applied(self):
        """execute_remediation with already_applied result must NOT call Slack."""
        from agents.operator import (
            execute_remediation, _execution_contexts, ExecutionContext,
        )
        import agents.operator as op_mod

        _execution_contexts["INC-DUP"] = ExecutionContext(
            incident_id="INC-DUP",
            authorization_type="policy",
            authorization_id="auth-1",
            plan_hash="plan1",
            action_hash="action1",
            envelopes=[{
                "action_id": "rollback_deploy",
                "target": "payment-service",
                "parameters": {},
            }],
        )

        original_webhook = op_mod.SLACK_WEBHOOK_URL
        op_mod.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"

        slack_calls = []

        class _FakeResp:
            def __init__(self, sc, data):
                self.status_code = sc
                self._data = data
                self.text = json.dumps(data)
            def json(self):
                return self._data

        class _FakeClient:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self_inner, url, **kw):
                if "hooks.slack.com" in url.lower():
                    slack_calls.append(url)
                    return _FakeResp(200, {"ok": True})
                return _FakeResp(200, {"status": "already_applied", "incident_id": "INC-DUP"})

        try:
            import types
            fake_httpx = types.ModuleType("fake_httpx")
            fake_httpx.AsyncClient = _FakeClient
            original_httpx = op_mod.httpx
            op_mod.httpx = fake_httpx
            try:
                result_json = _run_async(
                    execute_remediation("INC-DUP", "rollback_deploy", "payment-service", "{}")
                )
                result = json.loads(result_json)
            finally:
                op_mod.httpx = original_httpx

            self.assertEqual(result["status"], "already_applied")
            self.assertEqual(len(slack_calls), 0, "Slack must NOT be called on already_applied")
        finally:
            op_mod.SLACK_WEBHOOK_URL = original_webhook
            _execution_contexts.pop("INC-DUP", None)

    # Test 31: Successful remediation DOES send Slack
    def test_31_slack_on_success(self):
        """execute_remediation with success result DOES call Slack."""
        from agents.operator import (
            execute_remediation, _execution_contexts, ExecutionContext,
        )
        import agents.operator as op_mod

        _execution_contexts["INC-NEW"] = ExecutionContext(
            incident_id="INC-NEW",
            authorization_type="policy",
            authorization_id="auth-2",
            plan_hash="plan2",
            action_hash="action2",
            envelopes=[{
                "action_id": "rollback_deploy",
                "target": "payment-service",
                "parameters": {},
            }],
        )

        original_webhook = op_mod.SLACK_WEBHOOK_URL
        op_mod.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"

        slack_calls = []

        class _FakeResp:
            def __init__(self, sc, data):
                self.status_code = sc
                self._data = data
                self.text = json.dumps(data)
            def json(self):
                return self._data

        class _FakeClient:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self_inner, url, **kw):
                if "hooks.slack.com" in url.lower():
                    slack_calls.append(url)
                    return _FakeResp(200, {"ok": True})
                return _FakeResp(200, {"status": "healed", "incident_id": "INC-NEW"})

        try:
            import types
            fake_httpx = types.ModuleType("fake_httpx")
            fake_httpx.AsyncClient = _FakeClient
            original_httpx = op_mod.httpx
            op_mod.httpx = fake_httpx
            try:
                result_json = _run_async(
                    execute_remediation("INC-NEW", "rollback_deploy", "payment-service", "{}")
                )
                result = json.loads(result_json)
            finally:
                op_mod.httpx = original_httpx

            self.assertEqual(result["status"], "success")
            self.assertEqual(len(slack_calls), 1, "Slack MUST be called on success")
        finally:
            op_mod.SLACK_WEBHOOK_URL = original_webhook
            _execution_contexts.pop("INC-NEW", None)

if __name__ == "__main__":
    unittest.main(verbosity=2)

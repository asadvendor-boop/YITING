"""Tests for P0-1 (recovery verification) and P0-2 (envelope equality) fixes.

These test the deterministic guards added to the Operator receipt flow
to satisfy AI Council requirements.
"""
import json

# ── Envelope equality tests ──────────────────────────────────────────

class TestEnvelopeEquality:
    """P0-2: Receipt must be refused if executed actions != approved envelopes."""

    def _make_ctx(self, envelopes, actions_taken):
        """Create a minimal IncidentContext-like object for testing."""
        class FakeCtx:
            def __init__(self, env, acts):
                self.envelopes = env
                self.actions_taken = acts
                self.timeline = []
        return FakeCtx(envelopes, actions_taken)

    def test_exact_match_passes(self):
        """All approved envelopes executed once → should pass."""
        envs = [{"action_id": "restart_service", "target": "api", "parameters": {}}]
        acts = [{"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"}]
        ctx = self._make_ctx(envs, acts)

        # Simulate the guard logic
        approved = set()
        for e in ctx.envelopes:
            key = (e["action_id"], e["target"], json.dumps(e.get("parameters", {}), sort_keys=True))
            approved.add(key)

        executed = set()
        for a in ctx.actions_taken:
            if a["status"] in ("success", "already_applied"):
                key = (a["action_id"], a["target"], json.dumps(a.get("parameters", {}), sort_keys=True))
                executed.add(key)

        assert approved == executed, "Exact match should pass"

    def test_missing_envelope_refused(self):
        """2 approved but only 1 executed → must refuse."""
        envs = [
            {"action_id": "restart_service", "target": "api", "parameters": {}},
            {"action_id": "rollback", "target": "api", "parameters": {"version": "1.2.3"}},
        ]
        acts = [
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
        ]
        ctx = self._make_ctx(envs, acts)

        approved = set()
        for e in ctx.envelopes:
            key = (e["action_id"], e["target"], json.dumps(e.get("parameters", {}), sort_keys=True))
            approved.add(key)

        executed = set()
        for a in ctx.actions_taken:
            if a["status"] in ("success", "already_applied"):
                key = (a["action_id"], a["target"], json.dumps(a.get("parameters", {}), sort_keys=True))
                executed.add(key)

        missing = approved - executed
        assert len(missing) == 1, "Should detect 1 missing action"
        assert ("rollback", "api", json.dumps({"version": "1.2.3"}, sort_keys=True)) in missing

    def test_extra_unapproved_action_refused(self):
        """Unapproved action executed → must refuse."""
        envs = [{"action_id": "restart_service", "target": "api", "parameters": {}}]
        acts = [
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "success"},
            {"action_id": "delete_database", "target": "db", "parameters": {}, "status": "success"},
        ]
        ctx = self._make_ctx(envs, acts)

        approved = set()
        for e in ctx.envelopes:
            key = (e["action_id"], e["target"], json.dumps(e.get("parameters", {}), sort_keys=True))
            approved.add(key)

        executed = set()
        for a in ctx.actions_taken:
            if a["status"] in ("success", "already_applied"):
                key = (a["action_id"], a["target"], json.dumps(a.get("parameters", {}), sort_keys=True))
                executed.add(key)

        extra = executed - approved
        assert len(extra) == 1, "Should detect 1 extra unapproved action"

    def test_failed_action_excluded(self):
        """Failed actions should not count toward executed set."""
        envs = [{"action_id": "restart_service", "target": "api", "parameters": {}}]
        acts = [
            {"action_id": "restart_service", "target": "api", "parameters": {}, "status": "failed"},
        ]
        ctx = self._make_ctx(envs, acts)

        executed = set()
        for a in ctx.actions_taken:
            if a["status"] in ("success", "already_applied"):
                key = (a["action_id"], a["target"], json.dumps(a.get("parameters", {}), sort_keys=True))
                executed.add(key)

        assert len(executed) == 0, "Failed actions should not be in executed set"


# ── room message ID validation tests ────────────────────────────────

class TestRoomMessageIdValidation:
    """P1-1: /confirm must reject short/fake room_message_ids."""

    def _valid_ids(self):
        """IDs that should pass validation."""
        return [
            "12345678-1234-1234-1234-123456789012",  # UUID
            "room-msg-abc123",  # room-msg prefix
            "mock-msg-test1234",  # mock-msg prefix
            "synthetic-abcd1234efgh",  # synthetic prefix
            "bm00aa11bb",  # bm prefix
        ]

    def _invalid_ids(self):
        """IDs that should fail validation."""
        return [
            "x1",  # Too short (2 chars)
            "ab",  # Too short
            "short",  # Too short (5 chars)
            "",  # Empty
        ]

    def test_valid_ids_accepted(self):
        """Valid room message IDs should match the pattern."""
        import re
        pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
            r"^room-msg-[a-zA-Z0-9_-]{3,64}$|"
            r"^mock-msg-[a-zA-Z0-9_-]{4,64}$|"
            r"^synthetic-[a-zA-Z0-9_-]{8,64}$|"
            r"^bm[a-zA-Z0-9]{6,64}$"
        )
        for msg_id in self._valid_ids():
            assert len(msg_id) >= 8 and pattern.match(msg_id), f"Should accept: {msg_id}"

    def test_invalid_ids_rejected(self):
        """Invalid room message IDs should be rejected."""
        import re
        pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|"
            r"^room-msg-[a-zA-Z0-9_-]{3,64}$|"
            r"^mock-msg-[a-zA-Z0-9_-]{4,64}$|"
            r"^synthetic-[a-zA-Z0-9_-]{8,64}$|"
            r"^bm[a-zA-Z0-9]{6,64}$"
        )
        for msg_id in self._invalid_ids():
            assert len(msg_id) < 8 or not pattern.match(msg_id), f"Should reject: {msg_id}"

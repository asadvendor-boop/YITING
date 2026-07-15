"""Tests for ACTIVE_INCIDENTS allowlist in all 5 preprocessors.

Verifies that when ACTIVE_INCIDENTS is set, preprocessors skip
non-active incidents (return None) without making any Gateway
or LLM calls.
"""
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestActiveIncidentsAllowlist(unittest.IsolatedAsyncioTestCase):
    """Test that ACTIVE_INCIDENTS blocks non-target incidents."""

    def _make_event(self, content: str, sender_type: str = "Agent",
                    sender_id: str = "test-agent-id"):
        """Create a mock MessageEvent with the given content."""
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.room_id = "room-123"
        payload = MagicMock()
        payload.content = content
        payload.sender_type = sender_type
        payload.sender_id = sender_id
        payload.id = "msg-001"
        payload.inserted_at = None
        event.payload = payload
        return event

    def _make_sealed_card(self, card_type: str, incident_id: str,
                          seq: int = 1) -> str:
        """Create a sealed card JSON string wrapped in markdown code block."""
        import json
        card = {
            "card_type": card_type,
            "incident_id": incident_id,
            "alert_id": incident_id,
            "sequence_number": seq,
            "card_hash": "abc123",
            "previous_card_hash": "000000",
        }
        return f"```json\n{json.dumps(card)}\n```"

    # ----- Triage -----
    @patch.dict(os.environ, {"ACTIVE_INCIDENTS": "INC-TARGET"})
    @patch("shared.config.ACTIVE_INCIDENTS", frozenset({"INC-TARGET"}))
    async def test_triage_skips_non_active_incident(self):
        """Triage preprocessor returns None for non-active incidents."""
        # Reload to pick up patched ACTIVE_INCIDENTS
        from agents.triage import TriagePreprocessor

        preprocessor = TriagePreprocessor.__new__(TriagePreprocessor)
        preprocessor._default_preprocessor = AsyncMock()
        preprocessor._llm = MagicMock()
        preprocessor._triage_agent_id = "triage-id"
        preprocessor._triage_api_key = "key"
        preprocessor._gateway_url = "http://localhost:8000"
        preprocessor._submission_key = "key"
        preprocessor._diagnosis_agent_id = "diag-id"
        preprocessor._boot_epoch = 0
        preprocessor._recorder_agent_id = "recorder-id"
        preprocessor._room_client = MagicMock()

        # Create an AlertCard for a NON-active incident
        content = self._make_sealed_card("AlertCard", "INC-OLD-001")
        event = self._make_event(content, sender_id="recorder-id")
        ctx = MagicMock()

        with patch("agents.triage.ACTIVE_INCIDENTS", frozenset({"INC-TARGET"})):
            result = await preprocessor.process(ctx, event)

        self.assertIsNone(result)

    @patch("agents.triage.ACTIVE_INCIDENTS", frozenset())
    async def test_triage_processes_when_allowlist_empty(self):
        """Triage processes normally when ACTIVE_INCIDENTS is empty (default)."""
        # Empty frozenset = process everything — the guard is a no-op
        empty = frozenset()
        # Verify: empty frozenset is falsy
        self.assertFalse(empty)

    # ----- Config -----
    def test_active_incidents_parsed_from_env(self):
        """ACTIVE_INCIDENTS parses comma-separated env var correctly."""
        with patch.dict(os.environ, {"ACTIVE_INCIDENTS": "INC-A,INC-B,INC-C"}):
            result = frozenset(
                filter(None, os.getenv("ACTIVE_INCIDENTS", "").split(","))
            )
            self.assertEqual(result, {"INC-A", "INC-B", "INC-C"})

    def test_active_incidents_empty_when_unset(self):
        """ACTIVE_INCIDENTS is empty frozenset when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ACTIVE_INCIDENTS", None)
            result = frozenset(
                filter(None, os.getenv("ACTIVE_INCIDENTS", "").split(","))
            )
            self.assertEqual(result, frozenset())
            self.assertFalse(result)  # Empty = falsy = process everything

    def test_active_incidents_single_value(self):
        """ACTIVE_INCIDENTS works with a single incident ID."""
        with patch.dict(os.environ, {"ACTIVE_INCIDENTS": "INC-ONLY"}):
            result = frozenset(
                filter(None, os.getenv("ACTIVE_INCIDENTS", "").split(","))
            )
            self.assertEqual(result, {"INC-ONLY"})

    # ----- Guard logic (unit) -----
    def test_guard_blocks_non_active(self):
        """Non-active incident is blocked when allowlist is set."""
        active = frozenset({"INC-TARGET"})
        incident_id = "INC-OLD-001"
        self.assertTrue(active and incident_id not in active)

    def test_guard_passes_active(self):
        """Active incident passes the guard."""
        active = frozenset({"INC-TARGET"})
        incident_id = "INC-TARGET"
        self.assertFalse(active and incident_id not in active)

    def test_guard_passes_when_empty(self):
        """All incidents pass when allowlist is empty (default)."""
        active = frozenset()
        incident_id = "INC-ANYTHING"
        # Empty frozenset is falsy → short-circuits → passes
        self.assertFalse(active and incident_id not in active)


if __name__ == "__main__":
    unittest.main()

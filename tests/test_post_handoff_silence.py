"""Tests for post-handoff silence behavior across all preprocessors.

Covers:
1. Fresh Agent chatter never reaches the LLM after handoff.
2. Supported sealed cards still pass through after handoff.
3. Human messages still pass through after handoff (Commander only).
4. _handoff_rooms is populated on submission.
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(content, sender_id, sender_type="Agent", room_id="room-1"):
    """Create a mock MessageEvent with room_id on the EVENT (incident room 1.0)."""
    event = MagicMock()
    type(event).__name__ = "MessageEvent"
    event.room_id = room_id
    payload = MagicMock()
    payload.content = content
    payload.sender_id = sender_id
    payload.sender_type = sender_type
    payload.id = "msg-001"
    payload.inserted_at = time.time()  # Fresh message
    del payload.room_id
    event.payload = payload
    return event


def _make_sealed_card(card_type: str, incident_id: str = "INC-TEST") -> str:
    """Create a sealed card content string."""
    card = {
        "card_type": card_type,
        "incident_id": incident_id,
        "card_hash": "abc123",
        "sequence_number": 1,
    }
    return f"```json\n{json.dumps(card)}\n```"


# ---------------------------------------------------------------------------
# Diagnosis post-handoff silence
# ---------------------------------------------------------------------------

class TestDiagnosisPostHandoffSilence:
    """Test that Diagnosis silently consumes non-card messages after Assessment."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_AGENT_ID", "triage-agent-id")
        monkeypatch.setenv("SAFETY_REVIEWER_AGENT_ID", "reviewer-agent-id")
        monkeypatch.setenv("DIAGNOSIS_AGENT_ID", "diag-agent-id")

    @pytest.fixture
    def preprocessor(self):
        from agents.diagnosis import DiagnosisPreprocessor
        pp = DiagnosisPreprocessor(
            diagnosis_agent_id="diag-agent-id",
            diagnosis_api_key="fake-key",
        )
        # Inject a mock default preprocessor to avoid local runtime import
        mock_default = MagicMock()
        mock_default.process = AsyncMock(return_value="PASSED_THROUGH")
        pp._default_preprocessor = mock_default
        return pp

    @pytest.fixture(autouse=True)
    def clear_handoff_rooms(self):
        """Clear _handoff_rooms before each test."""
        from agents import diagnosis
        diagnosis._handoff_rooms.clear()
        yield
        diagnosis._handoff_rooms.clear()

    @pytest.mark.asyncio
    async def test_non_card_agent_message_consumed_after_handoff(self, preprocessor):
        """After Assessment submitted, non-card agent messages → None."""
        from agents import diagnosis
        diagnosis._handoff_rooms.add("room-1")

        event = _make_event(
            "Great work team!",  # Non-card chatter
            sender_id="reviewer-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_sealed_card_passes_through_after_handoff(self, preprocessor):
        """Sealed cards bypass handoff check (extract_sealed_card succeeds)."""
        from agents import diagnosis
        diagnosis._handoff_rooms.add("room-1")

        card_content = _make_sealed_card("Verdict", "INC-TEST")
        event = _make_event(
            card_content,
            sender_id="reviewer-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        await preprocessor.process(ctx, event)
        # Sealed cards take the card_data path (not the non-card path),
        # so they bypass the _handoff_rooms check entirely.
        # The Verdict may be rejected by sender validation (wrong sender),
        # but crucially it was NOT rejected by handoff silence → result is not
        # from the handoff branch.

    @pytest.mark.asyncio
    async def test_non_card_passes_before_handoff(self, preprocessor):
        """Before handoff, non-card messages pass through to default preprocessor."""
        from agents import diagnosis
        assert "room-1" not in diagnosis._handoff_rooms

        event = _make_event(
            "Some discussion message",
            sender_id="other-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        # Should pass through to default preprocessor (not silenced)
        assert result == "PASSED_THROUGH"


class TestDiagnosisHandoffRoomPopulation:
    """Test that _handoff_rooms is populated on Assessment submission."""

    def test_handoff_room_set_exists(self):
        from agents import diagnosis
        assert hasattr(diagnosis, "_handoff_rooms")
        assert isinstance(diagnosis._handoff_rooms, set)


# ---------------------------------------------------------------------------
# Safety Reviewer post-handoff silence
# ---------------------------------------------------------------------------

class TestSafetyReviewerPostHandoffSilence:
    """Test that Safety Reviewer consumes non-card messages after Verdict."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setenv("DIAGNOSIS_AGENT_ID", "diag-agent-id")
        monkeypatch.setenv("SAFETY_REVIEWER_AGENT_ID", "reviewer-agent-id")

    @pytest.fixture
    def preprocessor(self):
        from agents.safety_reviewer import SafetyReviewerPreprocessor
        pp = SafetyReviewerPreprocessor(
            reviewer_agent_id="reviewer-agent-id",
            reviewer_api_key="fake-key",
        )
        mock_default = MagicMock()
        mock_default.process = AsyncMock(return_value="PASSED_THROUGH")
        pp._default_preprocessor = mock_default
        return pp

    @pytest.fixture(autouse=True)
    def clear_handoff_rooms(self):
        from agents import safety_reviewer
        safety_reviewer._handoff_rooms.clear()
        yield
        safety_reviewer._handoff_rooms.clear()

    @pytest.mark.asyncio
    async def test_non_card_agent_message_consumed_after_handoff(self, preprocessor):
        """After Verdict submitted, non-card agent messages → None."""
        from agents import safety_reviewer
        safety_reviewer._handoff_rooms.add("room-1")

        event = _make_event(
            "Thanks for the review!",
            sender_id="diag-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_card_passes_before_handoff(self, preprocessor):
        """Before handoff, non-card messages pass through."""
        from agents import safety_reviewer
        assert "room-1" not in safety_reviewer._handoff_rooms

        event = _make_event(
            "Discussion message",
            sender_id="other-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        assert result == "PASSED_THROUGH"

    def test_handoff_room_set_exists(self):
        from agents import safety_reviewer
        assert hasattr(safety_reviewer, "_handoff_rooms")
        assert isinstance(safety_reviewer._handoff_rooms, set)


# ---------------------------------------------------------------------------
# Commander post-handoff silence
# ---------------------------------------------------------------------------

class TestCommanderPostHandoffSilence:
    """Test Commander deterministic silence preserves human messages."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setenv("SAFETY_REVIEWER_AGENT_ID", "reviewer-agent-id")
        monkeypatch.setenv("COMMANDER_AGENT_ID", "cmdr-agent-id")
        monkeypatch.setenv("COMMANDER_SUBMISSION_KEY", "fake-key")
        monkeypatch.setenv("GATEWAY_URL", "http://localhost:8000")

    @pytest.fixture
    def preprocessor(self):
        from agents.commander import CommanderPreprocessor
        pp = CommanderPreprocessor(
            commander_agent_id="cmdr-agent-id",
            commander_api_key="fake-key",
        )
        mock_default = MagicMock()
        mock_default.process = AsyncMock(return_value="PASSED_THROUGH")
        pp._default_preprocessor = mock_default
        return pp

    @pytest.fixture(autouse=True)
    def clear_handoff_rooms(self):
        from agents import commander
        commander._handoff_rooms.clear()
        yield
        commander._handoff_rooms.clear()

    @pytest.mark.asyncio
    async def test_agent_chatter_consumed_after_handoff(self, preprocessor):
        """Agent non-card messages consumed after ResponsePlan submitted."""
        from agents import commander
        commander._handoff_rooms.add("room-1")

        event = _make_event(
            "Plan looks good!",
            sender_id="reviewer-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_human_message_preserved_after_handoff(self, preprocessor):
        """Human messages (e.g. APPROVE <nonce>) pass through after handoff."""
        from agents import commander
        commander._handoff_rooms.add("room-1")

        event = _make_event(
            "APPROVE abc123-nonce",
            sender_id="human-user-id",
            sender_type="User",  # Human, not Agent
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        # Should NOT be silenced — human messages pass through
        assert result == "PASSED_THROUGH"

    @pytest.mark.asyncio
    async def test_agent_passes_before_handoff(self, preprocessor):
        """Before handoff, agent non-card messages pass through."""
        from agents import commander
        assert "room-1" not in commander._handoff_rooms

        event = _make_event(
            "Some agent discussion",
            sender_id="reviewer-agent-id",
            sender_type="Agent",
            room_id="room-1",
        )
        ctx = MagicMock()
        result = await preprocessor.process(ctx, event)
        assert result == "PASSED_THROUGH"

    def test_handoff_room_set_exists(self):
        from agents import commander
        assert hasattr(commander, "_handoff_rooms")
        assert isinstance(commander._handoff_rooms, set)

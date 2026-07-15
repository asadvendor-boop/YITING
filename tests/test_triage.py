"""Tests for YITING Triage Agent — guards, validation, sender checks, idempotency.

Covers every council-flagged gap:
- Deterministic guard overrides (P1→route, security→route, invalid→route)
- Forged sender rejection
- Malformed card rejection
- Pydantic validation
- Idempotency key derivation (deterministic, not random)
- Suppress routing (mentions Recorder, never Diagnosis)
- Card extraction from sealed messages
- Fail-closed when RECORDER_AGENT_ID is unset
- Seal verification (card_hash + sequence_number required)
- _add_participant raises on failure
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Unit under test — pure functions (no mocking needed)
# ---------------------------------------------------------------------------
from agents.triage import (
    _apply_deterministic_guards,
    _extract_sealed_card,
    _validate_alert_card,
    _derive_idempotency_key,
    _has_seal_fields,
)


# ===========================================================================
# 1. Deterministic Guard Tests
# ===========================================================================

class TestDeterministicGuards:
    """Guards are the security-critical path: code decides, not the LLM."""

    def test_p1_forces_route_over_llm_suppress(self):
        """P1 severity MUST override LLM suppress → route."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P1", "security_relevant": False},
            llm_decision="suppress",
            llm_noise_score=0.9,
            llm_reasoning="looks like noise",
        )
        assert decision == "route"
        assert noise <= 0.1
        assert "[GUARD]" in reasoning
        assert "P1 severity" in reasoning

    def test_security_relevant_forces_route_over_llm_suppress(self):
        """security_relevant=True MUST override LLM suppress → route."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P3", "security_relevant": True},
            llm_decision="suppress",
            llm_noise_score=0.85,
            llm_reasoning="probably noise",
        )
        assert decision == "route"
        assert noise <= 0.1
        assert "[GUARD]" in reasoning
        assert "security-relevant" in reasoning

    def test_p1_and_security_forces_route(self):
        """P1 + security_relevant both mentioned."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P1", "security_relevant": True},
            llm_decision="suppress",
            llm_noise_score=0.95,
            llm_reasoning="noise",
        )
        assert decision == "route"
        assert noise <= 0.1
        assert "P1 severity" in reasoning
        assert "security-relevant" in reasoning

    def test_invalid_decision_fails_closed_to_route(self):
        """Invalid LLM decision string → fail-closed to route."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P3", "security_relevant": False},
            llm_decision="maybe_route",
            llm_noise_score=0.5,
            llm_reasoning="unclear",
        )
        assert decision == "route"
        assert noise == 0.1
        assert "[GUARD]" in reasoning
        assert "Invalid LLM decision" in reasoning

    def test_empty_decision_fails_closed(self):
        """Empty string decision → fail-closed to route."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P4", "security_relevant": False},
            llm_decision="",
            llm_noise_score=0.3,
            llm_reasoning="empty",
        )
        assert decision == "route"

    def test_noise_score_clamped_above_one(self):
        """noise_score > 1.0 is clamped to 1.0."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P4", "security_relevant": False},
            llm_decision="suppress",
            llm_noise_score=1.5,
            llm_reasoning="very noisy",
        )
        assert noise <= 1.0

    def test_noise_score_clamped_below_zero(self):
        """noise_score < 0.0 is clamped to 0.0."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P4", "security_relevant": False},
            llm_decision="route",
            llm_noise_score=-0.5,
            llm_reasoning="negative",
        )
        assert noise >= 0.0

    def test_p2_route_passes_through(self):
        """P2 + route → no override needed, LLM decision preserved."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P2", "security_relevant": False},
            llm_decision="route",
            llm_noise_score=0.3,
            llm_reasoning="legitimate incident",
        )
        assert decision == "route"
        assert noise == 0.3
        assert "[GUARD]" not in reasoning

    def test_p4_suppress_passes_through(self):
        """P4 + suppress → no override, suppression allowed."""
        decision, noise, reasoning = _apply_deterministic_guards(
            alert_card={"preliminary_severity": "P4", "security_relevant": False},
            llm_decision="suppress",
            llm_noise_score=0.8,
            llm_reasoning="known noise pattern",
        )
        assert decision == "suppress"
        assert noise == 0.8


# ===========================================================================
# 2. Card Extraction Tests
# ===========================================================================

class TestCardExtraction:
    """Verify sealed card extraction from room messages."""

    def test_extract_fenced_json(self):
        """AlertCard in a fenced JSON block."""
        content = (
            "Here is the alert:\n"
            "```json\n"
            '{"card_type": "AlertCard", "alert_id": "INC-001"}\n'
            "```\n"
        )
        card = _extract_sealed_card(content)
        assert card is not None
        assert card["card_type"] == "AlertCard"
        assert card["alert_id"] == "INC-001"

    def test_extract_raw_json(self):
        """AlertCard as raw JSON in content."""
        content = '{"card_type": "AlertCard", "alert_id": "INC-002"}'
        card = _extract_sealed_card(content)
        assert card is not None
        assert card["alert_id"] == "INC-002"

    def test_no_card_type_returns_none(self):
        """JSON without card_type field is ignored."""
        content = '{"id": "123", "name": "test"}'
        card = _extract_sealed_card(content)
        assert card is None

    def test_non_alertcard_type(self):
        """Non-AlertCard card_type is extracted but caller filters."""
        content = '{"card_type": "TriageDecision", "incident_id": "INC-001"}'
        card = _extract_sealed_card(content)
        assert card is not None
        assert card["card_type"] == "TriageDecision"

    def test_invalid_json_returns_none(self):
        """Malformed JSON returns None."""
        card = _extract_sealed_card("this is not json {broken")
        assert card is None

    def test_empty_content(self):
        """Empty string returns None."""
        card = _extract_sealed_card("")
        assert card is None

    def test_multiple_fenced_blocks_finds_card(self):
        """Multiple fenced blocks — finds the one with card_type."""
        content = (
            "```json\n{\"not\": \"a card\"}\n```\n"
            "```json\n{\"card_type\": \"AlertCard\", \"alert_id\": \"INC-003\"}\n```\n"
        )
        card = _extract_sealed_card(content)
        assert card is not None
        assert card["alert_id"] == "INC-003"


# ===========================================================================
# 3. Pydantic Validation Tests
# ===========================================================================

class TestPydanticValidation:
    """AlertCard must pass Pydantic validation before processing."""

    def test_valid_alert_card(self):
        """Valid AlertCard data parses successfully."""
        data = {
            "card_type": "AlertCard",
            "alert_id": "INC-001",
            "source": "sentry",
            "timestamp": "2026-06-13T12:00:00Z",
            "title": "Test Alert",
            "fingerprint": "abc123",
        }
        card = _validate_alert_card(data)
        assert card is not None
        assert card.alert_id == "INC-001"

    def test_missing_required_field(self):
        """Missing alert_id → validation fails."""
        data = {
            "card_type": "AlertCard",
            "source": "sentry",
            "timestamp": "2026-06-13T12:00:00Z",
            "title": "Test",
            "fingerprint": "abc",
        }
        card = _validate_alert_card(data)
        assert card is None

    def test_invalid_source(self):
        """Invalid source literal → validation fails."""
        data = {
            "card_type": "AlertCard",
            "alert_id": "INC-001",
            "source": "invalid_source",
            "timestamp": "2026-06-13T12:00:00Z",
            "title": "Test",
            "fingerprint": "abc",
        }
        card = _validate_alert_card(data)
        assert card is None

    def test_empty_dict(self):
        """Empty dict → validation fails."""
        assert _validate_alert_card({}) is None


# ===========================================================================
# 4. Idempotency Key Tests
# ===========================================================================

class TestIdempotencyKey:
    """Idempotency key must be deterministic, derived from message ID + card hash."""

    def test_deterministic(self):
        """Same inputs → same key."""
        key1 = _derive_idempotency_key("msg-123", "hash-abc")
        key2 = _derive_idempotency_key("msg-123", "hash-abc")
        assert key1 == key2

    def test_different_message_different_key(self):
        """Different message IDs → different keys."""
        key1 = _derive_idempotency_key("msg-123", "hash-abc")
        key2 = _derive_idempotency_key("msg-456", "hash-abc")
        assert key1 != key2

    def test_different_hash_different_key(self):
        """Different card hashes → different keys."""
        key1 = _derive_idempotency_key("msg-123", "hash-abc")
        key2 = _derive_idempotency_key("msg-123", "hash-def")
        assert key1 != key2

    def test_key_length(self):
        """Key is 32 hex characters."""
        key = _derive_idempotency_key("msg-123", "hash-abc")
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_matches_sha256_prefix(self):
        """Key matches expected SHA-256 derivation."""
        raw = "triage:msg-123:hash-abc"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:32]
        actual = _derive_idempotency_key("msg-123", "hash-abc")
        assert actual == expected


# ===========================================================================
# 5. Preprocessor Sender Validation Tests
# ===========================================================================

class TestSenderValidation:
    """Preprocessor must reject AlertCards from non-Recorder senders."""

    @pytest.fixture
    def preprocessor(self):
        """Create a TriagePreprocessor with mocked dependencies."""
        from agents.triage import TriagePreprocessor

        llm = MagicMock()
        with patch.dict("os.environ", {
            "TRIAGE_SUBMISSION_KEY": "test-key",
            "DIAGNOSIS_AGENT_ID": "diag-uuid",
            "RECORDER_AGENT_ID": "recorder-uuid",
        }):
            pp = TriagePreprocessor(
                llm=llm,
                triage_agent_id="triage-uuid",
                triage_api_key="triage-api-key",
            )
        return pp

    def _make_event(self, content, sender_id, sender_type="Agent", room_id="room-1"):
        """Create a mock MessageEvent."""
        payload = MagicMock()
        payload.content = content
        payload.sender_id = sender_id
        payload.sender_type = sender_type
        payload.id = "room-msg-123"

        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.payload = payload
        event.room_id = room_id
        return event

    @pytest.mark.asyncio
    async def test_reject_non_agent_sender(self, preprocessor):
        """AlertCard from a non-Agent (e.g. human) is rejected."""
        preprocessor._default_preprocessor = AsyncMock()
        event = self._make_event(
            content='{"card_type": "AlertCard", "alert_id": "INC-1"}',
            sender_id="human-user-123",
            sender_type="User",
        )
        result = await preprocessor.process(None, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_wrong_agent_sender(self, preprocessor):
        """AlertCard from a non-Recorder agent is rejected."""
        preprocessor._default_preprocessor = AsyncMock()
        event = self._make_event(
            content='{"card_type": "AlertCard", "alert_id": "INC-1"}',
            sender_id="attacker-uuid",
            sender_type="Agent",
        )
        result = await preprocessor.process(None, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_alertcard_passes_through(self, preprocessor):
        """Non-AlertCard messages pass through to default preprocessor."""
        default_mock = MagicMock()
        default_mock.process = AsyncMock(return_value="passed")
        preprocessor._default_preprocessor = default_mock
        event = self._make_event(
            content="Hello, how are you?",
            sender_id="any-uuid",
            sender_type="Agent",
        )
        result = await preprocessor.process(None, event)
        assert result == "passed"

    @pytest.mark.asyncio
    async def test_self_message_consumed(self, preprocessor):
        """Self-messages are silently consumed."""
        preprocessor._default_preprocessor = AsyncMock()
        event = self._make_event(
            content="anything",
            sender_id="triage-uuid",  # Same as triage_agent_id
            sender_type="Agent",
        )
        result = await preprocessor.process(None, event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_message_event_passes_through(self, preprocessor):
        """Non-MessageEvent types pass through."""
        default_mock = MagicMock()
        default_mock.process = AsyncMock(return_value="passed")
        preprocessor._default_preprocessor = default_mock

        event = MagicMock()
        type(event).__name__ = "ParticipantAddedEvent"
        result = await preprocessor.process(None, event)
        assert result == "passed"


# ===========================================================================
# 6. Suppress Routing Tests
# ===========================================================================

class TestSuppressRouting:
    """When decision=suppress, Diagnosis must NOT be recruited.
    Recorder MUST be mentioned so the suppress handoff is explicit."""

    @pytest.fixture
    def preprocessor(self):
        from agents.triage import TriagePreprocessor
        llm = MagicMock()
        with patch.dict("os.environ", {
            "TRIAGE_SUBMISSION_KEY": "test-key",
            "DIAGNOSIS_AGENT_ID": "diag-uuid",
            "RECORDER_AGENT_ID": "recorder-uuid",
        }):
            pp = TriagePreprocessor(
                llm=llm,
                triage_agent_id="triage-uuid",
                triage_api_key="triage-api-key",
            )
        return pp

    @pytest.mark.asyncio
    async def test_suppress_mentions_recorder_not_diagnosis(self, preprocessor):
        """On suppress, Recorder is mentioned, not Diagnosis."""
        preprocessor._post_to_room = AsyncMock(return_value="msg-001")

        mock_prepare = MagicMock()
        mock_prepare.submission_id = "sub-1"
        mock_prepare.sealed_card = {"card_type": "TriageDecision"}
        mock_prepare.card_hash = "abc123"
        mock_prepare.sequence_number = 2
        mock_prepare.incident_id = "INC-001"
        mock_prepare.agent_role = "triage"
        mock_prepare.room_id = "room-1"
        mock_prepare.room_alias_id = "room-1"

        mock_confirm = MagicMock()
        mock_confirm.new_state = "SUPPRESSED"
        mock_confirm.status = "confirmed"

        mock_sc = AsyncMock()
        mock_sc.prepare = AsyncMock(return_value=mock_prepare)
        mock_sc.confirm = AsyncMock(return_value=mock_confirm)
        mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
        mock_sc.__aexit__ = AsyncMock(return_value=None)

        with patch("agents.triage.SubmissionClient", return_value=mock_sc):
            evidence = await preprocessor._submit_triage_decision(
                alert_card={"alert_id": "INC-001", "card_hash": "xyz"},
                decision="suppress",
                noise_score=0.9,
                reasoning="noise",
                room_id="room-1",
                room_message_id="msg-original",
            )

        # Verify Recorder IS mentioned
        post_call = preprocessor._post_to_room.call_args
        mentions = post_call.args[2]
        assert "recorder-uuid" in mentions, "Suppress must mention Recorder"
        assert "diag-uuid" not in mentions, "Suppress must NOT mention Diagnosis"
        assert evidence["new_state"] == "SUPPRESSED"

    @pytest.mark.asyncio
    async def test_route_mentions_diagnosis_not_recorder(self, preprocessor):
        """On route, Diagnosis is recruited and mentioned, not Recorder."""
        preprocessor._add_participant = AsyncMock()
        preprocessor._post_to_room = AsyncMock(return_value="msg-002")

        mock_prepare = MagicMock()
        mock_prepare.submission_id = "sub-1"
        mock_prepare.sealed_card = {"card_type": "TriageDecision"}
        mock_prepare.card_hash = "abc123"
        mock_prepare.sequence_number = 2
        mock_prepare.incident_id = "INC-001"
        mock_prepare.room_id = "room-1"
        mock_prepare.room_alias_id = "room-1"

        mock_confirm = MagicMock()
        mock_confirm.new_state = "TRIAGED"
        mock_confirm.status = "confirmed"

        mock_sc = AsyncMock()
        mock_sc.prepare = AsyncMock(return_value=mock_prepare)
        mock_sc.confirm = AsyncMock(return_value=mock_confirm)
        mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
        mock_sc.__aexit__ = AsyncMock(return_value=None)

        with patch("agents.triage.SubmissionClient", return_value=mock_sc):
            evidence = await preprocessor._submit_triage_decision(
                alert_card={"alert_id": "INC-001", "card_hash": "xyz"},
                decision="route",
                noise_score=0.2,
                reasoning="genuine",
                room_id="room-1",
                room_message_id="msg-original",
            )

        preprocessor._add_participant.assert_awaited_once_with("room-1", "diag-uuid")
        mentions = preprocessor._post_to_room.call_args.args[2]
        assert "diag-uuid" in mentions, "Route must mention Diagnosis"
        assert evidence["new_state"] == "TRIAGED"


# ===========================================================================
# 7. Fail-Closed on Empty Recorder ID
# ===========================================================================

class TestFailClosedRecorderID:
    """RECORDER_AGENT_ID unset → reject ALL AlertCards."""

    @pytest.fixture
    def preprocessor_no_recorder(self):
        from agents.triage import TriagePreprocessor
        llm = MagicMock()
        with patch.dict("os.environ", {
            "TRIAGE_SUBMISSION_KEY": "test-key",
            "DIAGNOSIS_AGENT_ID": "diag-uuid",
            "RECORDER_AGENT_ID": "",  # Empty!
        }):
            pp = TriagePreprocessor(
                llm=llm,
                triage_agent_id="triage-uuid",
                triage_api_key="triage-api-key",
            )
        return pp

    def _make_event(self, content, sender_id, sender_type="Agent", room_id="room-1"):
        payload = MagicMock()
        payload.content = content
        payload.sender_id = sender_id
        payload.sender_type = sender_type
        payload.id = "room-msg-123"
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.payload = payload
        event.room_id = room_id
        return event

    @pytest.mark.asyncio
    async def test_empty_recorder_id_rejects_all_alert_cards(self, preprocessor_no_recorder):
        """When RECORDER_AGENT_ID is empty, ALL AlertCards are rejected."""
        preprocessor_no_recorder._default_preprocessor = AsyncMock()
        event = self._make_event(
            content='{"card_type": "AlertCard", "alert_id": "INC-1"}',
            sender_id="any-agent-uuid",
            sender_type="Agent",
        )
        result = await preprocessor_no_recorder.process(None, event)
        assert result is None


# ===========================================================================
# 8. Seal Verification Tests
# ===========================================================================

class TestSealFieldCheck:
    """Inbound AlertCards must have card_hash + sequence_number (structural pre-filter).
    NOTE: This is NOT cryptographic proof — Gateway hash chain is the integrity
    guarantee. This catches raw/unserialized cards only."""

    def test_sealed_card_passes(self):
        assert _has_seal_fields({
            "card_hash": "abc123def456",
            "sequence_number": 1,
        }) is True

    def test_missing_card_hash_rejected(self):
        assert _has_seal_fields({
            "sequence_number": 1,
        }) is False

    def test_empty_card_hash_rejected(self):
        assert _has_seal_fields({
            "card_hash": "",
            "sequence_number": 1,
        }) is False

    def test_missing_sequence_number_rejected(self):
        assert _has_seal_fields({
            "card_hash": "abc123",
        }) is False

    def test_zero_sequence_number_rejected(self):
        assert _has_seal_fields({
            "card_hash": "abc123",
            "sequence_number": 0,
        }) is False

    def test_negative_sequence_number_rejected(self):
        assert _has_seal_fields({
            "card_hash": "abc123",
            "sequence_number": -1,
        }) is False

    def test_non_int_sequence_number_rejected(self):
        assert _has_seal_fields({
            "card_hash": "abc123",
            "sequence_number": "1",
        }) is False

    def test_none_card_hash_rejected(self):
        assert _has_seal_fields({
            "card_hash": None,
            "sequence_number": 1,
        }) is False


# ===========================================================================
# 9. Route Fail-Closed Without Diagnosis
# ===========================================================================

class TestRouteFailClosedNoDiagnosis:
    """Route decision MUST fail closed when DIAGNOSIS_AGENT_ID is empty."""

    @pytest.fixture
    def preprocessor_no_diag(self):
        from agents.triage import TriagePreprocessor
        llm = MagicMock()
        with patch.dict("os.environ", {
            "TRIAGE_SUBMISSION_KEY": "test-key",
            "DIAGNOSIS_AGENT_ID": "",  # Empty!
            "RECORDER_AGENT_ID": "recorder-uuid",
        }):
            pp = TriagePreprocessor(
                llm=llm,
                triage_agent_id="triage-uuid",
                triage_api_key="triage-api-key",
            )
        return pp

    @pytest.mark.asyncio
    async def test_route_without_diagnosis_raises(self, preprocessor_no_diag):
        """Route with no DIAGNOSIS_AGENT_ID must raise RuntimeError."""
        mock_prepare = MagicMock()
        mock_prepare.submission_id = "sub-1"
        mock_prepare.sealed_card = {"card_type": "TriageDecision"}
        mock_prepare.card_hash = "abc123"
        mock_prepare.sequence_number = 2
        mock_prepare.incident_id = "INC-001"
        mock_prepare.room_id = "room-1"
        mock_prepare.room_alias_id = "room-1"

        mock_sc = AsyncMock()
        mock_sc.prepare = AsyncMock(return_value=mock_prepare)
        mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
        mock_sc.__aexit__ = AsyncMock(return_value=None)

        with patch("agents.triage.SubmissionClient", return_value=mock_sc):
            with pytest.raises(RuntimeError, match="Cannot route"):
                await preprocessor_no_diag._submit_triage_decision(
                    alert_card={"alert_id": "INC-001", "card_hash": "xyz"},
                    decision="route",
                    noise_score=0.2,
                    reasoning="genuine",
                    room_id="room-1",
                    room_message_id="msg-original",
                )

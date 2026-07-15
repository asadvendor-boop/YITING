"""Regression tests for crash-recovery context restoration.

After a process restart the reasoning agents lose their in-memory
_trusted_context while the Gateway room ledger still holds the sealed cards.
Diagnosis must rebuild its context instead of dropping a CHALLENGE (which
would strand the room in CHALLENGED); Safety Reviewer must derive its
challenge budget from sealed CHALLENGE Verdicts instead of re-defaulting to
zero, so a restart can never grant extra challenges.
"""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.diagnosis as diagnosis_mod
import agents.safety_reviewer as safety_mod
from agents.diagnosis import DiagnosisPreprocessor
from agents.safety_reviewer import SafetyReviewerPreprocessor
from shared.context_restore import count_challenge_verdicts, latest_card_of_type

INCIDENT_ID = "INC-RESTORE-1"


def _make_event(content, sender_id, sender_type="Agent", room_id="room-1"):
    event = MagicMock()
    type(event).__name__ = "MessageEvent"
    event.room_id = room_id
    payload = MagicMock()
    payload.content = content
    payload.sender_id = sender_id
    payload.sender_type = sender_type
    payload.id = "msg-restore-001"
    del payload.room_id
    event.payload = payload
    return event


def _card_message(card: dict) -> str:
    return f"```json\n{json.dumps(card)}\n```"


def _sealed_cards(challenges: int = 1) -> list[dict]:
    """Ledger snapshot: TriageDecision + Assessment + N sealed CHALLENGE verdicts."""
    cards = [
        {
            "card_type": "TriageDecision",
            "incident_id": INCIDENT_ID,
            "alert_id": "ALT-9",
            "decision": "route",
            "card_hash": "hash-triage",
            "sequence_number": 2,
        },
        {
            "card_type": "Assessment",
            "incident_id": INCIDENT_ID,
            "severity": "P2",
            "evidence_strength": 0.8,
            "root_cause_hypothesis": "Bad deploy",
            "recommended_action": "rollback",
            "revision": 1,
            "card_hash": "hash-assessment",
            "sequence_number": 3,
        },
    ]
    for index in range(challenges):
        cards.append(
            {
                "card_type": "Verdict",
                "incident_id": INCIDENT_ID,
                "decision": "CHALLENGE",
                "cross_check_sources": ["sentry", "metrics"],
                "reasoning": "Evidence gap",
                "agrees_with_diagnosis": False,
                "challenge_request": f"Re-check source {index + 1}",
                "card_hash": f"hash-challenge-{index + 1}",
                "sequence_number": 4 + index,
            }
        )
    return cards


# ---------------------------------------------------------------------------
# Shared helper behavior
# ---------------------------------------------------------------------------

class TestRestoreHelpers:
    def test_count_challenge_verdicts_only_counts_challenges(self):
        cards = _sealed_cards(challenges=2)
        cards.append(
            {
                "card_type": "Verdict",
                "incident_id": INCIDENT_ID,
                "decision": "CONFIRM",
                "reasoning": "ok",
                "agrees_with_diagnosis": True,
                "card_hash": "hash-confirm",
                "sequence_number": 9,
            }
        )
        assert count_challenge_verdicts(cards) == 2

    def test_latest_card_of_type_returns_highest_sequence(self):
        cards = _sealed_cards(challenges=2)
        latest = latest_card_of_type(cards, "Verdict")
        assert latest is not None
        assert latest["card_hash"] == "hash-challenge-2"


# ---------------------------------------------------------------------------
# Diagnosis: CHALLENGE after restart must restore, not drop
# ---------------------------------------------------------------------------

class TestDiagnosisRestore:
    @pytest.fixture(autouse=True)
    def _clean_context(self):
        diagnosis_mod._trusted_context.clear()
        yield
        diagnosis_mod._trusted_context.clear()

    @pytest.fixture(autouse=True)
    def _disable_active_incidents_filter(self):
        with patch("agents.diagnosis.ACTIVE_INCIDENTS", new=set()):
            yield

    def _make_preprocessor(self):
        env = {
            "TRIAGE_AGENT_ID": "triage-uuid",
            "SAFETY_REVIEWER_AGENT_ID": "sr-agent-uuid",
        }
        with patch.dict(os.environ, env):
            pp = DiagnosisPreprocessor(
                diagnosis_agent_id="diag-456",
                diagnosis_api_key="key",
            )
        pp._default_preprocessor = MagicMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        return pp

    def _challenge_event(self, challenge_request="Check sentry again"):
        card = {
            "card_type": "Verdict",
            "incident_id": INCIDENT_ID,
            "decision": "CHALLENGE",
            "cross_check_sources": ["sentry"],
            "reasoning": "Insufficient evidence for claimed severity",
            "agrees_with_diagnosis": False,
            "challenge_request": challenge_request,
            "card_hash": "hash-challenge-live",
            "sequence_number": 4,
        }
        return _make_event(_card_message(card), sender_id="sr-agent-uuid")

    @pytest.mark.asyncio
    async def test_challenge_after_restart_restores_and_reinvestigates(self):
        pp = self._make_preprocessor()
        assert diagnosis_mod._trusted_context == {}

        with patch(
            "agents.diagnosis.fetch_confirmed_cards",
            new=AsyncMock(return_value=_sealed_cards(challenges=1)),
        ):
            await pp.process(MagicMock(), self._challenge_event())

        ctx = diagnosis_mod._trusted_context[INCIDENT_ID]
        assert ctx.submitted is False  # reset for re-investigation
        assert ctx.revision == 2  # one sealed challenge -> re-investigating v2
        assert ctx.alert_id == "ALT-9"
        assert ctx.challenge_request == "Check sentry again"
        assert ctx.tool_results == {}
        pp._default_preprocessor.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_challenge_without_sealed_assessment_still_dropped(self):
        pp = self._make_preprocessor()
        cards = [card for card in _sealed_cards(challenges=1) if card["card_type"] != "Assessment"]

        with patch(
            "agents.diagnosis.fetch_confirmed_cards",
            new=AsyncMock(return_value=cards),
        ):
            result = await pp.process(MagicMock(), self._challenge_event())

        assert result is None
        assert INCIDENT_ID not in diagnosis_mod._trusted_context
        pp._default_preprocessor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_derives_revision_from_sealed_challenges(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.diagnosis.fetch_confirmed_cards",
            new=AsyncMock(return_value=_sealed_cards(challenges=2)),
        ):
            await pp.process(MagicMock(), self._challenge_event())

        ctx = diagnosis_mod._trusted_context[INCIDENT_ID]
        assert ctx.revision == 3  # two sealed challenges -> re-investigating v3

    @pytest.mark.asyncio
    async def test_restore_unreachable_gateway_fails_closed(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.diagnosis.fetch_confirmed_cards",
            new=AsyncMock(return_value=[]),
        ):
            result = await pp.process(MagicMock(), self._challenge_event())

        assert result is None
        assert INCIDENT_ID not in diagnosis_mod._trusted_context

    @pytest.mark.asyncio
    async def test_terminal_challenge_after_restart_is_consumed_without_qwen(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.diagnosis.should_skip_terminal_incident",
            new=AsyncMock(return_value=True),
        ):
            result = await pp.process(MagicMock(), self._challenge_event())

        assert result is None
        assert INCIDENT_ID not in diagnosis_mod._trusted_context
        pp._default_preprocessor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_challenge_already_answered_by_later_assessment_is_consumed(self):
        pp = self._make_preprocessor()
        cards = _sealed_cards(challenges=1)
        cards.append(
            {
                "card_type": "Assessment",
                "incident_id": INCIDENT_ID,
                "severity": "P2",
                "evidence_strength": 0.9,
                "root_cause_hypothesis": "Bad deploy rechecked",
                "recommended_action": "circuit breaker",
                "revision": 2,
                "card_hash": "hash-assessment-v2",
                "sequence_number": 5,
            }
        )

        with patch(
            "agents.diagnosis.should_skip_terminal_incident",
            new=AsyncMock(return_value=False),
        ), patch(
            "agents.diagnosis.fetch_confirmed_cards",
            new=AsyncMock(return_value=cards),
        ):
            result = await pp.process(MagicMock(), self._challenge_event())

        assert result is None
        assert INCIDENT_ID not in diagnosis_mod._trusted_context
        pp._default_preprocessor.process.assert_not_called()


# ---------------------------------------------------------------------------
# Safety Reviewer: challenge budget survives restart
# ---------------------------------------------------------------------------

class TestSafetyReviewerBudgetRestore:
    @pytest.fixture(autouse=True)
    def _clean_context(self):
        safety_mod._trusted_context.clear()
        yield
        safety_mod._trusted_context.clear()

    @pytest.fixture(autouse=True)
    def _disable_active_incidents_filter(self):
        with patch("agents.safety_reviewer.ACTIVE_INCIDENTS", new=set()):
            yield

    @pytest.fixture(autouse=True)
    def _skip_stale_card_check(self):
        with patch(
            "agents.safety_reviewer.should_skip_stale_card",
            new=AsyncMock(return_value=False),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _agent_env(self, monkeypatch):
        monkeypatch.setenv("DIAGNOSIS_AGENT_ID", "diag-agent-id")

    def _make_preprocessor(self):
        pp = SafetyReviewerPreprocessor(
            reviewer_agent_id="reviewer-agent-id",
            reviewer_api_key="fake-key",
        )
        pp._default_preprocessor = MagicMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        return pp

    def _assessment_event(self, revision: int):
        card = {
            "card_type": "Assessment",
            "incident_id": INCIDENT_ID,
            "severity": "P2",
            "evidence_strength": 0.85,
            "root_cause_hypothesis": "Bad deploy",
            "recommended_action": "rollback",
            "revision": revision,
            "card_hash": f"hash-assessment-v{revision}",
            "sequence_number": 3 + revision,
        }
        return _make_event(_card_message(card), sender_id="diag-agent-id")

    @pytest.mark.asyncio
    async def test_restart_restores_challenge_budget_from_ledger(self):
        pp = self._make_preprocessor()
        assert safety_mod._trusted_context == {}

        with patch(
            "agents.safety_reviewer.fetch_confirmed_cards",
            new=AsyncMock(return_value=_sealed_cards(challenges=1)),
        ):
            await pp.process(MagicMock(), self._assessment_event(revision=2))

        ctx = safety_mod._trusted_context[INCIDENT_ID]
        assert ctx.challenge_count == 1  # NOT reset to 0 by the restart
        assert ctx.force_needs_human is False
        pp._default_preprocessor.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_with_exhausted_budget_goes_deterministic_needs_human(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.safety_reviewer.fetch_confirmed_cards",
            new=AsyncMock(return_value=_sealed_cards(challenges=2)),
        ), patch(
            "agents.safety_reviewer._submit_deterministic_verdict",
            new=AsyncMock(),
        ) as deterministic:
            result = await pp.process(MagicMock(), self._assessment_event(revision=3))

        assert result is None
        deterministic.assert_awaited_once()
        ctx = safety_mod._trusted_context[INCIDENT_ID]
        assert ctx.challenge_count == 2
        assert ctx.force_needs_human is True
        # No LLM review may be spent once the budget is exhausted.
        pp._default_preprocessor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_incident_cold_path_unchanged(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.safety_reviewer.fetch_confirmed_cards",
            new=AsyncMock(return_value=[]),
        ):
            await pp.process(MagicMock(), self._assessment_event(revision=1))

        ctx = safety_mod._trusted_context[INCIDENT_ID]
        assert ctx.challenge_count == 0
        assert ctx.force_needs_human is False
        pp._default_preprocessor.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminal_assessment_after_restart_is_consumed_without_qwen(self):
        pp = self._make_preprocessor()

        with patch(
            "agents.safety_reviewer.should_skip_terminal_incident",
            new=AsyncMock(return_value=True),
        ):
            result = await pp.process(MagicMock(), self._assessment_event(revision=1))

        assert result is None
        assert INCIDENT_ID not in safety_mod._trusted_context
        pp._default_preprocessor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_assessment_already_reviewed_in_ledger_is_consumed(self):
        pp = self._make_preprocessor()
        cards = _sealed_cards(challenges=0)
        cards.append(
            {
                "card_type": "Verdict",
                "incident_id": INCIDENT_ID,
                "decision": "CONFIRM",
                "cross_check_sources": ["sentry", "metrics"],
                "reasoning": "Assessment confirmed",
                "agrees_with_diagnosis": True,
                "card_hash": "hash-confirm",
                "sequence_number": 5,
            }
        )

        with patch(
            "agents.safety_reviewer.should_skip_terminal_incident",
            new=AsyncMock(return_value=False),
        ), patch(
            "agents.safety_reviewer.fetch_confirmed_cards",
            new=AsyncMock(return_value=cards),
        ):
            result = await pp.process(MagicMock(), self._assessment_event(revision=1))

        assert result is None
        assert INCIDENT_ID not in safety_mod._trusted_context
        pp._default_preprocessor.process.assert_not_called()

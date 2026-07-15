"""Safety Reviewer publication tests for Gateway-owned incident rooms."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.safety_reviewer import (
    ReviewContext,
    SubmitVerdict,
    _trusted_context,
    handle_submit_verdict,
)
from shared.models import Assessment


def _assessment() -> Assessment:
    return Assessment(
        incident_id="INC-SAFETY-ROOM",
        severity="P3",
        evidence_strength=0.85,
        blast_radius=["payment-service"],
        root_cause_hypothesis="Payment service deploy caused elevated errors.",
        recommended_action="Roll back the payment-service deployment.",
        revision=1,
        evidence={
            "signals": {
                "sentry": {"anomaly_detected": True},
                "metrics": {"anomaly_detected": True},
                "deploys": {"anomaly_detected": True},
                "uptime": {"anomaly_detected": False},
            },
            "tools_completed": ["sentry", "metrics", "deploys", "uptime"],
            "relevance_scores": {
                "sentry": 0.8,
                "metrics": 0.8,
                "deploys": 0.8,
                "uptime": 0.4,
            },
            "temporal_gap_minutes": 3,
        },
    )


@pytest.fixture(autouse=True)
def clean_context():
    _trusted_context.clear()
    yield
    _trusted_context.clear()


@pytest.mark.asyncio
async def test_confirm_verdict_uses_incident_room_client():
    assessment = _assessment()
    _trusted_context[assessment.incident_id] = ReviewContext(
        incident_id=assessment.incident_id,
        room_id="room-safety",
        room_message_id="msg-assessment",
        source_card_hash="hash-assessment",
        assessment_raw=assessment.model_dump(mode="json"),
        assessment=assessment,
    )

    mock_sc = AsyncMock()
    prepared = MagicMock()
    prepared.submission_id = "submission-safety"
    prepared.sealed_card = {"card_type": "Verdict", "card_hash": "hash-verdict"}
    prepared.card_hash = "hash-verdict"
    prepared.room_id = "room-safety"
    prepared.room_alias_id = "room-safety"
    prepared.incident_id = assessment.incident_id
    mock_sc.prepare = AsyncMock(return_value=prepared)
    mock_sc.confirm = AsyncMock(return_value=MagicMock(new_state="REVIEWED", status="confirmed"))
    mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
    mock_sc.__aexit__ = AsyncMock(return_value=False)

    mock_room = AsyncMock()
    mock_room.add_participant = AsyncMock()
    mock_room.post_message = AsyncMock(return_value="msg-verdict")
    mock_room.aclose = AsyncMock()

    with patch.dict(os.environ, {
        "SAFETY_REVIEWER_SUBMISSION_KEY": "safety-key",
        "SAFETY_REVIEWER_AGENT_ID": "safety-agent",
        "COMMANDER_AGENT_ID": "commander-agent",
    }), patch("agents.safety_reviewer.SubmissionClient", return_value=mock_sc), \
         patch("agents.safety_reviewer.IncidentRoomClient", return_value=mock_room):
        result = await handle_submit_verdict(SubmitVerdict(
            incident_id=assessment.incident_id,
            decision="CONFIRM",
            reasoning="Assessment is coherent and all evidence sources were queried.",
            agrees_with_diagnosis=True,
        ))

    assert "submitted successfully" in result
    mock_room.add_participant.assert_awaited_once_with(
        "room-safety",
        "commander-agent",
        role="commander",
        display_name="Commander",
    )
    post_kwargs = mock_room.post_message.call_args.kwargs
    assert post_kwargs["mentions"] == ["commander-agent"]
    assert post_kwargs["metadata"]["card_hash"] == "hash-verdict"
    mock_sc.confirm.assert_awaited_once_with(
        submission_id="submission-safety",
        incident_id=assessment.incident_id,
        card_hash="hash-verdict",
        message_id="msg-verdict",
        room_id="room-safety",
    )

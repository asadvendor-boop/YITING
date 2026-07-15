"""Commander publication tests for Gateway-owned incident rooms."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.commander import (
    CommanderContext,
    SubmitResponsePlan,
    _trusted_context,
    handle_submit_response_plan,
)


@pytest.fixture(autouse=True)
def clean_context():
    _trusted_context.clear()
    yield
    _trusted_context.clear()


@pytest.mark.asyncio
async def test_response_plan_uses_incident_room_client():
    incident_id = "INC-COMMANDER-ROOM"
    _trusted_context[incident_id] = CommanderContext(
        incident_id=incident_id,
        room_id="room-commander",
        room_message_id="msg-verdict",
        source_card_hash="hash-verdict",
        verdict_raw={"incident_id": incident_id, "decision": "CONFIRM"},
        assessment_raw={
            "incident_id": incident_id,
            "severity": "P4",
            "root_cause_hypothesis": "Checkout dependency latency is rising.",
            "recommended_action": "Enable a circuit breaker for checkout.",
            "blast_radius": ["payment-service"],
        },
        severity="P4",
        root_cause="Checkout dependency latency is rising.",
        recommended_action="Enable a circuit breaker for checkout.",
        blast_radius=["payment-service"],
    )

    mock_sc = AsyncMock()
    prepared = MagicMock()
    prepared.submission_id = "submission-commander"
    prepared.sealed_card = {
        "card_type": "ResponsePlan",
        "incident_id": incident_id,
        "card_hash": "hash-plan",
        "sequence_number": 5,
    }
    prepared.card_hash = "hash-plan"
    prepared.room_id = "room-commander"
    prepared.room_alias_id = "room-commander"
    prepared.incident_id = incident_id
    mock_sc.prepare = AsyncMock(return_value=prepared)
    mock_sc.confirm = AsyncMock(
        return_value=MagicMock(new_state="PLANNED", status="confirmed")
    )
    mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
    mock_sc.__aexit__ = AsyncMock(return_value=False)

    mock_room = AsyncMock()
    mock_room.add_participant = AsyncMock()
    mock_room.post_message = AsyncMock(return_value="msg-plan")
    mock_room.aclose = AsyncMock()

    with patch.dict(os.environ, {
        "COMMANDER_SUBMISSION_KEY": "commander-key",
        "COMMANDER_AGENT_ID": "commander-agent",
        "OPERATOR_AGENT_ID": "operator-agent",
    }), patch("agents.commander.SubmissionClient", return_value=mock_sc), \
         patch("agents.commander.IncidentRoomClient", return_value=mock_room), \
         patch("agents.commander._low_risk_flow", new=AsyncMock()) as low_flow:
        result = await handle_submit_response_plan(SubmitResponsePlan(
            incident_id=incident_id,
            runbook="RB-004",
            target_service="payment-service",
            reasoning="Circuit breaker limits dependency blast radius.",
        ))

    assert "ResponsePlan submitted" in result
    mock_room.add_participant.assert_awaited_once_with(
        "room-commander",
        "operator-agent",
        role="operator",
        display_name="Operator",
    )
    post_args = mock_room.post_message.call_args.args
    post_kwargs = mock_room.post_message.call_args.kwargs
    assert post_args[0] == "room-commander"
    assert "ResponsePlan" in post_args[1]
    assert post_kwargs["mentions"] == ["operator-agent"]
    assert post_kwargs["metadata"] == {
        "publisher": "commander",
        "card_hash": "hash-plan",
    }
    mock_sc.confirm.assert_awaited_once_with(
        submission_id="submission-commander",
        incident_id=incident_id,
        card_hash="hash-plan",
        message_id="msg-plan",
        room_id="room-commander",
    )
    low_flow.assert_awaited_once()

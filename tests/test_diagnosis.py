"""Tests for the Diagnosis agent (Gate A Checkpoint 2).

Tests cover:
  - Severity derivation (from impact metrics, NOT evidence_strength)
  - Evidence strength computation (shared/evidence.py integration)
  - Sender validation (only accepts Triage)
  - Decision filtering (route/suppress)
  - Trusted context lifecycle
  - submit_assessment guards
  - Recruitment ordering
  - Idempotency
  - Startup validation
  - Tool wiring (CustomToolDef tuples unpack correctly)
  - Room ID from event (not payload)

Architecture note:
  Tools use local-runtime tool callback: tuple[type[BaseModel], Callable].
  Callbacks receive validated Pydantic model, not **kwargs.
  Tool names: QueryMetrics → "querymetrics" (no underscores).
"""
from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Unit under test
# ---------------------------------------------------------------------------
from agents.diagnosis import (
    DiagnosisPreprocessor,
    IncidentContext,
    QueryMetrics,
    QueryErrors,
    QueryDeploys,
    QueryUptime,
    SubmitAssessment,
    _trusted_context,
    derive_severity,
    handle_query_metrics,
    handle_query_errors,
    handle_query_deploys,
    handle_query_uptime,
    handle_submit_assessment,
)
from shared.card_intake import (
    derive_idempotency_key,
)
from shared.evidence import compute_evidence_strength


# ---------------------------------------------------------------------------
# Module-level fixture: disable ACTIVE_INCIDENTS allowlist so test incident
# IDs (INC-TEST-001 etc.) aren't filtered by the VM's production allowlist.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _disable_active_incidents_filter():
    """Patch ACTIVE_INCIDENTS to empty set for all diagnosis tests."""
    with patch("agents.diagnosis.ACTIVE_INCIDENTS", new=set()):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(
    incident_id: str = "INC-TEST-001",
    **overrides,
) -> IncidentContext:
    """Create a test IncidentContext with defaults."""
    defaults = {
        "incident_id": incident_id,
        "alert_id": "ALT-001",
        "room_id": "room-abc",
        "room_message_id": "msg-123",
        "source_card_hash": "hash-abc",
        "triage_decision_raw": {"card_type": "TriageDecision"},
    }
    defaults.update(overrides)
    return IncidentContext(**defaults)


def _make_triage_decision_content(
    incident_id: str = "INC-TEST-001",
    decision: str = "route",
    card_hash: str = "abc123",
    sequence_number: int = 2,
) -> str:
    """Create a room message content string containing a TriageDecision."""
    card = {
        "card_type": "TriageDecision",
        "incident_id": incident_id,
        "alert_id": "ALT-001",
        "decision": decision,
        "noise_score": 0.1,
        "reasoning": "Test routing",
        "card_hash": card_hash,
        "sequence_number": sequence_number,
    }
    return f"```json\n{json.dumps(card)}\n```"


def _make_event(content, sender_id, sender_type="Agent", room_id="room-1"):
    """Create a mock MessageEvent with room_id on the EVENT (local room runtime)."""
    event = MagicMock()
    type(event).__name__ = "MessageEvent"
    # room_id lives on EVENT, not payload
    event.room_id = room_id
    payload = MagicMock()
    payload.content = content
    payload.sender_id = sender_id
    payload.sender_type = sender_type
    payload.id = "msg-001"
    # payload does NOT have room_id (local room runtime contract)
    del payload.room_id
    event.payload = payload
    return event


# ===========================
# TOOL WIRING TESTS
# ===========================

class TestToolWiring:
    """Verify tools conform to local-runtime tool callback contract."""

    def test_tools_are_tuples(self):
        """additional_tools must be list[tuple[BaseModel, Callable]]."""
        from agents.diagnosis import (
            SubmitAssessment,
            handle_query_metrics, handle_query_errors, handle_query_deploys,
            handle_query_uptime, handle_submit_assessment,
        )
        tools = [
            (QueryMetrics, handle_query_metrics),
            (QueryErrors, handle_query_errors),
            (QueryDeploys, handle_query_deploys),
            (QueryUptime, handle_query_uptime),
            (SubmitAssessment, handle_submit_assessment),
        ]
        for model, func in tools:  # Must unpack as (model, func)
            assert issubclass(model, __import__("pydantic").BaseModel)
            assert callable(func)

    def test_tool_name_derivation(self):
        """Tool names match local runtime's local tool name pattern."""
        # local tool name: strips "Input", lowercases
        expected = {
            "QueryMetrics": "querymetrics",
            "QueryErrors": "queryerrors",
            "QueryDeploys": "querydeploys",
            "QueryUptime": "queryuptime",
            "SubmitAssessment": "submitassessment",
        }
        for cls_name, expected_name in expected.items():
            # Simulate local tool name logic
            name = cls_name
            if name.endswith("Input"):
                name = name[:-5]
            name = name.lower()
            assert name == expected_name, f"{cls_name} → {name} != {expected_name}"

    def test_callbacks_accept_pydantic_model(self):
        """Callbacks must accept a single Pydantic model param (not **kwargs)."""
        import inspect
        for func in [
            handle_query_metrics, handle_query_errors,
            handle_query_deploys, handle_query_uptime,
            handle_submit_assessment,
        ]:
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            assert len(params) == 1, (
                f"{func.__name__} should have 1 param, has {len(params)}"
            )
            assert params[0].name == "input", (
                f"{func.__name__} first param should be 'input', is '{params[0].name}'"
            )


# ===========================
# SEVERITY DERIVATION TESTS
# ===========================

class TestDeriveSeverity:
    """Severity derives from IMPACT metrics, not evidence_strength."""

    def test_high_error_rate_is_p1(self):
        assert derive_severity({"error_rate": 35.0, "latency_p99": 100}, {"uptime_percentage": 99.9}) == "P1"

    def test_low_uptime_is_p1(self):
        assert derive_severity({"error_rate": 1.0}, {"uptime_percentage": 91.3}) == "P1"

    def test_moderate_error_rate_is_p2(self):
        assert derive_severity({"error_rate": 15.0}, {"uptime_percentage": 99.0}) == "P2"

    def test_high_latency_is_p2(self):
        assert derive_severity({"error_rate": 1.0, "latency_p99": 6000}, {"uptime_percentage": 99.0}) == "P2"

    def test_minor_error_rate_is_p3(self):
        assert derive_severity({"error_rate": 5.0}, {"uptime_percentage": 99.0}) == "P3"

    def test_minor_latency_is_p3(self):
        assert derive_severity({"error_rate": 0.5, "latency_p99": 3000}, {"uptime_percentage": 99.0}) == "P3"

    def test_healthy_is_p4(self):
        assert derive_severity({"error_rate": 0.1, "latency_p99": 45}, {"uptime_percentage": 99.97}) == "P4"

    def test_defaults_when_missing_fields(self):
        assert derive_severity({}, {}) == "P4"

    def test_severity_independent_of_evidence_strength(self):
        """P1 outage with low-confidence hypothesis is still P1."""
        assert derive_severity({"error_rate": 50.0}, {"uptime_percentage": 80.0}) == "P1"


# ===========================
# EVIDENCE STRENGTH TESTS
# ===========================

class TestEvidenceStrength:

    def test_zero_signals_produce_zero(self):
        signals = {k: {"anomaly_detected": False, "relevance_score": 0.0} for k in ("sentry", "metrics", "deploys", "uptime")}
        assert compute_evidence_strength(signals, "test") == pytest.approx(0.0, abs=0.01)

    def test_full_anomaly_produces_high_score(self):
        signals = {
            k: {"anomaly_detected": True, "relevance_score": 0.9}
            for k in ("sentry", "metrics", "deploys", "uptime")
        }
        signals["deploy_to_error_gap_minutes"] = 3
        signals["freshness_minutes"] = 5
        assert compute_evidence_strength(signals, "NullPointerException") > 0.7

    def test_partial_sources_produce_partial_score(self):
        signals = {
            "sentry": {"anomaly_detected": True, "relevance_score": 0.8},
            "metrics": {"anomaly_detected": True, "relevance_score": 0.8},
            "deploys": {"anomaly_detected": False, "relevance_score": 0.2},
            "uptime": {"anomaly_detected": False, "relevance_score": 0.2},
            "deploy_to_error_gap_minutes": 30,
            "freshness_minutes": 10,
        }
        result = compute_evidence_strength(signals, "test")
        assert 0.1 < result < 0.7

    def test_four_source_ceiling_exceeds_three(self):
        def make(n):
            return {
                k: {"anomaly_detected": True, "relevance_score": 1.0}
                for k in ("sentry", "metrics", "deploys", "uptime")[:n]
            }

        s3 = {**make(3), "uptime": {"anomaly_detected": False, "relevance_score": 0.0},
              "deploy_to_error_gap_minutes": 1, "freshness_minutes": 1}
        s4 = {**make(4), "deploy_to_error_gap_minutes": 1, "freshness_minutes": 1}
        assert compute_evidence_strength(s4, "h") > compute_evidence_strength(s3, "h")


# ===========================
# SENDER VALIDATION TESTS
# ===========================

class TestSenderValidation:

    @pytest.fixture
    def preprocessor(self):
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-uuid-123"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        return pp

    @pytest.mark.asyncio
    async def test_accepts_triage_sender(self, preprocessor):
        _trusted_context.clear()
        event = _make_event(_make_triage_decision_content(), "triage-uuid-123")
        await preprocessor.process(MagicMock(), event)
        assert "INC-TEST-001" in _trusted_context

    @pytest.mark.asyncio
    async def test_rejects_wrong_agent(self, preprocessor):
        _trusted_context.clear()
        event = _make_event(_make_triage_decision_content(), "wrong-agent")
        result = await preprocessor.process(MagicMock(), event)
        assert result is None
        assert "INC-TEST-001" not in _trusted_context

    @pytest.mark.asyncio
    async def test_rejects_non_agent_sender(self, preprocessor):
        _trusted_context.clear()
        event = _make_event(_make_triage_decision_content(), "triage-uuid-123", sender_type="User")
        result = await preprocessor.process(MagicMock(), event)
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_when_triage_id_not_configured(self):
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": ""}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-123", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        event = _make_event(_make_triage_decision_content(), "some-agent")
        result = await pp.process(MagicMock(), event)
        assert result is None


# ===========================
# ROOM ID SOURCE TEST
# ===========================

class TestRoomIdSource:
    """room_id must come from event, not payload (local room runtime)."""

    @pytest.mark.asyncio
    async def test_room_id_from_event(self):
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-uuid"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())

        event = _make_event(
            _make_triage_decision_content(incident_id="INC-ROOM"),
            "triage-uuid",
            room_id="correct-room-from-event",
        )
        await pp.process(MagicMock(), event)

        ctx = _trusted_context.get("INC-ROOM")
        assert ctx is not None
        assert ctx.room_id == "correct-room-from-event"


# ===========================
# DECISION FILTERING TESTS
# ===========================

class TestDecisionFiltering:

    @pytest.fixture
    def preprocessor(self):
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-uuid-123"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        return pp

    @pytest.mark.asyncio
    async def test_route_accepted(self, preprocessor):
        _trusted_context.clear()
        event = _make_event(_make_triage_decision_content(decision="route"), "triage-uuid-123")
        await preprocessor.process(MagicMock(), event)
        assert "INC-TEST-001" in _trusted_context

    @pytest.mark.asyncio
    async def test_suppress_rejected(self, preprocessor):
        _trusted_context.clear()
        event = _make_event(_make_triage_decision_content(decision="suppress"), "triage-uuid-123")
        result = await preprocessor.process(MagicMock(), event)
        assert result is None
        assert "INC-TEST-001" not in _trusted_context


# ===========================
# TRUSTED CONTEXT LIFECYCLE
# ===========================

class TestTrustedContextLifecycle:

    @pytest.mark.asyncio
    async def test_context_created_on_validation(self):
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-123"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        event = _make_event(
            _make_triage_decision_content(incident_id="INC-LC"),
            "triage-123", room_id="room-lc",
        )
        await pp.process(MagicMock(), event)
        ctx = _trusted_context["INC-LC"]
        assert ctx.room_id == "room-lc"
        assert not ctx.submitted

    @pytest.mark.asyncio
    async def test_duplicate_active_context_rejected(self):
        _trusted_context.clear()
        _trusted_context["INC-DUP"] = _make_context(incident_id="INC-DUP")
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-123"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        event = _make_event(
            _make_triage_decision_content(incident_id="INC-DUP"),
            "triage-123", room_id="room-2",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        assert _trusted_context["INC-DUP"].room_id == "room-abc"

    @pytest.mark.asyncio
    async def test_redelivery_after_submission_rejected(self):
        """Redelivered TriageDecision for already-submitted incident → rejected.

        Prevents duplicate Assessment publication and unnecessary LLM cost.
        """
        _trusted_context.clear()
        submitted_ctx = _make_context(incident_id="INC-DONE")
        submitted_ctx.submitted = True
        _trusted_context["INC-DONE"] = submitted_ctx
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-123"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-456", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        event = _make_event(
            _make_triage_decision_content(incident_id="INC-DONE"),
            "triage-123", room_id="room-redeliver",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        # Original submitted context preserved, NOT overwritten
        assert _trusted_context["INC-DONE"].room_id == "room-abc"
        assert _trusted_context["INC-DONE"].submitted is True


# ===========================
# SUBMIT_ASSESSMENT GUARDS
# ===========================

class TestSubmitAssessmentGuards:

    @pytest.mark.asyncio
    async def test_unknown_incident_rejected(self):
        _trusted_context.clear()
        input_model = SubmitAssessment(
            incident_id="INC-FAKE", root_cause_hypothesis="test",
            recommended_action="restart", blast_radius=["api"],
            sentry_relevance=0.5, metrics_relevance=0.5,
            deploys_relevance=0.5, uptime_relevance=0.5,
        )
        result = await handle_submit_assessment(input_model)
        assert "error" in result.lower() or "unknown" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_metrics_blocked(self):
        """Missing metrics → submission blocked."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-NO-MET")
        ctx.tools_completed = {"sentry", "deploys", "uptime"}
        _trusted_context["INC-NO-MET"] = ctx
        result = await handle_submit_assessment(SubmitAssessment(
            incident_id="INC-NO-MET", root_cause_hypothesis="t",
            recommended_action="r", blast_radius=[],
            sentry_relevance=0.5, metrics_relevance=0.5,
            deploys_relevance=0.5, uptime_relevance=0.5,
        ))
        assert "required" in result.lower() or "metrics" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_sentry_blocked(self):
        """Missing sentry → submission blocked."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-NO-SEN")
        ctx.tools_completed = {"metrics", "deploys", "uptime"}
        _trusted_context["INC-NO-SEN"] = ctx
        result = await handle_submit_assessment(SubmitAssessment(
            incident_id="INC-NO-SEN", root_cause_hypothesis="t",
            recommended_action="r", blast_radius=[],
            sentry_relevance=0.5, metrics_relevance=0.5,
            deploys_relevance=0.5, uptime_relevance=0.5,
        ))
        assert "required" in result.lower() or "sentry" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_deploys_blocked(self):
        """Missing deploys → submission blocked."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-NO-DEP")
        ctx.tools_completed = {"metrics", "sentry", "uptime"}
        _trusted_context["INC-NO-DEP"] = ctx
        result = await handle_submit_assessment(SubmitAssessment(
            incident_id="INC-NO-DEP", root_cause_hypothesis="t",
            recommended_action="r", blast_radius=[],
            sentry_relevance=0.5, metrics_relevance=0.5,
            deploys_relevance=0.5, uptime_relevance=0.5,
        ))
        assert "required" in result.lower() or "deploys" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_uptime_blocked(self):
        """Missing uptime → submission blocked."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-NO-UP")
        ctx.tools_completed = {"metrics", "sentry", "deploys"}
        _trusted_context["INC-NO-UP"] = ctx
        result = await handle_submit_assessment(SubmitAssessment(
            incident_id="INC-NO-UP", root_cause_hypothesis="t",
            recommended_action="r", blast_radius=[],
            sentry_relevance=0.5, metrics_relevance=0.5,
            deploys_relevance=0.5, uptime_relevance=0.5,
        ))
        assert "required" in result.lower() or "uptime" in result.lower()

    @pytest.mark.asyncio
    async def test_all_four_sources_allows_submission(self):
        """All 4 sources present → submission proceeds (hits saga mock)."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-ALL")
        ctx.tool_results = {
            "metrics": {"error_rate": 1.0, "latency_p99": 50, "anomaly_detected": False},
            "sentry": {"anomaly_detected": False},
            "deploys": {"anomaly_detected": False},
            "uptime": {"uptime_percentage": 99.9, "anomaly_detected": False},
        }
        ctx.tools_completed = {"metrics", "sentry", "deploys", "uptime"}
        _trusted_context["INC-ALL"] = ctx

        with patch.dict(os.environ, {
            "DIAGNOSIS_SUBMISSION_KEY": "k",
            "SAFETY_REVIEWER_AGENT_ID": "r",
            "DIAGNOSIS_AGENT_ID": "d",
        }), patch("agents.diagnosis.SubmissionClient") as MockSC, \
             patch("agents.diagnosis.IncidentRoomClient") as MockRoomClient:

            mock_sc = AsyncMock()
            mock_sc.prepare = AsyncMock(return_value=MagicMock(
                submission_id="s", sealed_card={}, card_hash="h",
                room_id="r", room_alias_id="r", incident_id="INC-ALL",
            ))
            mock_sc.confirm = AsyncMock(return_value=MagicMock(new_state="ASSESSED"))
            mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
            mock_sc.__aexit__ = AsyncMock(return_value=False)
            MockSC.return_value = mock_sc

            mock_room = AsyncMock()
            mock_room.add_participant = AsyncMock()
            mock_room.post_message = AsyncMock(return_value="m")
            mock_room.aclose = AsyncMock()
            MockRoomClient.return_value = mock_room

            result = await handle_submit_assessment(SubmitAssessment(
                incident_id="INC-ALL", root_cause_hypothesis="test",
                recommended_action="fix", blast_radius=[],
                sentry_relevance=0.5, metrics_relevance=0.5,
                deploys_relevance=0.5, uptime_relevance=0.5,
            ))
        assert "submitted" in result.lower() or "success" in result.lower()


# ===========================
# RECRUITMENT ORDER
# ===========================

class TestRecruitmentOrder:

    @pytest.mark.asyncio
    async def test_recruit_before_publish(self):
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-ORDER")
        ctx.tool_results = {
            "metrics": {"error_rate": 35.0, "latency_p99": 4800, "anomaly_detected": True},
            "sentry": {"anomaly_detected": True},
            "deploys": {"anomaly_detected": True, "deploy_to_error_gap_minutes": 3},
            "uptime": {"uptime_percentage": 91.3, "anomaly_detected": True},
        }
        ctx.tools_completed = {"metrics", "sentry", "deploys", "uptime"}
        _trusted_context["INC-ORDER"] = ctx

        call_order = []

        async def mock_prepare(*a, **k):
            call_order.append("prepare")
            r = MagicMock()
            r.submission_id = "sub-1"
            r.sealed_card = {"card_type": "Assessment"}
            r.card_hash = "hash-1"
            r.room_id = "room-1"
            r.room_alias_id = "room-1"
            r.incident_id = "INC-ORDER"
            return r

        async def mock_confirm(**k):
            call_order.append("confirm")
            r = MagicMock()
            r.new_state = "ASSESSED"
            return r

        mock_room = AsyncMock()

        async def mock_add_participant(*args, **kwargs):
            call_order.append("recruit")

        async def mock_post_message(*args, **kwargs):
            call_order.append("publish")
            return "msg-pub"

        mock_room.add_participant = mock_add_participant
        mock_room.post_message = mock_post_message
        mock_room.aclose = AsyncMock()

        with patch.dict(os.environ, {
            "DIAGNOSIS_SUBMISSION_KEY": "test-key",
            "SAFETY_REVIEWER_AGENT_ID": "reviewer-uuid",
            "DIAGNOSIS_AGENT_ID": "diag-uuid",
        }), patch("agents.diagnosis.SubmissionClient") as MockSC, \
             patch("agents.diagnosis.IncidentRoomClient", return_value=mock_room):

            mock_sc_inst = AsyncMock()
            mock_sc_inst.prepare = mock_prepare
            mock_sc_inst.confirm = mock_confirm
            mock_sc_inst.__aenter__ = AsyncMock(return_value=mock_sc_inst)
            mock_sc_inst.__aexit__ = AsyncMock(return_value=False)
            MockSC.return_value = mock_sc_inst

            input_model = SubmitAssessment(
                incident_id="INC-ORDER",
                root_cause_hypothesis="NullPointerException in auth",
                recommended_action="Rollback deploy v2.3.1",
                blast_radius=["auth-service", "api-gateway"],
                sentry_relevance=0.9, metrics_relevance=0.9,
                deploys_relevance=0.8, uptime_relevance=0.7,
            )
            result = await handle_submit_assessment(input_model)

        assert call_order == ["prepare", "recruit", "publish", "confirm"], f"Wrong order: {call_order}"
        assert "submitted" in result.lower() or "success" in result.lower()


# ===========================
# IDEMPOTENCY
# ===========================

class TestIdempotency:

    def test_same_input_produces_same_key(self):
        k1 = derive_idempotency_key("diagnosis", "msg-123", "hash-abc")
        k2 = derive_idempotency_key("diagnosis", "msg-123", "hash-abc")
        assert k1 == k2

    def test_different_agent_different_key(self):
        k_d = derive_idempotency_key("diagnosis", "msg-123", "hash-abc")
        k_t = derive_idempotency_key("triage", "msg-123", "hash-abc")
        assert k_d != k_t


# ===========================
# STARTUP VALIDATION
# ===========================

class TestStartupValidation:

    @pytest.mark.asyncio
    async def test_missing_env_vars_raise(self):
        with patch.dict(os.environ, {
            "DIAGNOSIS_AGENT_ID": "",
            "TRIAGE_AGENT_ID": "",
            "DASHSCOPE_API_KEY": "",
        }, clear=False):
            with pytest.raises(RuntimeError, match="missing required env vars"):
                from agents.diagnosis import create_diagnosis_agent
                await create_diagnosis_agent()


# ===========================
# INCIDENT ROOM CLIENT TEST
# ===========================

class TestIncidentRoomClientUse:
    """Diagnosis must publish through the Gateway-owned incident room client."""

    @pytest.mark.asyncio
    async def test_uses_incident_room_client_not_external_rest(self):
        """submit_assessment creates IncidentRoomClient with diagnosis role."""
        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-AUTH")
        ctx.tool_results = {
            "metrics": {"error_rate": 35.0, "latency_p99": 4800, "anomaly_detected": True},
            "sentry": {"anomaly_detected": True},
            "deploys": {"anomaly_detected": True, "deploy_to_error_gap_minutes": 3},
            "uptime": {"uptime_percentage": 91.3, "anomaly_detected": True},
        }
        ctx.tools_completed = {"metrics", "sentry", "deploys", "uptime"}
        _trusted_context["INC-AUTH"] = ctx

        captured_kwargs = {}

        with patch.dict(os.environ, {
            "DIAGNOSIS_SUBMISSION_KEY": "test-key",
            "SAFETY_REVIEWER_AGENT_ID": "reviewer",
            "DIAGNOSIS_AGENT_ID": "diag",
        }), patch("agents.diagnosis.SubmissionClient") as MockSC, \
             patch("agents.diagnosis.IncidentRoomClient") as MockRoomClient:

            mock_sc_inst = AsyncMock()
            mock_sc_inst.prepare = AsyncMock(return_value=MagicMock(
                submission_id="s", sealed_card={}, card_hash="h",
                room_id="r", room_alias_id="r", incident_id="INC-AUTH",
            ))
            mock_sc_inst.confirm = AsyncMock(return_value=MagicMock(new_state="ASSESSED"))
            mock_sc_inst.__aenter__ = AsyncMock(return_value=mock_sc_inst)
            mock_sc_inst.__aexit__ = AsyncMock(return_value=False)
            MockSC.return_value = mock_sc_inst

            mock_room = AsyncMock()
            mock_room.add_participant = AsyncMock()
            mock_room.post_message = AsyncMock(return_value="msg-1")
            mock_room.aclose = AsyncMock()

            def capture_constructor(**kwargs):
                captured_kwargs.update(kwargs)
                return mock_room

            MockRoomClient.side_effect = capture_constructor

            input_model = SubmitAssessment(
                incident_id="INC-AUTH", root_cause_hypothesis="test",
                recommended_action="fix", blast_radius=[],
                sentry_relevance=0.5, metrics_relevance=0.5,
                deploys_relevance=0.5, uptime_relevance=0.5,
            )
            await handle_submit_assessment(input_model)

        assert captured_kwargs["sender_id"] == "diag"
        assert captured_kwargs["sender_role"] == "diagnosis"
        mock_room.add_participant.assert_awaited_once()
        mock_room.post_message.assert_awaited_once()


# ===========================
# STATE RACE RETRY TESTS
# ===========================

class TestStateRaceRetry:
    """Publish-before-confirm race: prepare() retries on 409."""

    @pytest.mark.asyncio
    async def test_retries_on_409_then_succeeds(self):
        """409 on first attempt, success on second → Assessment submitted."""
        from shared.submission_client import SubmissionError

        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-RACE")
        ctx.tool_results = {
            "metrics": {"error_rate": 35.0, "latency_p99": 4800, "anomaly_detected": True},
            "sentry": {"anomaly_detected": True},
            "deploys": {"anomaly_detected": True, "deploy_to_error_gap_minutes": 3},
            "uptime": {"uptime_percentage": 91.3, "anomaly_detected": True},
        }
        ctx.tools_completed = {"metrics", "sentry", "deploys", "uptime"}
        _trusted_context["INC-RACE"] = ctx

        call_count = {"prepare": 0}

        async def mock_prepare(*a, **k):
            call_count["prepare"] += 1
            if call_count["prepare"] == 1:
                raise SubmissionError(409, "wrong state: DETECTED")
            r = MagicMock()
            r.submission_id = "s"
            r.sealed_card = {}
            r.card_hash = "h"
            r.room_id = "r"
            r.room_alias_id = "r"
            r.incident_id = "INC-RACE"
            return r

        with patch.dict(os.environ, {
            "DIAGNOSIS_SUBMISSION_KEY": "k",
            "SAFETY_REVIEWER_AGENT_ID": "rev",
            "DIAGNOSIS_AGENT_ID": "diag",
        }), patch("agents.diagnosis.SubmissionClient") as MockSC, \
             patch("agents.diagnosis.IncidentRoomClient") as MockRoomClient, \
             patch("agents.diagnosis.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_sc = AsyncMock()
            mock_sc.prepare = mock_prepare
            mock_sc.confirm = AsyncMock(return_value=MagicMock(new_state="ASSESSED"))
            mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
            mock_sc.__aexit__ = AsyncMock(return_value=False)
            MockSC.return_value = mock_sc

            mock_room = AsyncMock()
            mock_room.add_participant = AsyncMock()
            mock_room.post_message = AsyncMock(return_value="m")
            mock_room.aclose = AsyncMock()
            MockRoomClient.return_value = mock_room

            result = await handle_submit_assessment(SubmitAssessment(
                incident_id="INC-RACE", root_cause_hypothesis="test",
                recommended_action="fix", blast_radius=[],
                sentry_relevance=0.9, metrics_relevance=0.9,
                deploys_relevance=0.8, uptime_relevance=0.7,
            ))

        assert call_count["prepare"] == 2
        assert mock_sleep.called  # Backoff was applied
        assert "submitted" in result.lower() or "success" in result.lower()

    @pytest.mark.asyncio
    async def test_non_409_error_not_retried(self):
        """Non-409 error (e.g., 400) → propagates immediately."""
        from shared.submission_client import SubmissionError

        _trusted_context.clear()
        ctx = _make_context(incident_id="INC-400")
        ctx.tool_results = {
            "metrics": {"error_rate": 1.0, "anomaly_detected": False},
            "sentry": {"anomaly_detected": False},
            "deploys": {"anomaly_detected": False},
            "uptime": {"uptime_percentage": 99.9, "anomaly_detected": False},
        }
        ctx.tools_completed = {"metrics", "sentry", "deploys", "uptime"}
        _trusted_context["INC-400"] = ctx

        async def mock_prepare_400(*a, **k):
            raise SubmissionError(400, "bad request")

        with patch.dict(os.environ, {
            "DIAGNOSIS_SUBMISSION_KEY": "k",
            "SAFETY_REVIEWER_AGENT_ID": "rev",
            "DIAGNOSIS_AGENT_ID": "diag",
        }), patch("agents.diagnosis.SubmissionClient") as MockSC, \
             patch("agents.diagnosis.get_agent_api_key", return_value="k"):

            mock_sc = AsyncMock()
            mock_sc.prepare = mock_prepare_400
            mock_sc.__aenter__ = AsyncMock(return_value=mock_sc)
            mock_sc.__aexit__ = AsyncMock(return_value=False)
            MockSC.return_value = mock_sc

            result = await handle_submit_assessment(SubmitAssessment(
                incident_id="INC-400", root_cause_hypothesis="t",
                recommended_action="r", blast_radius=[],
                sentry_relevance=0.5, metrics_relevance=0.5,
                deploys_relevance=0.5, uptime_relevance=0.5,
            ))

        assert "error" in result.lower()


# ===========================
# FRESHNESS TIMESTAMP TESTS
# ===========================

class TestFreshnessTimestamp:
    """Freshness must use room message inserted_at (not created_at).

    local room runtime MessageCreatedPayload has inserted_at: str (ISO 8601).
    It does NOT have created_at. Tests must use the real field name.
    """

    @pytest.mark.asyncio
    async def test_uses_payload_inserted_at(self):
        """When payload.inserted_at is an ISO string, use it for alert_timestamp."""
        from datetime import datetime, timezone
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-ts"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-ts", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())

        # Build event with inserted_at on payload (local room field)
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.room_id = "room-ts"
        payload = MagicMock()
        payload.content = _make_triage_decision_content(incident_id="INC-TS")
        payload.sender_id = "triage-ts"
        payload.sender_type = "Agent"
        payload.id = "msg-ts"
        # local room runtime uses ISO 8601 string with Z suffix
        past_time = datetime(2026, 6, 13, 14, 0, 0, tzinfo=timezone.utc)
        payload.inserted_at = "2026-06-13T14:00:00Z"
        # Ensure created_at does NOT exist (real payload doesn't have it)
        del payload.created_at
        event.payload = payload

        await pp.process(MagicMock(), event)

        ctx = _trusted_context.get("INC-TS")
        assert ctx is not None
        assert ctx.alert_timestamp == pytest.approx(past_time.timestamp(), abs=1.0)
        # alert_timestamp should NOT be close to current time
        assert abs(ctx.alert_timestamp - time.time()) > 60

    @pytest.mark.asyncio
    async def test_falls_back_to_receipt_time(self):
        """When payload has no inserted_at, fall back to receipt time."""
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-fb"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-fb", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())

        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.room_id = "room-fb"
        payload = MagicMock()
        payload.content = _make_triage_decision_content(incident_id="INC-FB")
        payload.sender_id = "triage-fb"
        payload.sender_type = "Agent"
        payload.id = "msg-fb"
        # No inserted_at and no created_at
        del payload.inserted_at
        del payload.created_at
        event.payload = payload

        before = time.time()
        await pp.process(MagicMock(), event)
        after = time.time()

        ctx = _trusted_context.get("INC-FB")
        assert ctx is not None
        assert before <= ctx.alert_timestamp <= after

    @pytest.mark.asyncio
    async def test_inserted_at_with_z_suffix_parses(self):
        """The room runtime's ISO 8601 with Z suffix parses correctly."""
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-z"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-z", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())

        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.room_id = "room-z"
        payload = MagicMock()
        payload.content = _make_triage_decision_content(incident_id="INC-Z")
        payload.sender_id = "triage-z"
        payload.sender_type = "Agent"
        payload.id = "msg-z"
        payload.inserted_at = "2026-06-13T14:30:00.000Z"
        del payload.created_at
        event.payload = payload

        await pp.process(MagicMock(), event)

        ctx = _trusted_context.get("INC-Z")
        assert ctx is not None
        from datetime import datetime, timezone
        expected = datetime(2026, 6, 13, 14, 30, 0, tzinfo=timezone.utc).timestamp()
        assert ctx.alert_timestamp == pytest.approx(expected, abs=1.0)

    @pytest.mark.asyncio
    async def test_malformed_inserted_at_falls_back(self):
        """Malformed inserted_at → falls back to receipt time, doesn't crash."""
        _trusted_context.clear()
        with patch.dict(os.environ, {"TRIAGE_AGENT_ID": "triage-bad"}):
            pp = DiagnosisPreprocessor(diagnosis_agent_id="diag-bad", diagnosis_api_key="key")
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())

        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.room_id = "room-bad"
        payload = MagicMock()
        payload.content = _make_triage_decision_content(incident_id="INC-BAD")
        payload.sender_id = "triage-bad"
        payload.sender_type = "Agent"
        payload.id = "msg-bad"
        payload.inserted_at = "not-a-date"
        del payload.created_at
        event.payload = payload

        before = time.time()
        await pp.process(MagicMock(), event)
        after = time.time()

        ctx = _trusted_context.get("INC-BAD")
        assert ctx is not None
        assert before <= ctx.alert_timestamp <= after


# ===========================
# CHALLENGE LOOP TESTS
# ===========================

def _make_verdict_content(
    incident_id: str = "INC-TEST-001",
    decision: str = "CHALLENGE",
    challenge_request: str = "Evidence gaps in sentry data",
    card_hash: str = "verdict-hash-001",
    sequence_number: int = 4,
) -> str:
    """Create a room message content string containing a Verdict card."""
    card = {
        "card_type": "Verdict",
        "incident_id": incident_id,
        "decision": decision,
        "cross_check_sources": ["sentry", "metrics", "deploys", "uptime"],
        "reasoning": "Insufficient evidence strength for claimed severity",
        "agrees_with_diagnosis": False,
        "challenge_request": challenge_request,
        "card_hash": card_hash,
        "sequence_number": sequence_number,
    }
    return f"```json\n{json.dumps(card)}\n```"


class TestChallengeLoop:
    """Tests for Verdict(CHALLENGE) → Diagnosis re-investigation loop."""

    @pytest.fixture(autouse=True)
    def _clean_context(self):
        _trusted_context.clear()
        yield
        _trusted_context.clear()

    def _make_preprocessor(self, safety_reviewer_id="sr-agent-uuid"):
        """Create a DiagnosisPreprocessor with mocked default preprocessor."""
        env = {
            "TRIAGE_AGENT_ID": "triage-uuid",
            "SAFETY_REVIEWER_AGENT_ID": safety_reviewer_id,
        }
        with patch.dict(os.environ, env):
            pp = DiagnosisPreprocessor(
                diagnosis_agent_id="diag-456",
                diagnosis_api_key="key",
            )
        pp._default_preprocessor = AsyncMock()
        pp._default_preprocessor.process = AsyncMock(return_value=MagicMock())
        return pp

    def _seed_submitted_context(self, incident_id="INC-TEST-001", revision=1):
        """Pre-seed _trusted_context with a submitted Assessment context."""
        ctx = _make_context(
            incident_id=incident_id,
            submitted=True,
            revision=revision,
        )
        _trusted_context[incident_id] = ctx
        return ctx

    # ---- Acceptance Tests ----

    @pytest.mark.asyncio
    async def test_challenge_accepted_from_safety_reviewer(self):
        """Valid CHALLENGE from Safety Reviewer resets context and re-delegates."""
        pp = self._make_preprocessor(safety_reviewer_id="sr-agent-uuid")
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(decision="CHALLENGE"),
            sender_id="sr-agent-uuid",
            sender_type="Agent",
        )
        await pp.process(MagicMock(), event)

        ctx = _trusted_context["INC-TEST-001"]
        # Context should be reset for re-investigation
        assert ctx.submitted is False
        assert ctx.revision == 2
        assert ctx.challenge_request == "Evidence gaps in sentry data"
        assert len(ctx.tool_results) == 0
        assert len(ctx.tools_completed) == 0
        # Should have re-delegated to local diagnosis runtime
        pp._default_preprocessor.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_challenge_increments_revision_each_time(self):
        """Multiple challenges increment revision correctly."""
        pp = self._make_preprocessor()

        # First investigation → submitted
        ctx = self._seed_submitted_context(revision=1)
        ctx.tool_results = {"sentry": {"anomaly_detected": True}}
        ctx.tools_completed = {"sentry"}

        # First CHALLENGE
        event = _make_event(
            _make_verdict_content(challenge_request="Check deploys"),
            sender_id="sr-agent-uuid",
        )
        await pp.process(MagicMock(), event)
        assert _trusted_context["INC-TEST-001"].revision == 2
        assert _trusted_context["INC-TEST-001"].challenge_request == "Check deploys"

        # Mark re-submitted for second challenge
        _trusted_context["INC-TEST-001"].submitted = True

        # Second CHALLENGE
        event2 = _make_event(
            _make_verdict_content(challenge_request="Still missing metrics"),
            sender_id="sr-agent-uuid",
        )
        await pp.process(MagicMock(), event2)
        assert _trusted_context["INC-TEST-001"].revision == 3
        assert _trusted_context["INC-TEST-001"].challenge_request == "Still missing metrics"

    @pytest.mark.asyncio
    async def test_challenge_clears_tool_results(self):
        """Challenge must clear tool_results and tools_completed for re-investigation."""
        pp = self._make_preprocessor()
        ctx = self._seed_submitted_context()
        ctx.tool_results = {
            "sentry": {"anomaly_detected": True},
            "metrics": {"anomaly_detected": False},
            "deploys": {"anomaly_detected": False},
            "uptime": {"anomaly_detected": True},
        }
        ctx.tools_completed = {"sentry", "metrics", "deploys", "uptime"}

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        await pp.process(MagicMock(), event)

        ctx = _trusted_context["INC-TEST-001"]
        assert ctx.tool_results == {}
        assert ctx.tools_completed == set()

    # ---- Rejection Tests ----

    @pytest.mark.asyncio
    async def test_challenge_rejected_from_wrong_agent(self):
        """CHALLENGE from a non-Safety-Reviewer agent is rejected."""
        pp = self._make_preprocessor(safety_reviewer_id="sr-agent-uuid")
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(),
            sender_id="attacker-agent-uuid",
            sender_type="Agent",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        # Context should be unchanged
        assert _trusted_context["INC-TEST-001"].submitted is True
        assert _trusted_context["INC-TEST-001"].revision == 1

    @pytest.mark.asyncio
    async def test_challenge_rejected_from_user(self):
        """CHALLENGE from a User sender_type is rejected."""
        pp = self._make_preprocessor()
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
            sender_type="User",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        assert _trusted_context["INC-TEST-001"].submitted is True

    @pytest.mark.asyncio
    async def test_challenge_rejected_without_prior_assessment(self):
        """CHALLENGE without a prior submitted Assessment is rejected."""
        pp = self._make_preprocessor()
        # No context seeded — nothing submitted

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None

    @pytest.mark.asyncio
    async def test_challenge_rejected_if_not_yet_submitted(self):
        """CHALLENGE when Assessment is active but not yet submitted is rejected."""
        pp = self._make_preprocessor()
        # Context exists but submitted=False (still investigating)
        ctx = self._seed_submitted_context()
        ctx.submitted = False

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        # Revision should NOT increment
        assert _trusted_context["INC-TEST-001"].revision == 1

    @pytest.mark.asyncio
    async def test_challenge_rejected_when_safety_id_not_configured(self):
        """CHALLENGE is fail-closed when SAFETY_REVIEWER_AGENT_ID is empty."""
        pp = self._make_preprocessor(safety_reviewer_id="")
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        assert _trusted_context["INC-TEST-001"].submitted is True

    # ---- Non-CHALLENGE Verdict Handling ----

    @pytest.mark.asyncio
    async def test_non_challenge_verdict_ignored(self):
        """Verdict with CONFIRM decision is silently ignored by Diagnosis."""
        pp = self._make_preprocessor()
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(decision="CONFIRM"),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None
        # Context unchanged
        assert _trusted_context["INC-TEST-001"].submitted is True
        assert _trusted_context["INC-TEST-001"].revision == 1

    @pytest.mark.asyncio
    async def test_false_alarm_verdict_ignored(self):
        """Verdict(FALSE_ALARM) is silently ignored by Diagnosis."""
        pp = self._make_preprocessor()
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(decision="FALSE_ALARM"),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None

    @pytest.mark.asyncio
    async def test_needs_human_verdict_ignored(self):
        """Verdict(NEEDS_HUMAN) is silently ignored by Diagnosis."""
        pp = self._make_preprocessor()
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(decision="NEEDS_HUMAN"),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None

    # ---- Edge Cases ----

    @pytest.mark.asyncio
    async def test_challenge_for_wrong_incident_id(self):
        """CHALLENGE for an incident not in context is rejected."""
        pp = self._make_preprocessor()
        self._seed_submitted_context(incident_id="INC-DIFFERENT")

        event = _make_event(
            _make_verdict_content(incident_id="INC-UNKNOWN"),
            sender_id="sr-agent-uuid",
        )
        result = await pp.process(MagicMock(), event)
        assert result is None

    @pytest.mark.asyncio
    async def test_challenge_preserves_room_id_and_alert_id(self):
        """Challenge should preserve original room_id and alert_id from context."""
        pp = self._make_preprocessor()
        ctx = self._seed_submitted_context()
        original_room_id = ctx.room_id
        original_alert_id = ctx.alert_id

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        await pp.process(MagicMock(), event)

        ctx_after = _trusted_context["INC-TEST-001"]
        assert ctx_after.room_id == original_room_id
        assert ctx_after.alert_id == original_alert_id

    @pytest.mark.asyncio
    async def test_challenge_updates_room_message_id(self):
        """Challenge should update room_message_id to the Verdict message."""
        pp = self._make_preprocessor()
        self._seed_submitted_context()

        event = _make_event(
            _make_verdict_content(),
            sender_id="sr-agent-uuid",
        )
        # The event payload has id="msg-001" (from _make_event)
        await pp.process(MagicMock(), event)

        ctx = _trusted_context["INC-TEST-001"]
        assert ctx.room_message_id == "msg-001"

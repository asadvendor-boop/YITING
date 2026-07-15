"""Tests for the human revision parser and three-way decision feature.

Pure-function unit tests for:
- parse_human_runbook_constraint: keyword → runbook mapping
- get_allowed_runbooks: severity-based policy guard
- Operator APPROVED-only gate (structural)
- Three-way decision routing (structural)

These guard the demo's critical payoff:
  "use circuit breaker instead of rollback" → RB-004 (not RB-003)
"""


# ===========================================================================
# Test 1: parse_human_runbook_constraint — pure function, no mocks
# ===========================================================================

class TestParseHumanRunbookConstraint:
    """Keyword parser must resolve 'X instead of Y' to X, not Y."""

    def test_demo_instruction_maps_to_rb004(self):
        """The canonical demo instruction MUST map to RB-004 (circuit breaker)."""
        from agents.commander import parse_human_runbook_constraint
        result = parse_human_runbook_constraint(
            "use circuit breaker instead of rollback",
            rejected_runbook="RB-003",
        )
        assert result == "RB-004", (
            f"Expected RB-004 (circuit breaker), got {result!r}. "
            "This is the demo's payoff instruction — parser is broken!"
        )

    def test_circuit_breaker_without_instead(self):
        """Plain 'circuit breaker' maps to RB-004."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("use circuit breaker") == "RB-004"

    def test_rollback_maps_to_rb003(self):
        """Plain 'rollback' maps to RB-003."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("do a rollback") == "RB-003"

    def test_instead_of_pattern_picks_first_keyword(self):
        """'X instead of Y' pattern returns X (before 'instead'), not Y."""
        from agents.commander import parse_human_runbook_constraint
        result = parse_human_runbook_constraint(
            "use DNS failover instead of restart",
            rejected_runbook="RB-001",
        )
        assert result == "RB-005", f"Expected RB-005 (DNS failover), got {result!r}"

    def test_rejected_runbook_excluded(self):
        """If the only keyword matches the rejected runbook, return empty."""
        from agents.commander import parse_human_runbook_constraint
        result = parse_human_runbook_constraint(
            "do a rollback",
            rejected_runbook="RB-003",
        )
        assert result == "", (
            f"Should return '' when only match is the rejected runbook, got {result!r}"
        )

    def test_no_match_returns_empty(self):
        """Unrecognized instructions return empty string."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("do something creative") == ""

    def test_case_insensitive(self):
        """Parser should be case-insensitive."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("USE CIRCUIT BREAKER") == "RB-004"

    def test_scale_up_maps_to_rb002(self):
        """'scale up' / 'scale out' maps to RB-002."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("try scale up instead") == "RB-002"

    def test_maintenance_page_maps_to_rb006(self):
        """'maintenance page' maps to RB-006."""
        from agents.commander import parse_human_runbook_constraint
        assert parse_human_runbook_constraint("put up a maintenance page") == "RB-006"


# ===========================================================================
# Test 2: get_allowed_runbooks — severity-based policy
# ===========================================================================

class TestGetAllowedRunbooks:
    """RB-004 must be allowed at the demo severity (P2)."""

    def test_rb004_allowed_at_p2(self):
        """Circuit breaker (RB-004) must be allowed for P2 severity."""
        from agents.commander import get_allowed_runbooks
        allowed = get_allowed_runbooks("P2")
        assert "RB-004" in allowed, (
            f"RB-004 not in P2 allowed set: {allowed}. "
            "Demo will fail — revised plan would be rejected by policy!"
        )

    def test_rb004_allowed_at_all_severities(self):
        """RB-004 is allowed at all severity levels."""
        from agents.commander import get_allowed_runbooks
        for sev in ("P1", "P2", "P3", "P4"):
            assert "RB-004" in get_allowed_runbooks(sev), (
                f"RB-004 not allowed at {sev}"
            )

    def test_unknown_severity_gets_safe_default(self):
        """Unknown severity falls back to safe default (RB-001 only)."""
        from agents.commander import get_allowed_runbooks
        allowed = get_allowed_runbooks("unknown")
        assert allowed == {"RB-001"}, f"Expected safe default, got {allowed}"

    def test_p3_blocks_destructive_runbooks(self):
        """P3/P4 should not allow RB-003 (rollback) or RB-005 (DNS failover)."""
        from agents.commander import get_allowed_runbooks
        p3 = get_allowed_runbooks("P3")
        assert "RB-003" not in p3, "Rollback should be blocked at P3"
        assert "RB-005" not in p3, "DNS failover should be blocked at P3"


# ===========================================================================
# Test 3: Operator APPROVED-only gate (structural)
# ===========================================================================

class TestOperatorApprovedGate:
    """Operator must only execute APPROVED plans, not REJECTED/FALSE_ALARM."""

    def test_approved_gate_exists_in_operator(self):
        """Operator preprocessor must check decision == APPROVED."""
        import agents.operator as op_mod
        source = open(op_mod.__file__).read()
        sa_section = source[source.find('_is_structured_approval:'):]
        sa_section = sa_section[:3000]
        assert '!= "APPROVED"' in sa_section or "!= 'APPROVED'" in sa_section, (
            "Operator must have an APPROVED-only gate in StructuredApproval handler"
        )

    def test_rejected_ignored_log_message(self):
        """Operator should log when ignoring REJECTED/FALSE_ALARM."""
        import agents.operator as op_mod
        source = open(op_mod.__file__).read()
        assert "Operator only executes APPROVED" in source, (
            "Operator should log that it only executes APPROVED plans"
        )


# ===========================================================================
# Test 4: Three-way decision routing (structural)
# ===========================================================================

class TestThreeWayDecisionRouting:
    """approve_ui.py must route 'approve', 'revise', 'false_alarm' decisions."""

    def test_three_decision_values_handled(self):
        """POST handler must branch on all three decision values."""
        import gateway.routes.approve_ui as ui_mod
        source = open(ui_mod.__file__).read()
        assert 'decision == "approve"' in source
        assert 'decision == "revise"' in source
        assert 'decision == "false_alarm"' in source

    def test_resume_form_has_decision_field(self):
        """Resume form must include hidden decision=approve field."""
        import gateway.routes.approve_ui as ui_mod
        source = open(ui_mod.__file__).read()
        assert 'name="decision" value="approve"' in source, (
            "Resume form is missing decision=approve hidden field — "
            "retry clicks will hit 'Unknown decision' branch"
        )

    def test_revision_instructions_validation(self):
        """Revise path must validate revision_instructions is non-empty."""
        import gateway.routes.approve_ui as ui_mod
        source = open(ui_mod.__file__).read()
        assert "Revision instructions are required" in source

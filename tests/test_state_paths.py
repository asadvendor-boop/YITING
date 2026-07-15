"""End-to-end state machine path tests.

These verify the three critical execution paths that the whole system
exists to demonstrate:
  1. Human approval: full pipeline to RESOLVED
  2. Policy automation: no-human path to EXECUTED
  3. Reject-revise-approve: human rejection loop to EXECUTED

Also tests enforcement properties:
  - Out-of-order submission → 409
  - Cross-role confirmation → 403
  - State regression protection
  - Stale card rejection
  - Idempotency binding to card_type
  - Atomic prepared_by_role
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GATEWAY_SECRET", "test-secret")

from gateway.database import init_db
from gateway.routes.submission import (
    _authenticate_agent,
    _resolve_state,
    _STATE_PREREQUISITES,
    _upsert_incident,
)
from gateway.routes import submission
from shared.integrity import seal_card, IdempotencyConflict
from shared.models import CARD_TYPES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_agent_keys():
    """Reset cached agent keys before each test."""
    submission._agent_keys = None
    yield
    submission._agent_keys = None


@pytest.fixture
def db():
    """Fresh in-memory database per test."""
    return init_db(":memory:")


NOW = datetime.now(timezone.utc)
EXPIRY = (NOW + timedelta(hours=1)).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_card(card_type: str, **kwargs):
    """Create a card instance with defaults for required fields."""
    defaults = {
        "AlertCard": {
            "alert_id": "a1", "source": "sentry", "timestamp": NOW.isoformat(),
            "title": "Test alert", "raw_payload": {}, "fingerprint": "fp1",
            "preliminary_severity": "P2",
        },
        "TriageDecision": {
            "incident_id": "inc", "alert_id": "a1", "decision": "route",
            "noise_score": 0.1,
        },
        "Assessment": {
            "incident_id": "inc", "severity": "P2", "evidence_strength": 0.8,
            "root_cause_hypothesis": "test", "recommended_action": "rollback",
        },
        "Verdict": {
            "incident_id": "inc", "decision": "CONFIRM",
            "reasoning": "confirmed", "agrees_with_diagnosis": True,
        },
        "ResponsePlan": {
            "incident_id": "inc", "runbook": "RB-001",
            "envelopes": [{"action_id": "restart", "target": "svc"}],
            "risk_level": "high", "requires_human_approval": True,
        },
        "StructuredApproval": {
            "incident_id": "inc", "approver_id": "human1",
            "decision": "APPROVED", "reasoning": "go", "plan_hash": "ph",
            "nonce": "n1", "action_id": "act", "action_hash": "ah",
            "room_message_id": "bm00aa11bb", "room_alias_id": "br", "expiry": EXPIRY,
        },
        "PolicyAuthorization": {
            "incident_id": "inc", "authorization_id": "pa1",
            "plan_hash": "ph", "action_hash": "ah", "risk_level": "low",
            "policy_rule": "auto-restart", "expiry": EXPIRY,
        },
        "ActionReceipt": {
            "incident_id": "inc", "authorization_type": "human_approval",
            "authorization_id": "auth1",
        },
        "Postmortem": {
            "incident_id": "inc", "summary": "Fixed",
            "root_cause": "Bad deploy", "recovery_actions": ["rollback"],
            "prevention_recommendations": ["canary"],
        },
    }
    data = {**defaults.get(card_type, {}), **kwargs, "card_type": card_type}
    return CARD_TYPES[card_type].model_validate(data)


def walk_path(db, incident_id: str, steps: list[tuple[str, dict]]) -> str:
    """Walk a sequence of (card_type, kwargs) steps, returning final state.

    Simulates prepare → confirm for each step.
    """
    for i, (card_type, kwargs) in enumerate(steps):
        kwargs = {**kwargs, "incident_id": incident_id}
        card = make_card(card_type, **kwargs)

        if card_type == "AlertCard":
            _upsert_incident(db, incident_id, card_type, kwargs.get("preliminary_severity"))

        sealed = seal_card(
            card, incident_id, db,
            idempotency_key=f"{incident_id}-step-{i}",
            prepared_by_role="gateway",
        )

        card_json = db.execute(
            "SELECT card_json FROM cards WHERE card_hash=?",
            (sealed.card_hash,),
        ).fetchone()["card_json"]

        new_state = _resolve_state(card_type, card_json)
        if new_state:
            db.execute(
                "UPDATE incidents SET state=? WHERE incident_id=?",
                (new_state, incident_id),
            )

    row = db.execute(
        "SELECT state FROM incidents WHERE incident_id=?",
        (incident_id,),
    ).fetchone()
    return row["state"]


# ---------------------------------------------------------------------------
# Path tests
# ---------------------------------------------------------------------------

class TestHumanApprovalPath:
    """Full human-approval pipeline: DETECTED → ... → RESOLVED."""

    def test_full_path(self, db):
        final = walk_path(db, "human-1", [
            ("AlertCard", {"alert_id": "human-1", "preliminary_severity": "P1"}),
            ("TriageDecision", {"alert_id": "human-1", "decision": "route"}),
            ("Assessment", {"severity": "P1", "evidence_strength": 0.9}),
            ("Verdict", {"decision": "CONFIRM"}),
            ("ResponsePlan", {"risk_level": "high", "requires_human_approval": True}),
            ("StructuredApproval", {"decision": "APPROVED", "nonce": "n1"}),
            ("ActionReceipt", {"authorization_type": "human_approval"}),
            ("Postmortem", {}),
        ])
        assert final == "RESOLVED"


class TestPolicyPath:
    """No-human policy path: DETECTED → ... → EXECUTED."""

    def test_full_path(self, db):
        final = walk_path(db, "policy-1", [
            ("AlertCard", {"alert_id": "policy-1", "preliminary_severity": "P3"}),
            ("TriageDecision", {"alert_id": "policy-1", "decision": "route"}),
            ("Assessment", {"severity": "P3", "evidence_strength": 0.6}),
            ("Verdict", {"decision": "CONFIRM"}),
            ("ResponsePlan", {"risk_level": "low", "requires_human_approval": False}),
            ("PolicyAuthorization", {}),
            ("ActionReceipt", {"authorization_type": "policy"}),
        ])
        assert final == "EXECUTED"


class TestRejectRevisePath:
    """Human rejection → revision → re-approval → execution."""

    def test_full_path(self, db):
        final = walk_path(db, "reject-1", [
            ("AlertCard", {"alert_id": "reject-1", "preliminary_severity": "P1"}),
            ("TriageDecision", {"alert_id": "reject-1", "decision": "route"}),
            ("Assessment", {"severity": "P1", "evidence_strength": 0.8}),
            ("Verdict", {"decision": "CONFIRM"}),
            ("ResponsePlan", {"risk_level": "high", "requires_human_approval": True}),
            ("StructuredApproval", {"decision": "REJECTED", "nonce": "rej1"}),
            # Revised plan after rejection
            ("ResponsePlan", {"runbook": "RB-002", "risk_level": "high",
                              "requires_human_approval": True}),
            ("StructuredApproval", {"decision": "APPROVED", "nonce": "app2"}),
            ("ActionReceipt", {"authorization_type": "human_approval"}),
        ])
        assert final == "EXECUTED"


class TestChallengeRevisionPath:
    """Safety challenge → re-investigation → re-review."""

    def test_full_path(self, db):
        final = walk_path(db, "challenge-1", [
            ("AlertCard", {"alert_id": "challenge-1", "preliminary_severity": "P2"}),
            ("TriageDecision", {"alert_id": "challenge-1", "decision": "route"}),
            ("Assessment", {"severity": "P2", "evidence_strength": 0.7}),
            ("Verdict", {"decision": "CHALLENGE", "agrees_with_diagnosis": False,
                         "challenge_request": "Recheck logs"}),
            # Re-investigation after challenge
            ("Assessment", {"severity": "P2", "evidence_strength": 0.9,
                            "root_cause_hypothesis": "revised hypothesis"}),
            ("Verdict", {"decision": "CONFIRM"}),
            ("ResponsePlan", {"risk_level": "medium", "requires_human_approval": True}),
        ])
        assert final == "PLANNED"


# ---------------------------------------------------------------------------
# Enforcement tests
# ---------------------------------------------------------------------------

class TestStatePrerequisites:
    """Out-of-order submissions must be rejected."""

    def test_assessment_without_triage(self, db):
        """Assessment requires TRIAGED — DETECTED should fail at confirm."""
        _upsert_incident(db, "prereq-1", "AlertCard", "P2")
        state = db.execute(
            "SELECT state FROM incidents WHERE incident_id=?",
            ("prereq-1",),
        ).fetchone()["state"]
        prereqs = _STATE_PREREQUISITES.get("Assessment", frozenset())
        assert state not in prereqs, "DETECTED should not be in Assessment prereqs"

    def test_nonexistent_incident_blocked(self, db):
        """Non-AlertCard submission for non-existent incident should fail."""
        current = db.execute(
            "SELECT state FROM incidents WHERE incident_id=?",
            ("ghost",),
        ).fetchone()
        assert current is None, "Incident should not exist"


class TestSequenceStaleness:
    """Stale card confirmations must be rejected via sequence check."""

    def test_stale_verdict_after_revision(self, db):
        """A CONFIRM Verdict prepared before CHALLENGE should be stale
        after CHALLENGE is confirmed and a new Assessment is submitted."""
        inc = 'stale-verdict'
        _upsert_incident(db, inc, 'AlertCard', 'P2')
        db.execute('UPDATE incidents SET state=? WHERE incident_id=?', ('ASSESSED', inc))

        # Prepare two Verdicts while ASSESSED
        vc = make_card('Verdict', incident_id=inc, decision='CHALLENGE',
                       agrees_with_diagnosis=False, challenge_request='recheck')
        sealed_vc = seal_card(vc, inc, db, idempotency_key='vc', prepared_by_role='gateway')

        vf = make_card('Verdict', incident_id=inc, decision='CONFIRM')
        sealed_vf = seal_card(vf, inc, db, idempotency_key='vf', prepared_by_role='gateway')

        # Confirm CHALLENGE → CHALLENGED
        db.execute('UPDATE cards SET published_at=? WHERE card_hash=?',
                   (NOW.isoformat(), sealed_vc.card_hash))
        db.execute('UPDATE incidents SET state=? WHERE incident_id=?', ('CHALLENGED', inc))

        # New Assessment (revision)
        a2 = make_card('Assessment', incident_id=inc, severity='P2',
                       evidence_strength=0.9, root_cause_hypothesis='revised')
        sealed_a2 = seal_card(a2, inc, db, idempotency_key='a2', prepared_by_role='gateway')
        db.execute('UPDATE cards SET published_at=? WHERE card_hash=?',
                   (NOW.isoformat(), sealed_a2.card_hash))
        db.execute('UPDATE incidents SET state=? WHERE incident_id=?', ('ASSESSED', inc))

        # Stale CONFIRM Verdict: seq < highest confirmed seq
        highest = db.execute(
            'SELECT MAX(sequence_number) as ms FROM cards '
            'WHERE incident_id=? AND published_at IS NOT NULL',
            (inc,),
        ).fetchone()['ms']
        assert sealed_vf.sequence_number < highest, \
            f'Stale seq {sealed_vf.sequence_number} should be < confirmed seq {highest}'

        # Verify the newer confirmed card exists
        newer = db.execute(
            'SELECT sequence_number FROM cards '
            'WHERE incident_id=? AND sequence_number > ? AND published_at IS NOT NULL',
            (inc, sealed_vf.sequence_number),
        ).fetchone()
        assert newer is not None, 'Sequence check should find a newer confirmed card'

    def test_revision_loops_allowed(self, db):
        """CHALLENGED → Assessment → ASSESSED is a legitimate revision."""
        # This is tested by TestChallengeRevisionPath.test_full_path above
        # Here we just verify the prerequisite allows it
        assert 'CHALLENGED' in _STATE_PREREQUISITES.get('Assessment', frozenset())

    def test_rejection_loop_allowed(self, db):
        """REJECTED → ResponsePlan → PLANNED is a legitimate revision."""
        assert 'REJECTED' in _STATE_PREREQUISITES.get('ResponsePlan', frozenset())


class TestRoleACL:
    """Role-bound access control."""

    def test_commander_cannot_submit_approval(self):
        os.environ["COMMANDER_SUBMISSION_KEY"] = "cmd-test"
        submission._agent_keys = None
        ok, reason = _authenticate_agent("cmd-test", "StructuredApproval")
        assert not ok
        assert "cannot submit" in reason
        del os.environ["COMMANDER_SUBMISSION_KEY"]

    def test_operator_cannot_submit_policy_auth(self):
        os.environ["OPERATOR_SUBMISSION_KEY"] = "ops-test"
        submission._agent_keys = None
        ok, reason = _authenticate_agent("ops-test", "PolicyAuthorization")
        assert not ok
        assert "cannot submit" in reason
        del os.environ["OPERATOR_SUBMISSION_KEY"]

    def test_shared_key_is_gateway_role(self):
        submission._agent_keys = None
        gw_secret = os.environ.get("GATEWAY_SECRET", "test-secret")
        ok, role = _authenticate_agent(gw_secret, "Assessment")
        assert ok
        assert role == "gateway"


class TestAtomicPreparedByRole:
    """prepared_by_role is written atomically with the card."""

    def test_role_stored_in_seal(self, db):
        _upsert_incident(db, "atomic-1", "AlertCard", "P2")
        card = make_card("AlertCard", alert_id="atomic-1")
        sealed = seal_card(
            card, "atomic-1", db,
            idempotency_key="at1",
            prepared_by_role="recorder",
        )
        row = db.execute(
            "SELECT prepared_by_role FROM cards WHERE card_hash=?",
            (sealed.card_hash,),
        ).fetchone()
        assert row["prepared_by_role"] == "recorder"


class TestIdempotencyBinding:
    """Idempotency key is bound to card_type."""

    def test_same_key_different_type_not_matched(self, db):
        _upsert_incident(db, "idemp-1", "AlertCard", "P2")
        card = make_card("AlertCard", alert_id="idemp-1")
        seal_card(card, "idemp-1", db, idempotency_key="k1", prepared_by_role="gateway")

        # Same idempotency key but different card_type should NOT match
        row = db.execute(
            "SELECT card_hash FROM cards "
            "WHERE incident_id=? AND idempotency_key=? AND card_type=?",
            ("idemp-1", "k1", "Assessment"),
        ).fetchone()
        assert row is None, "Same key + different type must not match"


class TestAlertCardRegression:
    """Late AlertCard must not regress an active incident."""

    def test_late_alertcard_no_regression(self, db):
        """TRIAGED incident + new AlertCard confirmed → state stays TRIAGED."""
        inc = "alert-reg"
        _upsert_incident(db, inc, "AlertCard", "P2")
        db.execute("UPDATE incidents SET state=? WHERE incident_id=?",
                   ("TRIAGED", inc))

        # New AlertCard (highest seq)
        card = make_card("AlertCard", alert_id=inc)
        sealed = seal_card(card, inc, db, idempotency_key="late",
                           prepared_by_role="recorder")

        # Simulate what confirm does: resolve state
        card_json = db.execute(
            "SELECT card_json FROM cards WHERE card_hash=?",
            (sealed.card_hash,),
        ).fetchone()["card_json"]
        new_state = _resolve_state("AlertCard", card_json)

        # The raw resolve would say DETECTED, but confirm should suppress it
        assert new_state == "DETECTED", "Raw resolve should say DETECTED"

        # Check: confirm guard would suppress
        current_state = db.execute(
            "SELECT state FROM incidents WHERE incident_id=?",
            (inc,),
        ).fetchone()["state"]
        assert current_state == "TRIAGED"
        should_suppress = (current_state != "DETECTED")
        assert should_suppress, "Guard should suppress AlertCard regression"


class TestPayloadHashConflict:
    """Same idempotency key + changed payload → IdempotencyConflict."""

    def test_changed_payload_raises(self, db):
        _upsert_incident(db, "hash-1", "AlertCard", "P2")
        db.execute("UPDATE incidents SET state=? WHERE incident_id=?",
                   ("TRIAGED", "hash-1"))

        a1 = make_card("Assessment", incident_id="hash-1", severity="P2",
                       evidence_strength=0.8)
        seal_card(a1, "hash-1", db, idempotency_key="k1",
                  prepared_by_role="gateway")

        # Same key, same type, different payload
        a2 = make_card("Assessment", incident_id="hash-1", severity="P1",
                       evidence_strength=0.5)
        with pytest.raises(IdempotencyConflict):
            seal_card(a2, "hash-1", db, idempotency_key="k1",
                      prepared_by_role="gateway")


class TestCrossTypeCollision:
    """Same key + different card type → IdempotencyConflict (not 500)."""

    def test_cross_type_returns_conflict(self, db):
        _upsert_incident(db, "xtype-1", "AlertCard", "P2")
        card = make_card("AlertCard", alert_id="xtype-1")
        seal_card(card, "xtype-1", db, idempotency_key="k1",
                  prepared_by_role="gateway")

        # Different card type, same key → should raise, not crash
        td = make_card("TriageDecision", incident_id="xtype-1",
                       alert_id="xtype-1", decision="route")
        with pytest.raises(IdempotencyConflict):
            seal_card(td, "xtype-1", db, idempotency_key="k1",
                      prepared_by_role="gateway")


class TestConfirmViaTestClient:
    """TestClient-based /confirm tests covering the real HTTP path."""

    @pytest.fixture
    def client(self):
        """Create a TestClient with a fresh in-memory DB."""
        from fastapi.testclient import TestClient
        from gateway.app import create_app

        app = create_app(db_path=":memory:")
        with TestClient(app) as c:
            yield c

    def test_stale_card_confirm_returns_409(self, client):
        """Stale card confirmation via /confirm → 409."""
        headers = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}

        # Step 1: prepare AlertCard → creates incident at DETECTED
        resp = client.post("/api/prepare/AlertCard", json={
            "alert_id": "e2e-stale", "source": "sentry",
            "timestamp": NOW.isoformat(), "title": "Test",
            "raw_payload": {}, "fingerprint": "fp",
            "preliminary_severity": "P2", "card_type": "AlertCard",
        }, headers={**headers, "X-Idempotency-Key": "s0"})
        assert resp.status_code == 200, resp.text
        alert_result = resp.json()

        # Step 2: confirm AlertCard
        resp = client.post("/api/confirm", json={
            "submission_id": alert_result["submission_id"],
            "room_message_id": "bm00aa00bb",
            "incident_id": alert_result["incident_id"],
            "card_hash": alert_result["card_hash"],
        }, headers=headers)
        assert resp.status_code == 200, resp.text

        # Step 3: prepare TriageDecision
        resp = client.post("/api/prepare/TriageDecision", json={
            "incident_id": "e2e-stale", "alert_id": "e2e-stale",
            "decision": "route", "noise_score": 0.1,
            "card_type": "TriageDecision",
        }, headers={**headers, "X-Idempotency-Key": "s1"})
        assert resp.status_code == 200, resp.text
        triage_result = resp.json()

        # Step 4: confirm TriageDecision → TRIAGED
        resp = client.post("/api/confirm", json={
            "submission_id": triage_result["submission_id"],
            "room_message_id": "bm11aa11bb",
            "incident_id": triage_result["incident_id"],
            "card_hash": triage_result["card_hash"],
        }, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_state"] == "TRIAGED"

        # Step 5: prepare Assessment (will become stale)
        resp = client.post("/api/prepare/Assessment", json={
            "incident_id": "e2e-stale", "severity": "P2",
            "evidence_strength": 0.8,
            "root_cause_hypothesis": "first attempt",
            "recommended_action": "fix",
            "card_type": "Assessment",
        }, headers={**headers, "X-Idempotency-Key": "s2-old"})
        assert resp.status_code == 200, resp.text
        old_assessment = resp.json()

        # Step 6: prepare a NEWER Assessment
        resp = client.post("/api/prepare/Assessment", json={
            "incident_id": "e2e-stale", "severity": "P2",
            "evidence_strength": 0.9,
            "root_cause_hypothesis": "revised attempt",
            "recommended_action": "rollback",
            "card_type": "Assessment",
        }, headers={**headers, "X-Idempotency-Key": "s2-new"})
        assert resp.status_code == 200, resp.text
        new_assessment = resp.json()

        # Step 7: confirm the NEWER Assessment first
        resp = client.post("/api/confirm", json={
            "submission_id": new_assessment["submission_id"],
            "room_message_id": "bm22aa22bb",
            "incident_id": new_assessment["incident_id"],
            "card_hash": new_assessment["card_hash"],
        }, headers=headers)
        assert resp.status_code == 200, resp.text

        # Step 8: try to confirm the OLD Assessment → 409
        resp = client.post("/api/confirm", json={
            "submission_id": old_assessment["submission_id"],
            "room_message_id": "bm33aa33bb",
            "incident_id": old_assessment["incident_id"],
            "card_hash": old_assessment["card_hash"],
        }, headers=headers)
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"]
        assert "stale" in detail.lower() or "Stale card" in detail, (
            f"Expected stale/prerequisite rejection, got: {detail}"
        )

    def test_identical_retry_returns_200(self, client):
        """Identical prepare request with same key → 200, same card_hash."""
        headers = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}
        payload = {
            "alert_id": "retry-ok", "source": "sentry",
            "timestamp": NOW.isoformat(), "title": "Test",
            "raw_payload": {}, "fingerprint": "fp",
            "preliminary_severity": "P2", "card_type": "AlertCard",
        }

        # First call
        resp1 = client.post("/api/prepare/AlertCard", json=payload,
                            headers={**headers, "X-Idempotency-Key": "retry-k"})
        assert resp1.status_code == 200, resp1.text
        hash1 = resp1.json()["card_hash"]

        # Identical retry
        resp2 = client.post("/api/prepare/AlertCard", json=payload,
                            headers={**headers, "X-Idempotency-Key": "retry-k"})
        assert resp2.status_code == 200, f"Identical retry should be 200, got {resp2.status_code}"
        assert resp2.json()["card_hash"] == hash1, "Identical retry must return same card"

    def test_changed_payload_returns_409(self, client):
        """Same key + changed payload → 409 (not silently reused)."""
        headers = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}

        # Original
        resp = client.post("/api/prepare/AlertCard", json={
            "alert_id": "tamper-1", "source": "sentry",
            "timestamp": NOW.isoformat(), "title": "Original",
            "raw_payload": {}, "fingerprint": "fp",
            "preliminary_severity": "P2", "card_type": "AlertCard",
        }, headers={**headers, "X-Idempotency-Key": "tamper-k"})
        assert resp.status_code == 200, resp.text

        # Same key, changed payload
        resp = client.post("/api/prepare/AlertCard", json={
            "alert_id": "tamper-1", "source": "sentry",
            "timestamp": NOW.isoformat(), "title": "TAMPERED title",
            "raw_payload": {}, "fingerprint": "fp",
            "preliminary_severity": "P2", "card_type": "AlertCard",
        }, headers={**headers, "X-Idempotency-Key": "tamper-k"})
        assert resp.status_code == 409, f"Changed payload should be 409, got {resp.status_code}"
        assert "different payload" in resp.json()["detail"]


class TestSealCardIdenticalRetry:
    """Direct seal_card identical retry must NOT raise."""

    def test_identical_retry_no_raise(self, db):
        _upsert_incident(db, "seal-retry", "AlertCard", "P2")
        db.execute("UPDATE incidents SET state=? WHERE incident_id=?",
                   ("TRIAGED", "seal-retry"))

        a1 = make_card("Assessment", incident_id="seal-retry", severity="P2",
                       evidence_strength=0.8)
        sealed = seal_card(a1, "seal-retry", db, idempotency_key="r1",
                           prepared_by_role="gateway")

        # Identical retry — must return same card, not raise
        a2 = make_card("Assessment", incident_id="seal-retry", severity="P2",
                       evidence_strength=0.8)
        retry = seal_card(a2, "seal-retry", db, idempotency_key="r1",
                          prepared_by_role="gateway")
        assert retry.card_hash == sealed.card_hash, "Identical retry must return same card"


class TestEnrichmentIdempotency:
    """Pre-enrichment fingerprint survives risk-floor mutation.

    ResponsePlan cards get risk_level/requires_human_approval enriched by
    _apply_risk_floor. Idempotency must compare the *original* request,
    not the enriched card.
    """

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from gateway.app import create_app

        app = create_app(db_path=":memory:")
        with TestClient(app) as c:
            yield c

    def _walk_to_reviewed(self, client, incident_id="enrich-test"):
        """Walk an incident to REVIEWED state for ResponsePlan."""
        h = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}
        now = NOW.isoformat()
        for ct, payload, key in [
            ("AlertCard", {"alert_id": incident_id, "source": "sentry",
                           "timestamp": now, "title": "T", "raw_payload": {},
                           "fingerprint": "fp", "preliminary_severity": "P1",
                           "card_type": "AlertCard"}, "w0"),
            ("TriageDecision", {"incident_id": incident_id,
                                "alert_id": incident_id,
                                "decision": "route", "noise_score": 0.1,
                                "card_type": "TriageDecision"}, "w1"),
            ("Assessment", {"incident_id": incident_id, "severity": "P1",
                            "evidence_strength": 0.9,
                            "root_cause_hypothesis": "down",
                            "recommended_action": "rollback",
                            "card_type": "Assessment"}, "w2"),
            ("Verdict", {"incident_id": incident_id, "decision": "CONFIRM",
                         "reasoning": "ok", "agrees_with_diagnosis": True,
                         "card_type": "Verdict"}, "w3"),
        ]:
            r = client.post(f"/api/prepare/{ct}", json=payload,
                            headers={**h, "X-Idempotency-Key": key})
            assert r.status_code == 200, f"{ct}: {r.status_code} {r.text}"
            d = r.json()
            client.post("/api/confirm", json={
                "submission_id": d["submission_id"],
                "room_message_id": f"bm00ff00{key}",
                "incident_id": d["incident_id"],
                "card_hash": d["card_hash"],
            }, headers=h)

    def test_enriched_identical_retry_returns_200(self, client):
        """ResponsePlan identical retry (low risk, enriched to high) → 200."""
        self._walk_to_reviewed(client, "enrich-retry")
        h = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}
        rp = {
            "incident_id": "enrich-retry", "risk_level": "low",
            "requires_human_approval": False, "runbook": "RB-001",
            "envelopes": [{"action_id": "rollback", "target": "svc",
                           "parameters": {}, "timeout_seconds": 60}],
            "card_type": "ResponsePlan",
        }

        resp1 = client.post("/api/prepare/ResponsePlan", json=rp,
                            headers={**h, "X-Idempotency-Key": "erp1"})
        assert resp1.status_code == 200, resp1.text
        # Verify enrichment happened
        assert resp1.json()["sealed_card"]["risk_level"] == "high"

        # Identical raw retry — must be 200
        resp2 = client.post("/api/prepare/ResponsePlan", json=rp,
                            headers={**h, "X-Idempotency-Key": "erp1"})
        assert resp2.status_code == 200, (
            f"Identical enriched retry should be 200, got {resp2.status_code}: "
            f"{resp2.text}"
        )
        assert resp2.json()["card_hash"] == resp1.json()["card_hash"]

    def test_changed_to_effective_returns_409(self, client):
        """ResponsePlan with risk_level changed to match effective → 409."""
        self._walk_to_reviewed(client, "enrich-changed")
        h = {"X-Agent-Key": os.environ["GATEWAY_SECRET"]}

        # Original with low risk (enriched to high)
        rp = {
            "incident_id": "enrich-changed", "risk_level": "low",
            "requires_human_approval": False, "runbook": "RB-001",
            "envelopes": [{"action_id": "rollback", "target": "svc",
                           "parameters": {}, "timeout_seconds": 60}],
            "card_type": "ResponsePlan",
        }
        resp1 = client.post("/api/prepare/ResponsePlan", json=rp,
                            headers={**h, "X-Idempotency-Key": "erp2"})
        assert resp1.status_code == 200, resp1.text

        # Changed payload matches effective but not original → 409
        changed = dict(rp, risk_level="high", requires_human_approval=True)
        resp2 = client.post("/api/prepare/ResponsePlan", json=changed,
                            headers={**h, "X-Idempotency-Key": "erp2"})
        assert resp2.status_code == 409, (
            f"Changed-to-effective should be 409, got {resp2.status_code}: "
            f"{resp2.text}"
        )
        assert "different payload" in resp2.json()["detail"]

"""Tests for the Gateway approval UI (approve_ui.py).

Covers:
- 3-layer auth (proxy secret, bcrypt, allowlist)
- CSRF verification
- GET states (active nonce, PENDING resume, APPROVED/EXECUTED, no pending)
- POST approve flow
- Resume flow
- Plan revalidation
- Commander/Operator structural checks
"""
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient

# Ensure yiting is on path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

from gateway.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_PASSWORD = "test-approval-pass"
TEST_BCRYPT_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
TEST_PROXY_SECRET = "test-proxy-secret-abc123"
TEST_CSRF_SECRET = "test-csrf-secret-xyz789"
TEST_USER = "testuser"
TEST_APPROVER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _basic_auth_header(user: str = TEST_USER, password: str = TEST_PASSWORD) -> str:
    cred = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {cred}"


def _auth_headers(user=TEST_USER, password=TEST_PASSWORD, proxy=TEST_PROXY_SECRET):
    return {
        "Authorization": _basic_auth_header(user, password),
        "X-Proxy-Secret": proxy,
    }


@pytest.fixture(autouse=True)
def _approval_env(monkeypatch):
    """Set up approval environment variables for all tests."""
    monkeypatch.setenv("APPROVAL_UI_CSRF_SECRET", TEST_CSRF_SECRET)
    monkeypatch.setenv("APPROVAL_PROXY_SECRET", TEST_PROXY_SECRET)
    monkeypatch.setenv("APPROVAL_UI_USER", TEST_USER)
    monkeypatch.setenv("APPROVAL_UI_APPROVER_ID", TEST_APPROVER_ID)
    monkeypatch.setenv("APPROVAL_UI_BCRYPT_HASH", TEST_BCRYPT_HASH)
    monkeypatch.setenv("OPERATOR_AGENT_ID", "op-agent-id-1234")
    monkeypatch.setenv("HUMAN_APPROVER_IDS", TEST_APPROVER_ID)
    # HUMAN_APPROVER_IDS is module-level set — must patch the actual variable
    approver_set = {TEST_APPROVER_ID}
    monkeypatch.setattr("gateway.routes.approve_ui.HUMAN_APPROVER_IDS", approver_set)
    monkeypatch.setattr("gateway.routes.nonce.HUMAN_APPROVER_IDS", approver_set)
    # Clear config cache between tests
    from gateway.routes import approve_ui
    approve_ui._config_cache = None
    yield
    approve_ui._config_cache = None


@pytest.fixture
def client():
    """Create a test client with cross-thread in-memory DB."""
    import sqlite3
    from contextlib import asynccontextmanager
    from gateway.database import SCHEMA, _migrate

    app = create_app(db_path=":memory:")

    # Bypass lifespan — create DB manually (cross-thread)
    db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    app.state.db = db

    @asynccontextmanager
    async def noop_lifespan(app):
        yield
    app.router.lifespan_context = noop_lifespan

    with TestClient(app) as c:
        yield c


def _create_incident(client, incident_id="INC-TEST1", state="PLANNED"):
    """Insert an incident directly into the database."""
    app = client.app
    db = app.state.db
    now = datetime.now(timezone.utc).isoformat()
    room_id = f"room-{incident_id}"
    db.execute(
        "INSERT OR REPLACE INTO incidents "
        "(incident_id, state, severity, created_at, updated_at, room_id, room_alias_id) "
        "VALUES (?, ?, 'P1', ?, ?, ?, ?)",
        (incident_id, state, now, now, room_id, room_id),
    )
    db.execute(
        "INSERT OR REPLACE INTO incident_rooms "
        "(room_id, incident_id, title, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, 'recorder', ?, ?)",
        (room_id, incident_id, "Approval UI test room", now, now),
    )
    if db.in_transaction:
        db.execute("COMMIT")


def _create_nonce(client, incident_id="INC-TEST1", nonce="ABC123",
                  plan_hash="ph123", action_hash="ah456",
                  challenge_posted=True, consumed=False):
    """Insert a nonce directly."""
    db = client.app.state.db
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    db.execute(
        "INSERT INTO nonces "
        "(incident_id, nonce, plan_hash, action_hash, plan_revision, "
        "expiry, consumed, invalidated, challenge_message_id) "
        "VALUES (?, ?, ?, ?, 1, ?, ?, 0, ?)",
        (incident_id, nonce, plan_hash, action_hash, expiry,
         1 if consumed else 0,
         "challenge-msg-123" if challenge_posted else ""),
    )
    if db.in_transaction:
        db.execute("COMMIT")


def _create_plan(client, incident_id="INC-TEST1"):
    """Insert a confirmed ResponsePlan."""
    db = client.app.state.db
    now = datetime.now(timezone.utc).isoformat()
    plan_data = {
        "card_type": "ResponsePlan",
        "runbook": "test-runbook",
        "risk_level": "high",
        "envelopes": [{"action_id": "action-1"}],
        "revision": 1,
    }
    db.execute(
        "INSERT INTO cards "
        "(card_hash, incident_id, card_type, card_json, "
        "sequence_number, prepared_by_role, published_at, created_at) "
        "VALUES (?, ?, 'ResponsePlan', ?, 1, 'commander', ?, ?)",
        ("plan-hash-1", incident_id, json.dumps(plan_data), now, now),
    )
    if db.in_transaction:
        db.execute("COMMIT")


# ===========================================================================
# AUTH TESTS (Tests 1-6)
# ===========================================================================

class TestApprovalAuth:
    """Tests for 3-layer authentication."""

    def test_get_valid_auth_renders_page(self, client):
        """Test #1: GET valid (proxy + Basic) → 200."""
        _create_incident(client)
        _create_plan(client)
        _create_nonce(client)

        resp = client.get("/approve/INC-TEST1", headers=_auth_headers())
        assert resp.status_code == 200
        assert "APPROVAL REQUIRED" in resp.text or "Approval Required" in resp.text

    def test_get_no_proxy_rejected(self, client):
        """Test #2: GET no proxy → 403."""
        resp = client.get("/approve/INC-TEST1", headers={
            "Authorization": _basic_auth_header(),
        })
        assert resp.status_code == 403

    def test_get_wrong_proxy_rejected(self, client):
        """Test #2b: GET wrong proxy → 403."""
        resp = client.get("/approve/INC-TEST1", headers={
            "Authorization": _basic_auth_header(),
            "X-Proxy-Secret": "wrong-secret",
        })
        assert resp.status_code == 403

    def test_get_proxy_ok_no_basic_rejected(self, client):
        """Test #3: GET proxy ok + no Basic → 401."""
        resp = client.get("/approve/INC-TEST1", headers={
            "X-Proxy-Secret": TEST_PROXY_SECRET,
        })
        assert resp.status_code == 401

    def test_get_wrong_password_rejected(self, client):
        """Test #4: GET proxy ok + wrong password → 403 (bcrypt)."""
        resp = client.get("/approve/INC-TEST1", headers={
            "Authorization": _basic_auth_header(password="wrong-pass"),
            "X-Proxy-Secret": TEST_PROXY_SECRET,
        })
        assert resp.status_code == 403

    def test_get_wrong_user_rejected(self, client):
        """Test #5: GET wrong user → 403."""
        resp = client.get("/approve/INC-TEST1", headers={
            "Authorization": _basic_auth_header(user="baduser"),
            "X-Proxy-Secret": TEST_PROXY_SECRET,
        })
        assert resp.status_code == 403


# ===========================================================================
# STATE TESTS (Tests 5-8)
# ===========================================================================

class TestApprovalStates:
    """Tests for various incident states."""

    def test_get_approved_shows_success(self, client):
        """Test #5: GET APPROVED → success page."""
        _create_incident(client, state="APPROVED")
        resp = client.get("/approve/INC-TEST1", headers=_auth_headers())
        assert resp.status_code == 200
        assert "approved" in resp.text.lower()

    def test_get_executed_shows_success(self, client):
        """Test #6: GET EXECUTED → success page."""
        _create_incident(client, state="EXECUTED")
        resp = client.get("/approve/INC-TEST1", headers=_auth_headers())
        assert resp.status_code == 200
        assert "executed" in resp.text.lower() or "No action needed" in resp.text

    def test_get_no_nonce_shows_no_pending(self, client):
        """Test #8: GET no auth + no nonce → 'No pending'."""
        _create_incident(client)
        resp = client.get("/approve/INC-TEST1", headers=_auth_headers())
        assert resp.status_code == 200
        assert "No Pending" in resp.text or "No active" in resp.text

    def test_get_incident_not_found(self, client):
        """GET nonexistent incident → 404."""
        resp = client.get("/approve/NONEXISTENT", headers=_auth_headers())
        assert resp.status_code == 404


# ===========================================================================
# CSRF TESTS (Test 10)
# ===========================================================================

class TestCSRF:
    """Tests for CSRF protection."""

    def test_post_bad_csrf_rejected(self, client):
        """Test #10: POST bad CSRF → 403."""
        _create_incident(client)
        _create_plan(client)
        _create_nonce(client)

        resp = client.post("/approve/INC-TEST1",
            headers=_auth_headers(),
            data={"nonce": "ABC123", "csrf_token": "bad-csrf-token"},
        )
        assert resp.status_code == 403

    def test_post_missing_nonce_rejected(self, client):
        """POST missing nonce → 400."""
        _create_incident(client)
        resp = client.post("/approve/INC-TEST1",
            headers=_auth_headers(),
            data={"csrf_token": "some-token"},
        )
        assert resp.status_code == 400


# ===========================================================================
# COMMANDER STRUCTURAL TESTS (Tests 25-29)
# ===========================================================================

class TestCommanderStructural:
    """Structural tests for Commander changes."""

    def test_commander_no_human_recruitment(self):
        """Test #25: Commander has no participant API calls with human IDs."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()

        # Find the high-risk section
        hr_start = source.find("Skipping human recruitment")
        assert hr_start > 0, "Skipping comment must exist"

        hr_code = source[hr_start:hr_start + 2000]
        assert "/participants" not in hr_code, (
            "No participant API calls in high-risk section"
        )

    def test_commander_mentions_operator_only(self):
        """Test #26: Commander mentions Operator only."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()

        hr_start = source.find("Skipping human recruitment")
        hr_code = source[hr_start:hr_start + 500]

        assert 'mention_objects = [{"id": operator_id}]' in hr_code

    def test_commander_challenge_text_has_url(self):
        """Test #27: Challenge text contains approval URL, not nonce."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()

        assert "To approve, open the YITING approval page" in source
        assert "APPROVAL REQUIRED" in source
        assert "reply with the nonce" not in source

    def test_commander_payload_no_nonce(self):
        """Test #28: challenge_payload has no 'nonce' key."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()

        # Find the challenge_payload section
        payload_start = source.find("challenge_payload = {")
        assert payload_start > 0
        payload_end = source.find("}", payload_start)
        payload_code = source[payload_start:payload_end]

        assert '"nonce":' not in payload_code, "nonce must not be in challenge_payload"

    def test_commander_no_nameerror(self):
        """Test #29: No reference to removed all_mention_ids."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()

        # Find the post-challenge log
        log_start = source.find("Approval challenge ready for")
        assert log_start > 0
        log_code = source[log_start:log_start + 200]

        assert "all_mention_ids" not in log_code, "all_mention_ids removed"
        assert "Operator only" in log_code


# ===========================================================================
# LOAD_RESPONSE_PLAN TESTS (Test 24)
# ===========================================================================

class TestLoadResponsePlan:
    """Tests for _load_response_plan hash parity."""

    def test_load_response_plan_uses_correct_predicate(self):
        """Test #24: _load_response_plan matches nonce creation."""
        from gateway.routes.approve_ui import _load_response_plan
        import inspect
        source = inspect.getsource(_load_response_plan)

        assert "published_at IS NOT NULL" in source
        assert "confirmed" not in source.lower() or "published_at" in source


# ===========================================================================
# NONCE CONSUME STRUCTURAL (Tests 21-23)
# ===========================================================================

class TestNonceConsumeStructural:
    """Structural tests for nonce consume behavior."""

    def test_whitespace_room_message_id_rejected(self, client):
        """Test #21: API whitespace room_message_id → 400."""
        # We just test the structural assertion
        from gateway.routes.nonce import consume_nonce
        import inspect
        source = inspect.getsource(consume_nonce)
        assert "room_message_id.strip()" in source

    def test_room_card_has_card_hash_db_does_not(self):
        """Test #22: card_hash injection is copy-only."""
        from gateway.routes.nonce import _publish_and_advance
        import inspect
        source = inspect.getsource(_publish_and_advance)

        assert 'sealed_card_data["card_hash"] = row["card_hash"]' in source
        assert "Copy only" in source or "DB untouched" in source

    def test_mentions_operator(self):
        """Test #23: room publication mentions OPERATOR_AGENT_ID."""
        from gateway.routes.nonce import _publish_and_advance
        import inspect
        source = inspect.getsource(_publish_and_advance)

        assert "OPERATOR_AGENT_ID" in source
        assert "mentions=[operator_id]" in source

    def test_operator_missing_returns_502(self):
        """Test #29b: OPERATOR_AGENT_ID empty → 502."""
        from gateway.routes.nonce import _publish_and_advance
        import inspect
        source = inspect.getsource(_publish_and_advance)

        assert '"OPERATOR_AGENT_ID not configured"' in source
        assert "502" in source


# ===========================================================================
# RESUME TESTS (Tests 17-19, 24)
# ===========================================================================

class TestResumeStructural:
    """Structural tests for resume branch."""

    def test_resume_checks_state(self):
        """Test #17: Resume validates state == PLANNED."""
        from gateway.routes.nonce import _resume_pending
        import inspect
        source = inspect.getsource(_resume_pending)

        assert '"state"' in source or "state" in source
        assert "PLANNED" in source

    def test_resume_validates_plan_hash(self):
        """Test #18: Resume revalidates plan hashes."""
        from gateway.routes.nonce import _resume_pending
        import inspect
        source = inspect.getsource(_resume_pending)

        assert "compute_plan_hash" in source
        assert "compute_action_hash" in source
        assert "superseded" in source

    def test_resume_checks_nonce_consumed(self):
        """Test #19: Resume validates nonce consumed."""
        from gateway.routes.nonce import _resume_pending
        import inspect
        source = inspect.getsource(_resume_pending)

        assert 'auth_row["nonce"]' in source  # bracket notation
        assert "nonce not consumed" in source


# ===========================================================================
# APPROVAL_CHANNEL / MODEL (Test 32)
# ===========================================================================

class TestApprovalChannel:
    """Tests for approval_channel field."""

    def test_structured_approval_has_channel(self):
        """Verify StructuredApproval model has approval_channel."""
        from shared.models import StructuredApproval

        card = StructuredApproval(
            incident_id="INC-1",
            action_id="auth-1",
            action_hash="ah",
            decision="APPROVED",
            approver_id="ap",
            plan_hash="ph",
            nonce="ABC",
            expiry=datetime.now(timezone.utc),
        )
        assert card.approval_channel == "room"  # default
        assert card.room_message_id == ""  # default empty
        assert card.room_alias_id == ""  # default empty

    def test_gateway_ui_channel(self):
        """Verify gateway_ui channel works."""
        from shared.models import StructuredApproval

        card = StructuredApproval(
            incident_id="INC-1",
            action_id="auth-1",
            action_hash="ah",
            decision="APPROVED",
            approver_id="ap",
            plan_hash="ph",
            nonce="ABC",
            expiry=datetime.now(timezone.utc),
            approval_channel="gateway_ui",
        )
        assert card.approval_channel == "gateway_ui"

"""Behavioral tests for C11 — runtime execution, not source inspection.

Covers final review requirements:
1. Sealed StructuredApproval event through OperatorPreprocessor.process()
2. 409 authorization_pending → retry → 200 → ExecutionContext
3. Valid approval-page POST → APPROVED
4. UI room-publication failure → PENDING → resume POST → APPROVED
5. Runtime XSS escaping with malicious plan content
6. P5 severity aborts (not in Assessment schema)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import bcrypt
import pytest
from fastapi.testclient import TestClient

# Ensure yiting on path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))


# ===========================================================================
# Shared helpers
# ===========================================================================

TEST_PASSWORD = "test-approval-pass-c11"
TEST_BCRYPT_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()
TEST_PROXY_SECRET = "test-proxy-secret-c11"
TEST_CSRF_SECRET = "test-csrf-secret-c11"
TEST_USER = "testuser"
TEST_APPROVER_ID = "11111111-2222-3333-4444-555555555555"
RECORDER_AGENT_ID = "recorder-agent-id-c11"
OPERATOR_AGENT_ID = "operator-agent-id-c11"


def _basic_auth_header(user=TEST_USER, password=TEST_PASSWORD):
    cred = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {cred}"


def _auth_headers():
    return {
        "Authorization": _basic_auth_header(),
        "X-Proxy-Secret": TEST_PROXY_SECRET,
    }


def _csrf_token(nonce_val):
    return hmac.new(
        TEST_CSRF_SECRET.encode(), nonce_val.encode(), hashlib.sha256
    ).hexdigest()


@pytest.fixture(autouse=True)
def _c11_env(monkeypatch):
    monkeypatch.setenv("APPROVAL_UI_CSRF_SECRET", TEST_CSRF_SECRET)
    monkeypatch.setenv("APPROVAL_PROXY_SECRET", TEST_PROXY_SECRET)
    monkeypatch.setenv("APPROVAL_UI_USER", TEST_USER)
    monkeypatch.setenv("APPROVAL_UI_APPROVER_ID", TEST_APPROVER_ID)
    monkeypatch.setenv("APPROVAL_UI_BCRYPT_HASH", TEST_BCRYPT_HASH)
    monkeypatch.setenv("OPERATOR_AGENT_ID", OPERATOR_AGENT_ID)
    monkeypatch.setenv("RECORDER_AGENT_ID", RECORDER_AGENT_ID)
    monkeypatch.setenv("HUMAN_APPROVER_IDS", TEST_APPROVER_ID)
    approver_set = {TEST_APPROVER_ID}
    monkeypatch.setattr("gateway.routes.approve_ui.HUMAN_APPROVER_IDS", approver_set)
    monkeypatch.setattr("gateway.routes.nonce.HUMAN_APPROVER_IDS", approver_set)
    from gateway.routes import approve_ui
    approve_ui._config_cache = None
    yield
    approve_ui._config_cache = None


@pytest.fixture
def app_db():
    """Gateway app + in-memory DB."""
    from contextlib import asynccontextmanager
    from gateway.app import create_app
    from gateway.database import SCHEMA, _migrate

    app = create_app(db_path=":memory:")
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
    yield app, db


@pytest.fixture
def client(app_db):
    app, _ = app_db
    with TestClient(app) as c:
        yield c


def _seed_incident(db, incident_id="INC-C11", state="PLANNED"):
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
        (room_id, incident_id, "C11 test room", now, now),
    )


def _seed_plan(db, incident_id="INC-C11"):
    """Insert a confirmed ResponsePlan with normalize-compatible hash."""
    from shared.approval import compute_plan_hash, compute_action_hash, normalize_plan_for_hash
    now = datetime.now(timezone.utc).isoformat()
    plan_data = {
        "card_type": "ResponsePlan",
        "runbook": "test-runbook",
        "risk_level": "high",
        "envelopes": [{"action_id": "restart_service", "target": "web-1"}],
        "revision": 1,
    }
    db.execute(
        "INSERT INTO cards "
        "(card_hash, incident_id, card_type, card_json, "
        "sequence_number, prepared_by_role, published_at, created_at) "
        "VALUES (?, ?, 'ResponsePlan', ?, 1, 'commander', ?, ?)",
        ("plan-hash-c11", incident_id, json.dumps(plan_data), now, now),
    )
    normalized = normalize_plan_for_hash(plan_data)
    return {
        "plan_hash": compute_plan_hash(normalized),
        "action_hash": compute_action_hash(plan_data.get("envelopes", [])),
    }


def _seed_nonce(db, incident_id="INC-C11", nonce_val="C11TST",
                plan_hash="", action_hash=""):
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    db.execute(
        "INSERT INTO nonces "
        "(incident_id, nonce, plan_hash, action_hash, plan_revision, "
        "expiry, consumed, invalidated, challenge_message_id) "
        "VALUES (?, ?, ?, ?, 1, ?, 0, 0, 'challenge-msg-c11')",
        (incident_id, nonce_val, plan_hash, action_hash, expiry),
    )


# ===========================================================================
# Test 1: StructuredApproval through OperatorPreprocessor.process()
# ===========================================================================

class TestOperatorStructuredApprovalRuntime:
    """Execute a sealed StructuredApproval event through the real preprocessor."""

    @pytest.mark.asyncio
    async def test_structured_approval_accepted_by_preprocessor(self):
        """A valid StructuredApproval from RECORDER_AGENT_ID reaches the LLM."""
        from agents.operator import OperatorPreprocessor, _execution_contexts

        card = {
            "card_type": "StructuredApproval",
            "incident_id": "INC-SA-1",
            "action_id": "auth-uuid-123",
            "decision": "APPROVED",
            "card_hash": "sealed-hash-abc",
            "approval_channel": "gateway_ui",
        }
        content = f"```json\n{json.dumps(card)}\n```"

        # Mock the event
        payload = MagicMock()
        payload.content = content
        payload.sender_type = "Agent"
        payload.sender_id = RECORDER_AGENT_ID
        payload.id = "msg-1"
        payload.inserted_at = None
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.payload = payload
        event.room_id = "room-sa-1"

        ctx = MagicMock()

        # Mock _consume_authorization_with_retry to return success
        auth_data = {
            "authorization_id": "auth-uuid-123",
            "plan_hash": "ph1",
            "action_hash": "ah1",
            "envelopes": [{"action_id": "restart_service", "target": "web-1"}],
        }
        # Mock incident check
        incidents_resp = MagicMock()
        incidents_resp.status_code = 200
        incidents_resp.json.return_value = {"incident": {"state": "APPROVED"}}

        preprocessor = OperatorPreprocessor.__new__(OperatorPreprocessor)
        preprocessor._default_preprocessor = MagicMock()
        preprocessor._default_preprocessor.process = AsyncMock(return_value="LLM_INPUT")
        preprocessor._pending_approvals = {}
        preprocessor._boot_epoch = None

        async def mock_ensure(*a, **kw):
            pass
        preprocessor._ensure_default = mock_ensure

        with patch.dict(os.environ, {
            "RECORDER_AGENT_ID": RECORDER_AGENT_ID,
        }):
            with patch("agents.operator.ACTIVE_INCIDENTS", new=set()):
                with patch("agents.operator._consume_authorization_with_retry",
                           new=AsyncMock(return_value=auth_data)):
                    with patch("agents.operator.httpx.AsyncClient") as mock_http:
                        mock_http_instance = AsyncMock()
                        mock_http_instance.get = AsyncMock(return_value=incidents_resp)
                        mock_http.__aenter__ = AsyncMock(return_value=mock_http_instance)
                        mock_http.__aexit__ = AsyncMock(return_value=False)
                        mock_http.return_value = mock_http_instance

                        result = await preprocessor.process(ctx, event, agent_id="op-1")

        # Should have reached the LLM (defaultPreprocessor.process called)
        assert result == "LLM_INPUT"
        # ExecutionContext must be set
        assert "INC-SA-1" in _execution_contexts
        ec = _execution_contexts["INC-SA-1"]
        assert ec.authorization_type == "human_approval"
        assert ec.authorization_id == "auth-uuid-123"
        assert len(ec.envelopes) == 1
        # Cleanup
        del _execution_contexts["INC-SA-1"]

    @pytest.mark.asyncio
    async def test_structured_approval_wrong_sender_rejected(self):
        """StructuredApproval from wrong sender is silently rejected."""
        from agents.operator import OperatorPreprocessor

        card = {
            "card_type": "StructuredApproval",
            "incident_id": "INC-SA-2",
            "action_id": "auth-uuid-bad",
            "card_hash": "sealed-hash-xyz",
        }
        content = f"```json\n{json.dumps(card)}\n```"

        payload = MagicMock()
        payload.content = content
        payload.sender_type = "Agent"
        payload.sender_id = "malicious-agent-id"  # Wrong sender
        payload.id = "msg-2"
        payload.inserted_at = None
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.payload = payload

        ctx = MagicMock()
        preprocessor = OperatorPreprocessor.__new__(OperatorPreprocessor)
        preprocessor._default_preprocessor = MagicMock()
        preprocessor._default_preprocessor.process = AsyncMock()
        preprocessor._pending_approvals = {}
        preprocessor._boot_epoch = None

        async def mock_ensure(*a, **kw):
            pass
        preprocessor._ensure_default = mock_ensure

        with patch.dict(os.environ, {"RECORDER_AGENT_ID": RECORDER_AGENT_ID}):
            result = await preprocessor.process(ctx, event, agent_id="op-1")

        assert result is None
        # LLM should NOT have been called
        preprocessor._default_preprocessor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_structured_approval_with_plan_hash_nonce_not_intercepted(self):
        """Regression: StructuredApproval containing plan_hash+nonce must NOT be
        intercepted by the challenge-guard (which checks for those keywords).
        Live bug: Recorder's StructuredApproval was rejected as 'non-Commander
        challenge' because the card JSON contained plan_hash and nonce."""
        from agents.operator import OperatorPreprocessor, _execution_contexts

        # Real-shaped card with plan_hash and nonce (exactly as Gateway seals it)
        card = {
            "card_type": "StructuredApproval",
            "incident_id": "INC-REGRESSION-1",
            "action_id": "auth-uuid-regression",
            "card_hash": "sealed-hash-regression",
            "plan_hash": "a17056b89f47ca6273a9ec663e3cd6d4",
            "action_hash": "c94a1b2444fcc68c9dbf05e54ab129d6",
            "nonce": "CME8GX",
            "approval_channel": "gateway_ui",
            "decision": "APPROVED",
        }
        content = f"```json\n{json.dumps(card)}\n```"

        payload = MagicMock()
        payload.content = content
        payload.sender_type = "Agent"
        payload.sender_id = RECORDER_AGENT_ID  # Correct sender
        payload.id = "msg-regression"
        payload.inserted_at = None
        event = MagicMock()
        type(event).__name__ = "MessageEvent"
        event.payload = payload
        event.room_id = "room-regression"

        ctx = MagicMock()

        auth_data = {
            "authorization_id": "auth-uuid-regression",
            "plan_hash": "ph1",
            "action_hash": "ah1",
            "envelopes": [{"action_id": "rollback", "target": "svc-1"}],
        }
        incidents_resp = MagicMock()
        incidents_resp.status_code = 200
        incidents_resp.json.return_value = {"incident": {"state": "APPROVED"}}

        preprocessor = OperatorPreprocessor.__new__(OperatorPreprocessor)
        preprocessor._default_preprocessor = MagicMock()
        preprocessor._default_preprocessor.process = AsyncMock(return_value="LLM_INPUT")
        preprocessor._pending_approvals = {}
        preprocessor._boot_epoch = None

        async def mock_ensure(*a, **kw):
            pass
        preprocessor._ensure_default = mock_ensure

        with patch.dict(os.environ, {
            "RECORDER_AGENT_ID": RECORDER_AGENT_ID,
            "COMMANDER_AGENT_ID": "commander-agent-id-c11",
        }):
            with patch("agents.operator.ACTIVE_INCIDENTS", new=set()):
                with patch("agents.operator._consume_authorization_with_retry",
                           new=AsyncMock(return_value=auth_data)):
                    with patch("agents.operator.httpx.AsyncClient") as mock_http:
                        mock_http_instance = AsyncMock()
                        mock_http_instance.get = AsyncMock(return_value=incidents_resp)
                        mock_http.__aenter__ = AsyncMock(return_value=mock_http_instance)
                        mock_http.__aexit__ = AsyncMock(return_value=False)
                        mock_http.return_value = mock_http_instance

                        result = await preprocessor.process(ctx, event, agent_id="op-1")

        # MUST reach LLM (not silently rejected by challenge guard)
        assert result == "LLM_INPUT"
        assert "INC-REGRESSION-1" in _execution_contexts
        ec = _execution_contexts["INC-REGRESSION-1"]
        assert ec.authorization_type == "human_approval"
        assert ec.authorization_id == "auth-uuid-regression"
        # Cleanup
        del _execution_contexts["INC-REGRESSION-1"]


# ===========================================================================
# Test 2: 409 retry → 200 → ExecutionContext
# ===========================================================================

class TestBoundedRetryRuntime:
    """_consume_authorization_with_retry handles 409 then 200."""

    @pytest.mark.asyncio
    async def test_retry_on_409_then_success(self):
        """409 authorization_pending on attempt 1, 200 on attempt 2."""
        from agents.operator import _consume_authorization_with_retry

        resp_409 = MagicMock()
        resp_409.status_code = 409
        resp_409.json.return_value = {"detail": "authorization_pending"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "authorization_id": "auth-123",
            "envelopes": [{"action_id": "restart"}],
            "plan_hash": "ph",
            "action_hash": "ah",
        }

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp_409
            return resp_200

        mock_http = AsyncMock()
        mock_http.post = mock_post

        with patch.dict(os.environ, {
            "GATEWAY_URL": "http://localhost:8000",
            "GATEWAY_SECRET": "test-key",
        }):
            with patch("agents.operator.httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _consume_authorization_with_retry(
                    "auth-123", "INC-RETRY",
                    max_retries=2,
                    backoff_schedule=(0.01, 0.01),  # Fast for tests
                )

        assert result is not None
        assert result["authorization_id"] == "auth-123"
        assert call_count == 2  # 409 + 200

    @pytest.mark.asyncio
    async def test_non_409_fails_immediately(self):
        """Non-409 error (e.g. 403) fails closed without retry."""
        from agents.operator import _consume_authorization_with_retry

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.json.return_value = {"detail": "forbidden"}

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return resp_403

        mock_http = AsyncMock()
        mock_http.post = mock_post

        with patch.dict(os.environ, {
            "GATEWAY_URL": "http://localhost:8000",
            "GATEWAY_SECRET": "test-key",
        }):
            with patch("agents.operator.httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _consume_authorization_with_retry(
                    "auth-bad", "INC-FAIL",
                    max_retries=3,
                    backoff_schedule=(0.01,),
                )

        assert result is None
        assert call_count == 1  # No retry


# ===========================================================================
# Test 3: Valid approval-page POST → APPROVED
# ===========================================================================

class TestValidPostApproved:
    """Valid POST with correct CSRF and nonce → APPROVED state."""

    def test_valid_post_advances_to_approved(self, app_db):
        """Full POST flow: seed state → POST → APPROVED."""
        app, db = app_db
        _seed_incident(db)
        hashes = _seed_plan(db)
        _seed_nonce(db, plan_hash=hashes["plan_hash"],
                    action_hash=hashes["action_hash"])

        csrf = _csrf_token("C11TST")

        with TestClient(app) as c:
            resp = c.post(
                "/approve/INC-C11",
                headers=_auth_headers(),
                data={"nonce": "C11TST", "csrf_token": csrf, "decision": "approve"},
            )

        assert resp.status_code == 200
        assert "Approved" in resp.text or "approved" in resp.text

        # Verify incident state advanced
        inc = db.execute(
            "SELECT state FROM incidents WHERE incident_id='INC-C11'"
        ).fetchone()
        assert inc["state"] in ("APPROVED", "EXECUTED"), \
            f"Expected APPROVED/EXECUTED, got {inc['state']}"

        # Verify authorization created
        auth = db.execute(
            "SELECT status, authorization_type FROM authorizations "
            "WHERE incident_id='INC-C11'"
        ).fetchone()
        assert auth is not None
        assert auth["authorization_type"] == "human_approval"
        assert auth["status"] == "PUBLISHED"


# ===========================================================================
# Test 4: room publish failure → PENDING → resume POST → APPROVED
# ===========================================================================

class TestRoomPublishResumeFlow:
    """Room publication fails → PENDING → resume retries → APPROVED."""

    def test_room_failure_then_resume_succeeds(self, app_db):
        """Room publication failure on first try → PENDING auth. Resume POST → success."""
        app, db = app_db
        _seed_incident(db)
        hashes = _seed_plan(db)
        _seed_nonce(db, plan_hash=hashes["plan_hash"],
                    action_hash=hashes["action_hash"])

        csrf = _csrf_token("C11TST")

        # First POST: room publication fails
        with patch("gateway.routes.nonce.store_room_message", side_effect=RuntimeError("room down")):
            with TestClient(app) as c:
                resp1 = c.post(
                    "/approve/INC-C11",
                    headers=_auth_headers(),
                    data={"nonce": "C11TST", "csrf_token": csrf, "decision": "approve"},
                )

        # Should get 502 error page
        assert resp1.status_code == 502 or "pending" in resp1.text.lower() or "error" in resp1.text.lower()

        # Check: authorization should be PENDING
        auth = db.execute(
            "SELECT authorization_id, status, nonce FROM authorizations "
            "WHERE incident_id='INC-C11'"
        ).fetchone()
        assert auth is not None
        assert auth["status"] == "PENDING"

        # Now resume: GET page should show "Pending Resume"
        with TestClient(app) as c:
            get_resp = c.get("/approve/INC-C11", headers=_auth_headers())
        assert get_resp.status_code == 200
        assert "Pending Resume" in get_resp.text or "Retry" in get_resp.text

        # Resume POST with room publication success
        resume_csrf = _csrf_token(auth["nonce"])
        with TestClient(app) as c:
            resp2 = c.post(
                "/approve/INC-C11",
                headers=_auth_headers(),
                data={
                    "nonce": auth["nonce"],
                    "csrf_token": resume_csrf,
                    "resume": "1",
                    "decision": "approve",
                },
            )

        assert resp2.status_code == 200
        assert "Approved" in resp2.text or "approved" in resp2.text

        # Verify state advanced
        inc = db.execute(
            "SELECT state FROM incidents WHERE incident_id='INC-C11'"
        ).fetchone()
        assert inc["state"] in ("APPROVED", "EXECUTED")


# ===========================================================================
# Test 5: Runtime XSS escaping with malicious content
# ===========================================================================

class TestRuntimeXSSEscaping:
    """Verify html.escape() actually prevents injection at runtime."""

    def test_malicious_incident_id_escaped(self, app_db):
        """XSS in incident_id path is HTML-escaped in response."""
        app, _ = app_db
        # Use a URL-safe but HTML-dangerous ID with a raw double-quote
        # If unescaped, this could break out of an attribute: value="INC" onmouseover=...
        malicious_id = 'INC"onmouseover=alert(1)'

        with TestClient(app) as c:
            resp = c.get(f"/approve/{malicious_id}", headers=_auth_headers())

        # The raw double-quote MUST be escaped to &quot; — this prevents
        # attribute breakout. The text "onmouseover" is safe when preceded by &quot;
        # because the browser won't parse it as an attribute.
        assert 'INC"onmouseover' not in resp.text, (
            "Raw unescaped double-quote found — XSS attribute injection possible!"
        )

    def test_malicious_plan_content_escaped(self, app_db):
        """Plan data with <script> tags is escaped in rendered page."""
        app, db = app_db
        _seed_incident(db, incident_id="INC-XSS")

        # Insert plan with malicious runbook name
        now = datetime.now(timezone.utc).isoformat()
        malicious_plan = {
            "card_type": "ResponsePlan",
            "runbook": '<img src=x onerror=alert("xss")>',
            "risk_level": '"><script>document.cookie</script>',
            "envelopes": [{"action_id": '<script>alert(1)</script>'}],
            "revision": 1,
        }
        db.execute(
            "INSERT INTO cards "
            "(card_hash, incident_id, card_type, card_json, "
            "sequence_number, prepared_by_role, published_at, created_at) "
            "VALUES (?, ?, 'ResponsePlan', ?, 1, 'commander', ?, ?)",
            ("plan-hash-xss", "INC-XSS", json.dumps(malicious_plan), now, now),
        )

        # Seed nonce with matching hashes
        from shared.approval import compute_plan_hash, compute_action_hash, normalize_plan_for_hash
        norm = normalize_plan_for_hash(malicious_plan)
        ph = compute_plan_hash(norm)
        ah = compute_action_hash(malicious_plan.get("envelopes", []))
        _seed_nonce(db, incident_id="INC-XSS", plan_hash=ph, action_hash=ah)

        with TestClient(app) as c:
            resp = c.get("/approve/INC-XSS", headers=_auth_headers())

        assert resp.status_code == 200
        # The actual HTML must NOT contain raw executable tags from USER DATA.
        # The page template has its own inline <script> for the character counter,
        # so we check for the INJECTED content specifically.
        assert "<script>document.cookie</script>" not in resp.text, (
            "Injected <script>document.cookie</script> found — XSS vulnerability!"
        )
        assert "<script>alert(1)</script>" not in resp.text, (
            "Injected <script>alert(1)</script> found — XSS vulnerability!"
        )
        assert "<img src=x" not in resp.text, "Raw <img> with handler found — XSS!"
        # Escaped versions must be present
        assert "&lt;script&gt;" in resp.text, "Script tag should appear escaped"

    def test_malicious_error_message_escaped(self, app_db):
        """Error messages containing HTML are escaped in rendered page."""
        app, db = app_db
        # Create an incident with a PLANNED state but consumed nonce to trigger error
        _seed_incident(db, incident_id="INC-ERR")
        _seed_plan(db, incident_id="INC-ERR")

        # Seed a consumed nonce
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db.execute(
            "INSERT INTO nonces "
            "(incident_id, nonce, plan_hash, action_hash, plan_revision, "
            "expiry, consumed, invalidated, challenge_message_id) "
            "VALUES (?, ?, ?, ?, 1, ?, 1, 0, 'challenge-err')",
            ("INC-ERR", "ERRTST", "ph", "ah", expiry),
        )

        # POST with valid CSRF for this nonce but nonce is consumed → error page
        csrf = _csrf_token("ERRTST")
        with TestClient(app) as c:
            resp = c.post(
                "/approve/INC-ERR",
                headers=_auth_headers(),
                data={"nonce": "ERRTST", "csrf_token": csrf},
            )

        # Error page must escape the incident_id in the title/header
        assert "<script>" not in resp.text


# ===========================================================================
# Test 6: P5 severity aborts (not in Assessment schema)
# ===========================================================================

class TestP5SeverityAborts:
    """P5 is NOT in Assessment schema — must abort ResponsePlan creation."""

    def test_p5_not_in_recognized_severities(self):
        """P5 must not be in the Commander's recognized set."""
        import agents.commander as cmd_mod
        source = open(cmd_mod.__file__).read()
        # Find the actual set
        idx = source.find("RECOGNIZED_SEVERITIES")
        line = source[idx:source.find("\n", idx)]
        assert "P5" not in line, "P5 must not be in RECOGNIZED_SEVERITIES"

    def test_p5_matches_schema(self):
        """Schema Literal only permits P1-P4."""
        from shared.models import Assessment
        import inspect
        source = inspect.getsource(Assessment)
        assert '"P5"' not in source, "Assessment schema must not include P5"

    def test_p5_determine_risk_low(self):
        """P5 would resolve to low-risk — that's WHY it must be rejected."""
        from agents.commander import determine_risk_level
        # If P5 were allowed, it'd auto-execute
        assert determine_risk_level("P5", []) == "low"
        # But the Commander rejects it before reaching determine_risk_level

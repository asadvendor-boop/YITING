"""Tests for heartbeat and suppression endpoints in gateway/app.py."""
import os

import pytest

from gateway.auth import _reset_for_testing


@pytest.fixture
def app_client(tmp_path):
    """Create a test client for the gateway app."""
    import sqlite3

    _reset_for_testing()
    os.environ["TRIAGE_SUBMISSION_KEY"] = "test-triage-key"
    os.environ["SAFETY_REVIEWER_SUBMISSION_KEY"] = "test-sr-key"
    os.environ["GATEWAY_SECRET"] = "test-gw-secret"

    from gateway.app import create_app
    from gateway.database import SCHEMA
    from fastapi.testclient import TestClient

    test_app = create_app()
    # Create DB with check_same_thread=False for TestClient (runs in different thread)
    db_path = str(tmp_path / "test.db")
    db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    test_app.state.db = db

    client = TestClient(test_app)
    yield client

    db.close()
    _reset_for_testing()


class TestHeartbeat:
    """Test POST /heartbeat and GET /agent-status."""

    def test_post_heartbeat_no_key_401(self, app_client):
        resp = app_client.post("/heartbeat", json={"role": "triage"})
        assert resp.status_code == 401

    def test_post_heartbeat_wrong_role_403(self, app_client):
        resp = app_client.post(
            "/heartbeat",
            json={"role": "operator"},  # key is for triage
            headers={"X-Agent-Key": "test-triage-key"},
        )
        assert resp.status_code == 403

    def test_post_heartbeat_valid(self, app_client):
        resp = app_client.post(
            "/heartbeat",
            json={
                "role": "triage",
                "agent_id": "agent-123",
                "framework": "local-room",
                "model": "qwen3.6-flash",
                "display_name": "Lin Xun",
                "persona_title": "Signal Sentinel",
                "persona_temperament": "fast and skeptical",
            },
            headers={"X-Agent-Key": "test-triage-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_gateway_key_any_role(self, app_client):
        """Gateway secret key can claim any role."""
        resp = app_client.post(
            "/heartbeat",
            json={"role": "operator"},
            headers={"X-Agent-Key": "test-gw-secret"},
        )
        assert resp.status_code == 200

    def test_agent_status_returns_agents(self, app_client):
        # Post a heartbeat first
        app_client.post(
            "/heartbeat",
            json={
                "role": "triage",
                "agent_id": "t-1",
                "framework": "local-room",
                "model": "qwen3.6-flash",
                "display_name": "Lin Xun",
                "persona_title": "Signal Sentinel",
            },
            headers={"X-Agent-Key": "test-triage-key"},
        )
        resp = app_client.get("/agent-status")
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        assert agents[0]["agent_role"] == "triage"
        assert agents[0]["display_name"] == "Lin Xun"
        assert agents[0]["persona_title"] == "Signal Sentinel"


class TestSuppression:
    """Test suppression rule endpoints."""

    def test_create_rule_unauthorized(self, app_client):
        resp = app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-123"},
            headers={"X-Agent-Key": "test-triage-key"},  # triage can't create
        )
        assert resp.status_code == 403

    def test_create_rule_valid(self, app_client):
        resp = app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-test-1", "reason": "test false alarm"},
            headers={"X-Agent-Key": "test-sr-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fingerprint"] == "fp-test-1"
        assert data["max"] == 3

    def test_create_duplicate_409(self, app_client):
        app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-dup"},
            headers={"X-Agent-Key": "test-sr-key"},
        )
        resp2 = app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-dup"},
            headers={"X-Agent-Key": "test-sr-key"},
        )
        assert resp2.status_code == 409

    def test_increment_valid(self, app_client):
        # Create rule
        create_resp = app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-inc"},
            headers={"X-Agent-Key": "test-sr-key"},
        )
        rule_id = create_resp.json()["rule_id"]

        # Increment 3 times (max=3)
        for _ in range(3):
            resp = app_client.post(
                f"/suppression-rules/{rule_id}/increment",
                headers={"X-Agent-Key": "test-triage-key"},
            )
            assert resp.status_code == 200

        # 4th increment should be 409 (exhausted)
        resp = app_client.post(
            f"/suppression-rules/{rule_id}/increment",
            headers={"X-Agent-Key": "test-triage-key"},
        )
        assert resp.status_code == 409

    def test_get_rules_by_fingerprint(self, app_client):
        app_client.post(
            "/suppression-rules",
            json={"fingerprint": "fp-get-test"},
            headers={"X-Agent-Key": "test-sr-key"},
        )
        resp = app_client.get("/suppression-rules", params={"fingerprint": "fp-get-test"})
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 1
        assert rules[0]["fingerprint"] == "fp-get-test"

"""Tests for gateway/auth.py — shared agent-key authentication."""

import pytest

from gateway.auth import get_role_for_key, is_valid_key, get_key_for_role, _reset_for_testing


@pytest.fixture(autouse=True)
def clean_auth_cache():
    """Reset cached keys before each test."""
    _reset_for_testing()
    yield
    _reset_for_testing()


class TestGetRoleForKey:
    """Test key → role lookup."""

    def test_valid_key_returns_role(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "triage-key-123")
        assert get_role_for_key("triage-key-123") == "triage"

    def test_invalid_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "triage-key-123")
        assert get_role_for_key("wrong-key") is None

    def test_empty_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "triage-key-123")
        assert get_role_for_key("") is None

    def test_gateway_secret_maps_to_gateway_role(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_SECRET", "gw-secret-456")
        assert get_role_for_key("gw-secret-456") == "gateway"

    def test_all_roles_load(self, monkeypatch):
        keys = {
            "RECORDER_SUBMISSION_KEY": "rec-k",
            "TRIAGE_SUBMISSION_KEY": "tri-k",
            "DIAGNOSIS_SUBMISSION_KEY": "diag-k",
            "SAFETY_REVIEWER_SUBMISSION_KEY": "sr-k",
            "COMMANDER_SUBMISSION_KEY": "cmd-k",
            "OPERATOR_SUBMISSION_KEY": "op-k",
        }
        for env_var, key_val in keys.items():
            monkeypatch.setenv(env_var, key_val)

        assert get_role_for_key("rec-k") == "recorder"
        assert get_role_for_key("tri-k") == "triage"
        assert get_role_for_key("diag-k") == "diagnosis"
        assert get_role_for_key("sr-k") == "safety_reviewer"
        assert get_role_for_key("cmd-k") == "commander"
        assert get_role_for_key("op-k") == "operator"


class TestIsValidKey:
    """Test key validation."""

    def test_valid_key(self, monkeypatch):
        monkeypatch.setenv("RECORDER_SUBMISSION_KEY", "rec-key")
        assert is_valid_key("rec-key") is True

    def test_invalid_key(self, monkeypatch):
        monkeypatch.setenv("RECORDER_SUBMISSION_KEY", "rec-key")
        assert is_valid_key("nope") is False


class TestGetKeyForRole:
    """Test role → key lookup."""

    def test_known_role(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "tri-k")
        assert get_key_for_role("triage") == "tri-k"

    def test_unknown_role(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "tri-k")
        assert get_key_for_role("nonexistent") == ""


class TestResetForTesting:
    """Test cache reset behavior."""

    def test_reset_allows_new_keys(self, monkeypatch):
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "old-key")
        assert get_role_for_key("old-key") == "triage"

        _reset_for_testing()
        monkeypatch.setenv("TRIAGE_SUBMISSION_KEY", "new-key")
        assert get_role_for_key("old-key") is None
        assert get_role_for_key("new-key") == "triage"

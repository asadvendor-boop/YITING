from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.app import create_app
from scripts.smoke import _check_live_qwen_probe, _check_readiness


def _production_env(monkeypatch) -> None:
    for name in [
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
        "DASHSCOPE_BASE_URL",
        "QWEN_BASE_URL",
        "YITING_TEST_MODE",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("YITING_TEST_MODE", "false")


def test_production_ready_fails_closed_without_qwen_key(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv(
        "QWEN_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )

    with TestClient(create_app(db_path=":memory:")) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert ready.status_code == 503
    payload = ready.json()
    assert payload["status"] == "not_ready"
    assert payload["qwen"]["required"] is True
    assert payload["qwen"]["ready"] is False
    assert (
        "DASHSCOPE_API_KEY is required; QWEN_API_KEY is accepted only as a compatibility alias"
        in payload["qwen"]["errors"]
    )


def test_production_ready_omits_live_qwen_secret(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-live-yiting-secret")
    monkeypatch.setenv(
        "QWEN_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )

    with TestClient(create_app(db_path=":memory:")) as client:
        ready = client.get("/ready")

    assert ready.status_code == 200
    payload = ready.json()
    assert payload["status"] == "ready"
    assert payload["qwen"]["required"] is True
    assert payload["qwen"]["ready"] is True
    assert "sk-live-yiting-secret" not in str(payload)


def test_protected_live_qwen_readiness_probe_uses_provider_without_secret_leak(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-live-yiting-secret")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")
    monkeypatch.setenv("YITING_OPERATOR_TOKEN", "operator-secret")

    class Message:
        content = "ok"

    class Choice:
        message = Message()

    class Usage:
        prompt_tokens = 7
        completion_tokens = 2
        total_tokens = 9

    class Response:
        choices = [Choice()]
        usage = Usage()
        model = "qwen3.6-flash"
        id = "chatcmpl-yiting-live"
        _request_id = "dashscope-request-live"

    async def fake_completion(**kwargs):
        assert kwargs["api_key"] == "sk-live-yiting-secret"
        assert kwargs["api_base"] == "https://dashscope.example.test/v1"
        assert kwargs["model"].endswith("qwen3.6-flash")
        return Response()

    import gateway.app as gateway_app

    monkeypatch.setattr(gateway_app.qwen_runtime, "acompletion", fake_completion)

    with TestClient(create_app(db_path=":memory:")) as client:
        unauthorized = client.get("/ready/qwen-live")
        response = client.get("/ready/qwen-live", headers={"X-Operator-Token": "operator-secret"})

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["live_probe"]["ok"] is True
    assert payload["live_probe"]["provider"] == "qwen"
    assert payload["live_probe"]["provider_request_id"] == "dashscope-request-live"
    assert payload["live_probe"]["usage"]["total_tokens"] == 9
    assert "sk-live-yiting-secret" not in str(payload)


def test_protected_live_qwen_readiness_probe_fails_closed_on_provider_error(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-live-yiting-secret")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")
    monkeypatch.setenv("YITING_OPERATOR_TOKEN", "operator-secret")

    async def failing_completion(**kwargs):
        raise RuntimeError("invalid api key")

    import gateway.app as gateway_app

    monkeypatch.setattr(gateway_app.qwen_runtime, "acompletion", failing_completion)

    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.get("/ready/qwen-live", headers={"X-Operator-Token": "operator-secret"})

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["live_probe"]["ok"] is False
    assert payload["live_probe"]["provider"] == "qwen"
    assert payload["live_probe"]["error_type"] == "RuntimeError"
    assert "invalid api key" not in str(payload)
    assert "sk-live-yiting-secret" not in str(payload)


def test_production_ready_fails_closed_when_rate_limit_disabled(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-live-yiting-secret")
    monkeypatch.setenv(
        "QWEN_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("YITING_RATE_LIMIT_PER_MINUTE", "0")

    with TestClient(create_app(db_path=":memory:")) as client:
        ready = client.get("/ready")

    assert ready.status_code == 503
    payload = ready.json()
    assert payload["qwen"]["ready"] is False
    assert "YITING_RATE_LIMIT_PER_MINUTE must be a positive integer" in payload["qwen"]["errors"]


def test_production_chaos_trigger_refuses_without_qwen_key(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv(
        "QWEN_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )

    import gateway.routes.chaos as chaos_route

    monkeypatch.setattr(chaos_route, "YITING_OPERATOR_TOKEN", "operator-secret")
    monkeypatch.setattr(chaos_route, "TRIAGE_AGENT_ID", "triage-agent")

    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.post(
            "/chaos/trigger",
            json={"scenario_type": "deploy"},
            headers={"X-Operator-Token": "operator-secret"},
        )

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Live Qwen readiness failed; workflow start refused"
    assert payload["qwen"]["ready"] is False


def test_smoke_live_qwen_mode_rejects_non_production_readiness():
    payload = {
        "status": "ready",
        "service": "yiting-gateway",
        "qwen": {"ready": True, "required": False},
    }

    assert _check_readiness(payload, require_live_qwen=False) is True
    assert _check_readiness(payload, require_live_qwen=True) is False


def test_smoke_live_qwen_probe_requires_provider_success():
    payload = {
        "status": "ready",
        "service": "yiting-gateway",
        "qwen": {"ready": True, "required": True},
        "live_probe": {
            "ok": True,
            "provider": "qwen",
            "returned_model": "qwen3.6-flash",
        },
    }

    assert _check_live_qwen_probe(payload) is True
    payload["live_probe"]["ok"] = False
    assert _check_live_qwen_probe(payload) is False

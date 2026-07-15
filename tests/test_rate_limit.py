from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.app import create_app


def test_gateway_rate_limits_by_source_ip_but_exempts_health(monkeypatch):
    monkeypatch.setenv("YITING_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("YITING_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.delenv("YITING_TRUST_PROXY_HEADERS", raising=False)

    with TestClient(create_app(db_path=":memory:")) as client:
        assert client.get("/incidents").status_code == 200
        assert client.get("/incidents").status_code == 200
        limited = client.get("/incidents")
        assert limited.status_code == 429
        assert limited.json()["error"] == "Rate limit exceeded"
        assert limited.headers["Retry-After"] == "60"

        assert client.get("/health").status_code == 200


def test_gateway_rate_limits_by_authenticated_identity(monkeypatch):
    monkeypatch.setenv("YITING_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("YITING_RATE_LIMIT_WINDOW_SECONDS", "60")

    with TestClient(create_app(db_path=":memory:")) as client:
        assert client.get("/incidents", headers={"X-Agent-Key": "agent-a"}).status_code == 200
        assert client.get("/incidents", headers={"X-Agent-Key": "agent-a"}).status_code == 429
        assert client.get("/incidents", headers={"X-Agent-Key": "agent-b"}).status_code == 200

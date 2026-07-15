"""Tests for the real read-only MCP server at POST /mcp (gateway/mcp.py)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.mcp import MCP_PROTOCOL_VERSION, router
from shared.skill_registry import skill_manifest, skill_roles


def _rpc(client: TestClient, method: str, params: dict | None = None, msg_id: int = 1):
    body: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body)


def _tool_text(response) -> dict:
    payload = response.json()
    assert "error" not in payload
    content = payload["result"]["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_mcp_initialize_handshake_identifies_a_real_mcp_server():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "initialize")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "yiting-agent-skills"
    assert "tools" in result["capabilities"]
    assert "Read-only" in result["instructions"]


def test_mcp_initialized_notification_is_accepted_without_body():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

    assert response.status_code == 202
    assert response.content == b""


def test_mcp_tools_list_exposes_exactly_three_readonly_tools():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "tools/list")

    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "list_agent_skills",
        "get_agent_skill",
        "get_track3_benchmark",
    ]
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_list_agent_skills_serves_the_same_registry_as_the_manifest():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "tools/call", {"name": "list_agent_skills"})

    payload = _tool_text(response)
    assert response.json()["result"]["isError"] is False
    manifest = skill_manifest()
    assert payload["manifest_version"] == manifest["manifest_version"]
    assert payload["total_skills"] == 7
    assert payload["roles"] == skill_roles()
    assert payload["evidence_endpoints"]["mcp_server"] == "/mcp"


def test_mcp_get_agent_skill_returns_the_full_contract():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(
            client, "tools/call", {"name": "get_agent_skill", "arguments": {"role": "safety_reviewer"}}
        )

    skill = _tool_text(response)
    assert response.json()["result"]["isError"] is False
    assert skill["role"] == "safety_reviewer"
    assert skill["tool_name"].startswith("yiting.safety_reviewer.")
    assert skill["input_schema"]["type"] == "object"
    assert skill["output_schema"]
    assert skill["prompt_contract"]
    assert skill["deterministic_guardrail"]
    assert skill["evidence_artifact"]


def test_mcp_get_agent_skill_unknown_role_is_a_tool_error_not_a_crash():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(
            client, "tools/call", {"name": "get_agent_skill", "arguments": {"role": "root"}}
        )

    assert response.json()["result"]["isError"] is True
    payload = _tool_text(response)
    assert payload["valid_roles"] == skill_roles()


def test_mcp_get_track3_benchmark_reads_the_committed_artifact():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "tools/call", {"name": "get_track3_benchmark"})

    payload = _tool_text(response)
    assert response.json()["result"]["isError"] is False
    assert payload["project"]
    assert payload["scenario_count"]
    assert "comparison" in payload


def test_mcp_unknown_tool_returns_invalid_params_error():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "tools/call", {"name": "delete_incident"})

    error = response.json()["error"]
    assert error["code"] == -32602


def test_mcp_unknown_method_returns_method_not_found():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = _rpc(client, "resources/list")

    error = response.json()["error"]
    assert error["code"] == -32601


def test_mcp_rejects_non_object_payloads():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.post("/mcp", json=[1, 2, 3])

    assert response.json()["error"]["code"] == -32600


def test_mcp_rejects_invalid_json_bodies():
    with TestClient(create_app(db_path=":memory:")) as client:
        response = client.post(
            "/mcp", content=b"not json", headers={"content-type": "application/json"}
        )

    assert response.json()["error"]["code"] == -32700


def test_mcp_surface_is_a_single_post_route_and_read_only():
    routes = list(router.routes)
    assert len(routes) == 1
    assert routes[0].path == "/mcp"
    assert routes[0].methods == {"POST"}
    # Tool names must never advertise mutation.
    from gateway.mcp import _tool_definitions

    for tool in _tool_definitions():
        for verb in ("create", "delete", "approve", "execute", "update", "write"):
            assert verb not in tool["name"]

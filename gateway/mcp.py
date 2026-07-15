"""YITING MCP server — a real, read-only Model Context Protocol endpoint.

`/agent-skills` remains the inspectable review manifest. This module serves the
same seven custom agent-skill contracts — plus the committed Track 3 paired
benchmark artifact — over genuine MCP JSON-RPC 2.0 (streamable HTTP, single
POST /mcp endpoint): `initialize`, `tools/list`, and `tools/call`.

Read-only by design: no tool can create, mutate, approve, or execute anything,
and the incident pipeline never imports this module. Removing it changes no
runtime behavior, which keeps the frozen benchmark and evidence chain intact
while giving MCP clients (and judges) a real network MCP integration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from shared.skill_registry import list_agent_skills, skill_manifest, skill_roles

MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "yiting-agent-skills", "version": "1.0.0"}
SERVER_INSTRUCTIONS = (
    "Read-only registry of YITING's seven custom agent-skill contracts and the "
    "committed Track 3 paired benchmark. No tool mutates incidents, approvals, "
    "or evidence."
)

_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1] / "artifacts" / "track3-paired-benchmark.json"
)

router = APIRouter()


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_agent_skills",
            "description": (
                "List all seven YITING custom agent-skill contracts — the same "
                "registry served at GET /agent-skills: tool names, input/output "
                "schemas, Qwen prompt contracts, deterministic guardrails, and "
                "evidence artifacts."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_agent_skill",
            "description": (
                "Fetch one role's full skill contract: input/output schema, Qwen "
                "prompt contract, deterministic guardrail, evidence artifact, "
                "Track 3 requirement, and judge demo cue."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": skill_roles(),
                        "description": "Agent role key, e.g. 'safety_reviewer'.",
                    }
                },
                "required": ["role"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_track3_benchmark",
            "description": (
                "Read the committed paired society-vs-single-agent benchmark "
                "artifact (artifacts/track3-paired-benchmark.json). Read-only; "
                "never triggers model calls."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


def _call_tool(name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
    """Execute a read-only tool. Returns (payload, is_error)."""
    if name == "list_agent_skills":
        return skill_manifest(), False
    if name == "get_agent_skill":
        role = arguments.get("role")
        for skill in list_agent_skills():
            if skill["role"] == role:
                return skill, False
        return (
            {
                "error": f"Unknown role: {role!r}",
                "valid_roles": skill_roles(),
            },
            True,
        )
    if name == "get_track3_benchmark":
        try:
            return json.loads(_BENCHMARK_PATH.read_text(encoding="utf-8")), False
        except FileNotFoundError:
            return (
                {"error": "Benchmark artifact not present in this deployment."},
                True,
            )
    raise KeyError(name)


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
    )


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    """Public read-only MCP endpoint (JSON-RPC 2.0 over streamable HTTP)."""
    try:
        message = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error: body is not valid JSON")

    if not isinstance(message, dict):
        return _jsonrpc_error(None, -32600, "Invalid request: expected a JSON object")

    method = message.get("method")
    if not isinstance(method, str) or message.get("jsonrpc") != "2.0":
        return _jsonrpc_error(
            message.get("id"), -32600, "Invalid request: missing jsonrpc/method"
        )

    if "id" not in message:
        # Notification (e.g. notifications/initialized): accept, no body.
        return Response(status_code=202)

    msg_id = message["id"]

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": SERVER_INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_definitions()}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        known = {tool["name"] for tool in _tool_definitions()}
        if name not in known:
            return _jsonrpc_error(msg_id, -32602, f"Unknown tool: {name!r}")
        payload, is_error = _call_tool(name, arguments)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2, sort_keys=True, default=str),
                }
            ],
            "isError": is_error,
        }
    else:
        return _jsonrpc_error(msg_id, -32601, f"Method not found: {method}")

    return {"jsonrpc": "2.0", "id": msg_id, "result": result}

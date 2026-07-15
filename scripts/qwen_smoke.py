#!/usr/bin/env python3
"""Live Qwen smoke check for Alibaba Cloud Model Studio credentials.

This script intentionally performs small paid API calls. It is not run by the
offline test suite. Use it on Alibaba Cloud ECS after filling `.env`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from shared.qwen_reasoning import acompletion, normalize_litellm_model, qwen_reasoning_enabled
from shared.config import MODELS, get_qwen_api_key, get_qwen_base_url, qwen_readiness_status


def _extract_text(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _response_id(response: Any) -> str | None:
    value = getattr(response, "id", None) or getattr(response, "_response_id", None)
    return str(value) if value else None


def _provider_request_id(response: Any) -> str | None:
    value = (
        getattr(response, "_request_id", None)
        or getattr(response, "request_id", None)
        or getattr(response, "x_request_id", None)
    )
    return str(value) if value else None


def validate_live_smoke_configuration() -> None:
    """Fail closed before any billable call when the live proof config is unsafe."""
    status = qwen_readiness_status()
    checks = status.get("checks", {})
    errors: list[str] = []
    if not checks.get("api_key_present"):
        errors.append("DASHSCOPE_API_KEY is required; QWEN_API_KEY is accepted only as a compatibility alias")
    if checks.get("api_key_placeholder"):
        errors.append("Qwen API key looks like a placeholder")
    if not checks.get("base_url_explicit"):
        errors.append("QWEN_BASE_URL must be set explicitly; DASHSCOPE_BASE_URL is accepted only as a compatibility alias")
    if not checks.get("base_url_https"):
        errors.append("Qwen base URL must be an absolute https:// URL")
    if not checks.get("models_configured"):
        errors.append("all configured generation models must be Qwen models")
    if not checks.get("rate_limits_positive"):
        errors.append("YITING rate-limit settings must be positive integers")
    if errors:
        raise RuntimeError("; ".join(errors))


async def _smoke_role(role: str, *, require_structured_output: bool) -> dict[str, Any]:
    config = MODELS[role]
    model = normalize_litellm_model(config.model)
    if acompletion is None:
        raise RuntimeError("LiteLLM is not installed; cannot run live Qwen smoke")
    if require_structured_output:
        messages = [
            {
                "role": "system",
                "content": (
                    "Return exactly one compact JSON object with keys ok, provider, "
                    "project, and role. Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return this JSON shape with the same values: "
                    f'{{"ok": true, "provider": "qwen", "project": "YITING", "role": "{role}"}}'
                ),
            },
        ]
        response_kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}}
    else:
        messages = [
            {"role": "system", "content": "Answer in one short sentence."},
            {"role": "user", "content": "Say YITING can reach Qwen Cloud."},
        ]
        response_kwargs = {}
    started = time.perf_counter()
    response = await acompletion(
        model=model,
        api_key=get_qwen_api_key(),
        api_base=get_qwen_base_url(),
        messages=messages,
        temperature=0.1,
        max_tokens=min(160, config.max_tokens or 160),
        extra_body={"enable_thinking": False},
        **response_kwargs,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    text = _extract_text(response)
    payload = _parse_json(text) or {}
    returned_model = str(getattr(response, "model", "") or model)
    structured_ok = bool(payload) if require_structured_output else True
    semantic_ok = bool(text.strip()) if not require_structured_output else (
        payload.get("ok") is True
        or payload.get("reachable") is True
        or payload.get("provider") == "qwen"
        or str(payload.get("status", "")).lower() in {"ok", "success", "ready"}
    )
    provider = payload.get("provider") or ("qwen" if returned_model.startswith("qwen") else None)
    return {
        "ok": structured_ok and semantic_ok and provider == "qwen",
        "role": role,
        "provider": provider,
        "message": str(payload.get("message") or payload.get("target") or payload.get("status") or "")[:240],
        "requested_model": model,
        "returned_model": returned_model,
        "response_id": _response_id(response),
        "provider_request_id": _provider_request_id(response),
        "latency_ms": latency_ms,
        "usage": _usage_dict(response),
        "capabilities": {
            "chat": "required",
            "structured_output": "required" if require_structured_output else "not_assumed",
            "tools": "not_used",
        },
    }


async def run_capability_checks() -> dict[str, dict[str, Any]]:
    return {
        "operator": await _smoke_role("operator", require_structured_output=True),
        "commander": await _smoke_role("commander", require_structured_output=True),
    }


def build_report(result: dict | None = None, *, checks: dict[str, dict[str, Any]] | None = None) -> dict:
    """Return a sanitized Qwen Cloud proof artifact."""
    if checks is None:
        previous_result = result or {}
        checks = {
            "commander": {
                "ok": previous_result.get("ok") is True,
                "role": "commander",
                "provider": previous_result.get("provider"),
                "message": str(previous_result.get("message", ""))[:240],
                "requested_model": normalize_litellm_model(MODELS["commander"].model),
                "returned_model": normalize_litellm_model(MODELS["commander"].model),
                "response_id": None,
                "provider_request_id": None,
                "latency_ms": 0,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "capabilities": {
                    "chat": "required",
                    "structured_output": "required",
                    "tools": "not_used",
                },
            }
        }
    first = next(iter(checks.values()))
    return {
        "project": "YITING",
        "proof_type": "qwen-cloud-smoke",
        "artifact_class": "live_qwen_smoke",
        "submission_evidence": True,
        "verified_live": True,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(item.get("ok") is True for item in checks.values()),
        "provider": "qwen",
        "base_url": get_qwen_base_url(),
        "model": first["requested_model"],
        "capability_matrix": {
            item["requested_model"]: item["capabilities"]
            for item in checks.values()
        },
        "checks": checks,
        "response": {
            "ok": first.get("ok") is True,
            "provider": first.get("provider"),
            "message": str(first.get("message", ""))[:240],
            "response_id": first.get("response_id"),
            "provider_request_id": first.get("provider_request_id"),
            "usage": first.get("usage", {}),
        },
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a live Qwen Cloud smoke check")
    parser.add_argument("--output-json", type=Path, default=None, help="write sanitized Qwen proof artifact")
    args = parser.parse_args(argv)

    load_dotenv()
    if os.getenv("YITING_TEST_MODE", "").lower() in {"1", "true", "yes"}:
        print("YITING_TEST_MODE is enabled; live Qwen smoke is intentionally disabled.")
        return 2
    try:
        validate_live_smoke_configuration()
    except RuntimeError as exc:
        print(f"Live Qwen smoke configuration is not ready: {exc}", file=sys.stderr)
        return 1
    if not qwen_reasoning_enabled():
        print("Live Qwen reasoning is disabled; remove YITING_DISABLE_QWEN_REASONING before smoke testing.", file=sys.stderr)
        return 1

    checks = await run_capability_checks()
    report = build_report(checks=checks)
    if not report["passed"]:
        print(f"Qwen smoke failed: {checks!r}", file=sys.stderr)
        return 1

    if args.output_json:
        write_report(args.output_json, report)

    print("Qwen smoke passed")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

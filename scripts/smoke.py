#!/usr/bin/env python3
"""Smoke check for a deployed YITING URL.

The default checks are read-only. ``--require-live-qwen`` also calls the
operator-protected live-Qwen readiness probe, which performs one small paid
provider request and proves invalid credentials fail closed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only YITING HTTP smoke checks.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("YITING_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000",
        help="Public YITING base URL, or local gateway URL.",
    )
    parser.add_argument("--require-https", action="store_true", help="Require an HTTPS public URL.")
    parser.add_argument(
        "--require-live-qwen",
        action="store_true",
        help="Require config readiness plus a protected live Qwen probe.",
    )
    parser.add_argument(
        "--live-qwen-token",
        default=os.getenv("YITING_OPERATOR_TOKEN", ""),
        help="Operator token for /ready/qwen-live when --require-live-qwen is set.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output-json", type=Path, help="Write a sanitized smoke report.")
    return parser.parse_args(argv)


def _require_base_url(value: str, *, require_https: bool) -> str:
    base_url = value.rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    if require_https and parsed.scheme != "https":
        raise ValueError("--require-https needs an https:// base URL")
    return base_url


def _check_health(payload: dict[str, Any]) -> bool:
    return payload.get("status") == "ok" and payload.get("service") == "yiting-gateway"


def _check_readiness(payload: dict[str, Any], *, require_live_qwen: bool) -> bool:
    if payload.get("status") != "ready" or payload.get("service") != "yiting-gateway":
        return False
    qwen = payload.get("qwen")
    if not isinstance(qwen, dict) or qwen.get("ready") is not True:
        return False
    if require_live_qwen and qwen.get("required") is not True:
        return False
    return True


def _check_live_qwen_probe(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "ready" or payload.get("service") != "yiting-gateway":
        return False
    qwen = payload.get("qwen")
    live_probe = payload.get("live_probe")
    return (
        isinstance(qwen, dict)
        and qwen.get("ready") is True
        and qwen.get("required") is True
        and isinstance(live_probe, dict)
        and live_probe.get("ok") is True
        and live_probe.get("provider") == "qwen"
    )


def run(
    base_url: str,
    timeout: float,
    *,
    require_live_qwen: bool = False,
    live_qwen_token: str = "",
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=True) as client:
        health = client.get("/health")
        checks["health"] = {
            "ok": health.status_code == 200 and _check_health(health.json()),
            "status_code": health.status_code,
        }

        ready = client.get("/ready")
        ready_payload = ready.json()
        qwen = ready_payload.get("qwen") if isinstance(ready_payload, dict) else None
        checks["readiness"] = {
            "ok": ready.status_code == 200
            and isinstance(ready_payload, dict)
            and _check_readiness(ready_payload, require_live_qwen=require_live_qwen),
            "status_code": ready.status_code,
            "qwen_required": qwen.get("required") if isinstance(qwen, dict) else None,
            "qwen_ready": qwen.get("ready") if isinstance(qwen, dict) else None,
        }

        if require_live_qwen:
            headers = {"X-Operator-Token": live_qwen_token} if live_qwen_token else {}
            live = client.get("/ready/qwen-live", headers=headers)
            live_payload = live.json()
            live_probe = live_payload.get("live_probe") if isinstance(live_payload, dict) else None
            checks["live_qwen_probe"] = {
                "ok": live.status_code == 200
                and isinstance(live_payload, dict)
                and _check_live_qwen_probe(live_payload),
                "status_code": live.status_code,
                "provider": live_probe.get("provider") if isinstance(live_probe, dict) else None,
                "returned_model": live_probe.get("returned_model") if isinstance(live_probe, dict) else None,
                "provider_request_id": live_probe.get("provider_request_id") if isinstance(live_probe, dict) else None,
                "usage": live_probe.get("usage") if isinstance(live_probe, dict) else None,
            }

        skills = client.get("/agent-skills")
        skill_payload = skills.json()
        skill_items = (
            skill_payload
            if isinstance(skill_payload, list)
            else skill_payload.get("skills", [])
            if isinstance(skill_payload, dict)
            else []
        )
        checks["agent_skills"] = {
            "ok": skills.status_code == 200 and isinstance(skill_items, list) and len(skill_items) >= 5,
            "status_code": skills.status_code,
            "count": len(skill_items) if isinstance(skill_items, list) else 0,
        }

        stats = client.get("/stats")
        stats_payload = stats.json()
        checks["stats"] = {
            "ok": stats.status_code == 200 and isinstance(stats_payload, dict),
            "status_code": stats.status_code,
            "keys": sorted(stats_payload)[:12] if isinstance(stats_payload, dict) else [],
        }

        runsummary = client.get("/stats/runsummary")
        checks["runsummary"] = {
            "ok": runsummary.status_code == 200 and isinstance(runsummary.json(), dict),
            "status_code": runsummary.status_code,
        }

    return {
        "format": "yiting-http-smoke-v1",
        "project": "YITING",
        "base_url": base_url,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(item["ok"] for item in checks.values()),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base_url = _require_base_url(args.base_url, require_https=args.require_https)
        report = run(
            base_url,
            args.timeout,
            require_live_qwen=args.require_live_qwen,
            live_qwen_token=args.live_qwen_token,
        )
    except (ValueError, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"YITING smoke failed: {exc}", file=sys.stderr)
        return 1

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "base_url": report["base_url"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

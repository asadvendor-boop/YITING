#!/usr/bin/env python3
"""Reset YITING's controlled demo environment."""
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
    parser = argparse.ArgumentParser(description="Reset YITING victim telemetry and synthetic demo rows.")
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("GATEWAY_URL") or os.getenv("YITING_GATEWAY_URL") or "http://127.0.0.1:8000",
        help="Private YITING gateway URL, or public dashboard URL when --via-dashboard is used.",
    )
    parser.add_argument(
        "--via-dashboard",
        action="store_true",
        help="Call /dashboard/api/chaos/activate on a private recording deployment instead of /chaos/reset.",
    )
    parser.add_argument(
        "--operator-token-env",
        default="YITING_OPERATOR_TOKEN",
        help="Environment variable containing the private operator token.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--yes", action="store_true", help="Confirm the reset operation.")
    parser.add_argument("--output-json", type=Path, help="Write a sanitized reset report.")
    return parser.parse_args(argv)


def _require_url(value: str) -> str:
    url = value.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--gateway-url must be an absolute HTTP(S) URL")
    return url


def _operator_token(env_name: str) -> str:
    token = os.getenv(env_name, "").strip()
    if not token:
        raise ValueError(f"Set {env_name} to the private YITING operator token")
    return token


def run(gateway_url: str, token: str, timeout: float, *, via_dashboard: bool) -> dict[str, Any]:
    headers = {"X-Operator-Token": token}
    with httpx.Client(base_url=gateway_url, timeout=timeout, follow_redirects=False) as client:
        if via_dashboard:
            response = client.post(
                "/dashboard/api/chaos/activate",
                headers={**headers, "Content-Type": "application/json"},
                json={"scenario_type": "reset"},
            )
        else:
            response = client.post("/chaos/reset", headers=headers)
        response.raise_for_status()
        payload = response.json()
    return {
        "format": "yiting-demo-reset-v1",
        "project": "YITING",
        "gateway_url": gateway_url,
        "via_dashboard": via_dashboard,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": payload.get("success") is True and payload.get("status") == "reset",
        "result": payload,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.yes:
        print("Refusing to reset without --yes.", file=sys.stderr)
        return 2
    try:
        report = run(
            _require_url(args.gateway_url),
            _operator_token(args.operator_token_env),
            args.timeout,
            via_dashboard=args.via_dashboard,
        )
    except (ValueError, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"YITING reset failed: {exc}", file=sys.stderr)
        return 1

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "gateway_url": report["gateway_url"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

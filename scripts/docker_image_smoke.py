#!/usr/bin/env python3
"""Run local Docker image smoke checks for YITING preflight images."""
from __future__ import annotations

import argparse
import http.client
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test YITING Docker images locally.")
    parser.add_argument("--python-image", default="yiting-python:preflight")
    parser.add_argument("--dashboard-image", default="yiting-dashboard:preflight")
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output-json", type=Path, default=Path("artifacts/docker-image-smoke.json"))
    return parser.parse_args(argv)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def docker(docker_bin: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [docker_bin, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args)} failed with exit {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def http_get(url: str, *, timeout: float, accept_json: bool = True) -> tuple[int, dict[str, Any] | None, str]:
    headers = {"Accept": "application/json"} if accept_json else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            payload = json.loads(body) if accept_json else None
            return response.status, payload, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        payload: dict[str, Any] | None = None
        if accept_json:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        return exc.code, payload, body


def wait_for_http(
    url: str,
    *,
    timeout: float,
    accept_json: bool = True,
) -> tuple[int, dict[str, Any] | None, str]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return http_get(url, timeout=2.0, accept_json=accept_json)
        except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected, ConnectionResetError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def remove_container(docker_bin: str, name: str) -> None:
    docker(docker_bin, ["rm", "-f", name], check=False)


def run_detached(
    docker_bin: str,
    *,
    name: str,
    image: str,
    host_port: int,
    container_port: int,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    args = ["run", "--rm", "--name", name]
    for key, value in (env or {}).items():
        args.extend(["-e", f"{key}={value}"])
    args.extend(["-p", f"127.0.0.1:{host_port}:{container_port}", "-d", image])
    args.extend(command or [])
    docker(docker_bin, args)


def smoke_gateway(docker_bin: str, image: str, prefix: str, timeout: float) -> dict[str, Any]:
    name = f"{prefix}-gateway"
    port = free_port()
    run_detached(docker_bin, name=name, image=image, host_port=port, container_port=8000, command=["gateway"])
    try:
        health_status, health_payload, _ = wait_for_http(f"http://127.0.0.1:{port}/health", timeout=timeout)
        ready_status, ready_payload, _ = wait_for_http(f"http://127.0.0.1:{port}/ready", timeout=timeout)
        qwen = ready_payload.get("qwen") if isinstance(ready_payload, dict) else None
        return {
            "ok": (
                health_status == 200
                and ready_status == 200
                and isinstance(health_payload, dict)
                and health_payload.get("service") == "yiting-gateway"
                and isinstance(qwen, dict)
                and qwen.get("provider") == "qwen"
                and qwen.get("required") is False
            ),
            "container": name,
            "image": image,
            "health_status": health_status,
            "ready_status": ready_status,
            "qwen_required": qwen.get("required") if isinstance(qwen, dict) else None,
        }
    finally:
        remove_container(docker_bin, name)


def smoke_victim(docker_bin: str, image: str, prefix: str, timeout: float) -> dict[str, Any]:
    name = f"{prefix}-victim"
    port = free_port()
    run_detached(docker_bin, name=name, image=image, host_port=port, container_port=9000, command=["victim"])
    try:
        status, payload, _ = wait_for_http(f"http://127.0.0.1:{port}/healthz", timeout=timeout)
        return {
            "ok": status == 200 and isinstance(payload, dict) and payload.get("status") == "ok",
            "container": name,
            "image": image,
            "status_code": status,
            "source": payload.get("source") if isinstance(payload, dict) else None,
        }
    finally:
        remove_container(docker_bin, name)


def smoke_dashboard(docker_bin: str, image: str, prefix: str, timeout: float) -> dict[str, Any]:
    name = f"{prefix}-dashboard"
    port = free_port()
    run_detached(docker_bin, name=name, image=image, host_port=port, container_port=3000)
    try:
        status, _, body = wait_for_http(
            f"http://127.0.0.1:{port}/dashboard",
            timeout=timeout,
            accept_json=False,
        )
        return {
            "ok": status == 200 and "YITING" in body and "/dashboard/_next/" in body,
            "container": name,
            "image": image,
            "status_code": status,
            "base_path": "/dashboard",
        }
    finally:
        remove_container(docker_bin, name)


def smoke_production_negative(docker_bin: str, image: str, prefix: str, timeout: float) -> dict[str, Any]:
    name = f"{prefix}-prod-negative"
    port = free_port()
    run_detached(
        docker_bin,
        name=name,
        image=image,
        host_port=port,
        container_port=8000,
        command=["gateway"],
        env={"APP_ENV": "production"},
    )
    try:
        status, payload, _ = wait_for_http(f"http://127.0.0.1:{port}/ready", timeout=timeout)
        qwen = payload.get("qwen") if isinstance(payload, dict) else None
        errors = qwen.get("errors") if isinstance(qwen, dict) else []
        return {
            "ok": (
                status == 503
                and isinstance(qwen, dict)
                and qwen.get("required") is True
                and qwen.get("ready") is False
                and any("DASHSCOPE_API_KEY" in error for error in errors)
                and any("QWEN_BASE_URL" in error for error in errors)
            ),
            "container": name,
            "image": image,
            "status_code": status,
            "qwen_required": qwen.get("required") if isinstance(qwen, dict) else None,
            "qwen_ready": qwen.get("ready") if isinstance(qwen, dict) else None,
            "errors": errors,
        }
    finally:
        remove_container(docker_bin, name)


def run(args: argparse.Namespace) -> dict[str, Any]:
    prefix = f"yiting-image-smoke-{int(time.time())}-{id(args) % 10000}"
    checks = {
        "gateway": smoke_gateway(args.docker_bin, args.python_image, prefix, args.timeout),
        "victim": smoke_victim(args.docker_bin, args.python_image, prefix, args.timeout),
        "dashboard": smoke_dashboard(args.docker_bin, args.dashboard_image, prefix, args.timeout),
        "production_negative": smoke_production_negative(args.docker_bin, args.python_image, prefix, args.timeout),
    }
    return {
        "format": "yiting-docker-image-smoke-v1",
        "project": "YITING",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(item["ok"] for item in checks.values()),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:
        print(f"YITING Docker image smoke failed: {exc}", file=sys.stderr)
        return 1

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "output": str(args.output_json)}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

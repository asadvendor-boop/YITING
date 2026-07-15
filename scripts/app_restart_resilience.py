#!/usr/bin/env python3
"""Create the live app-restart resilience proof used by ECS ops acceptance."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017

sys.dont_write_bytecode = True

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_OUTPUT = Path("artifacts/live/app-restart-resilience.json")
APP_NAMES = ("yiting", "cotenant")
PROOF_FIELDS = ("state", "evidence", "logs")


def validate_public_https_url(url: str, field_name: str) -> list[str]:
    errors: list[str] = []
    value = url.strip()
    if not value:
        return [f"{field_name} is required"]
    if not value.startswith("https://"):
        errors.append(f"{field_name} must use https")
    if "localhost" in value or "127.0.0.1" in value or value.startswith("https://0.0.0.0"):
        errors.append(f"{field_name} must be public, not localhost")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write artifacts/live/app-restart-resilience.json.")
    parser.add_argument("--yiting-url", required=True, help="Final public HTTPS URL for the Track 3 app.")
    parser.add_argument("--cotenant-url", required=True, help="Final public HTTPS URL for the Track 4 app.")
    for app in APP_NAMES:
        for field in PROOF_FIELDS:
            parser.add_argument(
                f"--{app}-{field}-path",
                type=Path,
                required=True,
                help=f"Non-empty host path proving {app} {field} persisted after app-scoped restart.",
            )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def path_summary(path: Path) -> dict[str, Any]:
    exists = path.exists()
    kind = "missing"
    size_bytes = 0
    entry_count = 0
    if exists and path.is_dir():
        kind = "directory"
        entries = list(path.iterdir())
        entry_count = len(entries)
        size_bytes = sum(item.stat().st_size for item in entries if item.is_file())
    elif exists and path.is_file():
        kind = "file"
        size_bytes = path.stat().st_size
    elif exists:
        kind = "other"
    non_empty = entry_count > 0 or size_bytes > 0
    return {
        "path": str(path),
        "kind": kind,
        "exists": exists,
        "non_empty": non_empty,
        "entry_count": entry_count,
        "size_bytes": size_bytes,
    }


def probe_url(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "YitingAppRestartProof/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        final_url = url
    except urllib.error.URLError as exc:
        return {"url": url, "passed": False, "error": str(exc.reason)}
    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "passed": 200 <= status_code < 400,
    }


def build_payload(
    *,
    yiting_url: str,
    cotenant_url: str,
    proof_paths: dict[str, dict[str, Path]],
    timeout: float = 10.0,
    url_probe: Callable[[str, float], dict[str, Any]] = probe_url,
) -> dict[str, Any]:
    errors: list[str] = []
    urls = {"yiting": yiting_url, "cotenant": cotenant_url}
    for app, url in urls.items():
        errors.extend(validate_public_https_url(url, f"{app}_url"))
    if errors:
        raise ValueError("\n".join(errors))

    apps: list[dict[str, Any]] = []
    for app in APP_NAMES:
        health_probe = url_probe(urls[app], timeout)
        path_proofs = {field: path_summary(proof_paths[app][field]) for field in PROOF_FIELDS}
        app_errors = []
        if health_probe.get("passed") is not True:
            app_errors.append(f"{app} HTTPS probe failed")
        for field, proof in path_proofs.items():
            if proof.get("exists") is not True or proof.get("non_empty") is not True:
                app_errors.append(f"{app} {field} proof path is missing or empty")
        if app_errors:
            errors.extend(app_errors)
        apps.append(
            {
                "app": app,
                "url": urls[app].strip(),
                "healthy_after_restart": health_probe.get("passed") is True,
                "state_persisted": path_proofs["state"]["exists"] and path_proofs["state"]["non_empty"],
                "evidence_persisted": path_proofs["evidence"]["exists"] and path_proofs["evidence"]["non_empty"],
                "logs_persisted": path_proofs["logs"]["exists"] and path_proofs["logs"]["non_empty"],
                "health_probe": health_probe,
                "proof_paths": path_proofs,
            }
        )
    if errors:
        raise ValueError("\n".join(errors))

    return {
        "format": "shared-ecs-app-restart-resilience-v1",
        "artifact_class": "live_app_restart_resilience",
        "submission_evidence": True,
        "verified_live": True,
        "generated_at": now_iso(),
        "restart_scope": "app-scoped Docker Compose service restart",
        "host_rebooted": False,
        "apps": apps,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        proof_paths = {
            app: {field: getattr(args, f"{app}_{field}_path") for field in PROOF_FIELDS}
            for app in APP_NAMES
        }
        payload = build_payload(
            yiting_url=args.yiting_url,
            cotenant_url=args.cotenant_url,
            proof_paths=proof_paths,
            timeout=args.timeout,
        )
        write_json(args.output, payload)
        print(json.dumps({"output": str(args.output), "apps": 2}, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

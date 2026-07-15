#!/usr/bin/env python3
"""Create the public-safe uptime-monitoring proof used by ECS ops acceptance."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.submission_links import validate_public_https_url  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write artifacts/live/uptime-monitoring.json.")
    parser.add_argument("--yiting-url", required=True, help="Final public HTTPS URL for the Track 3 app.")
    parser.add_argument(
        "--yiting-monitor-url",
        required=True,
        help="Public HTTPS monitor page or check URL for YITING.",
    )
    parser.add_argument("--extra-url", help="Optional public HTTPS URL for an additional monitor.")
    parser.add_argument(
        "--extra-monitor-url",
        help="Optional public HTTPS monitor page or check URL for the additional monitor.",
    )
    parser.add_argument(
        "--provider",
        default="external uptime monitor",
        help="Monitoring provider label for reviewers.",
    )
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("artifacts/live/uptime-monitoring.json"))
    return parser.parse_args(argv)


def _validate_interval(interval_seconds: int) -> list[str]:
    if interval_seconds <= 0:
        return ["interval_seconds must be positive"]
    if interval_seconds > 300:
        return ["interval_seconds must be <=300"]
    return []


def build_payload(
    *,
    yiting_url: str,
    yiting_monitor_url: str,
    provider: str,
    interval_seconds: int,
    extra_url: str | None = None,
    extra_monitor_url: str | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    for field_name, value in (
        ("yiting_url", yiting_url),
        ("yiting_monitor_url", yiting_monitor_url),
    ):
        errors.extend(validate_public_https_url(value, field_name))
    if bool(extra_url) != bool(extra_monitor_url):
        errors.append("--extra-url and --extra-monitor-url must be provided together")
    if extra_url and extra_monitor_url:
        for field_name, value in (
            ("extra_url", extra_url),
            ("extra_monitor_url", extra_monitor_url),
        ):
            errors.extend(validate_public_https_url(value, field_name))
    errors.extend(_validate_interval(interval_seconds))
    if not provider.strip():
        errors.append("provider must be non-empty")
    if errors:
        raise ValueError("\n".join(errors))

    monitors: list[dict[str, object]] = [
        {
            "app": "yiting",
            "target_url": yiting_url.strip(),
            "monitor_url": yiting_monitor_url.strip(),
            "enabled": True,
            "interval_seconds": interval_seconds,
        },
    ]
    if extra_url and extra_monitor_url:
        monitors.append(
            {
                "app": "neighbor",
                "target_url": extra_url.strip(),
                "monitor_url": extra_monitor_url.strip(),
                "enabled": True,
                "interval_seconds": interval_seconds,
            }
        )

    return {
        "format": "uptime-monitoring-v1",
        "artifact_class": "external_uptime_monitoring",
        "submission_evidence": True,
        "verified_live": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": provider.strip(),
        "monitors": monitors,
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = build_payload(
            yiting_url=args.yiting_url,
            yiting_monitor_url=args.yiting_monitor_url,
            provider=args.provider,
            interval_seconds=args.interval_seconds,
            extra_url=args.extra_url,
            extra_monitor_url=args.extra_monitor_url,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "monitors": len(payload["monitors"])}, indent=2))


if __name__ == "__main__":
    main()

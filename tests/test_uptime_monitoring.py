from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ecs_ops_acceptance, uptime_monitoring


def _valid_payload_kwargs() -> dict[str, object]:
    return {
        "yiting_url": "https://yiting-qwen-demo.dev",
        "yiting_monitor_url": "https://status.qwen-demo.dev/yiting",
        "provider": "Better Stack",
        "interval_seconds": 60,
    }


def test_build_payload_matches_ecs_ops_uptime_contract(tmp_path: Path) -> None:
    payload = uptime_monitoring.build_payload(**_valid_payload_kwargs())

    assert payload["format"] == "uptime-monitoring-v1"
    assert payload["artifact_class"] == "external_uptime_monitoring"
    assert payload["submission_evidence"] is True
    assert payload["verified_live"] is True
    assert [monitor["app"] for monitor in payload["monitors"]] == ["yiting"]

    artifact = tmp_path / "uptime-monitoring.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    assert ecs_ops_acceptance.check_uptime_monitor(artifact).ok is True


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"yiting_url": "https://example.com"}, "reserved or example hostname"),
        ({"yiting_monitor_url": "https://localhost/status"}, "must not use localhost"),
        ({"extra_url": "https://neighbor-qwen-demo.dev"}, "--extra-url and --extra-monitor-url"),
        ({"interval_seconds": 301}, "interval_seconds must be <=300"),
        ({"provider": "  "}, "provider must be non-empty"),
    ],
)
def test_build_payload_rejects_non_public_or_unsafe_values(override: dict[str, object], expected: str) -> None:
    kwargs = _valid_payload_kwargs()
    kwargs.update(override)

    with pytest.raises(ValueError, match=expected):
        uptime_monitoring.build_payload(**kwargs)


def test_main_writes_artifact_accepted_by_ecs_ops_checker(tmp_path: Path) -> None:
    output = tmp_path / "live" / "uptime-monitoring.json"

    uptime_monitoring.main(
        [
            "--yiting-url",
            "https://yiting-qwen-demo.dev",
            "--yiting-monitor-url",
            "https://status.qwen-demo.dev/yiting",
            "--provider",
            "Better Stack",
            "--interval-seconds",
            "120",
            "--output",
            str(output),
        ]
    )

    assert output.is_file()
    assert ecs_ops_acceptance.check_uptime_monitor(output).ok is True

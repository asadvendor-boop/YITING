from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gateway_chaos_routes_require_operator_token() -> None:
    source = (ROOT / "gateway" / "routes" / "chaos.py").read_text(encoding="utf-8")

    assert "YITING_OPERATOR_TOKEN" in source
    assert "hmac.compare_digest" in source
    assert "Valid operator token is required" in source
    assert "YITING_OPERATOR_TOKEN is not configured" in source
    assert "async def chaos_trigger(" in source
    assert "async def chaos_reset(" in source


def test_judge_flow_scripts_and_docs_are_present() -> None:
    smoke = (ROOT / "scripts" / "smoke.py").read_text(encoding="utf-8")
    reset = (ROOT / "scripts" / "reset_demo.py").read_text(encoding="utf-8")
    backup = (ROOT / "scripts" / "backup_restore_check.py").read_text(encoding="utf-8")
    judge = (ROOT / "docs" / "JUDGE_TESTING.md").read_text(encoding="utf-8")

    assert "/agent-skills" in smoke
    assert "/ready" in smoke
    assert "/ready/qwen-live" in smoke
    assert "--require-live-qwen" in smoke
    assert "--live-qwen-token" in smoke
    assert "/stats/runsummary" in smoke
    assert "X-Operator-Token" in reset
    assert "/dashboard/api/chaos/activate" in reset
    assert "PRAGMA integrity_check" in backup
    assert "yiting-backup-restore-v1" in backup
    assert "--live-submission-evidence" in backup
    assert "--via-dashboard" in judge
    assert "python scripts/smoke.py" in judge
    assert "python scripts/reset_demo.py" in judge
    assert "artifacts/live/backup-restore.json" in judge

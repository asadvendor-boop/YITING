from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app" / "_components" / "YitingApp.js"
CHAOS_ROUTE = ROOT / "dashboard" / "app" / "api" / "chaos" / "activate" / "route.js"


def test_chaos_route_is_server_side_gated():
    source = CHAOS_ROUTE.read_text(encoding="utf-8")

    assert 'process.env.YITING_LIVE_CHAOS !== "1"' in source
    assert "YITING_OPERATOR_TOKEN" in source
    assert "x-operator-token" in source
    assert 'status: 401' in source
    assert 'status: 503' in source
    assert 'status: 403' in source
    assert '"/chaos/trigger"' in source
    assert '"/chaos/reset"' in source


def test_judge_mode_overview_navigates_to_replay_instead_of_opening_chaos_modal():
    source = APP.read_text(encoding="utf-8")
    marker = '<PrimaryButton icon="replay" href={navHref("/runs", data.selectedId)}>View Judge Replay</PrimaryButton>'

    assert marker in source
    assert 'YITING_MODE === "judge" ? <PrimaryButton tone="secondary" icon="incident" href={navHref("/runs", data.selectedId)}>Inspect Suspicious Deploy</PrimaryButton>' in source
    assert '<PrimaryButton tone="secondary" icon="incident" onClick={() => setChaosOpen(true)}>Trigger Suspicious Deploy</PrimaryButton>' in source


def test_runs_page_surfaces_track3_scorecard():
    source = APP.read_text(encoding="utf-8")

    assert "Track 3 collaboration scorecard" in source
    assert "Role handoffs" in source
    assert "Disagreement events" in source
    assert "total_human_rejections" in source
    assert "Baseline speedup" in source
    assert "Execution conflict resolution" in source
    assert "MANUAL_BASELINE_SECS" in source
    assert "BASELINE_INCIDENT_FAMILY" in source
    assert "same-family YITING runs" in source
    assert "Incident family" in source
    assert "incident_family" in source

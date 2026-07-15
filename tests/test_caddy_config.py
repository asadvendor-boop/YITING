from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CADDYFILE = ROOT / "deploy" / "Caddyfile"


def _caddyfile() -> str:
    return CADDYFILE.read_text(encoding="utf-8")


def test_caddy_uses_env_backed_judge_credentials_for_approval_only():
    text = _caddyfile()

    assert "{$YITING_JUDGE_USER} {$YITING_JUDGE_HASH}" in text
    assert "JUDGE_USER HASHED_PASSWORD" not in text
    assert "APPROVAL_PROXY_SECRET" in text

    dashboard_block = text.split("handle /dashboard*", 1)[1].split("# ── Approval UI", 1)[0]
    approval_block = text.split("handle /approve/*", 1)[1].split("handle /stats", 1)[0]
    assert "basic_auth" not in dashboard_block
    assert "reverse_proxy 127.0.0.1:3000" in dashboard_block
    assert "basic_auth" in approval_block
    assert "header_up X-Proxy-Secret {$APPROVAL_PROXY_SECRET}" in approval_block


def test_caddy_exposes_only_read_only_suppression_route():
    text = _caddyfile()

    assert "handle /suppression-rules {" in text
    assert "handle /suppression-rules/*" not in text
    assert "/heartbeat" in text
    assert "/submit" in text


def test_caddy_public_routes_keep_gateway_write_paths_internal():
    text = _caddyfile()

    exposed_block = text.split("# NOTE: /heartbeat", 1)[0]
    assert "handle /heartbeat" not in exposed_block
    assert "handle /submit" not in exposed_block
    assert "handle /api/export/evidence" not in exposed_block

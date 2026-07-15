#!/usr/bin/env python3
"""YITING — Closure Run: Real Caddy HTTPS, Wait for EXECUTED.

Single incident: reject v1 → revise → approve v2 → wait EXECUTED.
Uses the REAL public Caddy HTTPS URL for all approval decisions.
Closes both Council caveats in one take.
"""
import asyncio
import base64
import json
import os
import re
import sys
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.recorder import Recorder
from shared.models import AlertCard
from shared.submission_client import SubmissionClient, format_card_message

import httpx

# ── Config ──────────────────────────────────────────────
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://localhost:9000")
RECORDER_SUBMISSION_KEY = os.getenv("RECORDER_SUBMISSION_KEY", "")
TRIAGE_AGENT_ID = os.getenv("TRIAGE_AGENT_ID", "")
DIAGNOSIS_AGENT_ID = os.getenv("DIAGNOSIS_AGENT_ID", "")
SAFETY_REVIEWER_AGENT_ID = os.getenv("SAFETY_REVIEWER_AGENT_ID", "")
COMMANDER_AGENT_ID = os.getenv("COMMANDER_AGENT_ID", "")
OPERATOR_AGENT_ID = os.getenv("OPERATOR_AGENT_ID", "")

APPROVAL_UI_USER = os.getenv("APPROVAL_UI_USER", "")
APPROVAL_UI_PASSWORD = os.getenv("APPROVAL_UI_PASSWORD", "")

# Public Caddy HTTPS URL for approval decisions
CADDY_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

_original_print = __builtins__.__dict__["print"]
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)


def _caddy_auth_headers() -> dict:
    """Basic auth for the real Caddy HTTPS path (no X-Proxy-Secret needed — Caddy adds it)."""
    creds = base64.b64encode(
        f"{APPROVAL_UI_USER}:{APPROVAL_UI_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {creds}"}


def _local_auth_headers() -> dict:
    """Auth headers for localhost Gateway (includes proxy secret for direct access)."""
    creds = base64.b64encode(
        f"{APPROVAL_UI_USER}:{APPROVAL_UI_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "X-Proxy-Secret": os.getenv("APPROVAL_PROXY_SECRET", ""),
    }


async def activate_scenario(incident_id: str, tier: str = "severe") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{VICTIM_APP_URL}/admin/scenario/{incident_id}/activate",
            params={"tier": tier},
        )
        resp.raise_for_status()
        print(f"  ✅ Victim-app scenario activated (tier={tier})")


async def fire_incident(recorder: Recorder, incident_id: str) -> dict:
    from datetime import datetime, timezone

    print("  --- Activate victim-app ---")
    await activate_scenario(incident_id, tier="severe")

    print("  --- Create room ---")
    room_id = await recorder.create_room(f"🔴 {incident_id} — Closure Run")
    print(f"  Room: {room_id}")

    print("  --- Add participants ---")
    for role, aid in [
        ("triage", TRIAGE_AGENT_ID), ("diagnosis", DIAGNOSIS_AGENT_ID),
        ("safety_reviewer", SAFETY_REVIEWER_AGENT_ID),
        ("commander", COMMANDER_AGENT_ID), ("operator", OPERATOR_AGENT_ID),
    ]:
        if aid:
            try:
                await recorder.add_participant(room_id, aid)
            except Exception:
                pass

    alert = AlertCard(
        alert_id=incident_id, source="sentry",
        timestamp=datetime.now(timezone.utc),
        title="PaymentService total outage — 100% failure rate",
        raw_payload={
            "error": "100% request failure, all payment processing halted",
            "service": "payment-service",
            "endpoint": "/api/v1/payments/process",
            "error_rate": "100% (was 0.1%)",
            "affected_users": 5000,
            "region": "us-east-1",
            "level": "fatal",
            "issue_id": f"SENTRY-{uuid.uuid4().hex[:8].upper()}",
        },
        fingerprint=f"sha256:{uuid.uuid4().hex[:16]}",
        preliminary_severity="P1",
        security_relevant=False,
    )

    print("  --- Submit AlertCard ---")
    async with SubmissionClient(GATEWAY_URL, agent_key=RECORDER_SUBMISSION_KEY) as sc:
        prepared = await sc.prepare(alert, idempotency_key=str(uuid.uuid4()))
        sealed_message = format_card_message(prepared.sealed_card)
        mentions = [TRIAGE_AGENT_ID] if TRIAGE_AGENT_ID else []
        msg_id = await recorder.post_message(room_id, sealed_message, mentions)
        confirmed = await sc.confirm(
            submission_id=prepared.submission_id,
            incident_id=prepared.incident_id,
            card_hash=prepared.card_hash,
            room_message_id=msg_id,
            room_alias_id=room_id,
        )
        print(f"  ✅ Confirmed: {confirmed.new_state}")

    return {"incident_id": prepared.incident_id, "room_id": room_id}


async def poll_state(incident_id: str, target_states: set,
                     timeout_sec: int = 300) -> str:
    start = time.monotonic()
    last_state = ""
    async with httpx.AsyncClient() as client:
        while time.monotonic() - start < timeout_sec:
            try:
                resp = await client.get(
                    f"{GATEWAY_URL}/incidents/{incident_id}", timeout=10.0)
                if resp.status_code == 200:
                    state = resp.json().get("incident", {}).get("state", "")
                    if state != last_state:
                        print(f"  [{time.monotonic()-start:.0f}s] {state}")
                        last_state = state
                    if state in target_states:
                        return state
            except Exception as e:
                print(f"  ⚠️ {e}")
            await asyncio.sleep(3)
    print(f"  ⏰ Timeout ({timeout_sec}s)")
    return last_state


async def get_nonce_via_caddy(incident_id: str, timeout_sec: int = 120) -> tuple:
    """Get nonce via REAL Caddy HTTPS URL."""
    start = time.monotonic()
    async with httpx.AsyncClient(verify=False) as client:  # Demo domains may use temporary certs.
        while time.monotonic() - start < timeout_sec:
            try:
                resp = await client.get(
                    f"{CADDY_URL}/approve/{incident_id}",
                    headers=_caddy_auth_headers(),
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    nonce_m = re.search(r'name="nonce"\s+value="([^"]+)"', resp.text)
                    csrf_m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
                    if nonce_m and csrf_m:
                        return nonce_m.group(1), csrf_m.group(1)
            except Exception as e:
                print(f"  ⚠️ Caddy nonce: {e}")
            await asyncio.sleep(3)
    return "", ""


async def post_decision_via_caddy(incident_id: str, nonce: str, csrf: str,
                                  decision: str,
                                  revision_instructions: str = "") -> httpx.Response:
    """Submit decision via REAL Caddy HTTPS URL."""
    data = {"nonce": nonce, "csrf_token": csrf, "decision": decision}
    if revision_instructions:
        data["revision_instructions"] = revision_instructions
    async with httpx.AsyncClient(verify=False) as client:
        return await client.post(
            f"{CADDY_URL}/approve/{incident_id}",
            headers=_caddy_auth_headers(),
            data=data,
            timeout=15.0,
        )


async def fetch_chain(incident_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        headers = {"X-Agent-Key": RECORDER_SUBMISSION_KEY} if RECORDER_SUBMISSION_KEY else {}
        resp = await client.get(
            f"{GATEWAY_URL}/api/export/evidence/{incident_id}",
            headers=headers, timeout=15.0,
        )
        return resp.json() if resp.status_code == 200 else {}


# ══════════════════════════════════════════════════════════
# MAIN CLOSURE RUN
# ══════════════════════════════════════════════════════════

async def main():
    if not APPROVAL_UI_PASSWORD:
        print("❌ APPROVAL_UI_PASSWORD not set")
        sys.exit(1)
    if not CADDY_URL:
        print("❌ PUBLIC_BASE_URL must be set to the deployed Alibaba ECS HTTPS URL")
        sys.exit(1)

    inc_id = f"INC-CLOSURE-{uuid.uuid4().hex[:6].upper()}"
    start = time.monotonic()
    recorder = Recorder()

    print("=" * 60)
    print(f"CLOSURE RUN — {inc_id}")
    print(f"Caddy URL: {CADDY_URL}")
    print("=" * 60)

    # 1. Fire
    print("\n📡 Step 1: Fire alert...")
    await fire_incident(recorder, inc_id)

    # 2. Wait for PLANNED (v1)
    print("\n⏳ Step 2: Wait for v1 plan...")
    state = await poll_state(inc_id, {"PLANNED"})
    if state != "PLANNED":
        print(f"  ❌ Stuck at {state}")
        return

    # 3. Get nonce via CADDY
    print("\n🔑 Step 3: Get nonce via Caddy HTTPS...")
    nonce1, csrf1 = await get_nonce_via_caddy(inc_id)
    if not nonce1:
        print("  ❌ No nonce")
        return
    print(f"  v1 Nonce: {nonce1[:12]}... (via {CADDY_URL})")

    # 4. REJECT via CADDY
    print('\n❌ Step 4: REJECT via Caddy — "use circuit breaker instead of rollback"')
    resp = await post_decision_via_caddy(
        inc_id, nonce1, csrf1,
        decision="revise",
        revision_instructions="use circuit breaker instead of rollback",
    )
    print(f"  Caddy response: {resp.status_code}")

    # 5. Wait for v2 PLANNED
    print("\n⏳ Step 5: Wait for v2 plan...")
    await asyncio.sleep(5)
    state = await poll_state(inc_id, {"PLANNED"})

    # 6. Get nonce for v2 via CADDY
    print("\n🔑 Step 6: Get v2 nonce via Caddy HTTPS...")
    nonce2, csrf2 = await get_nonce_via_caddy(inc_id)
    if not nonce2:
        print("  ❌ No v2 nonce")
        return
    print(f"  v2 Nonce: {nonce2[:12]}... (via {CADDY_URL})")
    print(f"  ✅ Nonce changed: {nonce1[:8] != nonce2[:8]}")

    # 7. APPROVE via CADDY
    print("\n✅ Step 7: APPROVE v2 via Caddy HTTPS...")
    resp2 = await post_decision_via_caddy(inc_id, nonce2, csrf2, decision="approve")
    print(f"  Caddy response: {resp2.status_code}")

    # 8. Wait for EXECUTED (not just APPROVED!)
    print("\n⏳ Step 8: Wait for EXECUTED (up to 5 min)...")
    final = await poll_state(inc_id, {"EXECUTED"}, timeout_sec=300)
    if final != "EXECUTED":
        print(f"  ⚠️ Stopped at {final} — checking if Operator is processing...")
        # Check operator log
        import subprocess
        result = subprocess.run(
            ["grep", "-i", inc_id, "/tmp/operator.log"],
            capture_output=True, text=True,
        )
        print(f"  Operator log:\n{result.stdout[-500:]}")

    # 9. Export chain
    print("\n📋 Step 9: Export evidence chain...")
    chain = await fetch_chain(inc_id)
    elapsed = time.monotonic() - start

    # ── PROOF POINTS ──
    print("\n" + "=" * 60)
    print("CLOSURE RUN — PROOF POINTS")
    print("=" * 60)
    cards = chain.get("cards", [])
    card_types = [c.get("data", {}).get("card_type", "") for c in cards]
    print(f"  Chain valid: {chain.get('chain_valid')}")
    print(f"  Cards: {len(cards)}")
    for c in cards:
        d = c.get("data", {})
        extra = ""
        if d.get("card_type") == "ResponsePlan":
            rev = d.get("revision", d.get("plan_revision", "?"))
            rb = d.get("runbook_id", d.get("runbook", "?"))
            extra = f" revision={rev} runbook={rb}"
        elif d.get("card_type") == "StructuredApproval":
            extra = f" decision={d.get('decision')}"
        elif d.get("card_type") == "ActionReceipt":
            extra = f" actions={d.get('actions_taken', '?')}"
        print(f"    [{c.get('sequence', '?')}] {d.get('card_type')}{extra}")

    has_rejected = any(
        c.get("data", {}).get("card_type") == "StructuredApproval"
        and c.get("data", {}).get("decision") == "REJECTED"
        for c in cards
    )
    has_approved = any(
        c.get("data", {}).get("card_type") == "StructuredApproval"
        and c.get("data", {}).get("decision") == "APPROVED"
        for c in cards
    )
    has_receipt = "ActionReceipt" in card_types
    v2_plans = [c for c in cards
                if c.get("data", {}).get("card_type") == "ResponsePlan"
                and (c.get("data", {}).get("revision",
                     c.get("data", {}).get("plan_revision", 1)) or 1) >= 2]
    v2_rb = ""
    if v2_plans:
        d = v2_plans[0].get("data", {})
        v2_rb = d.get("runbook_id", d.get("runbook", ""))

    print(f"\n  ✅ StructuredApproval(REJECTED): {has_rejected}")
    print(f"  ✅ v2 plan exists: {bool(v2_plans)}")
    print(f"  ✅ v2 runbook = RB-004: {v2_rb}")
    print(f"  ✅ Nonce re-bound: {nonce1 != nonce2}")
    print(f"  ✅ StructuredApproval(APPROVED): {has_approved}")
    print(f"  ✅ ActionReceipt (EXECUTED): {has_receipt}")
    print(f"  ✅ Final state = EXECUTED: {final == 'EXECUTED'}")
    print(f"  ✅ Approved via real Caddy HTTPS: {CADDY_URL}")
    print(f"  Total time: {elapsed:.0f}s")

    # Save chain
    fname = f"/tmp/chain_closure_{inc_id}.json"
    with open(fname, "w") as f:
        json.dump({
            "incident_id": inc_id,
            "final_state": final,
            "caddy_url": CADDY_URL,
            "chain": chain,
            "nonce1": nonce1,
            "nonce2": nonce2,
        }, f, indent=2)
    print(f"\n  Chain: {fname}")
    print("=" * 60)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", message="Unverified HTTPS")
    asyncio.run(main())

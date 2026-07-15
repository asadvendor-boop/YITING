#!/usr/bin/env python3
"""YITING — Three-Way Decision Live Demo.

Fires two high-risk incidents and exercises the three-way decision:
  1. Reject & Revise: reject v1 plan → v2 with RB-004 → approve → EXECUTED
  2. False Alarm: mark as false alarm → CLOSED_FALSE_ALARM

Exports evidence chains for submission verification.
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

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://localhost:9000")
RECORDER_SUBMISSION_KEY = os.getenv("RECORDER_SUBMISSION_KEY", "")
TRIAGE_AGENT_ID = os.getenv("TRIAGE_AGENT_ID", "")
DIAGNOSIS_AGENT_ID = os.getenv("DIAGNOSIS_AGENT_ID", "")
SAFETY_REVIEWER_AGENT_ID = os.getenv("SAFETY_REVIEWER_AGENT_ID", "")
COMMANDER_AGENT_ID = os.getenv("COMMANDER_AGENT_ID", "")
OPERATOR_AGENT_ID = os.getenv("OPERATOR_AGENT_ID", "")

APPROVAL_PROXY_SECRET = os.getenv("APPROVAL_PROXY_SECRET", "")
APPROVAL_UI_USER = os.getenv("APPROVAL_UI_USER", "")
APPROVAL_UI_PASSWORD = os.getenv("APPROVAL_UI_PASSWORD", "")

_original_print = __builtins__.__dict__["print"]


def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _original_print(*args, **kwargs)


def _auth_headers() -> dict:
    """Basic auth + proxy secret for the approval page."""
    creds = base64.b64encode(
        f"{APPROVAL_UI_USER}:{APPROVAL_UI_PASSWORD}".encode()
    ).decode()
    return {
        "Authorization": f"Basic {creds}",
        "X-Proxy-Secret": APPROVAL_PROXY_SECRET,
    }


async def activate_scenario(incident_id: str, tier: str = "severe") -> None:
    """Activate victim-app scenario."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{VICTIM_APP_URL}/admin/scenario/{incident_id}/activate",
            params={"tier": tier},
        )
        resp.raise_for_status()
        print(f"  ✅ Victim-app scenario activated (tier={tier})")


async def fire_incident(
    recorder: Recorder,
    incident_id: str,
    severity: str = "P2",
    title: str = "Demo incident",
    description: str = "Demo",
    victim_tier: str = "severe",
) -> dict:
    """Fire an incident through the full Recorder → Gateway → incident room pipeline."""
    from datetime import datetime, timezone

    print("\n  --- Step 1: Activate victim-app ---")
    await activate_scenario(incident_id, tier=victim_tier)

    print("  --- Step 2: Create room ---")
    room_title = f"🔴 {incident_id} — {title}"
    room_id = await recorder.create_room(room_title)
    print(f"  Room: {room_id}")

    print("  --- Step 3: Add participants ---")
    for role, aid in [
        ("triage", TRIAGE_AGENT_ID),
        ("diagnosis", DIAGNOSIS_AGENT_ID),
        ("safety_reviewer", SAFETY_REVIEWER_AGENT_ID),
        ("commander", COMMANDER_AGENT_ID),
        ("operator", OPERATOR_AGENT_ID),
    ]:
        if aid:
            try:
                await recorder.add_participant(room_id, aid)
                print(f"    ✅ {role}")
            except Exception as e:
                print(f"    ⚠️ {role}: {e}")

    print("  --- Step 4: Build AlertCard ---")
    raw_payload = {
        "error": description,
        "service": "payment-service",
        "endpoint": "/api/v1/payments/process",
        "deploy_version": "v2.14.3",
        "previous_version": "v2.14.2",
        "error_rate": "47% (was 0.1%)",
        "affected_users": 2847,
        "region": "us-east-1",
        "level": "fatal",
        "issue_id": f"SENTRY-{uuid.uuid4().hex[:8].upper()}",
        "culprit": "PaymentProcessor.charge()",
    }

    alert = AlertCard(
        alert_id=incident_id,
        source="sentry",
        timestamp=datetime.now(timezone.utc),
        title=title,
        raw_payload=raw_payload,
        fingerprint=f"sha256:{uuid.uuid4().hex[:16]}",
        preliminary_severity=severity,
        security_relevant=False,
    )

    print("  --- Step 5: Submit AlertCard (prepare → publish → confirm) ---")
    idem_key = str(uuid.uuid4())
    async with SubmissionClient(GATEWAY_URL, agent_key=RECORDER_SUBMISSION_KEY) as sc:
        prepared = await sc.prepare(alert, idempotency_key=idem_key)
        print(f"    submission_id: {prepared.submission_id}")
        print(f"    card_hash: {prepared.card_hash[:24]}...")

        sealed_message = format_card_message(prepared.sealed_card)
        mentions = [TRIAGE_AGENT_ID] if TRIAGE_AGENT_ID else []
        msg_id = await recorder.post_message(room_id, sealed_message, mentions)
        print(f"    room message_id: {msg_id}")

        confirmed = await sc.confirm(
            submission_id=prepared.submission_id,
            incident_id=prepared.incident_id,
            card_hash=prepared.card_hash,
            room_message_id=msg_id,
            room_alias_id=room_id,
        )
        print(f"    ✅ Confirmed: state={confirmed.new_state}")

    return {
        "incident_id": prepared.incident_id,
        "room_id": room_id,
    }


async def poll_state(incident_id: str, target_states: set,
                     timeout_sec: int = 180) -> str:
    """Poll until incident reaches a target state."""
    start = time.monotonic()
    last_state = ""
    async with httpx.AsyncClient() as client:
        while time.monotonic() - start < timeout_sec:
            try:
                resp = await client.get(
                    f"{GATEWAY_URL}/incidents/{incident_id}",
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    state = resp.json().get("incident", {}).get("state", "")
                    if state != last_state:
                        elapsed = time.monotonic() - start
                        print(f"  [{elapsed:.0f}s] State: {state}")
                        last_state = state
                    if state in target_states:
                        return state
            except Exception as e:
                print(f"  ⚠️ Poll error: {e}")
            await asyncio.sleep(3)
    print(f"  ⏰ Timeout ({timeout_sec}s) — last: {last_state}")
    return last_state


async def get_nonce(incident_id: str, timeout_sec: int = 90) -> tuple:
    """Wait for approval nonce to appear, return (nonce, csrf_token)."""
    start = time.monotonic()
    async with httpx.AsyncClient() as client:
        while time.monotonic() - start < timeout_sec:
            try:
                resp = await client.get(
                    f"{GATEWAY_URL}/approve/{incident_id}",
                    headers=_auth_headers(),
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    text = resp.text
                    nonce_m = re.search(r'name="nonce"\s+value="([^"]+)"', text)
                    csrf_m = re.search(r'name="csrf_token"\s+value="([^"]+)"', text)
                    if nonce_m and csrf_m:
                        return nonce_m.group(1), csrf_m.group(1)
            except Exception as e:
                print(f"  ⚠️ Nonce fetch: {e}")
            await asyncio.sleep(3)
    print(f"  ⏰ Nonce timeout ({timeout_sec}s)")
    return "", ""


async def post_decision(incident_id: str, nonce: str, csrf: str,
                        decision: str, revision_instructions: str = "") -> httpx.Response:
    """Submit a decision to the approval page."""
    data = {"nonce": nonce, "csrf_token": csrf, "decision": decision}
    if revision_instructions:
        data["revision_instructions"] = revision_instructions
    async with httpx.AsyncClient() as client:
        return await client.post(
            f"{GATEWAY_URL}/approve/{incident_id}",
            headers=_auth_headers(),
            data=data,
            timeout=15.0,
        )


async def fetch_chain(incident_id: str) -> dict:
    """Fetch evidence chain for submission verification."""
    async with httpx.AsyncClient() as client:
        headers = {"X-Agent-Key": RECORDER_SUBMISSION_KEY} if RECORDER_SUBMISSION_KEY else {}
        resp = await client.get(
            f"{GATEWAY_URL}/api/export/evidence/{incident_id}",
            headers=headers,
            timeout=15.0,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"  ⚠️ Chain fetch: {resp.status_code}")
        return {}


async def fetch_incident(incident_id: str) -> dict:
    """Fetch incident details."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GATEWAY_URL}/incidents/{incident_id}",
            timeout=10.0,
        )
        return resp.json() if resp.status_code == 200 else {}


# ══════════════════════════════════════════════════════════
# INCIDENT 1: REJECT & REVISE
# ══════════════════════════════════════════════════════════

async def run_reject_revise(recorder: Recorder) -> dict:
    inc_id = f"INC-REVISE-{uuid.uuid4().hex[:6].upper()}"
    print("\n" + "=" * 60)
    print(f"INCIDENT 1: REJECT & REVISE — {inc_id}")
    print("=" * 60)

    # Fire alert
    print("\n📡 Step 1: Firing alert...")
    result = await fire_incident(
        recorder, inc_id,
        severity="P1",
        title="PaymentService latency spike — p99 > 5s",
        description="100% request failure, all payment processing halted",
        victim_tier="severe",
    )

    # Poll to PLANNED (v1)
    print("\n⏳ Step 2: Waiting for v1 plan (PLANNED)...")
    state = await poll_state(inc_id, {"PLANNED"}, timeout_sec=180)
    if state != "PLANNED":
        print(f"  ❌ Stuck at {state}")
        return {"incident_id": inc_id, "status": "FAILED", "reason": f"stuck at {state}"}

    # Get nonce for v1
    print("\n🔑 Step 3: Getting nonce for v1...")
    nonce1, csrf1 = await get_nonce(inc_id, timeout_sec=90)
    if not nonce1:
        return {"incident_id": inc_id, "status": "FAILED", "reason": "no nonce"}
    print(f"  v1 Nonce: {nonce1[:16]}...")

    # REJECT with "use circuit breaker instead of rollback"
    print('\n❌ Step 4: REJECTING v1 — "use circuit breaker instead of rollback"')
    resp = await post_decision(
        inc_id, nonce1, csrf1,
        decision="revise",
        revision_instructions="use circuit breaker instead of rollback",
    )
    print(f"  Response: {resp.status_code}")
    if resp.status_code == 200:
        print("  ✅ Rejection accepted")
    else:
        print(f"  ⚠️ {resp.text[:200]}")

    # Wait for v2 plan (Commander re-plans)
    print("\n⏳ Step 5: Waiting for v2 plan...")
    await asyncio.sleep(5)
    state = await poll_state(inc_id, {"PLANNED"}, timeout_sec=180)

    # Get nonce for v2
    print("\n🔑 Step 6: Getting nonce for v2...")
    nonce2, csrf2 = await get_nonce(inc_id, timeout_sec=90)
    if not nonce2:
        return {"incident_id": inc_id, "status": "PARTIAL", "reason": "no v2 nonce"}
    print(f"  v2 Nonce: {nonce2[:16]}...")
    print(f"  ✅ Nonce changed (old invalidated): {nonce1[:8] != nonce2[:8]}")

    # APPROVE v2
    print("\n✅ Step 7: Approving v2 plan...")
    resp2 = await post_decision(inc_id, nonce2, csrf2, decision="approve")
    print(f"  Response: {resp2.status_code}")

    # Wait for EXECUTED
    print("\n⏳ Step 8: Waiting for execution...")
    final = await poll_state(inc_id, {"EXECUTED", "APPROVED"}, timeout_sec=120)

    # Export chain
    print("\n📋 Step 9: Exporting evidence chain...")
    chain = await fetch_chain(inc_id)
    details = await fetch_incident(inc_id)

    # Proof points
    print("\n" + "=" * 60)
    print("REJECT & REVISE — PROOF POINTS")
    print("=" * 60)
    cards = chain.get("cards", [])
    print(f"  Chain valid: {chain.get('chain_valid')}")
    print(f"  Cards: {len(cards)}")
    for c in cards:
        d = c.get("data", {})
        extra = ""
        if d.get("card_type") == "ResponsePlan":
            extra = f" revision={d.get('revision', d.get('plan_revision', '?'))} runbook={d.get('runbook_id', d.get('runbook', '?'))}"
        elif d.get("card_type") == "StructuredApproval":
            extra = f" decision={d.get('decision')}"
        print(f"    [{c.get('sequence', '?')}] {d.get('card_type')}{extra}")

    has_rejected = any(
        c.get("data", {}).get("card_type") == "StructuredApproval"
        and c.get("data", {}).get("decision") == "REJECTED"
        for c in cards
    )
    v2_plans = [
        c for c in cards
        if c.get("data", {}).get("card_type") == "ResponsePlan"
        and (c.get("data", {}).get("revision", c.get("data", {}).get("plan_revision", 1)) or 1) >= 2
    ]
    v2_rb = ""
    if v2_plans:
        v2_data = v2_plans[0].get("data", {})
        v2_rb = v2_data.get("runbook_id", v2_data.get("runbook", ""))

    print(f"\n  ✅ StructuredApproval(REJECTED) in chain: {has_rejected}")
    print(f"  ✅ v2 plan exists: {bool(v2_plans)}")
    print(f"  ✅ v2 runbook = RB-004: {v2_rb}")
    print(f"  ✅ Old nonce invalidated: {nonce1 != nonce2}")
    print(f"  ✅ Final state: {final}")

    return {
        "incident_id": inc_id,
        "room_id": result["room_id"],
        "final_state": final,
        "chain": chain,
        "details": details,
        "nonce1": nonce1,
        "nonce2": nonce2,
    }


# ══════════════════════════════════════════════════════════
# INCIDENT 2: FALSE ALARM
# ══════════════════════════════════════════════════════════

async def run_false_alarm(recorder: Recorder) -> dict:
    inc_id = f"INC-FA-{uuid.uuid4().hex[:6].upper()}"
    print("\n" + "=" * 60)
    print(f"INCIDENT 2: FALSE ALARM — {inc_id}")
    print("=" * 60)

    # Fire alert
    print("\n📡 Step 1: Firing alert...")
    result = await fire_incident(
        recorder, inc_id,
        severity="P1",
        title="DiskUsage spike — 95% on worker-3",
        description="Disk usage warning on worker-3, possible storage issue",
        victim_tier="severe",
    )

    # Poll to PLANNED
    print("\n⏳ Step 2: Waiting for plan (PLANNED)...")
    state = await poll_state(inc_id, {"PLANNED"}, timeout_sec=180)
    if state != "PLANNED":
        print(f"  ❌ Stuck at {state}")
        return {"incident_id": inc_id, "status": "FAILED", "reason": f"stuck at {state}"}

    # Get nonce
    print("\n🔑 Step 3: Getting nonce...")
    nonce, csrf = await get_nonce(inc_id, timeout_sec=90)
    if not nonce:
        return {"incident_id": inc_id, "status": "FAILED", "reason": "no nonce"}
    print(f"  Nonce: {nonce[:16]}...")

    # Mark as FALSE ALARM
    print("\n🚫 Step 4: Marking as false alarm...")
    resp = await post_decision(inc_id, nonce, csrf, decision="false_alarm")
    print(f"  Response: {resp.status_code}")

    # Verify state
    print("\n📋 Step 5: Verifying final state...")
    await asyncio.sleep(3)
    details = await fetch_incident(inc_id)
    final_state = details.get("incident", {}).get("state", "unknown")
    print(f"  Final state: {final_state}")

    # Export chain
    print("\n📋 Step 6: Exporting evidence chain...")
    chain = await fetch_chain(inc_id)

    # Proof points
    print("\n" + "=" * 60)
    print("FALSE ALARM — PROOF POINTS")
    print("=" * 60)
    cards = chain.get("cards", [])
    card_types = [c.get("data", {}).get("card_type", "") for c in cards]
    print(f"  Chain valid: {chain.get('chain_valid')}")
    print(f"  Cards: {len(cards)}")
    for c in cards:
        d = c.get("data", {})
        extra = ""
        if d.get("card_type") == "StructuredApproval":
            extra = f" decision={d.get('decision')}"
        print(f"    [{c.get('sequence', '?')}] {d.get('card_type')}{extra}")

    has_fa = any(
        c.get("data", {}).get("card_type") == "StructuredApproval"
        and c.get("data", {}).get("decision") == "FALSE_ALARM"
        for c in cards
    )
    has_receipt = "ActionReceipt" in card_types

    print(f"\n  ✅ StructuredApproval(FALSE_ALARM) in chain: {has_fa}")
    print(f"  ✅ Final state = CLOSED_FALSE_ALARM: {final_state == 'CLOSED_FALSE_ALARM'}")
    print(f"  ✅ No ActionReceipt: {not has_receipt}")

    # Check Operator log for ignored non-APPROVED
    try:
        with open("/tmp/operator.log") as f:
            op_log = f.read()
        ignored = "Operator only executes APPROVED" in op_log
        print(f"  ✅ Operator logged ignored non-APPROVED: {ignored}")
    except Exception:
        print("  ⚠️ Could not check Operator log")

    return {
        "incident_id": inc_id,
        "room_id": result["room_id"],
        "final_state": final_state,
        "chain": chain,
        "details": details,
    }


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

async def main():
    if not APPROVAL_UI_PASSWORD:
        print("❌ APPROVAL_UI_PASSWORD not set")
        sys.exit(1)

    start = time.monotonic()
    recorder = Recorder()
    print("✅ Recorder ready")

    result1 = await run_reject_revise(recorder)
    result2 = await run_false_alarm(recorder)

    elapsed = time.monotonic() - start

    print("\n" + "=" * 60)
    print("THREE-WAY DECISION DEMO — FINAL SUMMARY")
    print("=" * 60)
    print(f"  Incident 1 (Reject & Revise): {result1['incident_id']} → {result1.get('final_state', '?')}")
    print(f"  Incident 2 (False Alarm):     {result2['incident_id']} → {result2.get('final_state', '?')}")
    print(f"  Total time: {elapsed:.0f}s")
    print()

    # Save chains
    for label, result in [("revise", result1), ("false_alarm", result2)]:
        fname = f"/tmp/chain_{label}_{result['incident_id']}.json"
        with open(fname, "w") as f:
            json.dump({
                "incident_id": result["incident_id"],
                "room_id": result.get("room_id"),
                "final_state": result.get("final_state"),
                "chain": result.get("chain", {}),
                "details": result.get("details", {}),
            }, f, indent=2)
        print(f"  Chain: {fname}")

    await recorder.close()
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

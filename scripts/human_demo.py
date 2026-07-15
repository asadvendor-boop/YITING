#!/usr/bin/env python3
"""Fire a single incident and wait for the human to interact via browser."""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.recorder import Recorder
from shared.models import AlertCard
from shared.submission_client import SubmissionClient, format_card_message
import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://localhost:9000")
RECORDER_KEY = os.getenv("RECORDER_SUBMISSION_KEY", "")


def _public_base_url() -> str:
    url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("PUBLIC_BASE_URL must be set to the deployed Alibaba ECS HTTPS URL")
    return url


async def main():
    inc_id = f"INC-HUMAN-{uuid.uuid4().hex[:6].upper()}"
    print(f"\n{'='*60}", flush=True)
    print(f"INCIDENT: {inc_id}", flush=True)
    print(f"{'='*60}\n", flush=True)

    recorder = Recorder()

    # Activate scenario
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{VICTIM_APP_URL}/admin/scenario/{inc_id}/activate",
                     params={"tier": "severe"})
    print("Alert fired, waiting for pipeline...", flush=True)

    # Create room + add participants
    room_id = await recorder.create_room(f"INC {inc_id} Human Demo")
    for v in ["TRIAGE_AGENT_ID", "DIAGNOSIS_AGENT_ID",
              "SAFETY_REVIEWER_AGENT_ID", "COMMANDER_AGENT_ID",
              "OPERATOR_AGENT_ID"]:
        aid = os.getenv(v, "")
        if aid:
            try:
                await recorder.add_participant(room_id, aid)
            except Exception:
                pass

    alert = AlertCard(
        alert_id=inc_id, source="sentry",
        timestamp=datetime.now(timezone.utc),
        title="PaymentService total outage",
        raw_payload={
            "error": "100% request failure",
            "service": "payment-service",
            "endpoint": "/api/v1/payments/process",
            "error_rate": "100%",
            "affected_users": 5000,
            "region": "us-east-1",
            "level": "fatal",
            "issue_id": f"SENTRY-{uuid.uuid4().hex[:8].upper()}",
        },
        fingerprint=f"sha256:{uuid.uuid4().hex[:16]}",
        preliminary_severity="P1",
        security_relevant=False,
    )

    async with SubmissionClient(GATEWAY_URL, agent_key=RECORDER_KEY) as sc:
        prepared = await sc.prepare(alert, idempotency_key=str(uuid.uuid4()))
        sealed = format_card_message(prepared.sealed_card)
        triage_id = os.getenv("TRIAGE_AGENT_ID", "")
        mentions = [triage_id] if triage_id else []
        msg_id = await recorder.post_message(room_id, sealed, mentions)
        await sc.confirm(
            submission_id=prepared.submission_id,
            incident_id=prepared.incident_id,
            card_hash=prepared.card_hash,
            room_message_id=msg_id,
            room_alias_id=room_id,
        )

    # Poll until PLANNED
    start = time.monotonic()
    last = ""
    async with httpx.AsyncClient() as c:
        while time.monotonic() - start < 300:
            try:
                r = await c.get(f"{GATEWAY_URL}/incidents/{inc_id}", timeout=10)
                if r.status_code == 200:
                    st = r.json().get("incident", {}).get("state", "")
                    if st != last:
                        elapsed = time.monotonic() - start
                        print(f"  [{elapsed:.0f}s] {st}", flush=True)
                        last = st
                    if st == "PLANNED":
                        break
            except Exception:
                pass
            await asyncio.sleep(3)

    print(f"\n{'='*60}", flush=True)
    print("OPEN THIS URL IN YOUR BROWSER:", flush=True)
    print("", flush=True)
    try:
        public_base_url = _public_base_url()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", flush=True)
        return
    print(f"  {public_base_url}/approve/{inc_id}", flush=True)
    print("", flush=True)
    print("Login: use the judge credentials configured in Caddy and .env", flush=True)
    print(f"{'='*60}", flush=True)
    print("\nMonitoring state transitions...\n", flush=True)

    # Monitor until terminal state
    while time.monotonic() - start < 900:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{GATEWAY_URL}/incidents/{inc_id}", timeout=10)
            if r.status_code == 200:
                st = r.json().get("incident", {}).get("state", "")
                if st != last:
                    elapsed = time.monotonic() - start
                    print(f"  >> [{elapsed:.0f}s] {last} -> {st}", flush=True)
                    last = st
                    if st == "PLANNED":
                        print("     New plan ready! Refresh the page.", flush=True)
                    if st in ("EXECUTED", "CLOSED_FALSE_ALARM"):
                        break
        except Exception:
            pass
        await asyncio.sleep(3)

    print(f"\nFINAL STATE: {last}", flush=True)

    # Export chain
    async with httpx.AsyncClient() as c:
        headers = {"X-Agent-Key": RECORDER_KEY} if RECORDER_KEY else {}
        r = await c.get(f"{GATEWAY_URL}/api/export/evidence/{inc_id}",
                        headers=headers, timeout=15)
        chain = r.json() if r.status_code == 200 else {}

    cards = chain.get("cards", [])
    print(f"\nEvidence Chain ({len(cards)} cards):", flush=True)
    for card in cards:
        d = card.get("data", {})
        extra = ""
        ct = d.get("card_type", "")
        if ct == "ResponsePlan":
            rev = d.get("revision", d.get("plan_revision", "?"))
            rb = d.get("runbook_id", d.get("runbook", "?"))
            extra = f" rev={rev} rb={rb}"
        elif ct == "StructuredApproval":
            extra = f" decision={d.get('decision')}"
        elif ct == "ActionReceipt":
            acts = d.get("actions_taken", d.get("actions", []))
            extra = f" actions={[a.get('action_id') for a in acts]}"
        seq = card.get("sequence", "?")
        print(f"  [{seq}] {ct}{extra}", flush=True)

    fname = f"/tmp/chain_human_{inc_id}.json"
    with open(fname, "w") as f:
        json.dump(chain, f, indent=2)
    print(f"\nChain saved: {fname}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

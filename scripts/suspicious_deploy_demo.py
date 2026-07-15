#!/usr/bin/env python3
"""Suspicious Deploy Demo: Fires a deploy-based alert that triggers security detection.

This script:
1. Hits victim-app /admin/break/deploy to get a suspicious deploy payload
2. Creates an incident room via Recorder
3. Submits an AlertCard with source="github_deploy" and the deploy payload
4. The Recorder marks security_relevant=True → Triage forces route (no suppress)

Run after: Gateway, Triage, and all agents are running.

IMPORTANT:
- source MUST be "github_deploy" — detector returns False for any other source
- raw_payload is response["deploy"] (not full response) — fields at top level
"""
import asyncio
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.recorder import Recorder
from shared.models import AlertCard
from shared.submission_client import SubmissionClient, format_card_message

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
RECORDER_SUBMISSION_KEY = os.getenv("RECORDER_SUBMISSION_KEY", "")
TRIAGE_AGENT_ID = os.getenv("TRIAGE_AGENT_ID", "")
VICTIM_APP_URL = os.getenv("VICTIM_APP_URL", "http://localhost:9000")


async def main():
    print("=" * 60)
    print("🕵️  Suspicious Deploy Demo")
    print("=" * 60)

    start_time = time.monotonic()

    # Step 1: Trigger suspicious deploy on victim-app
    print("\n--- Step 1: Trigger suspicious deploy ---")
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{VICTIM_APP_URL}/admin/break/deploy",
            json={"incident_id": f"INC-SUSDEP-{uuid.uuid4().hex[:6].upper()}"},
        )
        resp.raise_for_status()
        deploy_data = resp.json()

    incident_id = deploy_data["incident_id"]
    deploy_payload = deploy_data["deploy"]  # Pass deploy dict, NOT full response
    print(f"  Incident ID: {incident_id}")
    print(f"  Deployer: {deploy_payload['deployer']}")
    print(f"  Commit: {deploy_payload['commit_message']}")
    print(f"  Off-hours: {deploy_payload['is_off_hours']}")

    # Step 2: Create incident room
    print("\n--- Step 2: Create incident room ---")
    recorder = Recorder()
    room_title = f"🔴 {incident_id} — Suspicious Deploy Detected"
    room_id = await recorder.create_room(room_title)
    print(f"  Room ID: {room_id}")

    # Step 3: Add Triage
    print("\n--- Step 3: Add Triage participant ---")
    if TRIAGE_AGENT_ID:
        await recorder.add_participant(room_id, TRIAGE_AGENT_ID)
        print(f"  ✅ Triage added: {TRIAGE_AGENT_ID[:12]}...")

    # Step 4: Build AlertCard
    # source="github_deploy" is MANDATORY — detector is gated on it
    print("\n--- Step 4: Build AlertCard (source=github_deploy) ---")
    from datetime import datetime, timezone

    alert = AlertCard(
        alert_id=incident_id,
        source="github_deploy",  # MUST be github_deploy
        timestamp=datetime.now(timezone.utc),
        title=f"Suspicious deploy: {deploy_payload['service']} "
        f"v{deploy_payload['version']} by {deploy_payload['deployer']}",
        raw_payload=deploy_payload,  # Pass deploy dict so fields are at top level
        fingerprint=f"sha256:deploy-{deploy_payload['service']}-{deploy_payload['deployer']}",
        preliminary_severity="P2",
        security_relevant=True,  # Recorder._is_security_relevant would set this
    )
    print(f"  Source: {alert.source}")
    print(f"  security_relevant: {alert.security_relevant}")
    print(f"  Severity: {alert.preliminary_severity}")

    # Step 5: Submit via Gateway
    print("\n--- Step 5: Submit AlertCard via Gateway ---")
    idem_key = str(uuid.uuid4())

    async with SubmissionClient(
        GATEWAY_URL, agent_key=RECORDER_SUBMISSION_KEY
    ) as sc:
        prepared = await sc.prepare(alert, idempotency_key=idem_key)
        print(f"  Prepared: submission_id={prepared.submission_id}")
        print(f"  card_hash: {prepared.card_hash[:24]}...")

        sealed_message = format_card_message(prepared.sealed_card)
        mentions = [TRIAGE_AGENT_ID] if TRIAGE_AGENT_ID else []
        msg_id = await recorder.post_message(room_id, sealed_message, mentions)
        print(f"  Published to incident room: message_id={msg_id}")

        confirmed = await sc.confirm(
            submission_id=prepared.submission_id,
            incident_id=prepared.incident_id,
            card_hash=prepared.card_hash,
            room_message_id=msg_id,
            room_alias_id=room_id,
        )
        print(f"  Confirmed: state={confirmed.new_state}")

    elapsed = (time.monotonic() - start_time) * 1000

    # Summary
    print("\n" + "=" * 60)
    print("🕵️  SUSPICIOUS DEPLOY DEMO FIRED")
    print("=" * 60)
    print(f"  Incident ID:     {prepared.incident_id}")
    print(f"  Room ID:         {room_id}")
    print("  security_relevant: True")
    print("  Source:          github_deploy")
    print(f"  AlertCard hash:  {prepared.card_hash[:24]}...")
    print(f"  State:           {confirmed.new_state}")
    print(f"  Latency:         {elapsed:.0f}ms")
    print()
    print("  Expected behavior:")
    print("    → Triage sees security_relevant=True → forces ROUTE (no suppress)")
    print("    → Full pipeline: Triage → Diagnosis → SafetyReviewer → Commander → Operator")
    print("    → Verdict should reference security/deploy concerns")
    print()
    print(f"  Verify: curl {GATEWAY_URL}/incidents/{prepared.incident_id}")
    print("=" * 60)

    await recorder.client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

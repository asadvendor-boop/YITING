#!/usr/bin/env python3
"""No-network local certification for the YITING Gateway-owned incident room.

This script uses FastAPI's TestClient with a temporary SQLite database.  It
walks the policy-authorized path through the same HTTP routes used in a live
deployment:

prepare card -> post card to incident room -> confirm card -> verify evidence.

It intentionally disables `YITING_TEST_MODE` so `/api/confirm` must verify that
the claimed room message really exists in the Gateway-owned room ledger.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


KEYS = {
    "recorder": "local-recorder-key",
    "triage": "local-triage-key",
    "diagnosis": "local-diagnosis-key",
    "safety_reviewer": "local-safety-key",
    "commander": "local-commander-key",
    "operator": "local-operator-key",
    "gateway": "local-gateway-key",
}


def _configure_env() -> None:
    os.environ["YITING_TEST_MODE"] = "false"
    os.environ["GATEWAY_SECRET"] = KEYS["gateway"]
    os.environ["APPROVAL_UI_CSRF_SECRET"] = "local-certification-csrf-secret"
    os.environ["HUMAN_APPROVER_IDS"] = "local-human-approver"
    os.environ["RECORDER_AGENT_ID"] = "local-recorder"
    os.environ["TRIAGE_AGENT_ID"] = "local-triage"
    os.environ["DIAGNOSIS_AGENT_ID"] = "local-diagnosis"
    os.environ["SAFETY_REVIEWER_AGENT_ID"] = "local-safety"
    os.environ["COMMANDER_AGENT_ID"] = "local-commander"
    os.environ["OPERATOR_AGENT_ID"] = "local-operator"
    for role, key in KEYS.items():
        if role == "gateway":
            continue
        os.environ[f"{role.upper()}_SUBMISSION_KEY"] = key


def _headers(role: str, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"X-Agent-Key": KEYS[role]}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    return headers


def _post_json(client: TestClient, path: str, *, json: dict, headers: dict[str, str]) -> dict:
    response = client.post(path, json=json, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"{path} failed with {response.status_code}: {response.text}")
    return response.json()


def _create_room(client: TestClient, incident_id: str) -> str:
    result = _post_json(
        client,
        "/api/rooms",
        json={"title": f"YITING local certification — {incident_id}", "incident_id": incident_id},
        headers=_headers("recorder"),
    )
    return result["room_id"]


def _post_room_message(
    client: TestClient,
    *,
    room_id: str,
    role: str,
    content: str,
    card_hash: str,
) -> str:
    result = _post_json(
        client,
        f"/api/rooms/{room_id}/messages",
        json={
            "content": content,
            "sender_id": f"local-{role}",
            "sender_role": role,
            "sender_type": "Agent",
            "mentions": [],
            "metadata": {"card_hash": card_hash},
        },
        headers=_headers(role),
    )
    return result["message_id"]


def _prepare_publish_confirm(
    client: TestClient,
    *,
    role: str,
    card_type: str,
    payload: dict[str, Any],
    room_id: str | None,
    idempotency_key: str,
) -> tuple[dict[str, Any], str]:
    from shared.submission_client import format_card_message

    prepared = _post_json(
        client,
        f"/api/prepare/{card_type}",
        json=payload,
        headers=_headers(role, idempotency_key=idempotency_key),
    )

    incident_id = prepared["incident_id"]
    active_room_id = room_id or _create_room(client, incident_id)
    sealed_card = prepared["sealed_card"]
    message_id = _post_room_message(
        client,
        room_id=active_room_id,
        role=role,
        content=format_card_message(sealed_card),
        card_hash=prepared["card_hash"],
    )
    confirmed = _post_json(
        client,
        "/api/confirm",
        json={
            "submission_id": prepared["submission_id"],
            "incident_id": incident_id,
            "card_hash": prepared["card_hash"],
            "message_id": message_id,
            "room_id": active_room_id,
        },
        headers=_headers(role),
    )
    return confirmed, active_room_id


def _record_transition(
    transitions: list[dict[str, Any]],
    *,
    card_type: str,
    confirmed: dict[str, Any],
) -> None:
    transitions.append(
        {
            "card_type": card_type,
            "state": confirmed.get("new_state"),
            "card_hash": confirmed["card_hash"],
        }
    )


def _walk_to_planned(
    client: TestClient,
    *,
    incident_id: str,
    action: dict[str, Any],
    severity: str,
    risk_level: str,
    requires_human: bool,
    runbook: str,
    label: str,
) -> tuple[str, list[dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    room_id: str | None = None
    steps = [
        (
            "recorder",
            "AlertCard",
            {
                "card_type": "AlertCard",
                "alert_id": incident_id,
                "source": "metrics",
                "timestamp": now.isoformat(),
                "title": f"{label} incident",
                "raw_payload": {"scenario": label, "service": action["target"]},
                "fingerprint": f"sha256:local-certification-{label}",
                "preliminary_severity": severity,
                "security_relevant": risk_level in {"high", "critical"},
            },
        ),
        (
            "triage",
            "TriageDecision",
            {
                "card_type": "TriageDecision",
                "incident_id": incident_id,
                "alert_id": incident_id,
                "decision": "route",
                "noise_score": 0.05,
                "reasoning": f"{label} requires investigation.",
            },
        ),
        (
            "diagnosis",
            "Assessment",
            {
                "card_type": "Assessment",
                "incident_id": incident_id,
                "severity": severity,
                "evidence_strength": 0.88,
                "blast_radius": [action["target"]],
                "root_cause_hypothesis": f"{label} root cause verified.",
                "recommended_action": action["action_id"],
                "evidence": {"local_certification": label},
                "revision": 1,
            },
        ),
        (
            "safety_reviewer",
            "Verdict",
            {
                "card_type": "Verdict",
                "incident_id": incident_id,
                "decision": "CONFIRM",
                "cross_check_sources": ["metrics", "uptime"],
                "reasoning": f"{label} evidence is internally consistent.",
                "agrees_with_diagnosis": True,
            },
        ),
        (
            "commander",
            "ResponsePlan",
            {
                "card_type": "ResponsePlan",
                "incident_id": incident_id,
                "runbook": runbook,
                "envelopes": [action],
                "risk_level": risk_level,
                "requires_human_approval": requires_human,
                "priority_rank": 1,
                "revision": 1,
            },
        ),
    ]

    transitions: list[dict[str, Any]] = []
    for idx, (role, card_type, payload) in enumerate(steps, start=1):
        confirmed, room_id = _prepare_publish_confirm(
            client,
            role=role,
            card_type=card_type,
            payload=payload,
            room_id=room_id,
            idempotency_key=f"{incident_id}-{idx}-{card_type}",
        )
        _record_transition(transitions, card_type=card_type, confirmed=confirmed)
    if room_id is None:
        raise RuntimeError(f"{incident_id} never created an incident room")
    return room_id, transitions


def _verify_evidence(
    client: TestClient,
    *,
    incident_id: str,
    expected_cards: int,
) -> dict[str, Any]:
    evidence_response = client.get(f"/evidence/{incident_id}")
    if evidence_response.status_code != 200:
        raise RuntimeError(f"evidence export failed: {evidence_response.text}")
    evidence = evidence_response.json()
    if evidence["state"] != "EXECUTED":
        raise RuntimeError(f"expected EXECUTED, got {evidence['state']}")
    if evidence["chain_valid"] is not True:
        raise RuntimeError(f"chain invalid: {evidence['chain_errors']}")
    if evidence["total_cards"] != expected_cards:
        raise RuntimeError(f"expected {expected_cards} cards, got {evidence['total_cards']}")
    return evidence


def _assert_card_sequence(evidence: dict[str, Any], expected: list[str]) -> None:
    actual = [card["card_type"] for card in evidence.get("cards", [])]
    if actual != expected:
        raise RuntimeError(f"expected card sequence {expected}, got {actual}")


def _run_policy_path(client: TestClient) -> dict[str, Any]:
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    incident_id = "INC-LOCAL-POLICY"
    action = {
        "action_id": "renew_certificate",
        "target": "api-gateway",
        "parameters": {"domain": "api.internal.example"},
        "timeout_seconds": 300,
        "rollback_action": "restore_previous_certificate",
    }
    room_id, transitions = _walk_to_planned(
        client,
        incident_id=incident_id,
        action=action,
        severity="P4",
        risk_level="low",
        requires_human=False,
        runbook="RB-005",
        label="policy",
    )

    confirmed, room_id = _prepare_publish_confirm(
        client,
        role="gateway",
        card_type="PolicyAuthorization",
        payload={
            "card_type": "PolicyAuthorization",
            "incident_id": incident_id,
            "authorization_id": "auth-local-policy",
            "plan_hash": "plan-local-policy",
            "action_hash": "action-local-policy",
            "risk_level": "low",
            "policy_rule": "low-risk-certificate-renewal",
            "expiry": expiry,
            "envelopes": [action],
        },
        room_id=room_id,
        idempotency_key=f"{incident_id}-6-PolicyAuthorization",
    )
    _record_transition(transitions, card_type="PolicyAuthorization", confirmed=confirmed)

    confirmed, room_id = _prepare_publish_confirm(
        client,
        role="operator",
        card_type="ActionReceipt",
        payload={
            "card_type": "ActionReceipt",
            "incident_id": incident_id,
            "authorization_type": "policy",
            "authorization_id": "auth-local-policy",
            "actions_taken": [{**action, "status": "success"}],
            "timeline": [{"step": "renew_certificate", "status": "success"}],
            "resolution_summary": "Certificate renewed and TLS reloaded.",
        },
        room_id=room_id,
        idempotency_key=f"{incident_id}-7-ActionReceipt",
    )
    _record_transition(transitions, card_type="ActionReceipt", confirmed=confirmed)
    evidence = _verify_evidence(client, incident_id=incident_id, expected_cards=7)
    _assert_card_sequence(
        evidence,
        [
            "AlertCard",
            "TriageDecision",
            "Assessment",
            "Verdict",
            "ResponsePlan",
            "PolicyAuthorization",
            "ActionReceipt",
        ],
    )
    return {
        "path": "policy",
        "incident_id": incident_id,
        "room_id": room_id,
        "state": evidence["state"],
        "chain_valid": evidence["chain_valid"],
        "total_cards": evidence["total_cards"],
        "transitions": transitions,
    }


def _run_human_path(client: TestClient) -> dict[str, Any]:
    incident_id = "INC-LOCAL-HUMAN"
    action = {
        "action_id": "rollback_deploy",
        "target": "payment-service",
        "parameters": {"version": "2.14.2"},
        "timeout_seconds": 300,
        "rollback_action": "restore_current_deploy",
    }
    room_id, transitions = _walk_to_planned(
        client,
        incident_id=incident_id,
        action=action,
        severity="P1",
        risk_level="high",
        requires_human=True,
        runbook="RB-003",
        label="human",
    )

    nonce = _post_json(
        client,
        "/api/nonce/create",
        json={"incident_id": incident_id},
        headers=_headers("commander"),
    )
    challenge = _post_json(
        client,
        "/api/nonce/challenge-posted",
        json={
            "incident_id": incident_id,
            "nonce": nonce["nonce"],
            "challenge_text": "Approval required for rollback_deploy on payment-service.",
        },
        headers=_headers("commander"),
    )
    approval = _post_json(
        client,
        "/api/nonce/consume",
        json={
            "incident_id": incident_id,
            "nonce": nonce["nonce"],
            "plan_hash": nonce["plan_hash"],
            "action_hash": nonce["action_hash"],
            "consumed_by": "local-human-approver",
            "room_message_id": challenge["challenge_message_id"],
        },
        headers=_headers("operator"),
    )

    # StructuredApproval is sealed and published by the Gateway nonce route.
    transitions.append(
        {
            "card_type": "StructuredApproval",
            "state": "APPROVED",
            "card_hash": "pending-evidence-read",
        }
    )

    confirmed, room_id = _prepare_publish_confirm(
        client,
        role="operator",
        card_type="ActionReceipt",
        payload={
            "card_type": "ActionReceipt",
            "incident_id": incident_id,
            "authorization_type": "human_approval",
            "authorization_id": approval["authorization_id"],
            "actions_taken": [{**action, "status": "success"}],
            "timeline": [{"step": "rollback_deploy", "status": "success"}],
            "resolution_summary": "Deployment rolled back after human approval.",
        },
        room_id=room_id,
        idempotency_key=f"{incident_id}-7-ActionReceipt",
    )
    _record_transition(transitions, card_type="ActionReceipt", confirmed=confirmed)
    evidence = _verify_evidence(client, incident_id=incident_id, expected_cards=7)
    _assert_card_sequence(
        evidence,
        [
            "AlertCard",
            "TriageDecision",
            "Assessment",
            "Verdict",
            "ResponsePlan",
            "StructuredApproval",
            "ActionReceipt",
        ],
    )
    approval_card = next(
        card for card in evidence["cards"] if card["card_type"] == "StructuredApproval"
    )
    approval_data = approval_card["data"]
    if approval_data.get("decision") != "APPROVED":
        raise RuntimeError(f"expected APPROVED StructuredApproval, got {approval_data.get('decision')}")
    if approval_data.get("approval_channel") != "room":
        raise RuntimeError(
            f"expected room approval_channel, got {approval_data.get('approval_channel')}"
        )
    for transition in transitions:
        if transition["card_type"] == "StructuredApproval":
            transition["card_hash"] = approval_card["hash"]
    return {
        "path": "human",
        "incident_id": incident_id,
        "room_id": room_id,
        "state": evidence["state"],
        "chain_valid": evidence["chain_valid"],
        "total_cards": evidence["total_cards"],
        "transitions": transitions,
    }


def run() -> dict[str, Any]:
    _configure_env()

    from gateway import auth
    from gateway.app import create_app
    from gateway.routes import submission

    auth._reset_for_testing()
    submission._agent_keys = None

    with tempfile.TemporaryDirectory(prefix="yiting-cert-") as tmp:
        db_path = str(Path(tmp) / "cert.db")
        app = create_app(db_path=db_path)
        with TestClient(app) as client:
            paths = [_run_policy_path(client), _run_human_path(client)]
            return {"paths": paths}


def main() -> int:
    result = run()
    print("YITING local certification")
    print("=" * 28)
    for path in result["paths"]:
        print(f"\npath: {path['path']}")
        print(f"incident_id: {path['incident_id']}")
        print(f"room_id: {path['room_id']}")
        print(f"state: {path['state']}")
        print(f"chain_valid: {path['chain_valid']}")
        print(f"total_cards: {path['total_cards']}")
        print("cards:")
        for idx, item in enumerate(path["transitions"], start=1):
            print(f"  {idx}. {item['card_type']} -> {item['state']} ({item['card_hash'][:12]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

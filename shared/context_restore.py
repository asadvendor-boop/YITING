"""Shared crash-recovery context restoration for reasoning agents.

Reasoning agents hold per-incident context in process memory. The sealed room
ledger at the Gateway is the durable source of truth, so after a process
restart an agent must rebuild its context from confirmed cards instead of
dropping in-flight work (a dropped CHALLENGE strands the room in CHALLENGED).

Commander pioneered this pattern; Diagnosis and Safety Reviewer share these
helpers so challenge budgets and revisions are always derived from the ledger,
never re-defaulted after a restart.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

logger = logging.getLogger("yiting.context_restore")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
TERMINAL_INCIDENT_STATES = {
    "EXECUTED",
    "FAILED",
    "CLOSED_FALSE_ALARM",
    "SUPPRESSED",
}


def normalize_card_payload(card: dict | None) -> dict:
    """Return a card dict with Gateway envelope data merged into card_json/data."""
    if not isinstance(card, dict):
        return {}
    data = card.get("data") or card.get("card_json")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = {}
    merged = dict(data) if isinstance(data, dict) else {}
    for key, value in card.items():
        if key in {"data", "card_json"}:
            continue
        merged.setdefault(key, value)
    merged.setdefault("card_hash", card.get("hash", card.get("card_hash", "")))
    merged.setdefault("sequence_number", card.get("sequence", card.get("sequence_number")))
    return merged


async def fetch_incident_snapshot(incident_id: str, *, role: str) -> dict | None:
    """Fetch public incident state/cards for cheap restart guards.

    This helper is intentionally fail-open: stale-message filtering should save
    tokens, but Gateway state machines remain the authoritative safety boundary.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GATEWAY_URL}/incidents/{incident_id}")
        if resp.status_code != 200:
            logger.warning(
                "[%s] Incident snapshot returned %s for %s; proceeding fail-open",
                role,
                resp.status_code,
                incident_id,
            )
            return None
        return resp.json()
    except Exception as exc:
        logger.warning(
            "[%s] Incident snapshot failed for %s (%s); proceeding fail-open",
            role,
            incident_id,
            type(exc).__name__,
        )
        return None


async def should_skip_terminal_incident(incident_id: str, *, role: str) -> bool:
    """Return True when the Gateway confirms this incident is terminal."""
    if not incident_id:
        return False
    snapshot = await fetch_incident_snapshot(incident_id, role=role)
    if not snapshot:
        return False
    incident = snapshot.get("incident") if isinstance(snapshot, dict) else {}
    state = str((incident or {}).get("state") or "").upper()
    if state in TERMINAL_INCIDENT_STATES:
        logger.info(
            "[%s] Skipping stale work for terminal incident %s (state=%s)",
            role,
            incident_id,
            state,
        )
        return True
    return False


def _seq(card: dict | None) -> int:
    try:
        return int((card or {}).get("sequence_number") or (card or {}).get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def _revision(card: dict | None) -> int:
    try:
        return int((card or {}).get("revision") or 1)
    except (TypeError, ValueError):
        return 1


def challenge_already_answered(cards: list[dict], challenge_card: dict) -> bool:
    """True if a later Assessment revision already answered this CHALLENGE."""
    challenge = normalize_card_payload(challenge_card)
    challenge_seq = _seq(challenge)
    challenge_count = sum(
        1
        for raw in cards
        if (card := normalize_card_payload(raw)).get("card_type") == "Verdict"
        and card.get("decision") == "CHALLENGE"
        and _seq(card) <= challenge_seq
    )
    expected_revision = max(2, challenge_count + 1)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "Assessment"
        and _seq(card) > challenge_seq
        and _revision(card) >= expected_revision
        for raw in cards
    )


def assessment_already_reviewed(cards: list[dict], assessment_card: dict) -> bool:
    """True if a later Verdict already reviewed this Assessment."""
    assessment = normalize_card_payload(assessment_card)
    assessment_seq = _seq(assessment)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "Verdict"
        and _seq(card) > assessment_seq
        for raw in cards
    )


def alert_already_triaged(cards: list[dict], alert_card: dict) -> bool:
    """True if a later TriageDecision already exists for this AlertCard."""
    alert = normalize_card_payload(alert_card)
    alert_seq = _seq(alert)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "TriageDecision"
        and _seq(card) > alert_seq
        for raw in cards
    )


def verdict_already_planned(cards: list[dict], verdict_card: dict) -> bool:
    """True if a later ResponsePlan already exists for this CONFIRM Verdict."""
    verdict = normalize_card_payload(verdict_card)
    verdict_seq = _seq(verdict)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "ResponsePlan"
        and _seq(card) > verdict_seq
        for raw in cards
    )


def rejection_already_revised(cards: list[dict], rejection_card: dict) -> bool:
    """True if a later ResponsePlan revision already answered this rejection."""
    rejection = normalize_card_payload(rejection_card)
    rejected_revision = _revision({"revision": rejection.get("plan_revision", 1)})
    rejection_seq = _seq(rejection)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "ResponsePlan"
        and _seq(card) > rejection_seq
        and _revision(card) > rejected_revision
        for raw in cards
    )


def authorization_already_receipted(cards: list[dict], auth_card: dict) -> bool:
    """True if a later ActionReceipt already records execution for this auth."""
    auth = normalize_card_payload(auth_card)
    auth_seq = _seq(auth)
    return any(
        (card := normalize_card_payload(raw)).get("card_type") == "ActionReceipt"
        and _seq(card) > auth_seq
        for raw in cards
    )


async def fetch_confirmed_cards(incident_id: str, *, agent_key: str, role: str) -> list[dict]:
    """Fetch published cards for an incident, payload merged with envelope fields.

    Fail-closed to an empty list: a restore that cannot see the ledger must not
    invent state. Callers treat [] as "nothing to restore".
    """
    if not agent_key:
        logger.warning("[%s] Context restore skipped: no agent key configured", role)
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GATEWAY_URL}/api/incidents/{incident_id}/cards",
                headers={"X-Agent-Key": agent_key, "Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning(
                "[%s] Context restore fetch returned %s for %s",
                role,
                resp.status_code,
                incident_id,
            )
            return []
        body = resp.json()
        card_list = body if isinstance(body, list) else body.get("cards", [])
        merged_cards: list[dict] = []
        for card in card_list:
            if not card.get("published", True):
                continue
            merged = normalize_card_payload(card)
            merged_cards.append(merged)
        merged_cards.sort(key=lambda item: item.get("sequence_number") or 0)
        return merged_cards
    except Exception as exc:
        logger.warning(
            "[%s] Context restore fetch failed for %s (%s)",
            role,
            incident_id,
            type(exc).__name__,
        )
        return []


def latest_card_of_type(cards: list[dict], card_type: str) -> dict | None:
    """Return the highest-sequence card of the given type, or None."""
    for card in reversed(cards):
        if card.get("card_type") == card_type:
            return card
    return None


def count_challenge_verdicts(cards: list[dict]) -> int:
    """Count sealed Verdict(CHALLENGE) cards — the durable challenge budget."""
    return sum(
        1
        for card in cards
        if card.get("card_type") == "Verdict" and card.get("decision") == "CHALLENGE"
    )

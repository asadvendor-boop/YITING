"""YITING Recorder — deterministic Gateway agent (no LLM).

Creates Gateway-owned incident rooms, adds participants, publishes AlertCards,
and posts audit events. No LLM — pure deterministic code.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from shared.incident_room import IncidentRoomClient
from shared.models import AlertCard

logger = logging.getLogger("yiting.recorder")

VALID_SEVERITIES = frozenset({"P1", "P2", "P3", "P4", "unknown"})


class Recorder:
    """Gateway trust anchor — creates rooms, posts cards, posts events."""

    def __init__(self):
        self.agent_id = os.getenv("RECORDER_AGENT_ID", "")
        self.room_client = IncidentRoomClient(
            sender_id=self.agent_id or "recorder",
            sender_role="recorder",
        )
        # Compatibility for older call sites that close recorder.client.
        self.client = self.room_client

    async def create_room(self, title: str, incident_id: str | None = None) -> str:
        """Create a new Gateway incident room. Returns the room_id."""
        room_id = await self.room_client.create_room(title, incident_id=incident_id)
        logger.info(f"Created room: {room_id} ({title})")
        return room_id

    async def add_participant(self, room_id: str, agent_id: str) -> None:
        """Add an agent to a room (invite-before-mention)."""
        await self.room_client.add_participant(
            room_id,
            agent_id,
            role=agent_id,
            display_name=agent_id,
        )
        logger.info(f"Added participant {agent_id} to room {room_id}")

    async def post_message(
        self,
        room_id: str,
        content: str,
        mentions: list[str] | None = None,
    ) -> str:
        """Post a message to an incident room. Returns the message_id."""
        return await self.room_client.post_message(
            room_id,
            content,
            mentions=mentions or [],
        )

    async def get_messages(self, room_id: str) -> list[dict]:
        """Fetch messages from a Gateway incident room."""
        return await self.room_client.get_messages(room_id)

    async def post_event(
        self,
        room_id: str,
        content: str,
        message_type: str = "task",
    ) -> None:
        """Post an event to an incident room."""
        await self.room_client.post_event(room_id, content, message_type=message_type)
        logger.info(f"Posted {message_type} event to room {room_id}")

    def normalize_alert(
        self,
        source: str,
        raw_payload: dict,
    ) -> AlertCard:
        """Normalize a raw webhook/poller payload into an AlertCard."""
        fingerprint_data = json.dumps(
            {"source": source, "key_fields": self._extract_key_fields(source, raw_payload)},
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()

        title = self._extract_title(source, raw_payload)
        severity = self._classify_preliminary_severity(source, raw_payload)
        security = self._is_security_relevant(source, raw_payload)

        return AlertCard(
            alert_id=str(uuid.uuid4()),
            source=source,
            timestamp=datetime.now(timezone.utc),
            title=title,
            raw_payload=raw_payload,
            fingerprint=fingerprint,
            preliminary_severity=severity,
            security_relevant=security,
        )

    def _extract_key_fields(self, source: str, payload: dict) -> dict:
        """Extract dedup-relevant fields by source type."""
        if source == "sentry":
            return {
                "issue_id": payload.get("issue_id", ""),
                "culprit": payload.get("culprit", ""),
            }
        elif source == "github_deploy":
            return {
                "sha": payload.get("sha", payload.get("after", "")),
                "ref": payload.get("ref", ""),
            }
        elif source == "metrics":
            return {
                "metric": payload.get("metric_name", ""),
                "threshold": payload.get("threshold", ""),
            }
        elif source == "uptime":
            return {
                "url": payload.get("url", ""),
                "status": payload.get("status_code", ""),
            }
        return {}

    def _extract_title(self, source: str, payload: dict) -> str:
        """Extract a human-readable title from the payload."""
        if source == "sentry":
            return payload.get("title", payload.get("message", "Sentry alert"))
        elif source == "github_deploy":
            pusher = payload.get("pusher", {})
            name = pusher.get("name", "unknown") if isinstance(pusher, dict) else "unknown"
            return f"Deploy: {payload.get('ref', 'unknown')} by {name}"
        elif source == "metrics":
            return f"Metric anomaly: {payload.get('metric_name', 'unknown')}"
        elif source == "uptime":
            return f"Uptime alert: {payload.get('url', 'unknown')} -> {payload.get('status_code', '?')}"
        return f"Alert from {source}"

    def _classify_preliminary_severity(self, source: str, payload: dict) -> str:
        """Deterministic heuristic for pre-room suppression gate.
        
        Returns a validated severity string from the P1-P4/unknown Literal.
        """
        # Sentry: level-based
        level = payload.get("level", "").lower()
        if level == "fatal":
            return "P1"
        if level == "error":
            return "P2"
        if level == "warning":
            return "P3"

        # Metrics: threshold severity (validate before using)
        if source == "metrics":
            raw_severity = payload.get("severity", "")
            if raw_severity in VALID_SEVERITIES:
                return raw_severity

        # Uptime: status code based
        if source == "uptime":
            code = payload.get("status_code", 200)
            if isinstance(code, int):
                if code >= 500:
                    return "P2"
                if code >= 400:
                    return "P3"

        return "unknown"

    def _is_security_relevant(self, source: str, payload: dict) -> bool:
        """Check if the alert has security implications.

        For source="github_deploy", detects:
        - Suspicious keywords in commit message (dependency, package, auth, token, secret)
        - External/contractor deployers
        - Off-hours deployments
        - Unfamiliar committers

        Reads both head_commit.message (real GitHub webhook shape) and
        flat commit_message (demo payload) for compatibility.
        """
        if source == "github_deploy":
            # Support both real webhook and demo payload shapes
            message = (
                payload.get("head_commit", {}).get("message", "")
                or payload.get("commit_message", "")
            ).lower()
            if any(
                kw in message
                for kw in ("dependency", "package", "auth", "token", "secret")
            ):
                return True
            deployer = payload.get("deployer", "").lower()
            if "external" in deployer or "contractor" in deployer:
                return True
            if payload.get("is_off_hours", False):
                return True
            if payload.get("unfamiliar_committer", False):
                return True
        return False

    async def close(self):
        """Clean up HTTP client."""
        await self.client.aclose()

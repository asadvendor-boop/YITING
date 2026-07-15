"""Tests for SubmissionClient — full HTTP path through Gateway.

Uses FastAPI's TestClient (which handles lifespan automatically)
to verify the SubmissionClient contract from the HTTP layer,
then separately tests the async SubmissionClient methods with
a pre-initialized app.

Verifies the three-phase saga:
  prepare → (publish to incident room — mocked) → confirm
And the critical contract: always sends X-Idempotency-Key.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from datetime import datetime, timezone

# Set env before any imports that read it
os.environ.setdefault("GATEWAY_SECRET", "test-gw-secret")

from shared.submission_client import (
    SubmissionClient,
    SubmissionError,
    PrepareResult,
    ConfirmResult,
    format_card_message,
)
from shared.models import AlertCard, TriageDecision
from gateway.app import create_app
from gateway.database import init_db

NOW = datetime.now(timezone.utc)


def _make_async_client(app) -> SubmissionClient:
    """Wire SubmissionClient to a pre-initialized app via ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    sc = SubmissionClient(
        gateway_url="http://testserver",
        agent_key=os.environ["GATEWAY_SECRET"],
    )
    sc._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver/api",
        headers={
            "X-Agent-Key": os.environ["GATEWAY_SECRET"],
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    return sc


def _app_with_db():
    """Create an app with pre-initialized in-memory DB (no lifespan needed)."""
    app = create_app(db_path=":memory:")
    # Manually init DB so we don't need the lifespan context manager
    app.state.db = init_db(":memory:")
    return app


def _run(coro):
    """Run async code."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_alert(**kwargs) -> AlertCard:
    defaults = {
        "alert_id": "sc-test-1",
        "source": "sentry",
        "timestamp": NOW,
        "title": "Test alert",
        "raw_payload": {"level": "error"},
        "fingerprint": "fp-sc-test",
        "preliminary_severity": "P2",
    }
    defaults.update(kwargs)
    return AlertCard(**defaults)


class TestSubmissionClientPrepare:
    """Test the prepare phase via async SubmissionClient."""

    def test_prepare_returns_sealed_card(self):
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert()
            result = await sc.prepare(alert)
            assert isinstance(result, PrepareResult)
            assert result.card_hash  # non-empty SHA-256
            assert result.sequence_number == 1
            assert result.incident_id  # alert_id used as incident_id
            assert result.submission_id  # idempotency key echoed back
            assert result.sealed_card["card_type"] == "AlertCard"
            assert result.sealed_card["card_hash"] == result.card_hash
            await sc.close()

        _run(_test())

    def test_prepare_uses_provided_idempotency_key(self):
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert(alert_id="idem-test")
            result = await sc.prepare(alert, idempotency_key="my-key-1")
            assert result.submission_id == "my-key-1"
            await sc.close()

        _run(_test())

    def test_prepare_identical_retry_returns_same(self):
        """Identical retry with same idempotency key → same sealed card."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert(alert_id="retry-test")
            r1 = await sc.prepare(alert, idempotency_key="retry-k1")
            r2 = await sc.prepare(alert, idempotency_key="retry-k1")
            assert r1.card_hash == r2.card_hash
            assert r1.submission_id == r2.submission_id
            await sc.close()

        _run(_test())

    def test_prepare_changed_payload_raises_409(self):
        """Changed payload with same idempotency key → 409."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert1 = make_alert(alert_id="conflict-test", title="Original")
            await sc.prepare(alert1, idempotency_key="conflict-k1")

            alert2 = make_alert(alert_id="conflict-test", title="Changed")
            with pytest.raises(SubmissionError) as exc_info:
                await sc.prepare(alert2, idempotency_key="conflict-k1")
            assert exc_info.value.status_code == 409
            await sc.close()

        _run(_test())

    def test_prepare_generates_idempotency_key(self):
        """Without explicit key, a UUID is generated (not empty)."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert(alert_id="auto-key")
            result = await sc.prepare(alert)
            assert result.submission_id  # non-empty
            assert len(result.submission_id) == 36  # UUID4 format
            await sc.close()

        _run(_test())


class TestSubmissionClientConfirm:
    """Test the confirm phase."""

    def test_full_prepare_confirm_cycle(self):
        """Full saga: prepare → confirm → state advances."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert(alert_id="cycle-test")
            prepared = await sc.prepare(alert, idempotency_key="cycle-k1")

            confirmed = await sc.confirm(
                submission_id=prepared.submission_id,
                incident_id=prepared.incident_id,
                card_hash=prepared.card_hash,
                room_message_id="550e8400-e29b-41d4-a716-446655440001",
                room_alias_id="room-001",
            )

            assert isinstance(confirmed, ConfirmResult)
            assert confirmed.status == "confirmed"
            assert confirmed.incident_id == prepared.incident_id
            assert confirmed.card_hash == prepared.card_hash
            assert confirmed.room_message_id == "550e8400-e29b-41d4-a716-446655440001"
            await sc.close()

        _run(_test())

    def test_confirm_idempotent(self):
        """Confirming twice returns already_confirmed."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            alert = make_alert(alert_id="idem-confirm")
            prepared = await sc.prepare(alert, idempotency_key="idem-c1")

            c1 = await sc.confirm(
                submission_id=prepared.submission_id,
                incident_id=prepared.incident_id,
                card_hash=prepared.card_hash,
                room_message_id="660e8400-e29b-41d4-a716-446655440002",
            )
            assert c1.status == "confirmed"

            c2 = await sc.confirm(
                submission_id=prepared.submission_id,
                incident_id=prepared.incident_id,
                card_hash=prepared.card_hash,
                room_message_id="660e8400-e29b-41d4-a716-446655440002",
            )
            assert c2.status == "already_confirmed"
            await sc.close()

        _run(_test())


class TestSubmissionClientAuth:
    """Test authentication."""

    def test_bad_key_raises_401(self):
        """Invalid agent key → 401."""
        app = _app_with_db()
        transport = httpx.ASGITransport(app=app)
        bad_client = SubmissionClient(
            gateway_url="http://testserver",
            agent_key="wrong-key",
        )
        bad_client._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver/api",
            headers={
                "X-Agent-Key": "wrong-key",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        async def _test():
            alert = make_alert(alert_id="auth-test")
            with pytest.raises(SubmissionError) as exc_info:
                await bad_client.prepare(alert)
            assert exc_info.value.status_code == 401
            await bad_client.close()

        _run(_test())


class TestFormatCardMessage:
    """Test the room message formatter."""

    def test_alert_card_format(self):
        card = {
            "card_type": "AlertCard",
            "alert_id": "test-1",
            "title": "Payment service down",
            "preliminary_severity": "P1",
            "source": "sentry",
            "card_hash": "abcdef1234567890",
            "sequence_number": 1,
        }
        msg = format_card_message(card)
        assert "**AlertCard**" in msg
        assert "P1" in msg
        assert "Payment service down" in msg
        assert "```json" in msg
        assert '"card_type": "AlertCard"' in msg

    def test_verdict_format(self):
        card = {
            "card_type": "Verdict",
            "incident_id": "inc-1",
            "decision": "CONFIRM",
            "card_hash": "deadbeef12345678",
            "sequence_number": 4,
        }
        msg = format_card_message(card)
        assert "⚖️ Verdict: CONFIRM" in msg

    def test_response_plan_format(self):
        card = {
            "card_type": "ResponsePlan",
            "incident_id": "inc-1",
            "risk_level": "high",
            "requires_human_approval": True,
            "card_hash": "cafe0000babe1234",
            "sequence_number": 5,
        }
        msg = format_card_message(card)
        assert "Risk: high" in msg
        assert "Human approval: True" in msg


class TestSubmissionClientMultiCard:
    """Test multi-card submission through the full pipeline."""

    def test_two_card_chain(self):
        """AlertCard → confirm → TriageDecision → confirm → state=TRIAGED."""
        app = _app_with_db()
        sc = _make_async_client(app)

        async def _test():
            # Card 1: AlertCard
            alert = make_alert(alert_id="chain-test")
            p1 = await sc.prepare(alert, idempotency_key="chain-a1")
            assert p1.sequence_number == 1

            c1 = await sc.confirm(
                submission_id=p1.submission_id,
                incident_id=p1.incident_id,
                card_hash=p1.card_hash,
                room_message_id="bmchain0001",
            )
            assert c1.status == "confirmed"

            # Card 2: TriageDecision
            triage = TriageDecision(
                incident_id="chain-test",
                alert_id="chain-test",
                decision="route",
                noise_score=0.1,
            )
            p2 = await sc.prepare(triage, idempotency_key="chain-t1")
            assert p2.sequence_number == 2
            assert p2.sealed_card["card_type"] == "TriageDecision"

            c2 = await sc.confirm(
                submission_id=p2.submission_id,
                incident_id=p2.incident_id,
                card_hash=p2.card_hash,
                room_message_id="bmchain0002",
            )
            assert c2.status == "confirmed"
            assert c2.new_state == "TRIAGED"
            await sc.close()

        _run(_test())


class TestIdempotencyKeyAlwaysSent:
    """Verify the critical contract: X-Idempotency-Key is always present.

    This is THE contract — without it, a retry seals a duplicate card
    because the Gateway falls back to a random UUID.
    """

    def test_prepare_always_sends_idempotency_header(self):
        """Even without an explicit key, a UUID is sent as header."""
        app = _app_with_db()

        # Track the headers of all outgoing requests
        sent_headers: list[dict] = []
        original_post = httpx.AsyncClient.post

        async def tracking_post(self_client, path, **kwargs):
            headers = kwargs.get("headers", {})
            sent_headers.append(dict(headers))
            return await original_post(self_client, path, **kwargs)

        sc = _make_async_client(app)

        async def _test():
            import unittest.mock
            with unittest.mock.patch.object(
                httpx.AsyncClient, "post", tracking_post
            ):
                alert = make_alert(alert_id="header-test")
                await sc.prepare(alert)

            # The prepare call should have sent X-Idempotency-Key
            assert any(
                "X-Idempotency-Key" in h for h in sent_headers
            ), f"X-Idempotency-Key not found in any request headers: {sent_headers}"
            await sc.close()

        _run(_test())

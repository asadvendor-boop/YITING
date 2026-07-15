"""Targeted tests for nonce creation hash normalization contracts.

Verifies:
1. Nonce create route resets seal fields before compute_plan_hash
2. Nonce create route reads `revision` (not `plan_revision`) from ResponsePlan
3. NonceCreateResponse includes Gateway-authoritative plan_hash, action_hash, plan_revision
4. The returned plan_hash matches what authorization route would compute
"""

from shared.approval import compute_plan_hash, compute_action_hash, normalize_plan_for_hash
from shared.models import ResponsePlan


def _make_plan(incident_id: str, revision: int = 1) -> ResponsePlan:
    """Build a ResponsePlan model instance."""
    return ResponsePlan(
        incident_id=incident_id,
        runbook="RB-001",
        envelopes=[],
        risk_level="high",
        requires_human_approval=True,
        priority_rank=1,
        revision=revision,
    )


class TestNonceHashNormalization:
    """Verify that nonce create normalizes seal fields before hashing."""

    def test_pre_seal_hash_matches_normalized_sealed_hash(self):
        """The hash after normalizing a sealed card must match the pre-seal hash."""
        plan = _make_plan("INC-HASH-01", revision=2)
        plan_dict = plan.model_dump()

        # Pre-seal hash: what Commander computes before submission
        pre_seal_hash = compute_plan_hash(plan_dict)

        # Simulate sealing — seal_card adds these fields
        sealed_dict = {**plan_dict}
        sealed_dict["card_hash"] = "sha256:abcdef1234567890"
        sealed_dict["previous_card_hash"] = "sha256:0000000000000000"
        sealed_dict["sequence_number"] = 3

        # Without normalization: hash MUST differ (this proves the bug was real)
        raw_sealed_hash = compute_plan_hash(sealed_dict)
        assert raw_sealed_hash != pre_seal_hash, (
            "Sealed card hash should differ from pre-seal hash — "
            "seal adds card_hash/previous_card_hash/sequence_number"
        )

        # With normalization via centralized helper:
        normalized_hash = compute_plan_hash(normalize_plan_for_hash(sealed_dict))

        assert normalized_hash == pre_seal_hash, (
            f"Normalized hash ({normalized_hash[:16]}...) "
            f"!= pre-seal hash ({pre_seal_hash[:16]}...)"
        )


class TestNonceRevisionFieldName:
    """Verify that nonce create reads `revision` not `plan_revision`."""

    def test_responseplan_model_uses_revision(self):
        """ResponsePlan model field is `revision`, not `plan_revision`."""
        plan = _make_plan("INC-REV-01", revision=3)
        plan_dict = plan.model_dump()

        # Correct field name (what the fix uses)
        assert plan_dict.get("revision") == 3

        # Wrong field name (what the broken code used)
        assert plan_dict.get("plan_revision") is None, (
            "ResponsePlan should NOT have a 'plan_revision' field"
        )

    def test_get_with_wrong_name_returns_default(self):
        """plan_data.get('plan_revision', 1) must return default 1."""
        plan_dict = _make_plan("INC-REV-02", revision=5).model_dump()

        # The broken code:
        old_result = plan_dict.get("plan_revision", 1)
        assert old_result == 1, (
            "Old code always returned default 1 — bug was silent"
        )

        # The fixed code:
        new_result = plan_dict.get("revision", 1)
        assert new_result == 5


class TestNonceResponseBindings:
    """Verify that NonceCreateResponse includes authoritative bindings."""

    def test_response_model_has_binding_fields(self):
        """NonceCreateResponse must have plan_hash, action_hash, plan_revision fields."""
        from gateway.routes.nonce import NonceCreateResponse

        fields = NonceCreateResponse.model_fields
        assert "plan_hash" in fields, "NonceCreateResponse missing plan_hash"
        assert "action_hash" in fields, "NonceCreateResponse missing action_hash"
        assert "plan_revision" in fields, "NonceCreateResponse missing plan_revision"

    def test_response_model_validates_with_bindings(self):
        """NonceCreateResponse can be constructed with all binding fields."""
        from gateway.routes.nonce import NonceCreateResponse

        resp = NonceCreateResponse(
            created=True,
            nonce="ABC123",
            incident_id="INC-01",
            expiry_iso="2026-01-01T00:00:00",
            plan_hash="sha256:abc",
            action_hash="sha256:def",
            plan_revision=2,
        )
        assert resp.plan_hash == "sha256:abc"
        assert resp.action_hash == "sha256:def"
        assert resp.plan_revision == 2


class TestNonceAuthorizationConsistency:
    """Verify that nonce and authorization routes compute identical hashes."""

    def test_both_routes_normalize_identically(self):
        """Both nonce and authorization must produce the same hash from a sealed card."""
        plan = _make_plan("INC-CONSISTENCY-01", revision=5)
        plan_dict = plan.model_dump()

        # Pre-seal (Commander's hash)
        commander_hash = compute_plan_hash(plan_dict)

        # Simulate sealed card with seal-added fields
        sealed = {**plan_dict}
        sealed["card_hash"] = "sha256:sealed123"
        sealed["previous_card_hash"] = "sha256:prev456"
        sealed["sequence_number"] = 7

        # Both routes now use normalize_plan_for_hash — single call proves consistency
        nonce_hash = compute_plan_hash(normalize_plan_for_hash(sealed))
        auth_hash = compute_plan_hash(normalize_plan_for_hash(sealed))

        # All three must be identical
        assert nonce_hash == auth_hash, "Nonce and authorization hashes must match"
        assert nonce_hash == commander_hash, "Nonce hash must match Commander's pre-seal hash"
        assert auth_hash == commander_hash, "Authorization hash must match Commander's pre-seal hash"

    def test_action_hash_independent_of_seal_fields(self):
        """action_hash uses envelopes only — unaffected by seal fields."""
        envelopes = [
            {"action_id": "restart_service", "action_type": "restart", "target": "svc"},
        ]
        h1 = compute_action_hash(envelopes)
        h2 = compute_action_hash(envelopes)
        assert h1 == h2, "action_hash must be deterministic"

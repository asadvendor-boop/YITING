"""Regression pins for the saturation-vs-circuit-breaker routing fix.

The live paired eval (artifacts/track3-live-paired/) surfaced a routing
defect with two cooperating causes:

1. ``_root_cause_from_evidence`` branched on substrings of its own composed
   text, and the literal metric field name ``latency_p99=`` made the
   "latency" branch fire for every metric anomaly, injecting a circuit-breaker
   recommendation regardless of fault family.
2. ``select_runbook`` routed to RB-004 on bare "dependency"/"upstream"
   narration, ahead of explicit capacity signals.

These tests pin the corrected behavior using the exact phrasings observed in
the eval's losing incidents.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.commander import select_runbook  # noqa: E402
from agents.diagnosis import _root_cause_from_evidence  # noqa: E402


class _Ctx:
    def __init__(self, tool_results):
        self.tool_results = tool_results


def _ctx(metrics=None, errors=None, deploys=None, uptime=None):
    return _Ctx({
        "metrics": metrics or {},
        "sentry": errors or {},
        "deploys": deploys or {},
        "uptime": uptime or {},
    })


class TestSelectRunbookRouting:
    def test_saturation_language_routes_to_scale_not_breaker(self):
        # Observed live: latency-family diagnoses must scale, not break circuits.
        got = select_runbook(
            "api-gateway: metric anomaly error_rate=1.8 latency_p99=6200",
            "P2",
            "Scale up replicas/capacity to relieve the measured saturation.",
        )
        assert got == "RB-002", got

    def test_bare_dependency_narration_no_longer_routes_breaker(self):
        got = select_runbook(
            "worker-service degraded; upstream dependency chain suspected",
            "P1",
            "investigate the dependency path",
        )
        assert got != "RB-004", got

    def test_explicit_breaker_intent_still_routes_breaker(self):
        got = select_runbook(
            "cascading failure across downstream services",
            "P1",
            "enable circuit breaker",
        )
        assert got == "RB-004", got

    def test_scale_outranks_breaker_when_both_described(self):
        got = select_runbook(
            "gateway saturation with cascading timeouts",
            "P1",
            "scale up capacity; consider a circuit breaker",
        )
        assert got == "RB-002", got

    def test_release_mention_alone_does_not_force_rollback(self):
        # Observed live (sentry family): naming the release must not route
        # RB-003 when the remediation is restart-then-scale.
        got = select_runbook(
            "error spike after deployment of auth-service@4.8.2",
            "P1",
            "Restart the service; add replicas if queued traffic stays above capacity.",
        )
        assert got == "RB-002", got

    def test_explicit_bad_deploy_still_rolls_back(self):
        assert select_runbook("bad deployment caused outage", "P1", "rollback") == "RB-003"


class TestDiagnosisEvidenceBranching:
    def test_latency_family_saturation_recommends_scaling(self):
        _, action, _ = _root_cause_from_evidence(_ctx(metrics={
            "service": "api-gateway", "anomaly_detected": True,
            "error_rate": 1.8, "latency_p99": 6200,
            "saturation_percentage": 91.0, "rate_limit_utilization": 96.0,
        }))
        assert "scale" in action.lower(), action

    def test_db_pool_exhaustion_recommends_scaling(self):
        _, action, _ = _root_cause_from_evidence(_ctx(metrics={
            "service": "user-service", "anomaly_detected": True,
            "error_rate": 28.4, "latency_p99": 9300, "db_pool_utilization": 98.0,
        }))
        assert "scale" in action.lower(), action

    def test_memory_leak_recommends_restart(self):
        _, action, _ = _root_cause_from_evidence(_ctx(metrics={
            "service": "worker-service", "anomaly_detected": True,
            "error_rate": 14.2, "latency_p99": 5100, "heap_utilization": 94.0,
        }))
        assert "restart" in action.lower(), action

    def test_deploy_correlation_recommends_rollback(self):
        _, action, _ = _root_cause_from_evidence(_ctx(
            metrics={"anomaly_detected": True, "latency_p99": 4800},
            deploys={"service": "payment-service", "anomaly_detected": True},
        ))
        assert "rollback" in action.lower(), action

    def test_metric_anomaly_never_yields_circuit_breaker_text(self):
        # The literal field name latency_p99= must not steer remediation.
        for metrics in (
            {"anomaly_detected": True, "error_rate": 35.2, "latency_p99": 4800},
            {"anomaly_detected": True, "latency_p99": 6200, "saturation_percentage": 91.0},
            {"anomaly_detected": True, "latency_p99": 5100, "heap_utilization": 94.0},
        ):
            _, action, _ = _root_cause_from_evidence(_ctx(metrics=metrics))
            assert "circuit" not in action.lower(), action


class TestLeakPriorityGuard:
    def test_leak_with_restart_intent_outranks_scale_mention(self):
        # Observed live (memory family): the diagnosis recommended restart but
        # also mentioned scaling headroom; a leaking process must restart.
        got = select_runbook(
            "worker-service: metric anomaly heap_utilization=94.0 gc_pause_p99_ms=980",
            "P1",
            "Restart the affected service to clear the leaking process; "
            "consider scaling workers for headroom.",
        )
        assert got == "RB-001", got

    def test_saturation_without_leak_still_scales(self):
        got = select_runbook(
            "api-gateway: metric anomaly saturation_percentage=91.0",
            "P2",
            "Scale up replicas/capacity to relieve the measured saturation.",
        )
        assert got == "RB-002", got

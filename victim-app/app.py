"""YITING victim-app — live synthetic telemetry for incident diagnosis.

A FastAPI service (port 9000) that serves scenario-driven evidence data.
Scenarios are activated per incident_id with a severity tier; when active,
endpoints return anomalous signals that downstream agents can diagnose.

Severity tiers:
  - "severe"  → high error rate, long latency, 91.3% uptime (P1 / high-risk)
  - "mild"    → modest error rate, elevated latency, 99.2% uptime (P3 / low-risk)
  - None      → fully healthy (inactive scenario)
"""

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI(title="YITING Victim App", version="1.3.0")

# Per-incident scenario state.  Entries created through the generic activation
# endpoint have no scenario_type and retain the severe/mild
# evidence behavior.
_scenarios: dict[str, dict] = {}
SOURCE_LABEL = "live_synthetic_telemetry"

_SCENARIO_SERVICES = {
    "deploy": "payment-service",
    "sentry": "auth-service",
    "latency": "api-gateway",
    "db": "user-service",
    "memory": "worker-service",
    "cert": "api-gateway",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_tier(incident_id: str) -> str | None:
    entry = _scenarios.get(incident_id, {})
    if not entry.get("active", False):
        return None
    return entry.get("tier", "severe")


def _get_scenario_type(incident_id: str) -> str | None:
    entry = _scenarios.get(incident_id, {})
    if not entry.get("active", False):
        return None
    value = entry.get("scenario_type")
    return str(value) if value else None


async def _safe_json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _new_incident_id(body: dict) -> str:
    supplied = str(body.get("incident_id", "")).strip()
    return supplied or f"INC-CHAOS-{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Durable duplicate suppression for remediation idempotency.
# ---------------------------------------------------------------------------
_IDEM_DB_PATH = os.getenv(
    "HEAL_IDEMPOTENCY_DB",
    str(Path(__file__).parent / "heal_idempotency.db"),
)
_idem_lock = threading.Lock()


def _init_idem_db() -> sqlite3.Connection:
    db = sqlite3.connect(_IDEM_DB_PATH, check_same_thread=False)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS applied_actions (
            execution_key TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            result_json TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    db.commit()
    return db


_idem_db = _init_idem_db()


def _execution_key(
    incident_id: str,
    action_hash: str,
    action_id: str,
    target: str,
    params: dict,
) -> str:
    canonical = json.dumps(
        {
            "incident_id": incident_id,
            "action_hash": action_hash,
            "action_id": action_id,
            "target": target,
            "parameters": params,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class HealRequest(BaseModel):
    incident_id: str
    action: str
    target: str
    parameters: Optional[dict] = None
    action_hash: str


# ── Admin endpoints ───────────────────────────────────────────────────────


@app.post("/admin/scenario/{incident_id}/activate")
def activate_scenario(incident_id: str, tier: str = "severe"):
    """Activate a scenario for an incident.

    tier: "severe" (P1, high error) | "mild" (P3, modest anomaly)
    """
    valid_tiers = {"severe", "mild"}
    if tier not in valid_tiers:
        return {"error": f"Invalid tier '{tier}'. Use: {valid_tiers}"}
    _scenarios[incident_id] = {
        "active": True,
        "tier": tier,
        "activated_at": _now(),
    }
    return {
        "status": "activated",
        "incident_id": incident_id,
        "tier": tier,
        "source": SOURCE_LABEL,
    }


def _activate_break_scenario(incident_id: str, scenario_type: str, tier: str) -> None:
    """Use the canonical activation path, then attach scenario metadata."""
    activate_scenario(incident_id, tier)
    _scenarios[incident_id].update(
        {
            "scenario_type": scenario_type,
            "service": _SCENARIO_SERVICES[scenario_type],
        }
    )


def _alert_response(
    *,
    incident_id: str,
    scenario_type: str,
    alert_type: str,
    source: str,
    title: str,
    severity: str,
    preliminary_severity: str,
    raw_payload: dict,
    security_relevant: bool = False,
    fingerprint: str | None = None,
) -> dict:
    service = _SCENARIO_SERVICES[scenario_type]
    return {
        "incident_id": incident_id,
        "scenario_type": scenario_type,
        "alert": {
            "alert_type": alert_type,
            "source": source,
            "title": title,
            "severity": severity,
            "preliminary_severity": preliminary_severity,
            "service": service,
            "security_relevant": security_relevant,
            "fingerprint": fingerprint or f"sha256:chaos-{scenario_type}-{service}",
            "raw_payload": raw_payload,
        },
        "source": SOURCE_LABEL,
    }


@app.post("/admin/break/deploy")
async def trigger_suspicious_deploy(request: Request):
    """Inject the existing suspicious-deploy golden path unchanged."""
    body = await _safe_json(request)
    supplied = str(body.get("incident_id", "")).strip()
    incident_id = supplied or f"INC-SUSDEP-{uuid.uuid4().hex[:6].upper()}"
    _activate_break_scenario(incident_id, "deploy", "severe")

    # Keep the deploy object and values exactly so the proven golden path
    # and security-relevance detection continue to behave as before.
    deploy = {
        "service": "payment-service",
        "version": "2.5.0-rc1",
        "deployer": "external-contractor-42",
        "timestamp": "2026-06-17T03:42:00Z",
        "head_commit": {
            "message": "update dependency versions, package.json changes"
        },
        "commit_message": "update dependency versions, package.json changes",
        "changed_files": [
            "package.json",
            "package-lock.json",
            "src/auth/tokens.js",
        ],
        "is_off_hours": True,
        "unfamiliar_committer": True,
        "dependency_changes": True,
    }
    result = _alert_response(
        incident_id=incident_id,
        scenario_type="deploy",
        alert_type="suspicious_deploy",
        source="github_deploy",
        title=(
            f"Suspicious deploy: {deploy['service']} "
            f"v{deploy['version']} by {deploy['deployer']}"
        ),
        severity="critical",
        preliminary_severity="P2",
        raw_payload=deploy,
        security_relevant=True,
        fingerprint=f"sha256:deploy-{deploy['service']}-{deploy['deployer']}",
    )
    result["deploy"] = deploy
    return result


@app.post("/admin/break/sentry")
async def trigger_sentry_error_spike(request: Request):
    body = await _safe_json(request)
    incident_id = _new_incident_id(body)
    _activate_break_scenario(incident_id, "sentry", "severe")
    now = _now()
    raw = {
        "alert_type": "sentry_error_spike",
        "issue_id": f"AUTH-{incident_id[-6:]}",
        "title": "Authentication failures surged across login traffic",
        "message": "JWT signature validation failures exceeded the error budget",
        "level": "fatal",
        "culprit": "auth.tokens.verify_signature",
        "service": "auth-service",
        "environment": "production",
        "release": "auth-service@4.8.2",
        "event_count": 2384,
        "error_rate": 47.0,
        "first_seen": (now - timedelta(minutes=7)).isoformat(),
        "stack_trace": (
            "InvalidSignatureError: JWT kid does not match active signing key\n"
            "  at auth.tokens.verify_signature(tokens.py:214)\n"
            "  at auth.sessions.refresh(session.py:89)"
        ),
        "affected_endpoints": ["/v1/session/refresh", "/v1/login"],
        "recommended_action_hint": (
            "restart_service(auth-service), then add replicas if the queued "
            "authentication traffic remains above capacity"
        ),
    }
    return _alert_response(
        incident_id=incident_id,
        scenario_type="sentry",
        alert_type="sentry_error_spike",
        source="sentry",
        title="Critical Sentry spike — auth-service token validation failures",
        severity="critical",
        preliminary_severity="P1",
        raw_payload=raw,
        fingerprint=f"sha256:sentry-auth-token-validation-{incident_id[-6:]}",
    )


@app.post("/admin/break/latency")
async def trigger_latency_degradation(request: Request):
    body = await _safe_json(request)
    incident_id = _new_incident_id(body)
    _activate_break_scenario(incident_id, "latency", "severe")
    raw = {
        "alert_type": "latency_degradation",
        "metric_name": "http.server.duration.p99",
        "service": "api-gateway",
        "environment": "production",
        "threshold": 2000,
        "observed": 6200,
        "unit": "milliseconds",
        "duration_minutes": 11,
        "request_rate_per_second": 1840,
        "affected_routes": ["/checkout", "/payments", "/session"],
        "upstream_timeout_count": 186,
        "slow_query_signature": "checkout_items_by_customer (p99 4.8s)",
        "severity": "P2",
        "recommended_action_hint": (
            "adjust_rate_limits(api-gateway) and scale_horizontally(api-gateway)"
        ),
    }
    return _alert_response(
        incident_id=incident_id,
        scenario_type="latency",
        alert_type="latency_degradation",
        source="metrics",
        title="P99 latency exceeded 6 seconds on api-gateway",
        severity="high",
        # Controlled chaos alerts fail safe into the route path; Diagnosis can
        # reassess the final severity from the richer evidence below.
        preliminary_severity="P1",
        raw_payload=raw,
        fingerprint=f"sha256:latency-api-gateway-{incident_id[-6:]}",
    )


@app.post("/admin/break/db")
async def trigger_db_pool_exhaustion(request: Request):
    body = await _safe_json(request)
    incident_id = _new_incident_id(body)
    _activate_break_scenario(incident_id, "db", "severe")
    raw = {
        "alert_type": "db_pool_exhaustion",
        "metric_name": "db.connection_pool.utilization",
        "service": "user-service",
        "database": "users-primary",
        "environment": "production",
        "threshold": 90,
        "observed": 98,
        "unit": "percent",
        "pool_size": 100,
        "active_connections": 98,
        "waiting_requests": 342,
        "connection_timeouts_last_5m": 119,
        "long_running_queries": 17,
        "oldest_idle_transaction_seconds": 1260,
        "severity": "P1",
        "recommended_action_hint": (
            "kill_idle_connections(users-primary), increase_pool_size(user-service), "
            "and enable a temporary circuit breaker while the pool recovers"
        ),
    }
    return _alert_response(
        incident_id=incident_id,
        scenario_type="db",
        alert_type="db_pool_exhaustion",
        source="metrics",
        title="Database connection pool exhausted for user-service",
        severity="critical",
        preliminary_severity="P1",
        raw_payload=raw,
        fingerprint=f"sha256:db-pool-user-service-{incident_id[-6:]}",
    )


@app.post("/admin/break/memory")
async def trigger_memory_pressure(request: Request):
    body = await _safe_json(request)
    incident_id = _new_incident_id(body)
    _activate_break_scenario(incident_id, "memory", "severe")
    raw = {
        "alert_type": "memory_heap_pressure",
        "metric_name": "process.heap.utilization",
        "service": "worker-service",
        "environment": "production",
        "threshold": 85,
        "observed": 94,
        "unit": "percent",
        "heap_used_mb": 7520,
        "heap_limit_mb": 8192,
        "growth_rate_mb_per_minute": 186,
        "gc_pause_p99_ms": 980,
        "oom_restarts_last_hour": 3,
        "allocation_hotspot": "worker.jobs.export_batch.BatchBuffer",
        "severity": "P2",
        "recommended_action_hint": (
            "trigger_gc(worker-service), then perform a rolling_restart(worker-service)"
        ),
    }
    return _alert_response(
        incident_id=incident_id,
        scenario_type="memory",
        alert_type="memory_heap_pressure",
        source="metrics",
        title="Memory leak symptoms detected on worker-service",
        severity="high",
        preliminary_severity="P1",
        raw_payload=raw,
        fingerprint=f"sha256:memory-worker-service-{incident_id[-6:]}",
    )


@app.post("/admin/break/cert")
async def trigger_certificate_expiry(request: Request):
    body = await _safe_json(request)
    incident_id = _new_incident_id(body)
    _activate_break_scenario(incident_id, "cert", "mild")
    now = _now()
    expires_at = now + timedelta(hours=46)
    raw = {
        "alert_type": "certificate_expiry",
        "service": "api-gateway",
        "environment": "production",
        "url": "https://api.example.com",
        "status_code": 200,
        "certificate_common_name": "api.example.com",
        "certificate_issuer": "Example Trust Services",
        "certificate_serial": "03:A7:91:2B:6D:44",
        "expires_at": expires_at.isoformat(),
        "hours_remaining": 46,
        "warning_threshold_hours": 336,
        "auto_renewal_status": "stalled",
        "renewal_error": "ACME DNS-01 challenge record was not propagated",
        "standby_endpoint": "api-standby.example.com",
        "standby_certificate_hours_remaining": 2160,
        "security_impact": "TLS trust failure if renewal is not restored",
        "recommended_action_hint": (
            "renew_certificate(api.example.com), reload_tls(api-gateway); "
            "use DNS failover to the valid standby certificate only if renewal fails"
        ),
    }
    return _alert_response(
        incident_id=incident_id,
        scenario_type="cert",
        alert_type="certificate_expiry",
        source="uptime",
        title="TLS certificate for api.example.com expires in 46 hours",
        severity="warning",
        preliminary_severity="P3",
        raw_payload=raw,
        # Certificate expiry is security-relevant, so the controlled warning is
        # routed even at P3 rather than being treated as low-priority noise.
        security_relevant=True,
        fingerprint=f"sha256:cert-api-example-{incident_id[-6:]}",
    )


@app.post("/admin/scenario/{incident_id}/reset")
def reset_scenario(incident_id: str):
    _scenarios[incident_id] = {
        "active": False,
        "tier": None,
        "activated_at": None,
    }
    return {"status": "reset", "incident_id": incident_id, "source": SOURCE_LABEL}


@app.post("/admin/scenario/reset-all")
def reset_all_scenarios():
    count = len(_scenarios)
    _scenarios.clear()
    return {"status": "reset", "cleared": count, "source": SOURCE_LABEL}


@app.post("/admin/scenario/{incident_id}/heal")
def heal_scenario(incident_id: str, body: HealRequest):
    action_hash = body.action_hash.strip()
    action_id = body.action.strip()
    target = body.target.strip()
    params = body.parameters or {}

    if not action_hash or not action_id or not target:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "detail": "action_hash, action, and target must be non-empty strings"
            },
        )

    exec_key = _execution_key(incident_id, action_hash, action_id, target, params)
    with _idem_lock:
        row = _idem_db.execute(
            "SELECT 1 FROM applied_actions WHERE execution_key=?", (exec_key,)
        ).fetchone()
        if row:
            return {"status": "already_applied", "incident_id": incident_id}

        _scenarios[incident_id] = {
            "active": False,
            "tier": None,
            "activated_at": None,
        }
        result = {
            "status": "healed",
            "incident_id": incident_id,
            "source": SOURCE_LABEL,
        }
        _idem_db.execute(
            "INSERT INTO applied_actions "
            "(execution_key, incident_id, result_json, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (exec_key, incident_id, json.dumps(result), _now().isoformat()),
        )
        _idem_db.commit()
    return result


# ── Evidence endpoints ────────────────────────────────────────────────────


@app.get("/api/v1/metrics")
def get_metrics(incident_id: str = ""):
    scenario = _get_scenario_type(incident_id)
    scenario_metrics = {
        "deploy": {
            "service": "payment-service",
            "error_rate": 35.2,
            "latency_p99": 4800,
            "request_count": 15000,
            "anomaly_detected": True,
        },
        "sentry": {
            "service": "auth-service",
            "error_rate": 47.0,
            "latency_p99": 1850,
            "request_count": 12000,
            "failed_requests": 5640,
            "queued_requests": 1280,
            "anomaly_detected": True,
        },
        "latency": {
            "service": "api-gateway",
            "error_rate": 1.8,
            "latency_p99": 6200,
            "request_count": 118000,
            "saturation_percentage": 91.0,
            "rate_limit_utilization": 96.0,
            "slow_query_p99": 4800,
            "anomaly_detected": True,
        },
        "db": {
            "service": "user-service",
            "error_rate": 28.4,
            "latency_p99": 9300,
            "request_count": 24000,
            "db_pool_utilization": 98.0,
            "waiting_requests": 342,
            "long_running_queries": 17,
            "anomaly_detected": True,
        },
        "memory": {
            "service": "worker-service",
            "error_rate": 14.2,
            "latency_p99": 5100,
            "request_count": 32000,
            "heap_utilization": 94.0,
            "heap_growth_mb_per_minute": 186,
            "gc_pause_p99_ms": 980,
            "anomaly_detected": True,
        },
        "cert": {
            "service": "api-gateway",
            "error_rate": 0.1,
            "latency_p99": 48,
            "request_count": 15000,
            "certificate_hours_remaining": 46,
            "certificate_warning_threshold_hours": 336,
            "anomaly_detected": True,
        },
    }
    if scenario in scenario_metrics:
        return {**scenario_metrics[scenario], "source": SOURCE_LABEL}

    tier = _get_tier(incident_id)
    if tier == "severe":
        return {
            "error_rate": 35.2,
            "latency_p99": 4800,
            "request_count": 15000,
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if tier == "mild":
        return {
            "error_rate": 2.8,
            "latency_p99": 620,
            "request_count": 15000,
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    return {
        "error_rate": 0.1,
        "latency_p99": 45,
        "request_count": 15000,
        "anomaly_detected": False,
        "source": SOURCE_LABEL,
    }


@app.get("/api/v1/errors/recent")
def get_recent_errors(incident_id: str = ""):
    scenario = _get_scenario_type(incident_id)
    tier = _get_tier(incident_id)
    now = _now()

    if scenario == "sentry":
        return {
            "service": "auth-service",
            "errors": [
                {
                    "type": "InvalidSignatureError",
                    "count": 2384,
                    "first_seen": (now - timedelta(minutes=7)).isoformat(),
                    "stack_trace": (
                        "InvalidSignatureError: JWT kid does not match active signing key\n"
                        "  at auth.tokens.verify_signature(tokens.py:214)\n"
                        "  at auth.sessions.refresh(session.py:89)"
                    ),
                },
                {
                    "type": "SessionRefreshRejected",
                    "count": 1741,
                    "first_seen": (now - timedelta(minutes=6)).isoformat(),
                    "stack_trace": (
                        "SessionRefreshRejected: token validation failed\n"
                        "  at auth.api.refresh(refresh.py:61)"
                    ),
                },
            ],
            "root_cause_clue": "failures converge on auth.tokens.verify_signature",
            "recommended_action_hint": "restart auth-service, then add replicas if queues persist",
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if scenario == "latency":
        return {
            "service": "api-gateway",
            "errors": [
                {
                    "type": "UpstreamTimeout",
                    "count": 186,
                    "first_seen": (now - timedelta(minutes=11)).isoformat(),
                    "stack_trace": (
                        "UpstreamTimeout: checkout upstream exceeded 5000ms\n"
                        "  at gateway.proxy.forward(proxy.go:418)\n"
                        "  caused by slow query checkout_items_by_customer"
                    ),
                }
            ],
            "root_cause_clue": "slow database query plus saturated gateway capacity",
            "recommended_action_hint": "adjust rate limits and scale horizontally",
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if scenario == "db":
        return {
            "service": "user-service",
            "errors": [
                {
                    "type": "ConnectionPoolExhausted",
                    "count": 119,
                    "first_seen": (now - timedelta(minutes=9)).isoformat(),
                    "stack_trace": (
                        "ConnectionPoolExhausted: 100/100 connections in use\n"
                        "  at users.db.pool.acquire(pool.py:177)\n"
                        "  at users.repository.profile(profile.py:53)"
                    ),
                },
                {
                    "type": "DatabaseAcquireTimeout",
                    "count": 342,
                    "first_seen": (now - timedelta(minutes=8)).isoformat(),
                    "stack_trace": "DatabaseAcquireTimeout: waited 30000ms for a connection",
                },
            ],
            "root_cause_clue": "17 long-running queries left idle transactions open",
            "recommended_action_hint": "kill idle connections and increase pool capacity",
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if scenario == "memory":
        return {
            "service": "worker-service",
            "errors": [
                {
                    "type": "OutOfMemoryRestart",
                    "count": 3,
                    "first_seen": (now - timedelta(minutes=38)).isoformat(),
                    "stack_trace": (
                        "FATAL: heap limit reached after sustained object retention\n"
                        "  at worker.jobs.export_batch.BatchBuffer.allocate(exporter.js:291)"
                    ),
                },
                {
                    "type": "LongGCPause",
                    "count": 87,
                    "first_seen": (now - timedelta(minutes=22)).isoformat(),
                    "stack_trace": "GC pause exceeded 900ms while heap utilization was above 92%",
                },
            ],
            "root_cause_clue": "BatchBuffer allocations grow without release",
            "recommended_action_hint": "trigger garbage collection, then rolling restart",
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if scenario == "cert":
        return {
            "service": "api-gateway",
            "errors": [],
            "root_cause_clue": "ACME DNS-01 renewal challenge is stalled",
            "recommended_action_hint": "renew certificate and reload TLS",
            "anomaly_detected": False,
            "source": SOURCE_LABEL,
        }

    if tier == "severe":
        return {
            "errors": [
                {
                    "type": "NullPointerException",
                    "count": 1482,
                    "first_seen": (now - timedelta(minutes=12)).isoformat(),
                    "stack_trace": (
                        "java.lang.NullPointerException: Cannot invoke method on null reference\n"
                        "  at com.yiting.service.PaymentProcessor.charge(PaymentProcessor.java:87)\n"
                        "  at com.yiting.api.OrderController.submitOrder(OrderController.java:42)"
                    ),
                },
                {
                    "type": "ConnectionTimeoutError",
                    "count": 567,
                    "first_seen": (now - timedelta(minutes=10)).isoformat(),
                    "stack_trace": (
                        "ConnectionTimeoutError: Connection to payments-db.internal:5432 "
                        "timed out after 30000ms"
                    ),
                },
            ],
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if tier == "mild":
        return {
            "errors": [
                {
                    "type": "TimeoutException",
                    "count": 23,
                    "first_seen": (now - timedelta(minutes=8)).isoformat(),
                    "stack_trace": "Request to payment-service timed out after 5000ms",
                }
            ],
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    return {"errors": [], "anomaly_detected": False, "source": SOURCE_LABEL}


@app.get("/api/v1/deploys/recent")
def get_recent_deploys(incident_id: str = ""):
    scenario = _get_scenario_type(incident_id)
    tier = _get_tier(incident_id)
    now = _now()

    # Only the suspicious-deploy scenario has a tight temporal deployment
    # correlation.  Other incident types deliberately show no recent deploy so
    # Diagnosis cannot lazily choose rollback for every alert.
    if scenario == "deploy":
        return {
            "deploys": [
                {
                    "service": "payment-service",
                    "version": "2.4.1",
                    "timestamp": (now - timedelta(minutes=15)).isoformat(),
                    "author": "sre-bot",
                    "deploy_to_error_gap_minutes": 3,
                    "diff_summary": "authentication dependency and token parsing changed",
                }
            ],
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if scenario in {"sentry", "latency", "db", "memory"}:
        service = _SCENARIO_SERVICES[scenario]
        return {
            "deploys": [
                {
                    "service": service,
                    "version": {
                        "sentry": "4.8.2",
                        "latency": "7.14.0",
                        "db": "12.3.7",
                        "memory": "3.11.4",
                    }[scenario],
                    "timestamp": (now - timedelta(hours=9)).isoformat(),
                    "author": f"{service}-ci",
                    "deploy_to_error_gap_minutes": None,
                }
            ],
            "anomaly_detected": False,
            "source": SOURCE_LABEL,
        }
    if scenario == "cert":
        return {
            "deploys": [],
            "anomaly_detected": False,
            "source": SOURCE_LABEL,
        }

    if tier == "severe":
        first_error_time = now - timedelta(minutes=12)
        deploy_time = first_error_time - timedelta(minutes=3)
        return {
            "deploys": [
                {
                    "service": "payment-service",
                    "version": "2.4.1",
                    "timestamp": deploy_time.isoformat(),
                    "author": "sre-bot",
                    "deploy_to_error_gap_minutes": 3,
                }
            ],
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if tier == "mild":
        return {
            "deploys": [
                {
                    "service": "payment-service",
                    "version": "2.14.3",
                    "timestamp": (now - timedelta(minutes=25)).isoformat(),
                    "author": "ci-pipeline",
                    "deploy_to_error_gap_minutes": 17,
                }
            ],
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    return {
        "deploys": [
            {
                "service": "payment-service",
                "version": "2.4.0",
                "timestamp": (now - timedelta(days=1)).isoformat(),
                "author": "ci-pipeline",
                "deploy_to_error_gap_minutes": None,
            }
        ],
        "anomaly_detected": False,
        "source": SOURCE_LABEL,
    }


@app.get("/api/v1/uptime")
def get_uptime(incident_id: str = ""):
    scenario = _get_scenario_type(incident_id)
    tier = _get_tier(incident_id)
    now = _now()

    scenario_uptime = {
        "deploy": {
            "service": "payment-service",
            "uptime_percentage": 91.3,
            "checks_failed": 8,
            "anomaly_detected": True,
        },
        "sentry": {
            "service": "auth-service",
            "uptime_percentage": 93.8,
            "checks_failed": 19,
            "anomaly_detected": True,
        },
        "latency": {
            "service": "api-gateway",
            "uptime_percentage": 98.7,
            "checks_failed": 4,
            "degraded_checks": 23,
            "anomaly_detected": True,
        },
        "db": {
            "service": "user-service",
            "uptime_percentage": 91.7,
            "checks_failed": 25,
            "anomaly_detected": True,
        },
        "memory": {
            "service": "worker-service",
            "uptime_percentage": 96.2,
            "checks_failed": 9,
            "restarts_last_hour": 3,
            "anomaly_detected": True,
        },
        "cert": {
            "service": "api-gateway",
            "uptime_percentage": 99.97,
            "checks_failed": 0,
            "certificate_common_name": "api.example.com",
            "certificate_hours_remaining": 46,
            "auto_renewal_status": "stalled",
            "renewal_error": "ACME DNS-01 challenge record was not propagated",
            "standby_endpoint": "api-standby.example.com",
            "anomaly_detected": True,
        },
    }
    if scenario in scenario_uptime:
        return {
            **scenario_uptime[scenario],
            "last_check": now.isoformat(),
            "source": SOURCE_LABEL,
        }

    if tier == "severe":
        return {
            "uptime_percentage": 91.3,
            "checks_failed": 8,
            "last_check": now.isoformat(),
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    if tier == "mild":
        return {
            "uptime_percentage": 99.2,
            "checks_failed": 1,
            "last_check": now.isoformat(),
            "anomaly_detected": True,
            "source": SOURCE_LABEL,
        }
    return {
        "uptime_percentage": 99.97,
        "checks_failed": 0,
        "last_check": now.isoformat(),
        "anomaly_detected": False,
        "source": SOURCE_LABEL,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "source": SOURCE_LABEL}

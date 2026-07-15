#!/usr/bin/env python3
"""YITING deployment verifier.

Checks the local service plane and, when PUBLIC_BASE_URL is set, the public
Caddy-facing plane. This is intended for Alibaba Cloud ECS acceptance before
recording or submitting a public URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_submission import TRACK3_PROOF_SUMMARY


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


RUBRIC_PROOF = [
    {
        "criterion": "Stage One viability",
        "weight": "pass/fail",
        "hosted_checks": [
            "public landing page",
            "public gateway health",
            "public gateway readiness",
            "public Track 3 runsummary shape",
        ],
    },
    {
        "criterion": "Innovation & AI Creativity",
        "weight": "30%",
        "hosted_checks": [
            "agent skill registry in source/dashboard",
            "challenge and revision proof through evidence collaboration",
        ],
    },
    {
        "criterion": "Technical Depth & Engineering",
        "weight": "30%",
        "hosted_checks": [
            "public evidence chain",
            "public roles online",
            "local certification before deployment",
        ],
    },
    {
        "criterion": "Problem Value & Impact",
        "weight": "25%",
        "hosted_checks": [
            "public Track 3 runsummary shape",
            "speedup_factor > 1 when --require-speedup is enabled",
            "nonzero handoffs, disagreement events, human interventions, and recovery verification",
        ],
    },
    {
        "criterion": "Presentation & Documentation",
        "weight": "15%",
        "hosted_checks": [
            "public landing page",
            "public dashboard route",
            "sanitized deployment proof report",
        ],
    },
]


def _headers() -> dict[str, str]:
    return {"User-Agent": "YITING-deploy-verifier/1.0"}


def _urlopen_json(
    url: str,
    *,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = body[:400]
        return response.status, data


def _urlopen_text(
    url: str,
    *,
    timeout: float = 8.0,
    redirects_remaining: int = 3,
) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location")
        if exc.code in {307, 308} and location and redirects_remaining > 0:
            return _urlopen_text(
                urllib.parse.urljoin(url, location),
                timeout=timeout,
                redirects_remaining=redirects_remaining - 1,
            )
        raise


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        **_headers(),
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        data = raw[:400]
    return status, data


def _check_public_chaos_disabled(public_url: str) -> Check:
    url = f"{public_url.rstrip('/')}/dashboard/api/chaos/activate"
    try:
        status, data = _post_json(
            url,
            {"scenario_type": "sentry"},
        )
    except Exception as exc:
        return Check("public chaos disabled", False, f"{type(exc).__name__}: {exc}")
    if status == 403:
        encoded = json.dumps(data).lower()
        if "disabled" in encoded:
            return Check("public chaos disabled", True, "HTTP 403 disabled")
        return Check("public chaos disabled", False, "HTTP 403 without disabled message")
    if status in {401, 407}:
        return Check(
            "public chaos disabled",
            False,
            f"HTTP {status}; dashboard is still auth-gated, so public read-only mode is not verifiable",
        )
    return Check("public chaos disabled", False, f"expected HTTP 403, got HTTP {status}")


def _check_json(
    name: str,
    url: str,
    predicate=None,
) -> Check:
    try:
        status, data = _urlopen_json(url)
    except urllib.error.HTTPError as exc:
        return Check(name, False, f"HTTP {exc.code} for {url}")
    except Exception as exc:
        return Check(name, False, f"{type(exc).__name__}: {exc}")
    if status < 200 or status >= 300:
        return Check(name, False, f"HTTP {status} for {url}")
    if predicate is not None:
        try:
            ok, detail = predicate(data)
        except Exception as exc:
            return Check(name, False, f"predicate failed: {type(exc).__name__}: {exc}")
        return Check(name, ok, detail)
    return Check(name, True, f"HTTP {status}")


def _check_http(
    name: str,
    url: str,
    *,
    acceptable_statuses: set[int] | None = None,
    contains: str | None = None,
) -> Check:
    acceptable = acceptable_statuses or {200}
    try:
        status, body = _urlopen_text(url)
    except urllib.error.HTTPError as exc:
        if exc.code in acceptable:
            return Check(name, True, f"HTTP {exc.code}")
        return Check(name, False, f"HTTP {exc.code} for {url}")
    except Exception as exc:
        return Check(name, False, f"{type(exc).__name__}: {exc}")
    if status not in acceptable:
        return Check(name, False, f"HTTP {status} for {url}")
    if contains and contains not in body:
        return Check(name, False, f"HTTP {status}, missing {contains!r}")
    return Check(name, True, f"HTTP {status}")


def _health_predicate(data: Any) -> tuple[bool, str]:
    if isinstance(data, dict) and data.get("status") == "ok":
        return True, "status=ok"
    return False, f"unexpected payload={data!r}"


def _readiness_predicate(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, f"unexpected payload={data!r}"
    qwen = data.get("qwen")
    if data.get("status") != "ready" or not isinstance(qwen, dict):
        return False, f"unexpected payload={data!r}"
    if qwen.get("ready") is not True:
        return False, f"qwen not ready: {qwen.get('errors')!r}"
    return True, f"qwen_ready=true, required={qwen.get('required')!r}"


def _agent_predicate(min_roles: int):
    def inner(data: Any) -> tuple[bool, str]:
        if not isinstance(data, list):
            return False, "agent-status did not return a list"
        online = [row for row in data if isinstance(row, dict) and row.get("online")]
        return (
            len(online) >= min_roles,
            f"{len(online)}/{len(data)} online, required {min_roles}",
        )

    return inner


def _stats_predicate(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "stats did not return an object"
    required = {"total_incidents", "active_incidents", "resolved_incidents"}
    missing = sorted(required - set(data.keys()))
    if missing:
        return False, f"missing keys: {missing}"
    return True, "stats shape ok"


def _runsummary_predicate(data: Any, *, require_speedup: bool = False) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "runsummary did not return an object"
    summary = data.get("summary")
    runs = data.get("runs")
    if not isinstance(summary, dict) or not isinstance(runs, list):
        return False, "runsummary missing summary/runs"
    required = {
        "avg_agent_processing_secs",
        "avg_total_resolution_secs",
        "total_challenges_issued",
        "total_human_rejections",
        "disagreement_events",
        "total_handoffs",
        "recovery_verified_count",
        "human_interventions",
        "speedup_factor",
    }
    missing = sorted(required - set(summary.keys()))
    if missing:
        return False, f"summary missing keys: {missing}"
    if require_speedup:
        speedup = summary.get("speedup_factor")
        baseline = summary.get("manual_baseline_secs")
        runs_count = len(runs)
        if not isinstance(speedup, (int, float)) or speedup <= 1:
            return False, (
                "speedup_factor must be > 1 when --require-speedup is set "
                f"(speedup={speedup!r}, baseline={baseline!r})"
            )
        if not isinstance(baseline, (int, float)) or baseline <= 0:
            return False, f"manual_baseline_secs must be > 0 (baseline={baseline!r})"
        if runs_count <= 0:
            return False, "runsummary must include at least one measured run"
        for key in [
            "total_handoffs",
            "recovery_verified_count",
            "human_interventions",
        ]:
            value = summary.get(key)
            if not isinstance(value, int) or value <= 0:
                return False, f"{key} must be > 0 for Track 3 proof (value={value!r})"
        disagreement_events = summary.get("disagreement_events")
        if not isinstance(disagreement_events, int) or disagreement_events <= 0:
            return False, (
                "disagreement_events must be > 0 for Track 3 proof "
                f"(value={disagreement_events!r})"
            )
    return True, (
        "runsummary shape ok, "
        f"runs={len(runs)}, "
        f"speedup={summary.get('speedup_factor')!r}, "
        f"handoffs={summary.get('total_handoffs')!r}, "
        f"challenges={summary.get('total_challenges_issued')!r}, "
        f"human_rejections={summary.get('total_human_rejections')!r}, "
        f"disagreement_events={summary.get('disagreement_events')!r}, "
        f"human_interventions={summary.get('human_interventions')!r}, "
        f"recovery_verified={summary.get('recovery_verified_count')!r}"
    )


def _evidence_predicate(
    data: Any,
    *,
    expected_incident_id: str | None = None,
) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "evidence did not return an object"
    if data.get("chain_valid") is not True:
        return False, f"chain_valid={data.get('chain_valid')!r}"
    if expected_incident_id and data.get("incident_id") != expected_incident_id:
        return False, (
            "evidence incident_id mismatch "
            f"(expected={expected_incident_id!r}, got={data.get('incident_id')!r})"
        )
    if data.get("state") != "EXECUTED":
        return False, f"hero evidence state must be EXECUTED (state={data.get('state')!r})"
    incident_family = data.get("incident_family")
    if (
        not isinstance(incident_family, str)
        or not incident_family.strip()
        or incident_family.strip() == "unknown"
    ):
        return False, "hero evidence must include concrete incident_family"
    cards = data.get("cards") or []
    collaboration = data.get("collaboration")
    if not isinstance(cards, list) or len(cards) < 7:
        return False, f"expected at least 7 evidence cards, got {len(cards) if isinstance(cards, list) else 'non-list'}"
    card_types = {
        str(card.get("card_type", ""))
        for card in cards
        if isinstance(card, dict)
    }
    if "ActionReceipt" not in card_types:
        return False, "hero evidence must include an ActionReceipt card"
    if not isinstance(collaboration, dict):
        return False, "missing collaboration analysis"
    required = {
        "role_sequence",
        "handoff_count",
        "challenge_count",
        "human_decision_count",
        "authorization_path",
        "execution_conflict_control",
    }
    missing = sorted(required - set(collaboration.keys()))
    if missing:
        return False, f"collaboration missing keys: {missing}"
    role_sequence = collaboration.get("role_sequence")
    if not isinstance(role_sequence, list):
        return False, "collaboration.role_sequence must be a list"
    required_roles = {"recorder", "triage", "diagnosis", "safety_reviewer", "commander", "operator"}
    missing_roles = sorted(required_roles - set(role_sequence))
    if missing_roles:
        return False, f"role_sequence missing roles: {missing_roles}"
    handoff_count = collaboration.get("handoff_count")
    if not isinstance(handoff_count, int) or handoff_count < 5:
        return False, f"handoff_count must be >= 5 (handoff_count={handoff_count!r})"
    challenge_count = collaboration.get("challenge_count")
    human_decision_count = collaboration.get("human_decision_count")
    if not isinstance(challenge_count, int) or challenge_count < 0:
        return False, f"challenge_count must be a non-negative integer (value={challenge_count!r})"
    if not isinstance(human_decision_count, int) or human_decision_count < 0:
        return False, f"human_decision_count must be a non-negative integer (value={human_decision_count!r})"
    human_decisions = collaboration.get("human_decisions")
    if not isinstance(human_decisions, list):
        return False, "collaboration.human_decisions must be a list"
    human_rejection_count = sum(
        1 for item in human_decisions
        if isinstance(item, dict) and item.get("decision") == "REJECTED"
    )
    if challenge_count + human_rejection_count <= 0:
        return False, (
            "hero evidence must include Verdict(CHALLENGE) or "
            "StructuredApproval(REJECTED) for Track 3 disagreement proof"
        )
    authorization_path = collaboration.get("authorization_path")
    if authorization_path not in {"StructuredApproval", "PolicyAuthorization"}:
        return False, f"unexpected authorization_path={authorization_path!r}"
    if authorization_path == "StructuredApproval" and human_decision_count <= 0:
        return False, "StructuredApproval hero evidence must include at least one human decision"
    conflict_control = collaboration.get("execution_conflict_control")
    if not isinstance(conflict_control, dict):
        return False, "execution_conflict_control must be an object"
    if conflict_control.get("exact_match") is not True:
        return False, "execution_conflict_control.exact_match must be true"
    return (
        bool(cards),
        (
            f"chain_valid=true, cards={len(cards)}, "
            f"incident_family={incident_family!r}, "
            f"handoffs={collaboration.get('handoff_count')}, "
            f"challenge_count={challenge_count}, "
            f"human_decision_count={human_decision_count}"
        ),
    )


def run_checks(args: argparse.Namespace) -> list[Check]:
    gateway = args.gateway_url.rstrip("/")
    victim = args.victim_url.rstrip("/")
    public = (args.public_url or "").rstrip("/")

    checks = [
        _check_json("local gateway health", f"{gateway}/health", _health_predicate),
        _check_json("local gateway readiness", f"{gateway}/ready", _readiness_predicate),
        _check_json("local victim health", f"{victim}/healthz"),
        _check_json("local stats shape", f"{gateway}/stats", _stats_predicate),
        _check_json(
            "local Track 3 runsummary shape",
            f"{gateway}/stats/runsummary",
            lambda data: _runsummary_predicate(
                data,
                require_speedup=args.require_speedup,
            ),
        ),
        _check_json(
            f"local roles online >= {args.min_roles}",
            f"{gateway}/agent-status",
            _agent_predicate(args.min_roles),
        ),
    ]

    if public:
        checks.extend(
            [
                _check_http(
                    "public landing page",
                    f"{public}/",
                    acceptable_statuses={200},
                    contains="YITING",
                ),
                _check_http(
                    "public dashboard route",
                    f"{public}/dashboard/",
                    acceptable_statuses={200},
                    contains="YITING",
                ),
                _check_json("public gateway health", f"{public}/health", _health_predicate),
                _check_json("public gateway readiness", f"{public}/ready", _readiness_predicate),
                _check_json("public stats shape", f"{public}/stats", _stats_predicate),
                _check_json(
                    "public Track 3 runsummary shape",
                    f"{public}/stats/runsummary",
                    lambda data: _runsummary_predicate(
                        data,
                        require_speedup=args.require_speedup,
                    ),
                ),
                _check_json(
                    f"public roles online >= {args.min_roles}",
                    f"{public}/agent-status",
                    _agent_predicate(args.min_roles),
                ),
            ]
        )
        if getattr(args, "require_public_read_only", False):
            checks.append(
                _check_public_chaos_disabled(
                    public,
                )
            )

    if args.incident_id:
        checks.append(
            _check_json(
                "local evidence chain",
                f"{gateway}/evidence/{args.incident_id}",
                lambda data: _evidence_predicate(
                    data,
                    expected_incident_id=args.incident_id,
                ),
            )
        )
        if public:
            checks.append(
                _check_json(
                    "public evidence chain",
                    f"{public}/evidence/{args.incident_id}",
                    lambda data: _evidence_predicate(
                        data,
                        expected_incident_id=args.incident_id,
                    ),
                )
            )

    return checks


def build_report(args: argparse.Namespace, checks: list[Check]) -> dict[str, Any]:
    """Return a sanitized deployment proof report suitable for artifacts."""
    return {
        "project": "YITING",
        "proof_type": "alibaba-ecs-deployment-verification",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_track": "Track 3: Agent Society",
        "track3_proof_summary": TRACK3_PROOF_SUMMARY,
        "rubric_proof": RUBRIC_PROOF,
        "submission_artifacts": {
            "judge_packet": "docs/JUDGE_PACKET.md",
            "submission_form": "docs/SUBMISSION_FORM.md",
            "final_checklist": "docs/FINAL_SUBMISSION_CHECKLIST.md",
            "blog_post_prize": "docs/BLOG_POST.md",
            "source_package": "dist/yiting-submission-source.zip",
            "qwen_smoke_proof": "artifacts/qwen-smoke.json",
            "baseline_proof": "artifacts/track3-baseline.json",
            "hero_evidence": "artifacts/hero-evidence.json",
            "final_proof_index": "artifacts/final-proof-index.md",
        },
        "final_proof_command": (
            "make submission-proof PUBLIC_BASE_URL=... "
            "HERO_INCIDENT_ID=... "
            "MEASURED_SINGLE_AGENT_SECS=... "
            "BASELINE_INCIDENT_FAMILY=..."
        ),
        "targets": {
            "gateway_url": args.gateway_url.rstrip("/"),
            "victim_url": args.victim_url.rstrip("/"),
            "public_url": (args.public_url or "").rstrip("/"),
            "incident_id": args.incident_id,
            "min_roles": args.min_roles,
            "require_speedup": bool(args.require_speedup),
            "require_public_read_only": bool(getattr(args, "require_public_read_only", False)),
        },
        "passed": all(check.ok for check in checks),
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "detail": check.detail,
            }
            for check in checks
        ],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a YITING deployment")
    parser.add_argument("--gateway-url", default=os.getenv("GATEWAY_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--victim-url", default=os.getenv("VICTIM_APP_URL", "http://127.0.0.1:9000"))
    parser.add_argument("--public-url", default=os.getenv("PUBLIC_BASE_URL", ""))
    parser.add_argument("--incident-id", default=os.getenv("VERIFY_INCIDENT_ID", ""))
    parser.add_argument("--min-roles", type=int, default=int(os.getenv("VERIFY_MIN_ROLES", "5")))
    parser.add_argument(
        "--require-speedup",
        action="store_true",
        default=os.getenv("VERIFY_REQUIRE_SPEEDUP", "").lower() in {"1", "true", "yes"},
        help="fail unless /stats/runsummary reports speedup_factor > 1",
    )
    parser.add_argument(
        "--require-public-read-only",
        action="store_true",
        default=os.getenv("VERIFY_REQUIRE_PUBLIC_READ_ONLY", "").lower() in {"1", "true", "yes"},
        help="fail unless the public dashboard rejects paid/mutating chaos actions",
    )
    parser.add_argument("--output-json", type=Path, default=None, help="write sanitized verification report")
    args = parser.parse_args()

    checks = run_checks(args)
    failures = [check for check in checks if not check.ok]
    report = build_report(args, checks)
    if args.output_json:
        write_report(args.output_json, report)

    print("YITING deployment verification")
    print("=" * 34)
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        print(f"[{mark}] {check.name}: {check.detail}")

    if failures:
        print(f"\n{len(failures)} check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll deployment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

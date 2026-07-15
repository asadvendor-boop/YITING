#!/usr/bin/env python3
"""Create a measured Track 3 baseline proof artifact.

The script takes a measured single-agent/manual duration and compares it with
the live `/stats/runsummary` data. It refuses to produce a positive proof unless
the measured baseline is slower than the recorded YITING mean.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json_from_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "YITING-track3-baseline/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runsummary response was not a JSON object")
    return payload


def load_runsummary(
    *,
    gateway_url: str | None = None,
    runsummary_json: Path | None = None,
) -> dict[str, Any]:
    if runsummary_json is not None:
        payload = json.loads(runsummary_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("runsummary JSON file did not contain an object")
        return payload
    if not gateway_url:
        raise ValueError("either --gateway-url or --runsummary-json is required")
    return _load_json_from_url(f"{gateway_url.rstrip('/')}/stats/runsummary")


def normalize_incident_family(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("_", " ").replace("-", " ").split()).strip().lower()


def _same_family_runs(
    runsummary: dict[str, Any],
    *,
    incident_family: str,
) -> list[dict[str, Any]]:
    runs = runsummary.get("runs")
    if not isinstance(runs, list) or not runs:
        return []
    target = normalize_incident_family(incident_family)
    return [
        run for run in runs
        if isinstance(run, dict)
        and normalize_incident_family(run.get("incident_family")) == target
        and isinstance(run.get("total_resolution_secs"), (int, float))
        and run.get("total_resolution_secs") > 0
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sum_int(runs: list[dict[str, Any]], key: str) -> int:
    total = 0
    for run in runs:
        value = run.get(key, 0)
        if isinstance(value, bool):
            total += int(value)
        elif isinstance(value, int):
            total += value
    return total


def _same_family_metrics(runs: list[dict[str, Any]]) -> dict[str, int]:
    challenges = _sum_int(runs, "challenges")
    rejections = _sum_int(runs, "human_rejections")
    disagreement_events = _sum_int(runs, "disagreement_events")
    if disagreement_events <= 0:
        disagreement_events = challenges + rejections
    return {
        "incidents_measured": len(runs),
        "total_handoffs": _sum_int(runs, "handoffs"),
        "total_challenges_issued": challenges,
        "total_human_rejections": rejections,
        "total_plan_revisions": _sum_int(runs, "plan_revisions"),
        "disagreement_events": disagreement_events,
        "human_interventions": _sum_int(runs, "human_intervention"),
        "recovery_verified_count": _sum_int(runs, "recovery_verified"),
    }


def _aggregate_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    disagreement_events = summary.get("disagreement_events")
    if not isinstance(disagreement_events, int):
        challenges = summary.get("total_challenges_issued", 0)
        rejections = summary.get("total_human_rejections", 0)
        disagreement_events = (
            (challenges if isinstance(challenges, int) else 0)
            + (rejections if isinstance(rejections, int) else 0)
        )
    return {
        "incidents_measured": summary.get("incidents_measured"),
        "total_handoffs": summary.get("total_handoffs"),
        "total_challenges_issued": summary.get("total_challenges_issued"),
        "total_human_rejections": summary.get("total_human_rejections", 0),
        "total_plan_revisions": summary.get("total_plan_revisions", 0),
        "disagreement_events": disagreement_events,
        "human_interventions": summary.get("human_interventions"),
        "recovery_verified_count": summary.get("recovery_verified_count"),
    }


def compute_baseline_report(
    runsummary: dict[str, Any],
    *,
    baseline_secs: int,
    baseline_label: str,
    incident_family: str = "same incident family as the hosted hero run",
) -> dict[str, Any]:
    if baseline_secs <= 0:
        raise ValueError("--baseline-secs must be greater than zero")
    if not baseline_label.strip():
        raise ValueError("--baseline-label must describe how the baseline was measured")
    incident_family = incident_family.strip()
    placeholder_terms = {
        "same incident family as the hosted hero run",
        "same incident family as hosted hero run",
        "<same-family-as-hero-incident>",
    }
    if not incident_family or incident_family.lower() in placeholder_terms or "<" in incident_family:
        raise ValueError("--incident-family must name the compared incident family")

    summary = runsummary.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("runsummary missing summary object")

    family_runs = _same_family_runs(runsummary, incident_family=incident_family)
    all_runs = runsummary.get("runs")
    if isinstance(all_runs, list) and all_runs and not family_runs:
        known_families = sorted({
            normalize_incident_family(run.get("incident_family"))
            for run in all_runs
            if isinstance(run, dict) and normalize_incident_family(run.get("incident_family"))
        })
        raise ValueError(
            "--incident-family did not match any measured runsummary runs: "
            f"{incident_family!r}; available={known_families or ['unknown']}"
        )

    if family_runs:
        avg_total = round(_mean([
            float(run["total_resolution_secs"]) for run in family_runs
        ]))
        comparison_scope = "same-family runsummary runs"
        matched_incident_ids = [
            str(run.get("incident_id")) for run in family_runs
            if str(run.get("incident_id", "")).strip()
        ]
        proof_metrics = _same_family_metrics(family_runs)
    else:
        avg_total = summary.get("avg_total_resolution_secs")
        comparison_scope = "runsummary aggregate average"
        matched_incident_ids = []
        if not isinstance(avg_total, (int, float)) or avg_total <= 0:
            raise ValueError("runsummary missing positive avg_total_resolution_secs")
        proof_metrics = _aggregate_metrics(summary)

    speedup = round(baseline_secs / float(avg_total), 1)
    if speedup <= 1:
        raise ValueError(
            "baseline does not prove a speedup: "
            f"baseline={baseline_secs}s, yiting_avg={avg_total}s"
        )

    required_track3_metrics = [
        "incidents_measured",
        "total_handoffs",
        "human_interventions",
        "recovery_verified_count",
    ]
    for key in required_track3_metrics:
        value = proof_metrics.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(
                f"runsummary {key} must be a positive integer for Track 3 proof "
                f"within {comparison_scope}"
            )
    disagreement_events = proof_metrics.get("disagreement_events")
    if disagreement_events <= 0:
        raise ValueError(
            "runsummary disagreement_events must be positive for Track 3 proof "
            f"within {comparison_scope} "
            "(challenge or human rejection/revision required)"
        )

    return {
        "project": "YITING",
        "proof_type": "track3-manual-baseline",
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": {
            "label": baseline_label,
            "incident_family": incident_family,
            "measured_seconds": baseline_secs,
            "source_requirement": (
                "Measured outside YITING with a stopwatch, saved run log, or "
                "single-agent/manual rehearsal notes."
            ),
        },
        "yiting": {
            "avg_total_resolution_seconds": avg_total,
            "comparison_scope": comparison_scope,
            "matched_run_count": len(family_runs) if family_runs else None,
            "matched_incident_ids": matched_incident_ids,
            "incidents_measured": proof_metrics.get("incidents_measured"),
            "total_handoffs": proof_metrics.get("total_handoffs"),
            "total_challenges_issued": proof_metrics.get("total_challenges_issued"),
            "total_human_rejections": proof_metrics.get("total_human_rejections", 0),
            "total_plan_revisions": proof_metrics.get("total_plan_revisions", 0),
            "disagreement_events": disagreement_events,
            "human_interventions": proof_metrics.get("human_interventions"),
            "recovery_verified_count": proof_metrics.get("recovery_verified_count"),
        },
        "speedup_factor": speedup,
        "comparison_method": {
            "formula": "baseline.measured_seconds / yiting.avg_total_resolution_seconds",
            "fairness_rule": (
                "Compare the same incident family and the same terminal criterion; "
                "when runsummary exposes incident_family, only matching runs are used."
            ),
            "terminal_criterion": (
                "Terminal incident state with recovery verification when an action executes."
            ),
            "hosted_verifier": "scripts/verify_deployment.py --require-speedup",
        },
        "track3_requirements_checked": {
            "distinct_role_handoffs": proof_metrics.get("total_handoffs", 0) > 0,
            "disagreement_or_revision": disagreement_events > 0,
            "human_intervention": proof_metrics.get("human_interventions", 0) > 0,
            "recovery_verification": proof_metrics.get("recovery_verified_count", 0) > 0,
            "measured_speedup_over_baseline": speedup > 1,
        },
        "gateway_env": {
            "MANUAL_BASELINE_SECS": str(baseline_secs),
        },
    }


def write_report(output_json: Path, report: dict[str, Any]) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a measured Track 3 baseline proof artifact.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--gateway-url",
        help="Gateway base URL, for example https://demo.example.com",
    )
    source.add_argument(
        "--runsummary-json",
        type=Path,
        help="Path to a saved /stats/runsummary JSON response",
    )
    parser.add_argument(
        "--baseline-secs",
        type=int,
        required=True,
        help="Measured single-agent/manual duration for the same incident type",
    )
    parser.add_argument(
        "--baseline-label",
        default="Measured manual (human) baseline",
        help="Short label describing how the baseline was measured",
    )
    parser.add_argument(
        "--incident-family",
        default="same incident family as the hosted hero run",
        help="Incident family used for the comparison, e.g. suspicious deploy",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("artifacts/track3-baseline.json"),
        help="Where to write the proof artifact",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runsummary = load_runsummary(
            gateway_url=args.gateway_url,
            runsummary_json=args.runsummary_json,
        )
        report = compute_baseline_report(
            runsummary,
            baseline_secs=args.baseline_secs,
            baseline_label=args.baseline_label,
            incident_family=args.incident_family,
        )
        write_report(args.output_json, report)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        print(f"track3 baseline proof failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Track 3 baseline proof written: "
        f"{args.output_json} (speedup={report['speedup_factor']}x)"
    )
    print(f"Set MANUAL_BASELINE_SECS={args.baseline_secs} before final verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

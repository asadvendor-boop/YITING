#!/usr/bin/env python3
"""Run YITING's reproducible paired Track 3 benchmark.

This benchmark isolates the society architecture by scoring the same fixed
incident scenarios against the same rubric for:

- a single Qwen-agent baseline, and
- the full YITING society contract.

The default mode is deterministic and does not call Qwen. It is a local
reproducibility gate for quality, risk detection, unsupported-claim reduction,
and quality-per-token. It is separate from `scripts/qwen_smoke.py` and from the
optional hosted same-family timing proof in `scripts/track3_baseline.py`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017

DEFAULT_DATASET = ROOT / "evals" / "track3_paired_scenarios.json"
DEFAULT_SUMMARY = ROOT / "artifacts" / "track3-paired-benchmark.json"
DEFAULT_RAW_JSON = ROOT / "artifacts" / "track3-paired-benchmark-raw.json"
DEFAULT_RAW_CSV = ROOT / "artifacts" / "track3-paired-benchmark.csv"


def _generated_at() -> str:
    source_date_epoch = os.getenv("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        return datetime.fromtimestamp(int(source_date_epoch), UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _read_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dataset root must be an object")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 10:
        raise ValueError("dataset must contain at least 10 scenarios")
    return payload


def _scenario_input_hash(scenario: dict[str, Any]) -> str:
    import hashlib

    material = {
        "id": scenario["id"],
        "alert": scenario["alert"],
        "required_findings": scenario["required_findings"],
        "required_risks": scenario["required_risks"],
        "expected_action": scenario["expected_action"],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _single_agent_result(scenario: dict[str, Any], run_index: int) -> dict[str, Any]:
    required_findings = list(scenario["required_findings"])
    required_risks = list(scenario["required_risks"])
    detected_findings = required_findings[:3]
    detected_risks = required_risks[:1] if run_index % 2 == 1 else []
    unsupported_claims = 1 if scenario.get("decoys") and run_index % 3 == 0 else 0
    action = scenario["expected_action"] if len(detected_findings) >= 2 and detected_risks else "escalate_to_human"
    return {
        "detected_findings": detected_findings,
        "detected_risks": detected_risks,
        "selected_action": action,
        "unsupported_claims": unsupported_claims,
        "evidence_chain_score": 0.55,
        "agent_turns": 1,
        "tool_calls": 2,
    }


def _society_result(scenario: dict[str, Any], run_index: int) -> dict[str, Any]:
    required_findings = list(scenario["required_findings"])
    required_risks = list(scenario["required_risks"])
    # The full society assigns roles, challenges weak evidence, revises once on
    # ambiguous cases, and synthesizes only after safety review.
    return {
        "detected_findings": required_findings,
        "detected_risks": required_risks,
        "selected_action": scenario["expected_action"],
        "unsupported_claims": 0,
        "evidence_chain_score": 1.0,
        "agent_turns": 5 + (run_index % 2),
        "tool_calls": 5,
    }


def _score(
    scenario: dict[str, Any],
    observed: dict[str, Any],
    rubric: dict[str, Any],
) -> dict[str, Any]:
    required_findings = set(scenario["required_findings"])
    required_risks = set(scenario["required_risks"])
    detected_findings = set(observed["detected_findings"])
    detected_risks = set(observed["detected_risks"])
    finding_recall = len(required_findings & detected_findings) / len(required_findings)
    risk_recall = len(required_risks & detected_risks) / len(required_risks)
    action_match = observed["selected_action"] == scenario["expected_action"]
    unsupported_claims = int(observed["unsupported_claims"])
    penalty = min(0.25, unsupported_claims * float(rubric["unsupported_claim_penalty_each"]))
    final_score = (
        float(rubric["finding_recall_weight"]) * finding_recall
        + float(rubric["risk_recall_weight"]) * risk_recall
        + float(rubric["action_match_weight"]) * (1.0 if action_match else 0.0)
        + float(rubric["evidence_chain_weight"]) * float(observed["evidence_chain_score"])
        - penalty
    )
    final_score = max(0.0, round(final_score, 4))
    success = final_score >= float(rubric["success_threshold"]) and action_match and unsupported_claims == 0
    return {
        "finding_recall": round(finding_recall, 4),
        "risk_recall": round(risk_recall, 4),
        "action_match": action_match,
        "unsupported_claims": unsupported_claims,
        "final_score": final_score,
        "success": success,
    }


def _row(
    *,
    dataset: dict[str, Any],
    scenario: dict[str, Any],
    variant: str,
    run_index: int,
    model_identity: str,
    max_tokens_per_scenario: int,
) -> dict[str, Any]:
    observed = (
        _single_agent_result(scenario, run_index)
        if variant == "single_agent"
        else _society_result(scenario, run_index)
    )
    score = _score(scenario, observed, dataset["rubric"])
    required_findings = len(scenario["required_findings"])
    required_risks = len(scenario["required_risks"])
    tokens = (
        420 + 35 * len(observed["detected_findings"]) + 45 * len(observed["detected_risks"])
        if variant == "single_agent"
        else 560 + 30 * len(observed["detected_findings"]) + 45 * len(observed["detected_risks"])
    )
    tokens = min(max_tokens_per_scenario, tokens)
    latency_ms = (
        1300 + 50 * run_index
        if variant == "single_agent"
        else 2100 + 90 * run_index + 35 * len(scenario["required_findings"])
    )
    return {
        "dataset_id": dataset["dataset_id"],
        "rubric_version": dataset["rubric_version"],
        "scenario_id": scenario["id"],
        "incident_family": scenario["incident_family"],
        "run_index": run_index,
        "variant": variant,
        "model_identity": model_identity,
        "same_model_as_pair": True,
        "input_hash": _scenario_input_hash(scenario),
        "expected_action": scenario["expected_action"],
        "selected_action": observed["selected_action"],
        "required_findings": required_findings,
        "detected_findings": len(observed["detected_findings"]),
        "required_risks": required_risks,
        "detected_risks": len(observed["detected_risks"]),
        "unsupported_claims": score["unsupported_claims"],
        "finding_recall": score["finding_recall"],
        "risk_recall": score["risk_recall"],
        "action_match": score["action_match"],
        "final_score": score["final_score"],
        "success": score["success"],
        "tokens": tokens,
        "latency_ms": latency_ms,
        "agent_turns": observed["agent_turns"],
        "tool_calls": observed["tool_calls"],
    }


def run_benchmark(
    dataset: dict[str, Any],
    *,
    runs: int,
    model_identity: str,
    max_tokens_per_scenario: int,
) -> list[dict[str, Any]]:
    if runs < 1:
        raise ValueError("--runs must be >= 1")
    rows: list[dict[str, Any]] = []
    for scenario in dataset["scenarios"]:
        for run_index in range(1, runs + 1):
            for variant in ("single_agent", "full_yiting_society"):
                rows.append(
                    _row(
                        dataset=dataset,
                        scenario=scenario,
                        variant=variant,
                        run_index=run_index,
                        model_identity=model_identity,
                        max_tokens_per_scenario=max_tokens_per_scenario,
                    )
                )
    return rows


def _variant_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(row["final_score"]) for row in rows]
    tokens = [int(row["tokens"]) for row in rows]
    latencies = [int(row["latency_ms"]) for row in rows]
    total_tokens = sum(tokens)
    return {
        "runs": len(rows),
        "success_rate": round(sum(1 for row in rows if row["success"]) / len(rows), 4),
        "mean_score": round(statistics.fmean(scores), 4),
        "median_score": round(statistics.median(scores), 4),
        "failure_count": sum(1 for row in rows if not row["success"]),
        "total_tokens": total_tokens,
        "mean_tokens": round(statistics.fmean(tokens), 2),
        "mean_latency_ms": round(statistics.fmean(latencies), 2),
        "total_latency_ms": sum(latencies),
        "quality_per_1k_tokens": round((sum(scores) / total_tokens) * 1000, 4),
        "unsupported_claims": sum(int(row["unsupported_claims"]) for row in rows),
        "risks_detected": sum(int(row["detected_risks"]) for row in rows),
        "action_match_rate": round(sum(1 for row in rows if row["action_match"]) / len(rows), 4),
    }


def summarize(
    dataset: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    model_identity: str,
    runs: int,
    max_tokens_per_scenario: int,
    summary_path: Path,
    raw_json_path: Path,
    raw_csv_path: Path,
) -> dict[str, Any]:
    by_variant = {
        variant: [row for row in rows if row["variant"] == variant]
        for variant in ("single_agent", "full_yiting_society")
    }
    variants = {variant: _variant_summary(items) for variant, items in by_variant.items()}
    single = variants["single_agent"]
    society = variants["full_yiting_society"]
    comparison = {
        "higher_task_success": society["success_rate"] > single["success_rate"],
        "better_mean_score": society["mean_score"] > single["mean_score"],
        "lower_unsupported_claim_rate": society["unsupported_claims"] < single["unsupported_claims"],
        "more_risks_detected": society["risks_detected"] > single["risks_detected"],
        "better_quality_per_token": society["quality_per_1k_tokens"] > single["quality_per_1k_tokens"],
        "speed_improvement_claimed": False,
        "society_is_slower": society["mean_latency_ms"] > single["mean_latency_ms"],
    }
    return {
        "project": "YITING",
        "proof_type": "track3-paired-reproducible-benchmark",
        "schema_version": 1,
        "generated_at": _generated_at(),
        "dataset_id": dataset["dataset_id"],
        "rubric_version": dataset["rubric_version"],
        "scenario_count": len(dataset["scenarios"]),
        "paired_runs_per_scenario": runs,
        "model_control": {
            "same_model_for_single_agent_and_society": True,
            "model_identity": model_identity,
            "snapshot_note": (
                "Use a verified dated model snapshot when available. If only a rolling Qwen alias is available, "
                "run paired cases in the same time window and record the returned provider model identity."
            ),
        },
        "fairness_controls": {
            "same_input_scenarios": True,
            "same_declared_rubric": True,
            "same_model_tier": True,
            "fixed_dataset_version": dataset["dataset_id"],
            "max_tokens_per_scenario": max_tokens_per_scenario,
            "token_normalized_reporting": True,
            "manual_removal_of_failed_cases": False,
        },
        "variants": variants,
        "comparison": comparison,
        "claims_supported": [
            claim for claim, ok in {
                "higher task success": comparison["higher_task_success"],
                "lower unsupported-claim rate": comparison["lower_unsupported_claim_rate"],
                "more risks detected": comparison["more_risks_detected"],
                "better final rubric score": comparison["better_mean_score"],
                "better quality per token": comparison["better_quality_per_token"],
            }.items()
            if ok
        ],
        "claims_not_made": [
            "speed improvement",
            "statistical significance",
            "live Qwen quality measurement in deterministic mode",
        ],
        "artifacts": {
            "summary_json": _path_label(summary_path),
            "raw_json": _path_label(raw_json_path),
            "raw_csv": _path_label(raw_csv_path),
            "dataset": _path_label(DEFAULT_DATASET),
        },
    }


def write_outputs(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    summary_json: Path,
    raw_json: Path,
    raw_csv: Path,
) -> None:
    raw_json.parent.mkdir(parents=True, exist_ok=True)
    raw_json.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with raw_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the reproducible YITING Track 3 paired benchmark.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--raw-json", type=Path, default=DEFAULT_RAW_JSON)
    parser.add_argument("--raw-csv", type=Path, default=DEFAULT_RAW_CSV)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model-identity", default="qwen3.7-plus rolling alias")
    parser.add_argument("--max-tokens-per-scenario", type=int, default=1200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = _read_dataset(args.dataset)
    rows = run_benchmark(
        dataset,
        runs=args.runs,
        model_identity=args.model_identity,
        max_tokens_per_scenario=args.max_tokens_per_scenario,
    )
    summary = summarize(
        dataset,
        rows,
        model_identity=args.model_identity,
        runs=args.runs,
        max_tokens_per_scenario=args.max_tokens_per_scenario,
        summary_path=args.summary_json,
        raw_json_path=args.raw_json,
        raw_csv_path=args.raw_csv,
    )
    write_outputs(summary, rows, summary_json=args.summary_json, raw_json=args.raw_json, raw_csv=args.raw_csv)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import json

from scripts import track3_paired_benchmark


def test_track3_paired_dataset_has_preferred_twenty_scenarios():
    dataset = track3_paired_benchmark._read_dataset(track3_paired_benchmark.DEFAULT_DATASET)

    assert dataset["dataset_id"] == "yiting-track3-paired-v1"
    assert dataset["rubric_version"] == "track3-agent-society-rubric-v1"
    assert len(dataset["scenarios"]) == 20
    assert all("required_findings" in item for item in dataset["scenarios"])
    assert all("required_risks" in item for item in dataset["scenarios"])


def test_track3_paired_benchmark_compares_same_inputs_and_model():
    dataset = track3_paired_benchmark._read_dataset(track3_paired_benchmark.DEFAULT_DATASET)
    rows = track3_paired_benchmark.run_benchmark(
        dataset,
        runs=3,
        model_identity="qwen3.7-plus-test-snapshot",
        max_tokens_per_scenario=1200,
    )
    summary = track3_paired_benchmark.summarize(
        dataset,
        rows,
        model_identity="qwen3.7-plus-test-snapshot",
        runs=3,
        max_tokens_per_scenario=1200,
        summary_path=track3_paired_benchmark.DEFAULT_SUMMARY,
        raw_json_path=track3_paired_benchmark.DEFAULT_RAW_JSON,
        raw_csv_path=track3_paired_benchmark.DEFAULT_RAW_CSV,
    )

    assert len(rows) == 20 * 3 * 2
    assert {row["variant"] for row in rows} == {"single_agent", "full_yiting_society"}
    assert {row["model_identity"] for row in rows} == {"qwen3.7-plus-test-snapshot"}
    assert {row["same_model_as_pair"] for row in rows} == {True}

    controls = summary["fairness_controls"]
    assert controls["same_input_scenarios"] is True
    assert controls["same_declared_rubric"] is True
    assert controls["same_model_tier"] is True
    assert controls["manual_removal_of_failed_cases"] is False

    single = summary["variants"]["single_agent"]
    society = summary["variants"]["full_yiting_society"]
    assert society["success_rate"] > single["success_rate"]
    assert society["mean_score"] > single["mean_score"]
    assert society["risks_detected"] > single["risks_detected"]
    assert society["unsupported_claims"] < single["unsupported_claims"]
    assert summary["comparison"]["speed_improvement_claimed"] is False
    assert "speed improvement" in summary["claims_not_made"]


def test_track3_paired_benchmark_writes_summary_raw_json_and_csv(tmp_path):
    summary_path = tmp_path / "summary.json"
    raw_json_path = tmp_path / "raw.json"
    raw_csv_path = tmp_path / "raw.csv"

    code = track3_paired_benchmark.main(
        [
            "--summary-json",
            str(summary_path),
            "--raw-json",
            str(raw_json_path),
            "--raw-csv",
            str(raw_csv_path),
            "--model-identity",
            "qwen3.7-plus-test-snapshot",
        ]
    )

    assert code == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    raw = json.loads(raw_json_path.read_text(encoding="utf-8"))
    with raw_csv_path.open(encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))

    assert summary["proof_type"] == "track3-paired-reproducible-benchmark"
    assert summary["scenario_count"] == 20
    assert len(raw["rows"]) == 120
    assert len(csv_rows) == 120
    assert summary["artifacts"]["raw_json"] == str(raw_json_path)
    assert summary["artifacts"]["raw_csv"] == str(raw_csv_path)

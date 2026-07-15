"""Spec-drift guards for the live paired eval harness.

The initial runner implementation scored the solo arm's evidence_chain at
0.55, contradicting the dataset's scoring_method (solo: 1.0, an axis that
must advantage neither arm). Published rows were rescored; these pins keep
the executable aligned with the declared contract so a future run cannot
silently recreate the invalid scoring.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _runner_source() -> str:
    with open(os.path.join(ROOT, "scripts", "track3_live_paired_eval.py")) as fh:
        return fh.read()


def _dataset() -> dict:
    with open(os.path.join(ROOT, "evals", "track3_live_paired_scenarios.json")) as fh:
        return json.load(fh)


def test_solo_chain_score_matches_spec():
    src = _runner_source()
    assert "evidence_chain_score=1.0" in src
    # The invalid constant must never reappear as an argument (the historical
    # comment may reference it).
    assert "evidence_chain_score=0.55" not in src


def test_dataset_declares_neutral_solo_chain():
    method = _dataset()["scoring_method"]["evidence_chain_score"]
    assert "solo: 1.0" in method


def test_dataset_makes_no_equal_cap_promise():
    controls = _dataset()["fairness_controls"]
    assert "equal_aggregate_token_cap_per_incident" not in controls
    assert controls.get("token_usage_measured_and_published_per_incident") is True


def test_corrections_are_logged_in_dataset():
    corrections = _dataset().get("post_run_corrections", [])
    assert any("0.55" in c for c in corrections)
    assert any("equal_aggregate_token_cap_per_incident" in c for c in corrections)

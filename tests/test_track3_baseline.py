import json

from scripts import track3_baseline


def _runsummary(avg_total=80):
    return {
        "summary": {
            "incidents_measured": 2,
            "avg_total_resolution_secs": avg_total,
            "total_handoffs": 12,
            "total_challenges_issued": 1,
            "total_human_rejections": 0,
            "total_plan_revisions": 0,
            "disagreement_events": 1,
            "human_interventions": 1,
            "recovery_verified_count": 2,
        },
        "runs": [],
    }


def _runsummary_with_families():
    payload = _runsummary(avg_total=130)
    payload["runs"] = [
        {
            "incident_id": "INC-SUSPICIOUS-1",
            "incident_family": "suspicious deploy",
            "total_resolution_secs": 60,
            "handoffs": 6,
            "challenges": 1,
            "human_rejections": 0,
            "plan_revisions": 0,
            "disagreement_events": 1,
            "human_intervention": True,
            "recovery_verified": True,
        },
        {
            "incident_id": "INC-SUSPICIOUS-2",
            "incident_family": "suspicious_deploy",
            "total_resolution_secs": 80,
            "handoffs": 7,
            "challenges": 0,
            "human_rejections": 1,
            "plan_revisions": 1,
            "disagreement_events": 1,
            "human_intervention": True,
            "recovery_verified": True,
        },
        {
            "incident_id": "INC-CERT-1",
            "incident_family": "certificate expiry",
            "total_resolution_secs": 250,
            "handoffs": 99,
            "challenges": 99,
            "human_rejections": 99,
            "plan_revisions": 99,
            "disagreement_events": 198,
            "human_intervention": True,
            "recovery_verified": True,
        },
    ]
    return payload


def test_compute_baseline_report_records_measured_speedup():
    report = track3_baseline.compute_baseline_report(
        _runsummary(),
        baseline_secs=240,
        baseline_label="One-person incident response rehearsal",
        incident_family="suspicious deploy",
    )

    assert report["project"] == "YITING"
    assert report["proof_type"] == "track3-manual-baseline"
    assert report["schema_version"] == 2
    assert report["baseline"]["measured_seconds"] == 240
    assert report["baseline"]["label"] == "One-person incident response rehearsal"
    assert report["baseline"]["incident_family"] == "suspicious deploy"
    assert report["yiting"]["avg_total_resolution_seconds"] == 80
    assert report["yiting"]["comparison_scope"] == "runsummary aggregate average"
    assert report["yiting"]["matched_run_count"] is None
    assert report["yiting"]["matched_incident_ids"] == []
    assert report["yiting"]["total_handoffs"] == 12
    assert report["yiting"]["disagreement_events"] == 1
    assert report["speedup_factor"] == 3.0
    assert report["comparison_method"]["formula"] == (
        "baseline.measured_seconds / yiting.avg_total_resolution_seconds"
    )
    assert report["track3_requirements_checked"] == {
        "distinct_role_handoffs": True,
        "disagreement_or_revision": True,
        "human_intervention": True,
        "recovery_verification": True,
        "measured_speedup_over_baseline": True,
    }
    assert report["gateway_env"]["MANUAL_BASELINE_SECS"] == "240"


def test_compute_baseline_report_uses_same_family_runsummary_rows():
    report = track3_baseline.compute_baseline_report(
        _runsummary_with_families(),
        baseline_secs=280,
        baseline_label="One-person incident response rehearsal",
        incident_family="suspicious deploy",
    )

    assert report["yiting"]["avg_total_resolution_seconds"] == 70
    assert report["yiting"]["comparison_scope"] == "same-family runsummary runs"
    assert report["yiting"]["matched_run_count"] == 2
    assert report["yiting"]["matched_incident_ids"] == [
        "INC-SUSPICIOUS-1",
        "INC-SUSPICIOUS-2",
    ]
    assert report["yiting"]["incidents_measured"] == 2
    assert report["yiting"]["total_handoffs"] == 13
    assert report["yiting"]["total_challenges_issued"] == 1
    assert report["yiting"]["total_human_rejections"] == 1
    assert report["yiting"]["total_plan_revisions"] == 1
    assert report["yiting"]["disagreement_events"] == 2
    assert report["yiting"]["human_interventions"] == 2
    assert report["yiting"]["recovery_verified_count"] == 2
    assert report["speedup_factor"] == 4.0


def test_compute_baseline_report_rejects_same_family_without_track3_counters():
    payload = _runsummary_with_families()
    for run in payload["runs"]:
        if run["incident_family"].replace("_", " ") == "suspicious deploy":
            run["challenges"] = 0
            run["human_rejections"] = 0
            run["plan_revisions"] = 0
            run["disagreement_events"] = 0

    try:
        track3_baseline.compute_baseline_report(
            payload,
            baseline_secs=280,
            baseline_label="One-person incident response rehearsal",
            incident_family="suspicious deploy",
        )
    except ValueError as exc:
        assert "within same-family runsummary runs" in str(exc)
        assert "disagreement_events" in str(exc)
    else:
        raise AssertionError("expected same-family proof without disagreement to fail")


def test_compute_baseline_report_rejects_unmatched_family_when_runs_are_tagged():
    try:
        track3_baseline.compute_baseline_report(
            _runsummary_with_families(),
            baseline_secs=240,
            baseline_label="baseline",
            incident_family="latency spike",
        )
    except ValueError as exc:
        assert "did not match any measured runsummary runs" in str(exc)
        assert "certificate expiry" in str(exc)
        assert "suspicious deploy" in str(exc)
    else:
        raise AssertionError("expected unmatched family to fail")


def test_compute_baseline_report_rejects_missing_runsummary_average():
    payload = _runsummary(avg_total=None)

    try:
        track3_baseline.compute_baseline_report(
            payload,
            baseline_secs=240,
            baseline_label="baseline",
            incident_family="suspicious deploy",
        )
    except ValueError as exc:
        assert "avg_total_resolution_secs" in str(exc)
    else:
        raise AssertionError("expected missing average to fail")


def test_compute_baseline_report_rejects_non_positive_baseline():
    try:
        track3_baseline.compute_baseline_report(
            _runsummary(),
            baseline_secs=0,
            baseline_label="baseline",
            incident_family="suspicious deploy",
        )
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("expected non-positive baseline to fail")


def test_compute_baseline_report_rejects_blank_labels():
    for kwargs, expected in [
        ({"baseline_label": "   "}, "baseline-label"),
        ({"incident_family": ""}, "incident-family"),
    ]:
        params = {
            "baseline_secs": 240,
            "baseline_label": "baseline",
            "incident_family": "suspicious deploy",
        }
        params.update(kwargs)

        try:
            track3_baseline.compute_baseline_report(_runsummary(), **params)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected blank metadata to fail")


def test_compute_baseline_report_rejects_placeholder_incident_family():
    for value in [
        "same incident family as the hosted hero run",
        "same incident family as hosted hero run",
        "<same-family-as-hero-incident>",
    ]:
        try:
            track3_baseline.compute_baseline_report(
                _runsummary(),
                baseline_secs=240,
                baseline_label="baseline",
                incident_family=value,
            )
        except ValueError as exc:
            assert "incident-family" in str(exc)
        else:
            raise AssertionError("expected placeholder incident family to fail")


def test_compute_baseline_report_rejects_no_speedup():
    try:
        track3_baseline.compute_baseline_report(
            _runsummary(avg_total=120),
            baseline_secs=100,
            baseline_label="baseline",
            incident_family="suspicious deploy",
        )
    except ValueError as exc:
        assert "does not prove a speedup" in str(exc)
    else:
        raise AssertionError("expected no-speedup comparison to fail")


def test_compute_baseline_report_rejects_missing_track3_metrics():
    for key in [
        "incidents_measured",
        "total_handoffs",
        "human_interventions",
        "recovery_verified_count",
    ]:
        payload = _runsummary()
        payload["summary"][key] = 0

        try:
            track3_baseline.compute_baseline_report(
                payload,
                baseline_secs=240,
                baseline_label="baseline",
                incident_family="suspicious deploy",
            )
        except ValueError as exc:
            assert f"runsummary {key} must be a positive integer" in str(exc)
        else:
            raise AssertionError(f"expected {key}=0 to fail")


def test_compute_baseline_report_accepts_human_rejection_as_disagreement():
    payload = _runsummary()
    payload["summary"]["total_challenges_issued"] = 0
    payload["summary"]["total_human_rejections"] = 1
    payload["summary"]["total_plan_revisions"] = 1
    payload["summary"]["disagreement_events"] = 1

    report = track3_baseline.compute_baseline_report(
        payload,
        baseline_secs=240,
        baseline_label="One-person incident response rehearsal",
        incident_family="suspicious deploy",
    )

    assert report["yiting"]["total_challenges_issued"] == 0
    assert report["yiting"]["total_human_rejections"] == 1
    assert report["track3_requirements_checked"]["disagreement_or_revision"] is True


def test_compute_baseline_report_rejects_no_disagreement_or_revision():
    payload = _runsummary()
    payload["summary"]["total_challenges_issued"] = 0
    payload["summary"]["total_human_rejections"] = 0
    payload["summary"]["disagreement_events"] = 0

    try:
        track3_baseline.compute_baseline_report(
            payload,
            baseline_secs=240,
            baseline_label="baseline",
            incident_family="suspicious deploy",
        )
    except ValueError as exc:
        assert "disagreement_events" in str(exc)
    else:
        raise AssertionError("expected zero disagreement proof to fail")


def test_load_runsummary_from_json_file(tmp_path):
    path = tmp_path / "runsummary.json"
    path.write_text(json.dumps(_runsummary(avg_total=60)), encoding="utf-8")

    loaded = track3_baseline.load_runsummary(runsummary_json=path)

    assert loaded["summary"]["avg_total_resolution_secs"] == 60


def test_write_report_creates_parent_directory(tmp_path):
    output = tmp_path / "proofs" / "track3.json"

    track3_baseline.write_report(output, {"project": "YITING"})

    assert json.loads(output.read_text(encoding="utf-8"))["project"] == "YITING"

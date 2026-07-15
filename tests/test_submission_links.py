from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import submission_links


DEMO_VIDEO_URL = "https://youtu.be/yitingDemo123"
PROOF_VIDEO_URL = "https://vimeo.com/987654321"
FACEBOOK_VIDEO_URL = "https://www.facebook.com/watch/?v=123456789"
UNSUPPORTED_VIDEO_URL = "https://videos.examplevideo.dev/watch/yiting-demo"


def test_public_url_validator_rejects_placeholder_and_private_urls() -> None:
    rejected = (
        "https://PUBLIC_VIDEO_URL",
        "https://github.com/YOUR_ACCOUNT/yiting",
        "https://yiting-api.yourdomain.example",
        "https://example.com",
        "https://127.0.0.1/dashboard",
        "http://github.com/example/yiting",
    )

    for value in rejected:
        assert submission_links.validate_public_https_url(value, "url")


def test_public_url_validator_accepts_real_https_shape() -> None:
    assert not submission_links.validate_public_https_url("https://github.com/example-owner/yiting", "repository_url")


def test_submission_links_payload_requires_github_yiting_repository() -> None:
    payload = submission_links.build_payload(
        repository_url="https://github.com/example-owner/yiting",
        live_application_url="https://yiting.exampleapp.dev",
        demo_video_url=DEMO_VIDEO_URL,
        deployment_proof_video_url=PROOF_VIDEO_URL,
    )
    assert submission_links.validate_payload(payload) == []

    payload["repository_url"] = "https://github.com/example-owner/not-yiting"
    assert (
        "repository_url must be the public GitHub repository named yiting"
        in submission_links.validate_payload(payload)
    )


def test_submission_links_payload_requires_separate_videos() -> None:
    payload = submission_links.build_payload(
        repository_url="https://github.com/example-owner/yiting",
        live_application_url="https://yiting.exampleapp.dev",
        demo_video_url=DEMO_VIDEO_URL,
        deployment_proof_video_url=PROOF_VIDEO_URL,
    )
    payload["deployment_proof_video_url"] = payload["demo_video_url"]

    assert (
        "demo_video_url and deployment_proof_video_url must be separate public videos"
        in submission_links.validate_payload(payload)
    )


def test_submission_links_payload_requires_supported_video_hosts() -> None:
    assert not submission_links.validate_public_video_url(FACEBOOK_VIDEO_URL, "demo_video_url")
    errors = submission_links.validate_public_video_url(UNSUPPORTED_VIDEO_URL, "demo_video_url")
    assert "demo_video_url must be a public YouTube, Vimeo, or Facebook Video URL" in errors


def _reachability_for(payload: dict[str, object]) -> dict[str, object]:
    return {
        field_name: {
            "url": payload[field_name],
            "final_url": payload[field_name],
            "status_code": 200,
            "passed": True,
        }
        for field_name in submission_links.reachable_link_fields(payload)
    }


def test_submission_links_reachability_validation_requires_all_public_checks() -> None:
    payload = submission_links.build_payload(
        repository_url="https://github.com/example-owner/yiting",
        live_application_url="https://yiting.exampleapp.dev",
        demo_video_url=DEMO_VIDEO_URL,
        deployment_proof_video_url=PROOF_VIDEO_URL,
    )

    assert (
        "reachability_checked_at is required after --check-reachable"
        in submission_links.validate_reachability(payload)
    )

    payload["reachability_checked_at"] = "2026-06-21T00:00:00+00:00"
    payload["public_reachability"] = _reachability_for(payload)
    payload["public_reachability"]["demo_video_url"]["status_code"] = 403

    assert (
        "public_reachability.demo_video_url.status_code must be a successful HTTP status"
        in submission_links.validate_reachability(payload)
    )


def test_submission_links_main_writes_verified_artifact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "artifacts/live/submission-links.json"

    submission_links.main(
        [
            "--repository-url",
            "https://github.com/example-owner/yiting",
            "--live-application-url",
            "https://yiting.exampleapp.dev",
            "--demo-video-url",
            DEMO_VIDEO_URL,
            "--deployment-proof-video-url",
            PROOF_VIDEO_URL,
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["artifact_class"] == "public_submission_links"
    assert payload["submission_evidence"] is True
    assert payload["verified_live"] is True
    assert payload["repository_url"] == "https://github.com/example-owner/yiting"
    assert json.loads(capsys.readouterr().out)["output"] == str(output)


def test_submission_links_main_records_reachability_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "artifacts/live/submission-links.json"

    def check_reachable(payload: dict[str, object], timeout: float) -> tuple[list[str], dict[str, object]]:
        return [], _reachability_for(payload)

    monkeypatch.setattr(submission_links, "_check_reachable", check_reachable)

    submission_links.main(
        [
            "--repository-url",
            "https://github.com/example-owner/yiting",
            "--live-application-url",
            "https://yiting.exampleapp.dev",
            "--demo-video-url",
            DEMO_VIDEO_URL,
            "--deployment-proof-video-url",
            PROOF_VIDEO_URL,
            "--check-reachable",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["reachability_checked_at"]
    assert submission_links.validate_reachability(payload) == []
    assert json.loads(capsys.readouterr().out)["links"] == 4


def test_submission_links_main_accepts_optional_blog_url(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "artifacts/live/submission-links.json"

    def check_reachable(payload: dict[str, object], timeout: float) -> tuple[list[str], dict[str, object]]:
        return [], _reachability_for(payload)

    monkeypatch.setattr(submission_links, "_check_reachable", check_reachable)

    submission_links.main(
        [
            "--repository-url",
            "https://github.com/example-owner/yiting",
            "--live-application-url",
            "https://yiting.exampleapp.dev",
            "--demo-video-url",
            DEMO_VIDEO_URL,
            "--deployment-proof-video-url",
            PROOF_VIDEO_URL,
            "--blog-url",
            "https://blog.example.dev/yiting",
            "--check-reachable",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["blog_url"] == "https://blog.example.dev/yiting"
    assert submission_links.validate_reachability(payload) == []
    assert json.loads(capsys.readouterr().out)["links"] == 5


def test_submission_links_main_rejects_placeholder_artifact(tmp_path: Path) -> None:
    output = tmp_path / "submission-links.json"

    with pytest.raises(SystemExit) as exc_info:
        submission_links.main(
            [
                "--repository-url",
                "https://github.com/YOUR_ACCOUNT/yiting",
                "--live-application-url",
                "https://yiting.exampleapp.dev",
                "--demo-video-url",
                DEMO_VIDEO_URL,
                "--deployment-proof-video-url",
                PROOF_VIDEO_URL,
                "--output",
                str(output),
            ]
        )

    assert exc_info.value.code == 1
    assert not output.exists()

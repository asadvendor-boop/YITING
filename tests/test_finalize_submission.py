from pathlib import Path

import pytest

from scripts.finalize_submission import (
    FinalizeError,
    finalize_public_artifacts,
    next_steps,
    normalize_domain,
    validate_hero_incident_id,
    validate_repo_url,
    video_embed_src,
)


README_TEMPLATE = """# YITING

- **Public landing page:** `https://<your-yiting-domain>/`
- **Dashboard:** `https://<your-yiting-domain>/dashboard/`

```bash
python scripts/verify_deployment.py --public-url "https://<your-yiting-domain>"
```
"""


LANDING_TEMPLATE = """<!DOCTYPE html>
<html>
<body>
  <nav class="nav">
    <div class="nav-links">
      <a href="#features">Features</a>
      <a href="#architecture">Architecture</a>
      <a href="#demo">Demo</a>
      <a href="/dashboard/" class="nav-cta">Live Dashboard →</a>
    </div>
  </nav>
  <section id="demo" class="demo">
    <div class="demo-player">
      <div class="demo-placeholder">
        <span class="demo-play">▶</span>
        <span>Demo video — available during live presentation</span>
      </div>
    </div>
  </section>
</body>
</html>
"""


JUDGE_PACKET_TEMPLATE = """# Judge Packet

| Item | Final value |
|---|---|
| Hero incident | `HERO_INCIDENT_ID_PLACEHOLDER` |
| Evidence export | `HERO_EVIDENCE_URL_PLACEHOLDER` |
| Run summary | `RUNSUMMARY_URL_PLACEHOLDER` |
| Dashboard replay | `DASHBOARD_REPLAY_URL_PLACEHOLDER` |
"""


SUBMISSION_FORM_TEMPLATE = """# Hackathon Submission Form Fields

## Public Links To Fill In

- Landing page: `https://<deployment-domain>/`
- Dashboard: `https://<deployment-domain>/dashboard/`
- Evidence export: `https://<deployment-domain>/evidence/<hero-incident-id>`
- Public repository: `$PUBLIC_REPOSITORY_URL`
- Demo video: `https://youtu.be/<video-id>`
- Alibaba deployment-proof video: `https://youtu.be/<deployment-proof-video-id>`

## Alibaba Cloud Deployment Proof Code Links

- Primary code proof: `$PUBLIC_REPOSITORY_URL/blob/main/shared/config.py`
- Qwen smoke proof: `$PUBLIC_REPOSITORY_URL/blob/main/scripts/qwen_smoke.py`
- Hosted ECS verifier: `$PUBLIC_REPOSITORY_URL/blob/main/scripts/verify_deployment.py`
- ECS deployment guide: `$PUBLIC_REPOSITORY_URL/blob/main/deploy/alibaba-ecs/README.md`

## Final Proof Command

```bash
make submission-proof \\
  PUBLIC_BASE_URL="https://<deployment-domain>" \\
  HERO_INCIDENT_ID="<hero-incident-id>" \\
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \\
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```
"""


INSTALL_AND_RUN_TEMPLATE = """# Install And Run Guide

```bash
python scripts/verify_deployment.py \\
  --public-url "https://<deployment-domain>" \\
  --incident-id "<hero-incident-id>" \\
  --output-json artifacts/deployment-verification.json

make submission-proof \\
  PUBLIC_BASE_URL="https://<deployment-domain>" \\
  HERO_INCIDENT_ID="<hero-incident-id>" \\
  MEASURED_SINGLE_AGENT_SECS="<measured-single-agent-seconds>" \\
  BASELINE_INCIDENT_FAMILY="<same-family-as-hero-incident>"
```
"""


def _write_public_files(root: Path) -> None:
    (root / "landing").mkdir()
    (root / "docs").mkdir()
    (root / "README.md").write_text(README_TEMPLATE, encoding="utf-8")
    (root / "landing" / "index.html").write_text(LANDING_TEMPLATE, encoding="utf-8")
    (root / "docs" / "JUDGE_PACKET.md").write_text(JUDGE_PACKET_TEMPLATE, encoding="utf-8")
    (root / "docs" / "SUBMISSION_FORM.md").write_text(SUBMISSION_FORM_TEMPLATE, encoding="utf-8")
    (root / "docs" / "INSTALL_AND_RUN.md").write_text(INSTALL_AND_RUN_TEMPLATE, encoding="utf-8")


def test_normalize_domain_rejects_placeholders_and_non_https():
    assert normalize_domain("https://demo.yiting.ai/") == "https://demo.yiting.ai"

    with pytest.raises(FinalizeError):
        normalize_domain("http://demo.yiting.ai")
    with pytest.raises(FinalizeError):
        normalize_domain("https://your-yiting-domain.example.com")
    with pytest.raises(FinalizeError):
        normalize_domain("https://<your-yiting-domain>")


def test_validate_repo_url_requires_real_github_repo():
    assert validate_repo_url("https://github.com/example-owner/yiting") == "https://github.com/example-owner/yiting"

    with pytest.raises(FinalizeError):
        validate_repo_url("https://gitlab.com/example-owner/yiting")
    with pytest.raises(FinalizeError):
        validate_repo_url("https://github.com/your/repo")


def test_validate_hero_incident_id_rejects_unsafe_values():
    assert validate_hero_incident_id(" INC-HERO-123 ") == "INC-HERO-123"
    assert validate_hero_incident_id("b32332c6-1927-4614-b637-a6e70fe5716d") == (
        "b32332c6-1927-4614-b637-a6e70fe5716d"
    )

    for value in ["", "<hero-incident-id>", "INC/123", "INC 123"]:
        with pytest.raises(FinalizeError):
            validate_hero_incident_id(value)


def test_video_embed_src_supports_youtube_vimeo_and_facebook_video():
    assert video_embed_src("https://www.youtube.com/watch?v=abc123") == (
        "https://www.youtube.com/embed/abc123",
        True,
    )
    assert video_embed_src("https://youtu.be/abc123") == (
        "https://www.youtube.com/embed/abc123",
        True,
    )
    assert video_embed_src("https://vimeo.com/12345") == (
        "https://player.vimeo.com/video/12345",
        True,
    )
    assert video_embed_src("https://www.facebook.com/watch/?v=12345") == (
        "https://www.facebook.com/watch/?v=12345",
        False,
    )
    assert video_embed_src("https://fb.watch/abc123/") == (
        "https://fb.watch/abc123",
        False,
    )

    with pytest.raises(FinalizeError):
        video_embed_src("https://example.com/video")
    with pytest.raises(FinalizeError):
        video_embed_src("https://v.youku.com/v_show/id_XN12345.html")


def test_finalize_public_artifacts_replaces_readme_and_landing(tmp_path):
    _write_public_files(tmp_path)

    changed = finalize_public_artifacts(
        root=tmp_path,
        domain="https://demo.yiting.ai",
        repo_url="https://github.com/example-owner/yiting",
        video_url="https://youtu.be/abc123",
        deployment_proof_video_url="https://vimeo.com/987654321",
    )

    assert {path.relative_to(tmp_path) for path in changed} == {
        Path("README.md"),
        Path("landing/index.html"),
        Path("docs/INSTALL_AND_RUN.md"),
        Path("docs/SUBMISSION_FORM.md"),
    }

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "https://demo.yiting.ai/" in readme
    assert "<your-yiting-domain>" not in readme

    landing = (tmp_path / "landing" / "index.html").read_text(encoding="utf-8")
    assert 'href="https://github.com/example-owner/yiting"' in landing
    assert 'class="nav-github"' in landing
    assert 'src="https://www.youtube.com/embed/abc123"' in landing
    assert "finalized-proof-links" not in landing
    assert "Demo video — available during live presentation" not in landing

    form = (tmp_path / "docs" / "SUBMISSION_FORM.md").read_text(encoding="utf-8")
    assert "https://demo.yiting.ai/" in form
    assert "https://github.com/example-owner/yiting" in form
    assert "https://github.com/example-owner/yiting/blob/main/shared/config.py" in form
    assert "https://github.com/example-owner/yiting/blob/main/scripts/qwen_smoke.py" in form
    assert "https://github.com/example-owner/yiting/blob/main/scripts/verify_deployment.py" in form
    assert "https://github.com/example-owner/yiting/blob/main/deploy/alibaba-ecs/README.md" in form
    assert "https://youtu.be/abc123" in form
    assert "https://vimeo.com/987654321" in form
    assert "https://<deployment-domain>" not in form
    assert "$PUBLIC_REPOSITORY_URL" not in form
    assert "https://youtu.be/<video-id>" not in form
    assert "https://youtu.be/<deployment-proof-video-id>" not in form

    guide = (tmp_path / "docs" / "INSTALL_AND_RUN.md").read_text(encoding="utf-8")
    assert "https://demo.yiting.ai" in guide
    assert "https://<deployment-domain>" not in guide
    assert "<hero-incident-id>" in guide


def test_finalize_public_artifacts_accepts_facebook_video_link(tmp_path):
    _write_public_files(tmp_path)

    video_url = "https://www.facebook.com/watch/?v=12345"
    finalize_public_artifacts(
        root=tmp_path,
        domain="https://demo.yiting.ai",
        repo_url="https://github.com/example-owner/yiting",
        video_url=video_url,
        deployment_proof_video_url="https://vimeo.com/987654321",
    )

    landing = (tmp_path / "landing" / "index.html").read_text(encoding="utf-8")
    assert '<iframe class="demo-iframe"' not in landing
    assert f'href="{video_url}"' in landing
    assert "Watch public demo video" in landing
    assert "Demo video — available during live presentation" not in landing

    form = (tmp_path / "docs" / "SUBMISSION_FORM.md").read_text(encoding="utf-8")
    assert video_url in form
    assert "https://vimeo.com/987654321" in form
    assert "https://youtu.be/<video-id>" not in form


def test_finalize_public_artifacts_can_stamp_hero_evidence_links(tmp_path):
    _write_public_files(tmp_path)

    changed = finalize_public_artifacts(
        root=tmp_path,
        domain="https://demo.yiting.ai",
        repo_url="https://github.com/example-owner/yiting",
        video_url="https://youtu.be/abc123",
        deployment_proof_video_url="https://vimeo.com/987654321",
        hero_incident_id="INC-HERO-123",
    )

    assert tmp_path / "docs" / "JUDGE_PACKET.md" in changed
    packet = (tmp_path / "docs" / "JUDGE_PACKET.md").read_text(encoding="utf-8")
    assert "INC-HERO-123" in packet
    assert "https://demo.yiting.ai/evidence/INC-HERO-123" in packet
    assert "https://demo.yiting.ai/stats/runsummary" in packet
    assert "https://demo.yiting.ai/runs" in packet
    assert "HERO_INCIDENT_ID_PLACEHOLDER" not in packet

    landing = (tmp_path / "landing" / "index.html").read_text(encoding="utf-8")
    assert 'class="finalized-proof-links"' in landing
    assert "Verified hero incident" in landing
    assert "INC-HERO-123" in landing
    assert 'href="https://demo.yiting.ai/evidence/INC-HERO-123"' in landing
    assert 'href="https://demo.yiting.ai/stats/runsummary"' in landing
    assert 'href="https://demo.yiting.ai/runs"' in landing

    form = (tmp_path / "docs" / "SUBMISSION_FORM.md").read_text(encoding="utf-8")
    assert "https://demo.yiting.ai/evidence/INC-HERO-123" in form
    assert 'HERO_INCIDENT_ID="INC-HERO-123"' in form
    assert "<hero-incident-id>" not in form
    assert "https://vimeo.com/987654321" in form

    guide = (tmp_path / "docs" / "INSTALL_AND_RUN.md").read_text(encoding="utf-8")
    assert "https://demo.yiting.ai" in guide
    assert 'HERO_INCIDENT_ID="INC-HERO-123"' in guide
    assert "--incident-id \"INC-HERO-123\"" in guide
    assert "<hero-incident-id>" not in guide


def test_finalize_public_artifacts_rejects_missing_or_duplicate_deployment_proof_video(tmp_path):
    _write_public_files(tmp_path)

    with pytest.raises(FinalizeError, match="deployment-proof video URL"):
        finalize_public_artifacts(
            root=tmp_path,
            domain="https://demo.yiting.ai",
            repo_url="https://github.com/example-owner/yiting",
            video_url="https://youtu.be/abc123",
            deployment_proof_video_url="https://videos.example.dev/proof",
        )

    with pytest.raises(FinalizeError, match="separate public videos"):
        finalize_public_artifacts(
            root=tmp_path,
            domain="https://demo.yiting.ai",
            repo_url="https://github.com/example-owner/yiting",
            video_url="https://youtu.be/abc123",
            deployment_proof_video_url="https://youtu.be/abc123",
        )


def test_finalize_public_artifacts_is_idempotent(tmp_path):
    _write_public_files(tmp_path)
    kwargs = {
        "root": tmp_path,
        "domain": "https://demo.yiting.ai",
        "repo_url": "https://github.com/example-owner/yiting",
        "video_url": "https://youtu.be/abc123",
        "deployment_proof_video_url": "https://vimeo.com/987654321",
        "hero_incident_id": "INC-HERO-123",
    }

    finalize_public_artifacts(**kwargs)
    second = finalize_public_artifacts(**kwargs)

    assert second == []
    landing = (tmp_path / "landing" / "index.html").read_text(encoding="utf-8")
    assert landing.count('class="nav-github"') == 1
    assert landing.count('class="finalized-proof-links"') == 1


def test_next_steps_include_commit_package_and_deployment_proof():
    steps = "\n".join(next_steps())

    assert "docs/SUBMISSION_FORM.md" in steps
    assert "docs/INSTALL_AND_RUN.md" in steps
    assert "EXECUTED evidence chain" in steps
    assert "ActionReceipt" in steps
    assert "Verdict(CHALLENGE) or StructuredApproval(REJECTED)" in steps
    assert "Commit the finalized public artifacts" in steps
    assert "make submission-ready" in steps
    assert "make submission-proof" in steps
    assert "HERO_INCIDENT_ID" in steps
    assert "MEASURED_SINGLE_AGENT_SECS" in steps
    assert "artifacts/qwen-smoke.json" in steps
    assert "artifacts/track3-baseline.json" in steps
    assert "artifacts/deployment-verification.json" in steps
    assert "artifacts/hero-evidence.json" in steps
    assert "artifacts/final-proof-index.md" in steps
    assert "Commit generated proof artifacts" in steps
    assert "make submission-package" in steps
    assert "submission_audit.py --strict" in steps

#!/usr/bin/env python3
"""Finalize public submission placeholders after deployment/video recording.

This script intentionally edits only public-facing static artifacts.  It does
not create remotes, deploy infrastructure, or fabricate proof.  Use it after
you have:

- a public GitHub repository URL,
- a hosted Alibaba ECS domain, and
- a public YouTube/Vimeo/Facebook Video demo video URL.
- a separate public YouTube/Vimeo/Facebook Video Alibaba deployment-proof video URL.
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]


class FinalizeError(ValueError):
    """Raised when a final submission value is invalid."""


_INCIDENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")


def _require_https_url(value: str, *, label: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise FinalizeError(f"{label} must be an absolute https:// URL")
    if "<" in value or ">" in value:
        raise FinalizeError(f"{label} still contains angle-bracket placeholder text")
    if parsed.netloc.endswith("example.com") or "your-" in parsed.netloc.lower():
        raise FinalizeError(f"{label} still looks like a placeholder: {value}")
    return value


def normalize_domain(value: str) -> str:
    """Return a normalized public deployment base URL."""
    return _require_https_url(value, label="domain")


def validate_repo_url(value: str) -> str:
    """Return a normalized public GitHub repository URL."""
    url = _require_https_url(value, label="repo URL")
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        raise FinalizeError("repo URL must be a public https://github.com/... URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise FinalizeError("repo URL must include owner and repository name")
    forbidden = {"your", "example", "placeholder", "<owner>", "<repo>"}
    if any(part.lower() in forbidden for part in parts[:2]):
        raise FinalizeError("repo URL owner/repository still looks like a placeholder")
    return url


def validate_hero_incident_id(value: str) -> str:
    """Return a sanitized hero incident id suitable for public proof links."""
    value = value.strip()
    if not value:
        raise FinalizeError("hero incident id is required when provided")
    if "<" in value or ">" in value:
        raise FinalizeError("hero incident id still contains placeholder text")
    if "/" in value or "\\" in value:
        raise FinalizeError("hero incident id must not contain path separators")
    if not _INCIDENT_ID_RE.fullmatch(value):
        raise FinalizeError("hero incident id contains unsupported characters")
    return value


def video_embed_src(value: str) -> tuple[str, bool]:
    """Return (URL, embeddable) for a supported public demo video URL."""
    url = _require_https_url(value, label="video URL")
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host in {"youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        if not video_id:
            raise FinalizeError("YouTube URL must include a v= video id")
        return f"https://www.youtube.com/embed/{video_id}", True
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
        if not video_id:
            raise FinalizeError("youtu.be URL must include a video id")
        return f"https://www.youtube.com/embed/{video_id}", True
    if host == "vimeo.com":
        video_id = parsed.path.strip("/").split("/", 1)[0]
        if not video_id:
            raise FinalizeError("Vimeo URL must include a video id")
        return f"https://player.vimeo.com/video/{video_id}", True
    if host in {"facebook.com", "m.facebook.com"} or host.endswith(".facebook.com"):
        has_video_id = bool(parse_qs(parsed.query).get("v", [""])[0].strip())
        has_video_path = "videos" in [part.lower() for part in parsed.path.split("/") if part]
        if not has_video_id and not has_video_path:
            raise FinalizeError("Facebook Video URL must include a public video id or videos path")
        return url, False
    if host == "fb.watch":
        if parsed.path.strip("/") == "":
            raise FinalizeError("Facebook Video URL must include a public video path")
        return url, False
    raise FinalizeError("video URL must be YouTube, Vimeo, or Facebook Video")


def validate_public_video_url(value: str, *, label: str) -> str:
    """Return a normalized supported public video URL."""
    url = _require_https_url(value, label=label)
    try:
        video_embed_src(url)
    except FinalizeError as exc:
        raise FinalizeError(f"{label} must be YouTube, Vimeo, or Facebook Video") from exc
    return url


def _replace_or_fail(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise FinalizeError(f"{label} placeholder not found")
    return text.replace(old, new)


def _video_markup(video_url: str) -> str:
    src, embeddable = video_embed_src(video_url)
    escaped_src = html.escape(src, quote=True)
    if embeddable:
        return (
            '<iframe class="demo-iframe" '
            f'src="{escaped_src}" '
            'title="YITING demo video" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            'gyroscope; picture-in-picture; web-share" '
            'allowfullscreen></iframe>'
        )
    return (
        '<div class="demo-placeholder demo-ready">'
        '<span class="demo-play">▶</span>'
        f'<a href="{escaped_src}" target="_blank" rel="noopener noreferrer">'
        'Watch public demo video</a>'
        "</div>"
    )


def _landing_proof_links_markup(*, domain: str, hero_incident_id: str) -> str:
    hero_incident_id = validate_hero_incident_id(hero_incident_id)
    escaped_incident = html.escape(hero_incident_id)
    escaped_evidence = html.escape(f"{domain}/evidence/{hero_incident_id}", quote=True)
    escaped_runsummary = html.escape(f"{domain}/stats/runsummary", quote=True)
    escaped_replay = html.escape(f"{domain}/runs", quote=True)
    return (
        '    <div class="finalized-proof-links" aria-label="Verified hero incident proof links">\n'
        f'      <span>Verified hero incident: <code>{escaped_incident}</code></span>\n'
        f'      <a href="{escaped_evidence}">Evidence chain</a>\n'
        f'      <a href="{escaped_runsummary}">Run summary</a>\n'
        f'      <a href="{escaped_replay}">Dashboard replay</a>\n'
        "    </div>"
    )


def _patch_judge_packet(root: Path, *, domain: str, hero_incident_id: str) -> Path | None:
    hero_incident_id = validate_hero_incident_id(hero_incident_id)
    packet_path = root / "docs" / "JUDGE_PACKET.md"
    packet = packet_path.read_text(encoding="utf-8")
    evidence_url = f"{domain}/evidence/{hero_incident_id}"
    runsummary_url = f"{domain}/stats/runsummary"
    replay_url = f"{domain}/runs"
    replacements = {
        "HERO_INCIDENT_ID_PLACEHOLDER": hero_incident_id,
        "HERO_EVIDENCE_URL_PLACEHOLDER": evidence_url,
        "RUNSUMMARY_URL_PLACEHOLDER": runsummary_url,
        "DASHBOARD_REPLAY_URL_PLACEHOLDER": replay_url,
    }

    updated = packet
    for old, new in replacements.items():
        updated = updated.replace(old, new)

    if updated != packet:
        packet_path.write_text(updated, encoding="utf-8")
        return packet_path

    if all(value in packet for value in replacements.values()):
        return None
    raise FinalizeError("judge packet hero placeholders not found or already contain different values")


def _patch_submission_form(
    root: Path,
    *,
    domain: str,
    repo_url: str,
    video_url: str,
    deployment_proof_video_url: str,
    hero_incident_id: str | None,
) -> Path | None:
    form_path = root / "docs" / "SUBMISSION_FORM.md"
    form = form_path.read_text(encoding="utf-8")
    updated = form.replace("https://<deployment-domain>", domain)
    updated = updated.replace("$PUBLIC_REPOSITORY_URL", repo_url)
    updated = updated.replace("https://youtu.be/<video-id>", video_url)
    updated = updated.replace("https://youtu.be/<deployment-proof-video-id>", deployment_proof_video_url)
    if hero_incident_id:
        updated = updated.replace("<hero-incident-id>", hero_incident_id)

    if updated != form:
        form_path.write_text(updated, encoding="utf-8")
        return form_path
    return None


def _patch_install_guide(root: Path, *, domain: str, hero_incident_id: str | None) -> Path | None:
    guide_path = root / "docs" / "INSTALL_AND_RUN.md"
    if not guide_path.exists():
        return None

    guide = guide_path.read_text(encoding="utf-8")
    updated = guide.replace("https://<deployment-domain>", domain)
    if hero_incident_id:
        updated = updated.replace("<hero-incident-id>", hero_incident_id)

    if updated != guide:
        guide_path.write_text(updated, encoding="utf-8")
        return guide_path
    return None


def finalize_public_artifacts(
    *,
    root: Path,
    domain: str,
    repo_url: str,
    video_url: str,
    deployment_proof_video_url: str,
    hero_incident_id: str | None = None,
) -> list[Path]:
    """Patch public submission artifacts with final deployment values."""
    domain = normalize_domain(domain)
    repo_url = validate_repo_url(repo_url)
    video_url = validate_public_video_url(video_url, label="demo video URL")
    deployment_proof_video_url = validate_public_video_url(
        deployment_proof_video_url,
        label="deployment-proof video URL",
    )
    if video_url == deployment_proof_video_url:
        raise FinalizeError("demo video URL and deployment-proof video URL must be separate public videos")
    video_markup = _video_markup(video_url)
    if hero_incident_id:
        hero_incident_id = validate_hero_incident_id(hero_incident_id)

    changed: list[Path] = []

    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    updated_readme = readme.replace("https://<your-yiting-domain>", domain)
    updated_readme = updated_readme.replace("https://your-yiting-domain.example.com", domain)
    if updated_readme != readme:
        readme_path.write_text(updated_readme, encoding="utf-8")
        changed.append(readme_path)

    landing_path = root / "landing" / "index.html"
    landing = landing_path.read_text(encoding="utf-8")
    if 'class="nav-github"' not in landing:
        landing = _replace_or_fail(
            landing,
            '      <a href="#demo">Demo</a>\n',
            (
                '      <a href="#demo">Demo</a>\n'
                f'      <a href="{html.escape(repo_url, quote=True)}" '
                'class="nav-github" target="_blank" rel="noopener noreferrer">'
                'GitHub ↗</a>\n'
            ),
            label="landing GitHub nav",
        )
    old_demo = (
        '      <div class="demo-placeholder">\n'
        '        <span class="demo-play">▶</span>\n'
        '        <span>Demo video — available during live presentation</span>\n'
        '      </div>'
    )
    if old_demo in landing:
        landing = landing.replace(old_demo, f"      {video_markup}")
    elif "Demo video — available during live presentation" in landing:
        raise FinalizeError("landing has demo placeholder text in an unexpected shape")
    if hero_incident_id and 'class="finalized-proof-links"' not in landing:
        proof_links = _landing_proof_links_markup(
            domain=domain,
            hero_incident_id=hero_incident_id,
        )
        proof_insertions = [
            (
                '    </div>\n  </section>\n\n  <section id="judging" class="judge-pack">',
                (
                    '    </div>\n'
                    f'{proof_links}\n'
                    '  </section>\n\n'
                    '  <section id="judging" class="judge-pack">'
                ),
            ),
            (
                '    </div>\n  </section>\n</body>',
                (
                    '    </div>\n'
                    f'{proof_links}\n'
                    '  </section>\n</body>'
                ),
            ),
        ]
        for old, new in proof_insertions:
            if old in landing:
                landing = landing.replace(old, new, 1)
                break
        else:
            raise FinalizeError("landing final proof links placeholder not found")
    if landing != landing_path.read_text(encoding="utf-8"):
        landing_path.write_text(landing, encoding="utf-8")
        changed.append(landing_path)

    if hero_incident_id:
        patched_packet = _patch_judge_packet(
            root,
            domain=domain,
            hero_incident_id=hero_incident_id,
        )
        if patched_packet is not None:
            changed.append(patched_packet)

    patched_form = _patch_submission_form(
        root,
        domain=domain,
        repo_url=repo_url,
        video_url=video_url,
        deployment_proof_video_url=deployment_proof_video_url,
        hero_incident_id=hero_incident_id,
    )
    if patched_form is not None:
        changed.append(patched_form)

    patched_install_guide = _patch_install_guide(
        root,
        domain=domain,
        hero_incident_id=hero_incident_id,
    )
    if patched_install_guide is not None:
        changed.append(patched_install_guide)

    return changed


def next_steps() -> list[str]:
    """Return the exact post-finalization commands to finish submission proof."""
    return [
        (
            "Review README.md, landing/index.html, docs/JUDGE_PACKET.md, "
            "docs/SUBMISSION_FORM.md, and docs/INSTALL_AND_RUN.md."
        ),
        (
            "Confirm HERO_INCIDENT_ID points to an EXECUTED evidence chain with "
            "ActionReceipt plus Verdict(CHALLENGE) or StructuredApproval(REJECTED)."
        ),
        "Commit the finalized public artifacts.",
        "Run: make submission-ready",
        (
            "Run on Alibaba ECS: make submission-proof "
            "PUBLIC_BASE_URL=\"$PUBLIC_BASE_URL\" "
            "HERO_INCIDENT_ID=\"$HERO_INCIDENT_ID\" "
            "MEASURED_SINGLE_AGENT_SECS=\"$MEASURED_SINGLE_AGENT_SECS\" "
            "BASELINE_INCIDENT_FAMILY=\"$BASELINE_INCIDENT_FAMILY\""
        ),
        (
            "Keep generated proof artifacts: artifacts/qwen-smoke.json, "
            "artifacts/track3-baseline.json, "
            "artifacts/track3-paired-benchmark.json, and "
            "artifacts/deployment-verification.json, artifacts/hero-evidence.json, "
            "and artifacts/final-proof-index.md"
        ),
        "Commit generated proof artifacts, run make submission-package, and push the final proof commit.",
        "Run: python scripts/submission_audit.py --strict",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize YITING public submission placeholders")
    parser.add_argument("--domain", required=True, help="Public Alibaba ECS base URL, e.g. https://yiting.example.com")
    parser.add_argument("--repo-url", required=True, help="Public GitHub repository URL")
    parser.add_argument("--video-url", required=True, help="Public YouTube, Vimeo, or Facebook Video demo video URL")
    parser.add_argument(
        "--deployment-proof-video-url",
        required=True,
        help="Separate public YouTube, Vimeo, or Facebook Video Alibaba deployment-proof video URL",
    )
    parser.add_argument("--hero-incident-id", default="", help="Optional final hero incident id for docs/JUDGE_PACKET.md")
    args = parser.parse_args()

    try:
        changed = finalize_public_artifacts(
            root=ROOT,
            domain=args.domain,
            repo_url=args.repo_url,
            video_url=args.video_url,
            deployment_proof_video_url=args.deployment_proof_video_url,
            hero_incident_id=args.hero_incident_id or None,
        )
    except FinalizeError as exc:
        print(f"finalize failed: {exc}")
        return 2

    if changed:
        print("Updated:")
        for path in changed:
            print(f"  - {path.relative_to(ROOT)}")
    else:
        print("No changes needed; public artifacts were already finalized.")
    print("Next:")
    for index, step in enumerate(next_steps(), start=1):
        print(f"  {index}. {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017


LIVE_LINK_FIELDS = (
    "repository_url",
    "live_application_url",
    "demo_video_url",
    "deployment_proof_video_url",
)
OPTIONAL_LINK_FIELDS = ("blog_url",)

PLACEHOLDER_MARKERS = (
    "INSERT_",
    "PUBLIC_",
    "YOUR_",
    "TODO",
    "TBD",
    "PLACEHOLDER",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create YITING public submission link evidence.")
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--live-application-url", required=True)
    parser.add_argument("--demo-video-url", required=True)
    parser.add_argument("--deployment-proof-video-url", required=True)
    parser.add_argument("--blog-url")
    parser.add_argument("--output", type=Path, default=Path("artifacts/live/submission-links.json"))
    parser.add_argument(
        "--check-reachable",
        action="store_true",
        help="Fetch each URL as an unauthenticated public visitor before writing the artifact.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def validate_public_https_url(value: object, field_name: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{field_name} must be a non-empty HTTPS URL"]

    url = value.strip()
    errors: list[str] = []
    parsed = urlparse(url)
    host = parsed.hostname or ""
    host_lower = host.lower()
    upper_url = url.upper()

    if url != value:
        errors.append(f"{field_name} must not contain leading or trailing whitespace")
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"{field_name} must start with https:// and include a hostname")
    if parsed.username or parsed.password:
        errors.append(f"{field_name} must not embed credentials")
    if any(marker in upper_url for marker in PLACEHOLDER_MARKERS):
        errors.append(f"{field_name} contains placeholder text")
    if "yourdomain" in host_lower or host_lower in {"example.com", "example.net", "example.org"}:
        errors.append(f"{field_name} uses a reserved or example hostname")
    if host_lower.endswith((".example", ".example.com", ".example.net", ".example.org", ".test", ".invalid")):
        errors.append(f"{field_name} uses a reserved or example hostname")
    if host_lower == "localhost":
        errors.append(f"{field_name} must not use localhost")

    try:
        parsed_ip = ip_address(host_lower.strip("[]"))
    except ValueError:
        parsed_ip = None
    if parsed_ip and (parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local):
        errors.append(f"{field_name} must use a public hostname or address")
    return errors


def validate_public_video_url(value: object, field_name: str) -> list[str]:
    """Validate hackathon-supported public video hosts."""
    errors = validate_public_https_url(value, field_name)
    if errors:
        return errors

    parsed = urlparse(str(value).strip())
    host = (parsed.hostname or "").lower()
    path_parts = [part.lower() for part in parsed.path.split("/") if part]

    supported = False
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        supported = True
    elif host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        supported = True
    elif host in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"} or host.endswith(
        ".facebook.com"
    ):
        supported = True

    if not supported:
        errors.append(f"{field_name} must be a public YouTube, Vimeo, or Facebook Video URL")
    elif host == "youtu.be" and not parsed.path.strip("/"):
        errors.append(f"{field_name} youtu.be URL must include a video id")
    elif (
        host in {"youtube.com", "www.youtube.com", "m.youtube.com"}
        and not parse_qs(parsed.query).get("v", [""])[0].strip()
        and "shorts" not in path_parts
        and "embed" not in path_parts
    ):
        errors.append(f"{field_name} YouTube URL must include a video id")
    elif host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"} and not parsed.path.strip("/"):
        errors.append(f"{field_name} Vimeo URL must include a video id")
    elif host == "fb.watch" and not parsed.path.strip("/"):
        errors.append(f"{field_name} Facebook Video URL must include a public video path")
    elif (
        ("facebook.com" in host or host.endswith(".facebook.com"))
        and "watch" not in path_parts
        and "videos" not in path_parts
    ):
        errors.append(f"{field_name} Facebook Video URL must include a watch or videos path")
    return errors


def build_payload(
    *,
    repository_url: str,
    live_application_url: str,
    demo_video_url: str,
    deployment_proof_video_url: str,
    blog_url: str | None = None,
) -> dict[str, object]:
    payload = {
        "artifact_class": "public_submission_links",
        "submission_evidence": True,
        "verified_live": True,
        "repository_url": repository_url.strip(),
        "live_application_url": live_application_url.strip(),
        "demo_video_url": demo_video_url.strip(),
        "deployment_proof_video_url": deployment_proof_video_url.strip(),
    }
    if blog_url:
        payload["blog_url"] = blog_url.strip()
    errors = validate_payload(payload)
    if errors:
        raise ValueError("\n".join(errors))
    return payload


def reachable_link_fields(payload: dict[str, object]) -> tuple[str, ...]:
    optional = tuple(field for field in OPTIONAL_LINK_FIELDS if field in payload)
    return (*LIVE_LINK_FIELDS, *optional)


def validate_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("artifact_class") != "public_submission_links":
        errors.append("artifact_class must be public_submission_links")
    if payload.get("submission_evidence") is not True or payload.get("verified_live") is not True:
        errors.append("submission links must be marked as verified live submission evidence")

    for field_name in LIVE_LINK_FIELDS:
        if field_name not in {"demo_video_url", "deployment_proof_video_url"}:
            errors.extend(validate_public_https_url(payload.get(field_name), field_name))
    for field_name in ("demo_video_url", "deployment_proof_video_url"):
        errors.extend(validate_public_video_url(payload.get(field_name), field_name))
    if "blog_url" in payload:
        errors.extend(validate_public_https_url(payload.get("blog_url"), "blog_url"))

    repository_url = str(payload.get("repository_url", ""))
    parsed_repository = urlparse(repository_url)
    repo_parts = [part for part in parsed_repository.path.strip("/").split("/") if part]
    if (
        parsed_repository.hostname != "github.com"
        or len(repo_parts) != 2
        or repo_parts[-1].removesuffix(".git") != "yiting"
    ):
        errors.append("repository_url must be the public GitHub repository named yiting")
    if payload.get("demo_video_url") == payload.get("deployment_proof_video_url"):
        errors.append("demo_video_url and deployment_proof_video_url must be separate public videos")
    return errors


def validate_reachability(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    checked_at = payload.get("reachability_checked_at")
    if not isinstance(checked_at, str) or not checked_at:
        errors.append("reachability_checked_at is required after --check-reachable")

    reachability = payload.get("public_reachability")
    if not isinstance(reachability, dict):
        errors.append("public_reachability is required after --check-reachable")
        return errors

    for field_name in reachable_link_fields(payload):
        check = reachability.get(field_name)
        if not isinstance(check, dict):
            errors.append(f"public_reachability requires {field_name}")
            continue
        if check.get("url") != payload.get(field_name):
            errors.append(f"public_reachability.{field_name}.url must match {field_name}")
        if check.get("passed") is not True:
            errors.append(f"public_reachability.{field_name}.passed must be true")
        status_code = check.get("status_code")
        if not isinstance(status_code, int) or status_code >= 400:
            errors.append(f"public_reachability.{field_name}.status_code must be a successful HTTP status")
        final_url = check.get("final_url")
        final_url_field = f"public_reachability.{field_name}.final_url"
        final_url_errors = validate_public_https_url(final_url, final_url_field)
        if final_url_errors:
            errors.append(f"public_reachability.{field_name}.final_url must be a public HTTPS URL")
        video_final_url_errors = []
        if field_name in {"demo_video_url", "deployment_proof_video_url"} and not final_url_errors:
            video_final_url_errors = validate_public_video_url(final_url, final_url_field)
        if video_final_url_errors:
            errors.append(
                f"public_reachability.{field_name}.final_url must be a public YouTube, Vimeo, or Facebook Video URL"
            )
    return errors


def _check_reachable(payload: dict[str, object], timeout: float) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    checks: dict[str, object] = {}
    headers = {"User-Agent": "YITING-public-link-check/1.0"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for field_name in reachable_link_fields(payload):
            url = str(payload[field_name])
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                errors.append(f"{field_name} is not publicly reachable: {exc}")
                checks[field_name] = {"url": url, "passed": False, "error": str(exc)}
                continue
            checks[field_name] = {
                "url": url,
                "final_url": str(response.url),
                "status_code": response.status_code,
                "passed": response.status_code < 400,
            }
            if response.status_code >= 400:
                errors.append(f"{field_name} returned HTTP {response.status_code}")
    return errors, checks


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        payload = build_payload(
            repository_url=args.repository_url,
            live_application_url=args.live_application_url,
            demo_video_url=args.demo_video_url,
            deployment_proof_video_url=args.deployment_proof_video_url,
            blog_url=args.blog_url,
        )
        if args.check_reachable:
            reachability_errors, checks = _check_reachable(payload, args.timeout)
            if reachability_errors:
                raise ValueError("\n".join(reachability_errors))
            payload["reachability_checked_at"] = datetime.now(UTC).isoformat()
            payload["public_reachability"] = checks
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Submission links failed validation:\n{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps({"output": str(args.output), "links": len(reachable_link_fields(payload))}, indent=2))


if __name__ == "__main__":
    main()

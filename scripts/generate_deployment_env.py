#!/usr/bin/env python3
"""Generate a deployment-ready YITING .env and Caddy env drop-in.

The generator keeps humans out of the secret-copying danger zone:

- one Qwen/DashScope model credential source,
- random Gateway/agent/proxy/CSRF keys,
- bcrypt hash for the approval UI password,
- matching Caddy APPROVAL_PROXY_SECRET,
- 0600 permissions for generated env files.

It refuses to overwrite existing files unless ``--force`` is supplied.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shlex
from pathlib import Path
from urllib.parse import urlparse

import bcrypt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ROOT / "deploy" / "alibaba-ecs" / "yiting.env.example"


class GenerateEnvError(ValueError):
    """Raised when deployment env generation cannot continue safely."""


def _secret() -> str:
    return secrets.token_urlsafe(32)


def _require_https_url(value: str, *, label: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise GenerateEnvError(f"{label} must be an absolute https:// URL")
    if "<" in value or ">" in value or "your-" in parsed.netloc.lower() or parsed.netloc.endswith("example.com"):
        raise GenerateEnvError(f"{label} still looks like a placeholder: {value}")
    return value


def _public_host(public_base_url: str) -> str:
    return urlparse(public_base_url).netloc


def _qwen_credential(*, dashscope_api_key: str, qwen_api_key: str) -> tuple[str, str]:
    dashscope_api_key = dashscope_api_key.strip()
    qwen_api_key = qwen_api_key.strip()
    if bool(dashscope_api_key) == bool(qwen_api_key):
        raise GenerateEnvError("Provide exactly one of --dashscope-api-key or --qwen-api-key")
    if dashscope_api_key:
        return "DASHSCOPE_API_KEY", dashscope_api_key
    return "QWEN_API_KEY", qwen_api_key


def _bcrypt_hash(password: str) -> str:
    if len(password) < 12:
        raise GenerateEnvError("approval password must be at least 12 characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _env_line(key: str, value: str) -> str:
    """Render a shell/source-compatible .env assignment."""
    if any(char in value for char in "$'\"`\\ \t\n"):
        return f"{key}={shlex.quote(value)}"
    return f"{key}={value}"


def _render_env(template: str, replacements: dict[str, str], *, qwen_key_name: str, qwen_key_value: str) -> str:
    lines: list[str] = []
    inserted_qwen_api_key = False
    for line in template.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key == "DASHSCOPE_API_KEY":
            if qwen_key_name == "DASHSCOPE_API_KEY":
                lines.append(_env_line("DASHSCOPE_API_KEY", qwen_key_value))
            else:
                lines.append("DASHSCOPE_API_KEY=")
                lines.append(_env_line("QWEN_API_KEY", qwen_key_value))
                inserted_qwen_api_key = True
            continue
        if key in replacements:
            lines.append(_env_line(key, replacements[key]))
        else:
            lines.append(line)
    if qwen_key_name == "QWEN_API_KEY" and not inserted_qwen_api_key:
        lines.append(_env_line("QWEN_API_KEY", qwen_key_value))
    return "\n".join(lines).rstrip() + "\n"


def _write_new(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise GenerateEnvError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def build_replacements(
    *,
    public_base_url: str,
    judge_user: str,
    judge_password: str,
    approver_id: str,
) -> dict[str, str]:
    public_base_url = _require_https_url(public_base_url, label="public base URL")
    judge_user = judge_user.strip()
    approver_id = approver_id.strip()
    if not judge_user:
        raise GenerateEnvError("judge user is required")
    if not approver_id:
        raise GenerateEnvError("approver id is required")

    return {
        "GATEWAY_SECRET": _secret(),
        "PUBLIC_BASE_URL": public_base_url,
        "RECORDER_SUBMISSION_KEY": _secret(),
        "TRIAGE_SUBMISSION_KEY": _secret(),
        "DIAGNOSIS_SUBMISSION_KEY": _secret(),
        "SAFETY_REVIEWER_SUBMISSION_KEY": _secret(),
        "COMMANDER_SUBMISSION_KEY": _secret(),
        "OPERATOR_SUBMISSION_KEY": _secret(),
        "INCIDENT_ROOM_API_KEY": _secret(),
        "HUMAN_APPROVER_IDS": approver_id,
        "APPROVAL_PROXY_SECRET": _secret(),
        "APPROVAL_UI_USER": judge_user,
        "APPROVAL_UI_BCRYPT_HASH": _bcrypt_hash(judge_password),
        "APPROVAL_UI_APPROVER_ID": approver_id,
        "APPROVAL_UI_CSRF_SECRET": _secret(),
    }


def generate_files(
    *,
    template_path: Path,
    env_out: Path,
    caddy_env_out: Path,
    public_base_url: str,
    dashscope_api_key: str,
    qwen_api_key: str,
    judge_user: str,
    judge_password: str,
    approver_id: str,
    yiting_root: str,
    force: bool,
) -> list[Path]:
    qwen_key_name, qwen_key_value = _qwen_credential(
        dashscope_api_key=dashscope_api_key,
        qwen_api_key=qwen_api_key,
    )
    replacements = build_replacements(
        public_base_url=public_base_url,
        judge_user=judge_user,
        judge_password=judge_password,
        approver_id=approver_id,
    )
    template = template_path.read_text(encoding="utf-8")
    env_content = _render_env(
        template,
        replacements,
        qwen_key_name=qwen_key_name,
        qwen_key_value=qwen_key_value,
    )
    caddy_content = (
        "[Service]\n"
        f"Environment=YITING_DOMAIN={_public_host(public_base_url)}\n"
        f"Environment=YITING_ROOT={yiting_root}\n"
        f"Environment=APPROVAL_PROXY_SECRET={replacements['APPROVAL_PROXY_SECRET']}\n"
        f"Environment=YITING_JUDGE_USER={replacements['APPROVAL_UI_USER']}\n"
        f"Environment=YITING_JUDGE_HASH={replacements['APPROVAL_UI_BCRYPT_HASH']}\n"
    )
    _write_new(env_out, env_content, force=force)
    _write_new(caddy_env_out, caddy_content, force=force)
    return [env_out, caddy_env_out]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate YITING deployment env files")
    parser.add_argument("--public-base-url", required=True, help="Hosted public base URL, e.g. https://yiting.example.com")
    parser.add_argument("--dashscope-api-key", default=os.getenv("DASHSCOPE_API_KEY", ""))
    parser.add_argument("--qwen-api-key", default=os.getenv("QWEN_API_KEY", ""))
    parser.add_argument("--judge-user", required=True)
    parser.add_argument("--judge-password", default=os.getenv("YITING_JUDGE_PASSWORD", ""))
    parser.add_argument("--approver-id", required=True)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--env-out", type=Path, default=Path(".env"))
    parser.add_argument("--caddy-env-out", type=Path, default=Path("deploy/alibaba-ecs/caddy.generated.env"))
    parser.add_argument("--yiting-root", default="/opt/yiting")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.judge_password:
        print("generate failed: provide --judge-password or YITING_JUDGE_PASSWORD")
        return 2

    try:
        changed = generate_files(
            template_path=args.template,
            env_out=args.env_out,
            caddy_env_out=args.caddy_env_out,
            public_base_url=args.public_base_url,
            dashscope_api_key=args.dashscope_api_key,
            qwen_api_key=args.qwen_api_key,
            judge_user=args.judge_user,
            judge_password=args.judge_password,
            approver_id=args.approver_id,
            yiting_root=args.yiting_root,
            force=args.force,
        )
    except GenerateEnvError as exc:
        print(f"generate failed: {exc}")
        return 2

    print("Generated deployment env files:")
    for path in changed:
        print(f"  - {path}")
    print("Store the judge password securely; only the bcrypt hash was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

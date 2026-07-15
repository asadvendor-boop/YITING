from pathlib import Path
import subprocess

import bcrypt
import pytest

from scripts.generate_deployment_env import (
    GenerateEnvError,
    build_replacements,
    generate_files,
)


TEMPLATE = """DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
GATEWAY_SECRET=
PUBLIC_BASE_URL=https://your-yiting-domain.example.com
RECORDER_SUBMISSION_KEY=
TRIAGE_SUBMISSION_KEY=
DIAGNOSIS_SUBMISSION_KEY=
SAFETY_REVIEWER_SUBMISSION_KEY=
COMMANDER_SUBMISSION_KEY=
OPERATOR_SUBMISSION_KEY=
INCIDENT_ROOM_API_KEY=
HUMAN_APPROVER_IDS=
APPROVAL_PROXY_SECRET=
APPROVAL_UI_USER=
APPROVAL_UI_BCRYPT_HASH=
APPROVAL_UI_APPROVER_ID=
APPROVAL_UI_CSRF_SECRET=
"""


def _template(tmp_path: Path) -> Path:
    path = tmp_path / "template.env"
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("'\"'\"'", "'")
        values[key] = value
    return values


def test_build_replacements_rejects_placeholder_domain_and_short_password():
    with pytest.raises(GenerateEnvError):
        build_replacements(
            public_base_url="https://your-yiting-domain.example.com",
            judge_user="judge",
            judge_password="very-secret-password",
            approver_id="human-1",
        )

    with pytest.raises(GenerateEnvError):
        build_replacements(
            public_base_url="https://demo.yiting.ai",
            judge_user="judge",
            judge_password="short",
            approver_id="human-1",
        )


def test_generate_files_writes_matching_env_and_caddy_secret(tmp_path):
    template = _template(tmp_path)
    env_out = tmp_path / ".env"
    caddy_out = tmp_path / "caddy.env"

    changed = generate_files(
        template_path=template,
        env_out=env_out,
        caddy_env_out=caddy_out,
        public_base_url="https://demo.yiting.ai",
        dashscope_api_key="dashscope-key",
        qwen_api_key="",
        judge_user="judge",
        judge_password="very-secret-password",
        approver_id="human-1",
        yiting_root="/opt/yiting",
        force=False,
    )

    assert changed == [env_out, caddy_out]
    assert oct(env_out.stat().st_mode & 0o777) == "0o600"
    assert oct(caddy_out.stat().st_mode & 0o777) == "0o600"

    values = _env_values(env_out)
    assert values["DASHSCOPE_API_KEY"] == "dashscope-key"
    assert "QWEN_API_KEY" not in values
    assert values["PUBLIC_BASE_URL"] == "https://demo.yiting.ai"
    assert values["APPROVAL_UI_USER"] == "judge"
    assert values["APPROVAL_UI_APPROVER_ID"] == "human-1"
    assert values["HUMAN_APPROVER_IDS"] == "human-1"
    assert bcrypt.checkpw(
        b"very-secret-password",
        values["APPROVAL_UI_BCRYPT_HASH"].encode(),
    )

    caddy_text = caddy_out.read_text(encoding="utf-8")
    assert "Environment=YITING_DOMAIN=demo.yiting.ai" in caddy_text
    assert f"Environment=APPROVAL_PROXY_SECRET={values['APPROVAL_PROXY_SECRET']}" in caddy_text
    assert "Environment=YITING_JUDGE_USER=judge" in caddy_text
    assert f"Environment=YITING_JUDGE_HASH={values['APPROVAL_UI_BCRYPT_HASH']}" in caddy_text
    assert "APPROVAL_UI_BCRYPT_HASH='$2" in env_out.read_text(encoding="utf-8")


def test_generate_files_supports_qwen_api_key_alias(tmp_path):
    template = _template(tmp_path)
    env_out = tmp_path / ".env"
    caddy_out = tmp_path / "caddy.env"

    generate_files(
        template_path=template,
        env_out=env_out,
        caddy_env_out=caddy_out,
        public_base_url="https://demo.yiting.ai",
        dashscope_api_key="",
        qwen_api_key="qwen-key",
        judge_user="judge",
        judge_password="very-secret-password",
        approver_id="human-1",
        yiting_root="/opt/yiting",
        force=False,
    )

    values = _env_values(env_out)
    assert values["DASHSCOPE_API_KEY"] == ""
    assert values["QWEN_API_KEY"] == "qwen-key"


def test_generate_files_requires_exactly_one_qwen_credential(tmp_path):
    kwargs = {
        "template_path": _template(tmp_path),
        "env_out": tmp_path / ".env",
        "caddy_env_out": tmp_path / "caddy.env",
        "public_base_url": "https://demo.yiting.ai",
        "judge_user": "judge",
        "judge_password": "very-secret-password",
        "approver_id": "human-1",
        "yiting_root": "/opt/yiting",
        "force": False,
    }

    with pytest.raises(GenerateEnvError):
        generate_files(**kwargs, dashscope_api_key="", qwen_api_key="")
    with pytest.raises(GenerateEnvError):
        generate_files(**kwargs, dashscope_api_key="dashscope-key", qwen_api_key="qwen-key")


def test_generate_files_refuses_overwrite_without_force(tmp_path):
    template = _template(tmp_path)
    env_out = tmp_path / ".env"
    caddy_out = tmp_path / "caddy.env"
    env_out.write_text("existing", encoding="utf-8")

    with pytest.raises(GenerateEnvError):
        generate_files(
            template_path=template,
            env_out=env_out,
            caddy_env_out=caddy_out,
            public_base_url="https://demo.yiting.ai",
            dashscope_api_key="dashscope-key",
            qwen_api_key="",
            judge_user="judge",
            judge_password="very-secret-password",
            approver_id="human-1",
            yiting_root="/opt/yiting",
            force=False,
        )


def test_generated_env_can_be_sourced_without_mangling_bcrypt_hash(tmp_path):
    template = _template(tmp_path)
    env_out = tmp_path / ".env"
    caddy_out = tmp_path / "caddy.env"

    generate_files(
        template_path=template,
        env_out=env_out,
        caddy_env_out=caddy_out,
        public_base_url="https://demo.yiting.ai",
        dashscope_api_key="dashscope-key",
        qwen_api_key="",
        judge_user="judge",
        judge_password="very-secret-password",
        approver_id="human-1",
        yiting_root="/opt/yiting",
        force=False,
    )

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"set -a; source {env_out}; set +a; printf '%s' \"$APPROVAL_UI_BCRYPT_HASH\"",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    values = _env_values(env_out)
    assert result.stdout == values["APPROVAL_UI_BCRYPT_HASH"]

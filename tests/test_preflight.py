import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _base_env(tmp_path: Path) -> dict[str, str]:
    caddy_env = tmp_path / "caddy.env"
    caddy_env.write_text(
        (
            "[Service]\n"
            "Environment=APPROVAL_PROXY_SECRET=proxy-secret\n"
            "Environment=YITING_JUDGE_USER=judge\n"
            "Environment=YITING_JUDGE_HASH=hash\n"
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    for key in ["DASHSCOPE_API_KEY", "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_BASE_URL"]:
        env.pop(key, None)
    env.update({
        "QWEN_API_KEY": "qwen-key",
        "QWEN_BASE_URL": "https://dashscope.example.test/compatible-mode/v1",
        "RECORDER_AGENT_ID": "recorder",
        "TRIAGE_AGENT_ID": "triage",
        "DIAGNOSIS_AGENT_ID": "diagnosis",
        "SAFETY_REVIEWER_AGENT_ID": "safety_reviewer",
        "COMMANDER_AGENT_ID": "commander",
        "OPERATOR_AGENT_ID": "operator",
        "RECORDER_SUBMISSION_KEY": "recorder-key",
        "TRIAGE_SUBMISSION_KEY": "triage-key",
        "DIAGNOSIS_SUBMISSION_KEY": "diagnosis-key",
        "SAFETY_REVIEWER_SUBMISSION_KEY": "safety-key",
        "COMMANDER_SUBMISSION_KEY": "commander-key",
        "OPERATOR_SUBMISSION_KEY": "operator-key",
        "GATEWAY_SECRET": "gateway-secret",
        "GATEWAY_DB_PATH": str(tmp_path / "yiting.db"),
        "APPROVAL_PROXY_SECRET": "proxy-secret",
        "APPROVAL_UI_USER": "judge",
        "APPROVAL_UI_BCRYPT_HASH": "hash",
        "APPROVAL_UI_APPROVER_ID": "approver",
        "APPROVAL_UI_CSRF_SECRET": "csrf",
        "HUMAN_APPROVER_IDS": "approver",
        "CADDYFILE_PATH": str(tmp_path / "missing-Caddyfile"),
        "CADDY_ENV_PATH": str(caddy_env),
    })
    return env


def _run_preflight(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/preflight.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_accepts_qwen_api_key_alias(tmp_path):
    result = _run_preflight(_base_env(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "QWEN_API_KEY compatibility alias" in result.stdout
    assert "PREFLIGHT PASSED" in result.stdout


def test_preflight_requires_all_agent_submission_keys(tmp_path):
    env = _base_env(tmp_path)
    env.pop("DIAGNOSIS_SUBMISSION_KEY")

    result = _run_preflight(env)

    assert result.returncode == 1
    assert "Missing: DIAGNOSIS_SUBMISSION_KEY" in result.stdout


def test_preflight_rejects_explicit_generic_openai_source_credentials(tmp_path):
    env = _base_env(tmp_path)
    env["OPENAI_API_KEY"] = "compat-provider-key"

    result = _run_preflight(env)

    assert result.returncode == 1
    assert "Remove explicit OPENAI_* source credentials" in result.stdout


def test_preflight_detects_proxy_secret_mismatch(tmp_path):
    env = _base_env(tmp_path)
    env["APPROVAL_PROXY_SECRET"] = "different-secret"

    result = _run_preflight(env)

    assert result.returncode == 1
    assert "APPROVAL_PROXY_SECRET MISMATCH" in result.stdout


def test_preflight_detects_judge_auth_mismatch(tmp_path):
    env = _base_env(tmp_path)
    env["APPROVAL_UI_USER"] = "different"

    result = _run_preflight(env)

    assert result.returncode == 1
    assert "Judge auth mismatch" in result.stdout

import pytest

from scripts import qwen_smoke
from shared.config import (
    MODELS,
    QWEN_DEFAULT_BASE_URL,
    configure_openai_compatible_env,
    get_qwen_api_key,
    get_qwen_base_url,
)
from shared import qwen_reasoning
from shared.qwen_budget import QwenBudgetExceeded


def test_normalize_litellm_model_accepts_pydantic_style_prefix():
    assert qwen_reasoning.normalize_litellm_model("openai:qwen3.7-plus") == "openai/qwen3.7-plus"


def test_normalize_litellm_model_adds_openai_route_for_plain_qwen_name():
    assert qwen_reasoning.normalize_litellm_model("qwen3.6-flash") == "openai/qwen3.6-flash"


def test_configured_qwen_defaults_are_provider_neutral():
    for config in MODELS.values():
        assert config.model.startswith("qwen")
        assert config.fallback is None or config.fallback.startswith("qwen")


def test_qwen_credentials_do_not_fall_back_to_generic_openai_env(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "compat-non-qwen-key")

    assert get_qwen_api_key() == ""
    assert qwen_reasoning.qwen_reasoning_enabled() is False


def test_qwen_base_url_does_not_fall_back_to_generic_openai_env(monkeypatch):
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "https://compat.example.invalid/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://compat.example.invalid/v1")

    assert get_qwen_base_url() == QWEN_DEFAULT_BASE_URL


def test_openai_compatible_env_is_populated_from_qwen_values(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    configure_openai_compatible_env()

    assert get_qwen_api_key() == "dashscope-key"
    assert get_qwen_base_url() == "https://dashscope.example.test/v1"
    assert qwen_reasoning.os.getenv("OPENAI_API_KEY") == "dashscope-key"
    assert qwen_reasoning.os.getenv("OPENAI_API_BASE") == "https://dashscope.example.test/v1"
    assert qwen_reasoning.os.getenv("OPENAI_BASE_URL") == "https://dashscope.example.test/v1"


def test_bounded_text_rejects_empty_and_non_string_values():
    assert qwen_reasoning.bounded_text("", max_len=10) is None
    assert qwen_reasoning.bounded_text(123, max_len=10) is None
    assert qwen_reasoning.bounded_text("  abcdef  ", max_len=3) == "abc"


@pytest.mark.asyncio
async def test_ask_qwen_json_bypasses_network_in_test_mode(monkeypatch):
    async def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("network call should be bypassed")

    monkeypatch.setenv("YITING_TEST_MODE", "true")
    monkeypatch.setattr(qwen_reasoning, "acompletion", fail_if_called)

    result = await qwen_reasoning.ask_qwen_json(
        role="commander",
        system="Return JSON",
        user={"incident_id": "INC-TEST"},
    )

    assert result is None


@pytest.mark.asyncio
async def test_ask_qwen_json_blocks_before_network_when_daily_budget_exceeded(tmp_path, monkeypatch):
    async def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("network call should be blocked by the budget guard")

    monkeypatch.delenv("YITING_TEST_MODE", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("YITING_DAILY_TOKEN_LIMIT", "10")
    monkeypatch.setenv("YITING_QWEN_USAGE_METER_PATH", str(tmp_path / "qwen-usage.json"))
    monkeypatch.setattr(qwen_reasoning, "acompletion", fail_if_called)

    with pytest.raises(QwenBudgetExceeded, match="daily Qwen token budget exceeded"):
        await qwen_reasoning.ask_qwen_json(
            role="commander",
            system="Return JSON",
            user={"incident_id": "INC-BUDGET"},
            max_tokens=100,
        )


def test_qwen_smoke_report_is_sanitized_proof_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")
    report = qwen_smoke.build_report({
        "ok": True,
        "provider": "qwen",
        "message": "credential works",
    })

    assert report["project"] == "YITING"
    assert report["proof_type"] == "qwen-cloud-smoke"
    assert report["artifact_class"] == "live_qwen_smoke"
    assert report["submission_evidence"] is True
    assert report["verified_live"] is True
    assert report["passed"] is True
    assert report["provider"] == "qwen"
    assert report["base_url"] == "https://dashscope.example.test/v1"
    assert "qwen" in report["model"].lower()
    assert report["capability_matrix"]
    assert report["checks"]["commander"]["capabilities"]["structured_output"] == "required"
    assert report["checks"]["commander"]["capabilities"]["tools"] == "not_used"
    assert report["checks"]["commander"]["latency_ms"] == 0
    assert report["checks"]["commander"]["usage"]["total_tokens"] == 0
    assert report["response"]["ok"] is True
    assert "provider_request_id" in report["response"]
    assert "usage" in report["response"]
    assert "api_key" not in str(report).lower()

    output = tmp_path / "artifacts" / "qwen-smoke.json"
    qwen_smoke.write_report(output, report)
    assert output.read_text(encoding="utf-8").startswith("{")


def _clear_live_smoke_env(monkeypatch):
    for name in [
        "APP_ENV",
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "DASHSCOPE_BASE_URL",
        "YITING_TEST_MODE",
        "YITING_DISABLE_QWEN_REASONING",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_qwen_smoke_configuration_requires_explicit_base_url(monkeypatch):
    _clear_live_smoke_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-live-yiting-secret")

    with pytest.raises(RuntimeError, match="QWEN_BASE_URL must be set explicitly"):
        qwen_smoke.validate_live_smoke_configuration()


def test_qwen_smoke_configuration_rejects_placeholder_key(monkeypatch):
    _clear_live_smoke_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "your-qwen-cloud-api-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.example.test/v1")

    with pytest.raises(RuntimeError, match="Qwen API key looks like a placeholder"):
        qwen_smoke.validate_live_smoke_configuration()


def test_qwen_smoke_records_provider_request_id_when_available():
    class Response:
        id = "chatcmpl-test"
        _request_id = "dashscope-request-123"

    assert qwen_smoke._response_id(Response()) == "chatcmpl-test"
    assert qwen_smoke._provider_request_id(Response()) == "dashscope-request-123"

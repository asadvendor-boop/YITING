"""YITING configuration — centralized model, cloud, and agent settings.

All reasoning agents route to Qwen models through Alibaba Cloud Model Studio.
Some local adapter libraries require compatibility environment variables; those
are derived from DashScope/Qwen settings here rather than supplied separately.
"""
from __future__ import annotations

import logging as _logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


# ---------------------------------------------------------------------------
# Qwen Cloud / Alibaba Cloud settings
# ---------------------------------------------------------------------------
QWEN_DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_PLACEHOLDER_MARKERS = (
    "your-qwen-cloud-api-key",
    "replace-with",
    "generate-",
    "changeme",
    "placeholder",
    "dummy",
)


def get_qwen_api_key() -> str:
    """Return the Alibaba Cloud Model Studio / DashScope API key."""
    return (
        os.getenv("DASHSCOPE_API_KEY", "")
        or os.getenv("QWEN_API_KEY", "")
    )


def get_qwen_base_url() -> str:
    """Return the Qwen / DashScope endpoint for the selected region."""
    return (
        os.getenv("QWEN_BASE_URL", "")
        or os.getenv("DASHSCOPE_BASE_URL", "")
        or QWEN_DEFAULT_BASE_URL
    )


def live_qwen_required() -> bool:
    """Return True when production must fail closed without live Qwen config."""
    if os.getenv("YITING_TEST_MODE", "").strip().lower() in _TRUE_VALUES:
        return False
    return (
        os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}
        or os.getenv("YITING_REQUIRE_LIVE_QWEN", "").strip().lower() in _TRUE_VALUES
    )


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def _positive_int_setting(name: str, default: int, errors: list[str]) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default > 0
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be a positive integer")
        return False
    if value <= 0:
        errors.append(f"{name} must be a positive integer")
        return False
    return True


def _explicit_qwen_base_url() -> str:
    return (
        os.getenv("QWEN_BASE_URL", "").strip()
        or os.getenv("DASHSCOPE_BASE_URL", "").strip()
    )


def qwen_readiness_status() -> dict:
    """Return sanitized live-Qwen readiness details for production gates.

    The report intentionally omits credentials.  Local development can remain
    runnable without Qwen, but production ECS profiles set APP_ENV=production,
    which turns missing or placeholder Qwen settings into a hard readiness
    failure.
    """
    required = live_qwen_required()
    errors: list[str] = []

    api_key = get_qwen_api_key().strip()
    api_key_ok = bool(api_key) and not _looks_like_placeholder(api_key)
    if required and not api_key:
        errors.append("DASHSCOPE_API_KEY is required; QWEN_API_KEY is accepted only as a compatibility alias")
    elif required and not api_key_ok:
        errors.append("Qwen API key looks like a placeholder")

    explicit_base_url = _explicit_qwen_base_url()
    effective_base_url = get_qwen_base_url().strip()
    parsed = urlparse(explicit_base_url or effective_base_url)
    base_url_ok = parsed.scheme == "https" and bool(parsed.netloc)
    if required and not explicit_base_url:
        errors.append("QWEN_BASE_URL must be set explicitly; DASHSCOPE_BASE_URL is accepted only as a compatibility alias")
    elif required and not base_url_ok:
        errors.append("Qwen base URL must be an absolute https:// URL")

    model_names = {role: cfg.model.strip() for role, cfg in MODELS.items()}
    invalid_models = [
        role for role, model in model_names.items()
        if not model or not model.startswith("qwen")
    ]
    if required and invalid_models:
        errors.append(
            "Invalid Qwen model configuration for: "
            + ", ".join(sorted(invalid_models))
        )
    rate_limits_ok = (
        _positive_int_setting("YITING_RATE_LIMIT_PER_MINUTE", 600, errors)
        and _positive_int_setting("YITING_RATE_LIMIT_WINDOW_SECONDS", 60, errors)
    )

    ready = not errors
    return {
        "status": "ready" if ready else "not_ready",
        "required": required,
        "ready": ready,
        "provider": "qwen",
        "checks": {
            "api_key_present": bool(api_key),
            "api_key_placeholder": bool(api_key) and not api_key_ok,
            "base_url_explicit": bool(explicit_base_url),
            "base_url_https": base_url_ok,
            "models_configured": not invalid_models,
            "rate_limits_positive": rate_limits_ok,
        },
        "base_url": effective_base_url if base_url_ok else None,
        "models": model_names,
        "errors": errors,
    }


def require_live_qwen_ready() -> dict:
    """Return readiness status or raise RuntimeError when production is unsafe."""
    status = qwen_readiness_status()
    if status["required"] and not status["ready"]:
        raise RuntimeError("; ".join(status["errors"]))
    return status


def configure_openai_compatible_env() -> None:
    """Populate adapter compatibility env vars for clients that read globals.

    Some client libraries infer provider settings from OPENAI_API_KEY /
    OPENAI_API_BASE. We set those from Qwen/DashScope variables so no separate
    third-party model credentials are needed.
    """
    api_key = get_qwen_api_key()
    base_url = get_qwen_base_url()
    if api_key:
        os.environ.setdefault("OPENAI_API_KEY", api_key)
    if base_url:
        os.environ.setdefault("OPENAI_API_BASE", base_url)
        os.environ.setdefault("OPENAI_BASE_URL", base_url)


# ---------------------------------------------------------------------------
# Model configurations per agent
# ---------------------------------------------------------------------------
@dataclass
class ModelConfig:
    """Configuration for a single agent's model routing."""
    adapter: str
    model: str
    fallback: str | None = None
    streaming: bool = True
    provider: str = "qwen"
    fallback_provider: str = "qwen"
    max_tokens: int | None = None
    extra: dict = field(default_factory=dict)


MODELS: dict[str, ModelConfig] = {
    "triage": ModelConfig(
        adapter="langchain_openai",
        model=os.getenv("QWEN_TRIAGE_MODEL", "qwen3.6-flash"),
        fallback=os.getenv("QWEN_TRIAGE_FALLBACK_MODEL", "qwen3.7-plus"),
        streaming=False,
    ),
    "diagnosis": ModelConfig(
        adapter="local_room_qwen",
        model=os.getenv("QWEN_DIAGNOSIS_MODEL", "qwen3.7-plus"),
        fallback=os.getenv("QWEN_DIAGNOSIS_FALLBACK_MODEL", "qwen3.6-flash"),
        max_tokens=4096,
    ),
    "safety_reviewer": ModelConfig(
        adapter="local_room_qwen",
        model=os.getenv("QWEN_SAFETY_MODEL", "qwen3.7-plus"),
        fallback=os.getenv("QWEN_SAFETY_FALLBACK_MODEL", "qwen3.6-flash"),
    ),
    "commander": ModelConfig(
        adapter="local_room_qwen",
        model=os.getenv("QWEN_COMMANDER_MODEL", "qwen3.7-plus"),
        fallback=os.getenv("QWEN_COMMANDER_FALLBACK_MODEL", "qwen3.6-flash"),
        max_tokens=2000,
    ),
    "operator": ModelConfig(
        adapter="local_room_qwen",
        model=os.getenv("QWEN_OPERATOR_MODEL", "qwen3.6-flash"),
        fallback=os.getenv("QWEN_OPERATOR_FALLBACK_MODEL", "qwen3.7-plus"),
        streaming=False,
    ),
}


# ---------------------------------------------------------------------------
# Resilient model fallback (§20.4)
# ---------------------------------------------------------------------------
_fallback_logger = _logging.getLogger("yiting.config")

# Track which agents have switched to fallback (in-memory, per-process)
_agents_on_fallback: dict[str, bool] = {}


def get_model_with_fallback(role: str) -> tuple[str, str]:
    """Return (model_string, provider) for an agent role.

    On first call, returns the primary model. If switch_to_fallback()
    has been called for this role, returns the fallback model/provider.

    Returns:
        (model, provider) tuple ready for adapter use.
    """
    cfg = MODELS.get(role)
    if cfg is None:
        raise ValueError(f"Unknown agent role: {role}")

    if _agents_on_fallback.get(role, False) and cfg.fallback:
        _fallback_logger.info(
            f"[config] Using FALLBACK model for {role}: {cfg.fallback} "
            f"(provider: {cfg.fallback_provider})"
        )
        return cfg.fallback, cfg.fallback_provider
    return cfg.model, cfg.provider


def switch_to_fallback(role: str) -> bool:
    """Switch an agent to its fallback model. Returns True if switched.

    Call this when the primary model fails (API error, timeout, etc.).
    The switch persists for the lifetime of the process.
    """
    cfg = MODELS.get(role)
    if cfg is None or not cfg.fallback:
        _fallback_logger.warning(
            f"[config] Cannot switch {role} to fallback — "
            f"{'unknown role' if cfg is None else 'no fallback configured'}"
        )
        return False

    if not _agents_on_fallback.get(role, False):
        _agents_on_fallback[role] = True
        _fallback_logger.warning(
            f"[config] SWITCHED {role}: {cfg.model} → {cfg.fallback} "
            f"(provider: {cfg.provider} → {cfg.fallback_provider})"
        )
        return True
    return False  # Already on fallback


def reset_to_primary(role: str) -> None:
    """Reset an agent back to its primary model."""
    _agents_on_fallback.pop(role, None)


# ---------------------------------------------------------------------------
# Agent ID registry (populated from env vars, gitignored)
# ---------------------------------------------------------------------------
def get_agent_ids() -> dict[str, str]:
    """Load registered agent IDs from environment."""
    return {
        "recorder": os.getenv("RECORDER_AGENT_ID", ""),
        "triage": os.getenv("TRIAGE_AGENT_ID", ""),
        "diagnosis": os.getenv("DIAGNOSIS_AGENT_ID", ""),
        "safety_reviewer": os.getenv("SAFETY_REVIEWER_AGENT_ID", ""),
        "commander": os.getenv("COMMANDER_AGENT_ID", ""),
        "operator": os.getenv("OPERATOR_AGENT_ID", ""),
        "scribe": os.getenv("SCRIBE_AGENT_ID", ""),
    }


def get_trusted_agent_ids() -> set[str]:
    """Get the set of all trusted agent UUIDs for lookup_peers filtering."""
    return {v for v in get_agent_ids().values() if v}


def get_agent_api_key(role: str) -> str:
    """Get transport API key for a specific agent role."""
    key = os.getenv(f"{role.upper()}_SUBMISSION_KEY", "")
    if not key:
        key = os.getenv(f"{role.upper()}_API_KEY", "")
    if not key:
        key = os.getenv("INCIDENT_ROOM_API_KEY", "") or os.getenv("GATEWAY_SECRET", "")
    return key


# ---------------------------------------------------------------------------
# Provider API settings
# ---------------------------------------------------------------------------
def get_provider_settings() -> dict:
    """Get API keys and base URLs for all providers."""
    return {
        "qwen": {
            "api_key": get_qwen_api_key(),
            "api_base": get_qwen_base_url(),
        },
    }


# ---------------------------------------------------------------------------
# Gateway settings
# ---------------------------------------------------------------------------
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "")
GATEWAY_DB_PATH = Path(os.getenv("GATEWAY_DB_PATH", "yiting.db"))


# ---------------------------------------------------------------------------
# Human approver allowlist
# ---------------------------------------------------------------------------
HUMAN_APPROVER_IDS: set[str] = set(
    filter(None, os.getenv("HUMAN_APPROVER_IDS", "").split(","))
)


# ---------------------------------------------------------------------------
# Active incident allowlist (credit protection)
# ---------------------------------------------------------------------------
# When set, preprocessors skip ANY incident not in this set — zero Gateway
# calls, zero LLM calls on old rooms. Empty string = process everything.
# Usage: ACTIVE_INCIDENTS=INC-ABC123,INC-DEF456
ACTIVE_INCIDENTS: frozenset[str] = frozenset(
    s.strip() for s in os.getenv("ACTIVE_INCIDENTS", "").split(",") if s.strip()
)

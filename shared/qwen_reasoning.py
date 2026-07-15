"""Qwen advisory reasoning helpers for local incident-room agents.

The safety-critical state transitions in YITING remain deterministic.  This
module lets local-runtime agents ask Qwen for concise reasoning text or
candidate summaries without letting the model own authorization, runbook
policy, nonce binding, or execution validation.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from .config import MODELS, get_qwen_api_key, get_qwen_base_url
from .qwen_budget import QwenBudgetExceeded, estimate_tokens, reserve, response_total_tokens

logger = logging.getLogger("yiting.qwen")

try:  # Import lazily enough that offline test shells can still import agents.
    from litellm import acompletion
except ImportError:  # pragma: no cover - exercised in dependency-light shells
    acompletion = None


def qwen_reasoning_enabled() -> bool:
    """Return True when live Qwen calls are allowed for agent reasoning."""
    if os.getenv("YITING_TEST_MODE", "").lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("YITING_DISABLE_QWEN_REASONING", "").lower() in {"1", "true", "yes"}:
        return False
    return bool(get_qwen_api_key())


def normalize_litellm_model(model: str) -> str:
    """Normalize configured Qwen model strings for LiteLLM's compatibility route."""
    model = (model or "").strip()
    if model.startswith("openai:"):
        return "openai/" + model.split(":", 1)[1]
    if model.startswith("openai/"):
        return model
    return "openai/" + model


def _extract_text(response: Any) -> str:
    """Extract assistant content from LiteLLM's chat-completion response."""
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


async def ask_qwen_json(
    *,
    role: str,
    system: str,
    user: dict[str, Any],
    max_tokens: int = 700,
) -> dict[str, Any] | None:
    """Ask the configured Qwen model for a JSON object.

    Returns ``None`` on test mode, missing credentials, API failure, or malformed
    output.  Callers must treat the result as advisory and preserve their
    deterministic guards.
    """
    if not qwen_reasoning_enabled():
        return None

    config = MODELS.get(role)
    if config is None:
        logger.warning("[qwen] Unknown role for advisory reasoning: %s", role)
        return None
    if acompletion is None:
        logger.warning("[qwen] LiteLLM is not installed; skipping %s reasoning", role)
        return None

    estimated_tokens = estimate_tokens(system, user, max_tokens=min(max_tokens, config.max_tokens or max_tokens))
    reservation = reserve(estimated_tokens)
    try:
        response = await acompletion(
            model=normalize_litellm_model(config.model),
            api_key=get_qwen_api_key(),
            api_base=get_qwen_base_url(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        system.strip()
                        + "\nReturn only one compact JSON object. Do not include markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(user, sort_keys=True, default=str),
                },
            ],
            temperature=0.1,
            max_tokens=min(max_tokens, config.max_tokens or max_tokens),
            response_format={"type": "json_object"},
        )
        reservation.commit(response_total_tokens(response))
    except Exception as exc:
        if isinstance(exc, QwenBudgetExceeded):
            raise
        reservation.release()
        logger.warning(
            "[qwen] Advisory reasoning failed for %s (%s)",
            role,
            type(exc).__name__,
        )
        return None

    parsed = _parse_json_object(_extract_text(response))
    if parsed is None:
        logger.warning("[qwen] Advisory reasoning returned non-JSON for %s", role)
    _raw_log(role, config.model, system, user, response)
    return parsed


def _raw_log(role, model, system, user, response) -> None:
    """Opt-in raw provider-response logger for offline evaluation only.

    Off by default; active only when YITING_QWEN_RAW_LOG_DIR is set. The judge
    deployment never sets it, so this is inert in production.
    """
    log_dir = os.getenv("YITING_QWEN_RAW_LOG_DIR", "").strip()
    if not log_dir:
        return
    try:
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "role": role,
            "model": model,
            "system": system,
            "user": user,
            "raw_text": _extract_text(response),
            "usage_total_tokens": response_total_tokens(response),
        }
        with open(os.path.join(log_dir, "qwen_raw.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:  # never let logging break reasoning
        logger.debug("[qwen] raw-log write skipped", exc_info=True)


def bounded_text(value: Any, *, max_len: int) -> str | None:
    """Return a stripped string bounded to max_len, or None if unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_len]

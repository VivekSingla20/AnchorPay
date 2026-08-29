"""
classify/llm_client.py — thin, provider-optional LLM client abstraction.

Design goal: `make eval` must be fully reproducible on a clean clone with NO
API key and NO network access ("Reproducibility is a scored property", Build
Spec Part 11). So this module:
  - Reads RECOVERY_ENGINE_USE_LLM from the environment. Default: false.
  - When false — or when the optional `anthropic` package isn't installed,
    or a call fails, times out, or returns invalid JSON — every caller falls
    back to its OWN deterministic default and records that as an
    ActorType.LLM_FALLBACK decision. `call_structured` never raises.
  - When true, calls Anthropic's Claude with a strict JSON schema embedded
    in the system prompt and validates the response with Pydantic before
    trusting a single field of it.

This is the ONLY module in the codebase allowed to import the optional
`anthropic` package. src/policy/* and src/guardrails/* must never import
this module (or `anthropic`/`openai` directly) — enforced by
tests/test_no_llm_in_policy.py.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class LlmCallResult:
    """Whatever happens, callers get one of these back — never an exception
    (Build Spec §5.4: "a defined behaviour when output fails validation ...
    never to retry indefinitely")."""

    ok: bool
    parsed: Optional[BaseModel]
    raw_text: Optional[str]
    latency_ms: float
    model: Optional[str]
    error: Optional[str]


@dataclass
class UsageStats:
    """Real, accumulated usage across every call_structured invocation in the
    current process — this is what makes the "LLM cost" section of
    EVALUATION.md a measurement instead of a hardcoded sentence (Razorpay
    Agent Studio principle 7, "transparent pricing / cost")."""

    call_count: int = 0
    ok_count: int = 0
    fallback_count: int = 0
    total_latency_ms: float = 0.0


_usage = UsageStats()


def get_usage_stats() -> UsageStats:
    return UsageStats(**vars(_usage))


def reset_usage_stats() -> None:
    """Test/eval-run isolation — call between independent runs, same spirit
    as ingest/normaliser.py's reset_idempotency_cache()."""
    global _usage
    _usage = UsageStats()


def llm_enabled() -> bool:
    return os.getenv("RECOVERY_ENGINE_USE_LLM", "false").strip().lower() in ("1", "true", "yes")


def _get_client():
    try:
        import anthropic  # optional dependency — see requirements-llm.txt
    except ImportError:
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def call_structured(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: Type[T],
) -> LlmCallResult:
    """Public entry point — every caller goes through here so usage is
    tracked in exactly one place, regardless of which of
    _call_structured_uncounted's several return paths fired."""
    result = _call_structured_uncounted(system_prompt=system_prompt, user_prompt=user_prompt, response_model=response_model)
    _usage.call_count += 1
    _usage.ok_count += int(result.ok)
    _usage.fallback_count += int(not result.ok)
    _usage.total_latency_ms += result.latency_ms
    return result


def _call_structured_uncounted(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: Type[T],
) -> LlmCallResult:
    """Attempts a real LLM call IF enabled and configured; otherwise returns
    ok=False immediately with a clear error string so the caller's
    deterministic fallback path runs. Never raises — a malformed/timed-out
    call must degrade one mandate's classification quality, not crash a
    batch of thousands (Failure Injection #1/#2)."""
    if not llm_enabled():
        return LlmCallResult(False, None, None, 0.0, None, "RECOVERY_ENGINE_USE_LLM is not set to true")

    client = _get_client()
    if client is None:
        return LlmCallResult(False, None, None, 0.0, None, "anthropic package not installed or ANTHROPIC_API_KEY not set")

    model = os.getenv("RECOVERY_ENGINE_MODEL", "claude-sonnet-4-5")
    timeout_s = float(os.getenv("RECOVERY_ENGINE_LLM_TIMEOUT_SECONDS", "8"))

    schema_hint = json.dumps(response_model.model_json_schema(), indent=2)
    full_system = (
        f"{system_prompt}\n\nRespond with ONLY a single JSON object matching this schema, "
        f"no markdown fences, no commentary:\n{schema_hint}"
    )

    start = time.monotonic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=full_system,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=timeout_s,
        )
        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    except Exception as exc:  # noqa: BLE001 — any SDK/network failure must degrade gracefully, never crash a batch
        latency_ms = (time.monotonic() - start) * 1000
        return LlmCallResult(False, None, None, latency_ms, model, f"LLM call raised: {exc!r}")

    latency_ms = (time.monotonic() - start) * 1000
    try:
        payload = json.loads(raw_text)
        parsed = response_model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        return LlmCallResult(False, None, raw_text, latency_ms, model, f"schema validation failed: {exc}")

    return LlmCallResult(True, parsed, raw_text, latency_ms, model, None)

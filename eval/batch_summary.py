"""
eval/batch_summary.py — LLM-assisted, one-paragraph narration of an already-
computed metrics dict, for a human reader at the top of EVALUATION.md.

Reads numbers `eval/run_eval.py`'s compute_metrics() already produced —
never computes, alters, or rounds a single one itself (Build Spec §5.4's
permitted "summarising the batch for a human reader"). Same deterministic-
fallback contract as every other LLM-assisted stage: off/unreachable/invalid
output all degrade to a plain templated paragraph, never a blank or a crash.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.classify.llm_client import call_structured, llm_enabled
from src.domain.enums import ActorType


class _LlmSummarySchema(BaseModel):
    summary_text: str


def _deterministic_summary(metrics: dict) -> str:
    return (
        f"On the {metrics['split']} split ({metrics['n_records']} records), the {metrics['strategy']} "
        f"strategy recovered Rs {metrics['recovered_paise'] / 100:,.2f} of Rs {metrics['at_risk_paise'] / 100:,.2f} "
        f"at risk ({metrics['recovery_rate'] * 100:.2f}%), with {metrics['violations_total']} compliance violations "
        f"and {metrics['retries_wasted_on_terminal']} retries wasted on structurally unretryable reasons."
    )


def generate(metrics: dict) -> tuple[str, str]:
    """Returns (summary_text, actor)."""
    fallback = _deterministic_summary(metrics)

    system_prompt = (
        "You write ONE short paragraph (2-4 sentences) narrating a payments-recovery batch result for "
        "an engineer. Use ONLY the numbers given, verbatim. Never invent a figure, never editorialise "
        "beyond what the numbers show, never suggest a different decision than what already happened."
    )
    user_prompt = str(metrics)
    result = call_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=_LlmSummarySchema)
    if result.ok and result.parsed is not None:
        return result.parsed.summary_text, ActorType.LLM.value  # type: ignore[union-attr]
    return fallback, (ActorType.LLM_FALLBACK.value if llm_enabled() else ActorType.DETERMINISTIC.value)

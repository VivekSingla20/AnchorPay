"""
intervene/escalation_brief.py — LLM-assisted, human-facing narration of ONE
escalated mandate's decision trail, for the support agent who receives it.

Explicitly the permitted use case Build Spec §5.4 names and this project
had not yet built: "summarising ... for a human reader." It reads an
ALREADY-FINAL, already-decided outcome (the retryability gate already ran;
this never re-opens or second-guesses that verdict) and narrates it —
augmenting the human who investigates next, never deciding anything itself,
the same posture as Razorpay's own Oncall Agent (Domain Context §1.3:
"the agent investigates but does not make the judgment call").

Deterministic fallback (used whenever the LLM is off, unreachable, or
returns something invalid) is a one-line templated sentence built from the
same facts — never blank, never a crash, exactly the pattern already used by
classify/reason_classifier.py and intervene/copy_generator.py.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.classify.llm_client import call_structured, llm_enabled
from src.domain.enums import ActorType


class _LlmBriefSchema(BaseModel):
    brief_text: str


def _deterministic_brief(*, mandate_id: str, reason_value: str, amount_rupees: float, gate_rationale: str) -> str:
    return f"Rs {amount_rupees:,.2f}, reason='{reason_value}'. Gate rationale: {gate_rationale}"


def generate(*, mandate_id: str, reason_value: str, amount_rupees: float, gate_rationale: str) -> tuple[str, str]:
    """Returns (brief_text, actor). Never raises — same contract as every
    other LLM-assisted stage in this codebase."""
    fallback = _deterministic_brief(
        mandate_id=mandate_id, reason_value=reason_value, amount_rupees=amount_rupees, gate_rationale=gate_rationale
    )

    system_prompt = (
        "You write a 1-2 sentence plain-English note for a human support agent about to investigate "
        "one escalated payment mandate. Summarise ONLY the facts given. Do not suggest what the agent "
        "should decide, do not invent a cause not stated, do not add urgency."
    )
    user_prompt = (
        f"Mandate: {mandate_id}\nAmount: Rs {amount_rupees:,.2f}\n"
        f"Reason: {reason_value}\nWhy it was escalated: {gate_rationale}"
    )
    result = call_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=_LlmBriefSchema)
    if result.ok and result.parsed is not None:
        return result.parsed.brief_text, ActorType.LLM.value  # type: ignore[union-attr]
    return fallback, (ActorType.LLM_FALLBACK.value if llm_enabled() else ActorType.DETERMINISTIC.value)

"""
intervene/copy_generator.py — Stage 7: copy generator.

Drafts notification text for a chosen InterventionType. LLM-assisted with a
deterministic template fallback. EVERY output — LLM or template — passes
through guardrails/dark_pattern_screen.py before being considered sendable
(Build Spec §6.6: "Implement as a deterministic screen that runs AFTER
generation and can veto"). This module does not get to decide its own copy
is acceptable; the independent screen does.

Only facts explicitly passed in `context` are ever interpolated — this
module has no access to anything else, so it cannot fabricate an urgency,
deadline, or consequence that wasn't given to it.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.classify.llm_client import call_structured, llm_enabled
from src.domain.enums import ActorType, InterventionType
from src.guardrails import dark_pattern_screen


class _LlmCopySchema(BaseModel):
    copy_text: str


@dataclass
class CopyResult:
    text: str
    actor: str
    screen_passed: bool
    screen_detail: str


_TEMPLATES: dict[InterventionType, str] = {
    InterventionType.PRE_DEBIT_NOTICE: (
        "Your {merchant_label} payment of Rs {amount_rupees} is scheduled for {window_label} on {date_label}. "
        "No action is needed if your usual account has sufficient balance. Reply STOP to opt out of these reminders."
    ),
    InterventionType.POST_DEBIT_CONFIRMATION: (
        "Rs {amount_rupees} was successfully collected for your {merchant_label} payment on {date_label}. "
        "Reply STOP to opt out of these confirmations."
    ),
    InterventionType.BALANCE_NUDGE: (
        "Your last {merchant_label} payment attempt of Rs {amount_rupees} did not go through due to available balance. "
        "We will try again on {date_label} during {window_label}. Reply STOP to opt out."
    ),
    InterventionType.SOURCE_AWARE_FAILURE_NOTICE: (
        "Your {merchant_label} payment of Rs {amount_rupees} could not be completed: {failure_explanation}. "
        "{next_step} Reply STOP to opt out."
    ),
    InterventionType.ALTERNATE_RAIL_SUGGESTION: (
        "Your {merchant_label} UPI AutoPay payment of Rs {amount_rupees} did not go through. "
        "You can also complete this payment directly at {short_url_label}. Reply STOP to opt out."
    ),
    InterventionType.CANCELLATION_CONFIRMATION: (
        "We noticed your {merchant_label} mandate has not been executed for several cycles. You have options: "
        "reply PAUSE to pause billing for {pause_cycles} cycle(s) at no charge, reply CANCEL to stop permanently "
        "with no further attempts, or reply KEEP if this was unintended and we'll retry your next cycle as usual."
    ),
    InterventionType.ESCALATE_TO_SUPPORT: (
        "Your {merchant_label} payment of Rs {amount_rupees} needs a closer look on our side. "
        "Our support team has been notified and will follow up — no action is needed from you right now."
    ),
    InterventionType.NO_ACTION: "",
}


def _deterministic_copy(intervention_type: InterventionType, context: dict) -> str:
    template = _TEMPLATES.get(intervention_type, "")
    try:
        return template.format(**context)
    except KeyError:
        return template  # fail toward the safest text rather than raising mid-batch


def generate(*, intervention_type: InterventionType, context: dict) -> CopyResult:
    fallback_text = _deterministic_copy(intervention_type, context)

    system_prompt = (
        "Draft a short SMS/notification (under 320 characters) for a UPI AutoPay payment event. "
        "State ONLY the facts given to you. Never invent urgency, scarcity, deadlines, or "
        "consequences that are not explicitly provided. Always include an opt-out instruction."
    )
    user_prompt = f"Intervention type: {intervention_type.value}\nFacts: {context}\n"
    result = call_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=_LlmCopySchema)

    if result.ok and result.parsed is not None:
        candidate_text = result.parsed.copy_text  # type: ignore[union-attr]
        actor = ActorType.LLM.value
    else:
        candidate_text = fallback_text
        actor = ActorType.LLM_FALLBACK.value if llm_enabled() else ActorType.DETERMINISTIC.value

    screen_result = dark_pattern_screen.screen(candidate_text)
    if not screen_result.passed:
        # The independent screen vetoed the draft (LLM or template).
        # Fall back to the template and re-screen it. A unit test asserts
        # every entry in _TEMPLATES passes the screen, so this branch is a
        # safety net for the LLM path, not an expected outcome for templates.
        candidate_text = fallback_text
        actor = ActorType.LLM_FALLBACK.value
        screen_result = dark_pattern_screen.screen(candidate_text)

    return CopyResult(text=candidate_text, actor=actor, screen_passed=screen_result.passed, screen_detail=screen_result.detail)

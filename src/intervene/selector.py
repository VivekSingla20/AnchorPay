"""
intervene/selector.py — Stage 6: the intervention selector.

Chooses exactly ONE InterventionType from the enumerated set (never invents
a new action) given structured context: retryability verdict, attempt
number, arrears, whether a fresh pre-debit notice is due. LLM-assisted with
a deterministic rule table as both the fallback AND the reference the LLM is
shown — so the system behaves identically whether or not an API key is
configured; the LLM's only value-add is nuance in ambiguous cases, never the
allowed action set itself, and never the grace-period ceiling (INV-10),
which is enforced independently regardless of what either path proposes.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.classify.llm_client import call_structured
from src.domain import regulatory_constants as RC
from src.domain.entities import Mandate
from src.domain.enums import ActorType, InterventionType, RetryabilityVerdict


class InterventionChoice(BaseModel):
    intervention_type: str
    grace_period_days: Optional[int] = None
    rationale: str
    actor: str


class _LlmInterventionSchema(BaseModel):
    intervention_type: str = Field(description="must be exactly one value from the allowed enumerated set")
    grace_period_days: Optional[int] = Field(default=None, description="only if implying a grace period; must be 1, 2, or 3")
    rationale: str


_ALLOWED_TYPES = {t.value for t in InterventionType}


def _deterministic_choice(*, verdict: RetryabilityVerdict, attempt_number: int, mandate: Mandate) -> InterventionChoice:
    """The rule table this engine falls back to — and, absent an API key,
    always uses. A plain conditional chain over ENUMERATED outcomes, not
    free-form generation."""
    if verdict == RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT:
        return InterventionChoice(
            intervention_type=InterventionType.CANCELLATION_CONFIRMATION.value,
            rationale="intent-inference flagged this as likely intentional non-payment; confirm rather than chase (Domain Context §3.2).",
            actor=ActorType.DETERMINISTIC.value,
        )
    if verdict == RetryabilityVerdict.TERMINAL:
        return InterventionChoice(
            intervention_type=InterventionType.SOURCE_AWARE_FAILURE_NOTICE.value,
            rationale="terminal reason — notify with the true cause so the customer knows to act, but never schedule another debit attempt.",
            actor=ActorType.DETERMINISTIC.value,
        )
    if verdict == RetryabilityVerdict.INVESTIGATE:
        return InterventionChoice(
            intervention_type=InterventionType.ESCALATE_TO_SUPPORT.value,
            rationale="reason requires investigation per Razorpay's own guidance; route to support rather than guess.",
            actor=ActorType.DETERMINISTIC.value,
        )
    # RETRYABLE: a debit IS being scheduled, so the notification MUST be a
    # pre-debit notice (RBI E-Mandate Framework, §2.2) for EVERY attempt, not
    # just the first — this is a standing regulatory obligation, not a
    # choice. The only real choice left is whether a grace period accompanies
    # it, and only from the merchant-configured allowlist (INV-10).
    grace = RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS[0] if (mandate.arrears_paise > 0 and attempt_number >= 3) else None
    return InterventionChoice(
        intervention_type=InterventionType.PRE_DEBIT_NOTICE.value,
        grace_period_days=grace,
        rationale="RETRYABLE — a debit is being scheduled, so a pre-debit notice is a standing obligation (§2.2) for every attempt, "
        "regardless of attempt number; a grace-period nudge is attached only when arrears exist late in the budget.",
        actor=ActorType.DETERMINISTIC.value,
    )


def select(*, verdict: RetryabilityVerdict, attempt_number: int, mandate: Mandate) -> InterventionChoice:
    fallback = _deterministic_choice(verdict=verdict, attempt_number=attempt_number, mandate=mandate)

    system_prompt = (
        "You select exactly ONE customer intervention for a failed UPI AutoPay mandate, "
        f"from this fixed enumerated set only: {sorted(_ALLOWED_TYPES)}. You never invent a "
        f"new intervention type. If you suggest a grace period, it must be exactly one of "
        f"{RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS} days — never any other number."
    )
    user_prompt = (
        f"Retryability verdict: {verdict.value}\n"
        f"Attempt number: {attempt_number}\n"
        f"Arrears (paise): {mandate.arrears_paise}\n"
        f"Deterministic reference choice (you may agree, or propose a better fit from the "
        f"allowed set): {fallback.intervention_type}"
    )
    result = call_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=_LlmInterventionSchema)
    if not result.ok or result.parsed is None:
        return fallback

    parsed: _LlmInterventionSchema = result.parsed  # type: ignore[assignment]
    if parsed.intervention_type not in _ALLOWED_TYPES:
        return InterventionChoice(
            intervention_type=fallback.intervention_type,
            grace_period_days=fallback.grace_period_days,
            rationale=f"LLM proposed '{parsed.intervention_type}', outside the allowed set; used the deterministic fallback instead.",
            actor=ActorType.LLM_FALLBACK.value,
        )
    if parsed.grace_period_days is not None and parsed.grace_period_days not in RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS:
        return InterventionChoice(
            intervention_type=parsed.intervention_type,
            grace_period_days=None,
            rationale=f"LLM proposed grace_period_days={parsed.grace_period_days}, outside the allowlist; dropped (INV-10 protects this independently anyway).",
            actor=ActorType.LLM_FALLBACK.value,
        )
    return InterventionChoice(
        intervention_type=parsed.intervention_type,
        grace_period_days=parsed.grace_period_days,
        rationale=parsed.rationale,
        actor=ActorType.LLM.value,
    )

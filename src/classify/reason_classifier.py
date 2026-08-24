"""
classify/reason_classifier.py — Stage 2: the classifier.

Deliberately narrow scope (see DECISIONS.md ADR-005): a FailureEvent's
`reason` is ALREADY a structured enum whenever Razorpay supplied a
recognised one — there is nothing to classify in that case, and calling an
LLM to relabel a value we already have would be pure waste (cost, latency,
one more chance to get it wrong). This module only does real work when
`reason == FailureReason.UNKNOWN` (Failure Injection #5: a reason not in the
taxonomy arrives). Even then, its suggestion is advisory only — it is NEVER
read by policy/retryability.py, which always routes an unresolved UNKNOWN to
INVESTIGATE regardless of what the classifier guesses. The classifier exists
to shorten a human reviewer's triage time, not to make the retry decision.

Structured output, strict schema, deterministic fallback on any failure —
per Build Spec §5.4. NO import from src.policy or src.guardrails.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.classify.llm_client import call_structured
from src.domain.entities import FailureEvent
from src.domain.enums import ActorType, FailureReason


class ClassificationResult(BaseModel):
    """The strict schema the LLM must fill — this IS the response_model
    passed to call_structured, so any output not matching this shape fails
    validation and triggers the deterministic fallback automatically."""

    suggested_reason: str = Field(description="one of the known FailureReason values that best fits the free text")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(description="a short quote or paraphrase of the input supporting this suggestion")


class ClassifierOutcome(BaseModel):
    suggested_reason: Optional[FailureReason]
    confidence: float
    evidence: str
    actor: str  # an ActorType value


_KNOWN_REASON_VALUES = {r.value for r in FailureReason if r != FailureReason.UNKNOWN}


def classify_unknown_reason(event: FailureEvent) -> ClassifierOutcome:
    """Only meaningful when event.reason == FailureReason.UNKNOWN. Returns a
    SUGGESTION for the audit trail / a human reviewer — never consumed by
    policy/retryability.py, which treats every UNKNOWN as INVESTIGATE no
    matter what this returns (see that module and DECISIONS.md ADR-005)."""
    fallback = ClassifierOutcome(
        suggested_reason=None,
        confidence=0.0,
        evidence="deterministic fallback: no LLM configured, or the call failed; unresolved reason routed to INVESTIGATE regardless",
        actor=ActorType.DETERMINISTIC.value,
    )

    system_prompt = (
        "You classify a failed UPI AutoPay mandate execution's raw reason text into "
        "the single closest match from a fixed, closed taxonomy. You NEVER invent a "
        "new reason value outside that taxonomy. If nothing fits reasonably, say so "
        "with a low confidence score rather than forcing a match."
    )
    user_prompt = (
        f"Raw/unrecognised reason text: {event.raw_reason_text!r}\n"
        f"Description: {event.description!r}\n"
        f"Known taxonomy values: {sorted(_KNOWN_REASON_VALUES)}\n"
        "Which known value is the closest match, and why?"
    )
    result = call_structured(system_prompt=system_prompt, user_prompt=user_prompt, response_model=ClassificationResult)
    if not result.ok or result.parsed is None:
        return fallback

    parsed: ClassificationResult = result.parsed  # type: ignore[assignment]
    if parsed.suggested_reason not in _KNOWN_REASON_VALUES:
        # The model proposed a value outside the closed taxonomy. JSON
        # parsing succeeded but this IS the validation failure Build Spec
        # §5.4 requires falling back on.
        return ClassifierOutcome(
            suggested_reason=None,
            confidence=0.0,
            evidence=f"LLM proposed '{parsed.suggested_reason}', outside the closed taxonomy; discarded.",
            actor=ActorType.LLM_FALLBACK.value,
        )
    return ClassifierOutcome(
        suggested_reason=FailureReason(parsed.suggested_reason),
        confidence=parsed.confidence,
        evidence=parsed.evidence,
        actor=ActorType.LLM.value,
    )

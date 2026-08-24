"""
policy/retryability.py — Stage 3: the retryability gate. Deterministic.

This is the "official" gate the allocator (stage 5) consults when proposing
a schedule. guardrails/validator.py and guardrails/invariants.py deliberately
DUPLICATE the terminality check rather than import it from here — see their
module docstrings for why (independence: stage 8 must not trust stage 3's
stored verdict, it must re-derive it).

NO LLM IMPORT — enforced by tests/test_no_llm_in_policy.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain import regulatory_constants as RC
from src.domain.entities import FailureEvent, Mandate
from src.domain.enums import RetryabilityVerdict


@dataclass
class RetryabilityResult:
    verdict: RetryabilityVerdict
    rationale: str
    spec_reference: str


def evaluate(event: FailureEvent, mandate: Mandate) -> RetryabilityResult:
    """Pure function of (event, mandate) — same inputs always produce the
    same verdict. No wall-clock, no randomness, no LLM."""
    if event.npci_code is not None and event.npci_code in RC.NPCI_CODE_VERDICT_OVERRIDE:
        verdict = RC.NPCI_CODE_VERDICT_OVERRIDE[event.npci_code]
        return RetryabilityResult(
            verdict,
            f"NPCI code {event.npci_code.value} overrides the reason-level verdict "
            f"({'structural per-transaction ceiling, cannot succeed unchanged' if verdict == RetryabilityVerdict.TERMINAL else 'transient, but immediate retry re-triggers the same velocity limit'}).",
            "Build Spec Part 4.1 rows 4-5 (Z7/Z8)",
        )

    row = RC.REASON_STRATEGY_BY_REASON.get(event.reason)
    if row is None:
        # Failure Injection #5: a reason not in the taxonomy (FailureReason.UNKNOWN,
        # or any future Razorpay reason this table hasn't been updated for).
        # Deterministic, conservative default: do NOT auto-retry on money's
        # behalf against an unrecognised reason. The classifier (stage 2,
        # LLM-assisted) may later propose a taxonomy mapping for a human to
        # confirm, but the gate itself never guesses.
        return RetryabilityResult(
            RetryabilityVerdict.INVESTIGATE,
            f"reason '{event.reason.value}' is not in the known taxonomy; "
            f"conservative default is INVESTIGATE, never an automatic retry.",
            "Build Spec Part 10 item 5 (failure injection: unrecognised reason)",
        )

    verdict = row.verdict
    rationale = row.rationale

    # Intent inference (Domain Context §3.2 — this engine's signature
    # feature). Even a nominally RETRYABLE insufficient_funds failure is
    # re-routed if THIS mandate's own recorded history shows the "empty
    # account used as a cancel button" pattern documented on TechnoFino.
    # Deterministic: a count and a ratio threshold over the mandate's own
    # history — never an LLM judgment call, because a payment does not get
    # stopped or retried based on a language model's opinion (Build Spec
    # §0.1 / §5.4). See ASSUMPTIONS.md #A2 and DECISIONS.md ADR-001.
    if verdict == RetryabilityVerdict.RETRYABLE and _looks_intentional(mandate):
        return RetryabilityResult(
            RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT,
            "persistent low-balance pattern across consecutive cycles resembles the "
            "deliberate 'empty account as a cancel button' signal (Domain Context §3.2, "
            "TechnoFino) — routed to cancellation-confirmation instead of recovery, per "
            "the 'a no ends the sequence' principle.",
            "Domain Context §3.2, Tier-1 idea #1 (intent inference)",
        )

    return RetryabilityResult(verdict, rationale, row.spec_reference)


def _looks_intentional(mandate: Mandate) -> bool:
    if mandate.consecutive_same_reason_failures < RC.UNVERIFIED_INTENT_MIN_CONSECUTIVE_SAME_REASON_FAILURES:
        return False
    if mandate.account_balance_paise_hint is None:
        return False
    ratio = mandate.account_balance_paise_hint / max(mandate.amount_paise, 1)
    return ratio <= RC.UNVERIFIED_INTENT_MAX_BALANCE_TO_AMOUNT_RATIO

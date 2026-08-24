"""
guardrails/validator.py — Stage 8: THE independent validation layer.

Every proposed action (a scheduled execution attempt, an outbound
notification, a grace-period offer) passes through here IMMEDIATELY BEFORE
IT HAPPENS — not only when it was first scheduled. This module re-derives
legality from the raw event and the regulatory constants; it does not trust
any upstream stage's stored verdict.

This is what makes Failure Injection #8 (an opt-out arriving between
scheduling and execution) resolve correctly: the check that matters is the
one run at send/execute time against CURRENT state, not the one run when the
schedule was first proposed. See FAILURES.md #8.

INDEPENDENCE RULE (enforced by tests/test_no_llm_in_policy.py): this module
imports ONLY from src.domain. It never imports src.policy, src.classify, or
src.intervene — "the agent proposes, the platform disposes" (Build Spec §1
principle 4) is only true if this layer cannot be silently trusted-through by
an upstream bug.

LIMITATION, stated honestly: `_mint_token` below is a plain SHA-256 digest,
not an HMAC signed with a server-held secret. That is sufficient to prove the
*shape* of "execution requires a token minted by this exact module, at this
exact time, and the executor verifies it" for this simulation, but a real
deployment must use an HMAC (or better, a KMS-backed signature) keyed to a
secret only this module holds, so a compromised caller cannot forge a token.
Recorded in LIMITATIONS.md.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import Mandate
from src.domain.enums import FailureReason, NpciResponseCode, RetryabilityVerdict


@dataclass
class GuardrailDecision:
    approved: bool
    reason: str
    approval_token: Optional[str] = None


def _mint_token(mandate_id: str, action_kind: str, at: int) -> str:
    raw = f"{mandate_id}:{action_kind}:{at}".encode()
    return "tok_" + hashlib.sha256(raw).hexdigest()[:24]


def _is_terminal_event(reason: FailureReason, npci_code: Optional[NpciResponseCode]) -> bool:
    """Independently re-derived — deliberately duplicated from
    policy/retryability.py's identical helper. See module docstring."""
    if npci_code is not None and npci_code in RC.NPCI_CODE_VERDICT_OVERRIDE:
        return RC.NPCI_CODE_VERDICT_OVERRIDE[npci_code] == RetryabilityVerdict.TERMINAL
    row = RC.REASON_STRATEGY_BY_REASON.get(reason)
    return row is not None and row.verdict == RetryabilityVerdict.TERMINAL


def validate_execution(
    *,
    mandate: Mandate,
    proposed_scheduled_at: int,
    attempt_number: int,
    prior_terminal_reason: Optional[FailureReason],
    prior_terminal_npci_code: Optional[NpciResponseCode],
    now: int,
) -> GuardrailDecision:
    """Re-checks, at the moment of execution, everything that could make
    this attempt illegal. Called by src/execute/simulator.py immediately
    before running an attempt — never relying on a check done only when the
    schedule was first created.

    Includes an opt-out check even though opt-out is "a consent/contact
    rule": an execution's mandatory POST-debit notice (INV-07) could be
    blocked by an opt-out that arrives between scheduling and execution,
    which would silently produce a debit with no notice either side of it —
    caught by this engine's own test suite (see AI_USAGE.md, FAILURES.md
    #8). Vetoing the execution itself, not just the follow-up notice, is
    the simpler and only internally-consistent rule: an opt-out stops
    EVERYTHING from that point forward, not just messages.
    """
    if attempt_number > RC.MAX_EXECUTION_ATTEMPTS_TOTAL:
        return GuardrailDecision(
            False, f"attempt {attempt_number} exceeds the {RC.MAX_EXECUTION_ATTEMPTS_TOTAL}-attempt cap (INV-02)."
        )
    if prior_terminal_reason is not None and _is_terminal_event(prior_terminal_reason, prior_terminal_npci_code):
        return GuardrailDecision(
            False,
            f"prior failure reason '{prior_terminal_reason.value}' is terminal; "
            f"no further attempt is legal (INV-03).",
        )
    if not timeutils.is_permitted_execution_time(proposed_scheduled_at):
        return GuardrailDecision(
            False,
            f"{timeutils.to_ist(proposed_scheduled_at).isoformat()} IST falls inside a peak window (INV-01).",
        )
    if mandate.customer.opted_out_at is not None and now >= mandate.customer.opted_out_at:
        return GuardrailDecision(False, "customer opted out before this execution time; a debit with no valid post-debit notice path is not legal (INV-07/INV-08).")
    if mandate.subscription.status.value == "cancelled":
        return GuardrailDecision(False, "subscription is cancelled; no execution may proceed.")
    token = _mint_token(mandate.mandate_id, "execute", now)
    return GuardrailDecision(True, "all checks re-verified at execution time.", token)


_REGULATORY_MANDATORY_NOTICE_TYPES = frozenset({
    "pre_debit_notice",         # RBI E-Mandate Framework §2.2: 24h pre-debit notification is a standing obligation
    "post_debit_confirmation",  # §2.2: post-debit confirmation "after every collection" — INV-06/INV-07
    "source_aware_failure_notice",  # the failed-attempt half of "after every collection attempt outcome" — INV-07
})


def validate_notification(
    *,
    mandate: Mandate,
    intervention_type: str,
    now: int,
) -> GuardrailDecision:
    """Re-checks CURRENT opt-out state and today's contact budget. This is
    the check that resolves Failure Injection #8 correctly: opt-out is
    checked HERE, at send time, not only when the notification was queued.

    Contact budget is derived from `last_contacted_at`'s calendar day rather
    than an incrementing counter that would need an explicit daily reset —
    a counter-based design silently locks a mandate out forever after its
    first contact if nothing ever resets it. Comparing calendar days is
    stateless and cannot get stuck.

    The daily budget NEVER applies to pre_debit_notice, post_debit_confirmation,
    or source_aware_failure_notice: these three are standing regulatory
    obligations (§2.2) and INV-06/INV-07 requirements, not discretionary
    nudges. An UNVERIFIED self-imposed "fewer, better-timed messages" budget
    (ASSUMPTIONS.md #A1) must never be able to silently cause a regulatory
    invariant to fail — discovered by this engine's own smoke test, see
    AI_USAGE.md and FAILURES.md.
    """
    if mandate.customer.opted_out_at is not None and now >= mandate.customer.opted_out_at:
        return GuardrailDecision(False, "customer opted out before this notification's send time (INV-08).")
    if intervention_type not in _REGULATORY_MANDATORY_NOTICE_TYPES and mandate.customer.last_contacted_at is not None:
        if RC.UNVERIFIED_MAX_CONTACTS_PER_MANDATE_PER_DAY <= 1 and timeutils.start_of_ist_day(mandate.customer.last_contacted_at) == timeutils.start_of_ist_day(now):
            return GuardrailDecision(False, "daily contact budget already spent for this mandate (ASSUMPTIONS.md #A1).")
    token = _mint_token(mandate.mandate_id, f"notify:{intervention_type}", now)
    return GuardrailDecision(True, "consent and contact-budget checks passed at send time.", token)


def validate_grace_period(days: int) -> GuardrailDecision:
    if days not in RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS or days > RC.MERCHANT_GRACE_PERIOD_CEILING_DAYS:
        return GuardrailDecision(
            False,
            f"grace_period_days={days} is outside the merchant-configured allowlist "
            f"{RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS} (INV-10).",
        )
    return GuardrailDecision(
        True, "within the merchant-configured allowlist and ceiling.", _mint_token("n/a", "grace_period", int(time.time()))
    )

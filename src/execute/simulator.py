"""
execute/simulator.py — Stage 9: the executor. Test-mode/simulation only
(Build Spec §1.4: "Not a real payment integration").

Two entry points, used differently by the engine vs. the four baselines —
see eval/baselines.py and eval/run_eval.py for how each is wired:

  - `simulate_outcome(...)` is the pure stochastic core: given a (mandate,
    scheduled_at) pair, would this specific attempt have succeeded? Used
    IDENTICALLY by every strategy so a comparison is about scheduling
    quality, not differing luck. The draw is deterministic per
    (mandate_id, hour) — the same slot always yields the same outcome no
    matter which strategy reaches it or how many times it's evaluated.

  - `execute_with_guardrail(...)` is used ONLY by the engine's own pipeline
    (src/orchestrator.py). It calls guardrails/validator.py immediately
    before "executing" — re-checking legality against CURRENT state, not
    state at schedule time. This is what makes Failure Injection #8 (opt-out
    arriving between scheduling and execution) resolve correctly for the
    engine, and it is deliberately NOT used by the baselines: a baseline has
    no independent guardrail layer by definition, so it executes whatever
    its own (possibly illegal) logic proposed. guardrails/invariants.py,
    applied after the fact in eval/run_eval.py, is what still counts a
    baseline's violations even though nothing blocked them from happening.

UNVERIFIED outcome model (ASSUMPTIONS.md #A8): base per-reason success rates
are this engine's own calibration, chosen only to be directionally plausible
(insufficient_funds lowest, transient technical errors highest — matching
the hard/soft-decline doctrine, Domain Context §4.5) and to leave clear,
measurable headroom for the salary-cycle and bank-health heuristics to move
the needle. Never presented as an empirical success-rate figure.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import Attempt, FailureEvent, Mandate
from src.domain.enums import FailureReason, FailureSource, NpciResponseCode, WindowLabel
from src.guardrails import validator
from src.policy.bank_health import DowntimeRecord, bank_health_score

_BASE_SUCCESS_RATE: dict[FailureReason, float] = {
    FailureReason.INSUFFICIENT_FUNDS: 0.35,
    FailureReason.BANK_TECHNICAL_ERROR: 0.55,
    FailureReason.GATEWAY_TECHNICAL_ERROR: 0.55,
    FailureReason.PAYMENT_DECLINED: 0.40,
    FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED: 0.45,
    FailureReason.PAYMENT_TIMED_OUT: 0.45,
    FailureReason.CREDIT_FAILED: 0.30,
    FailureReason.VPA_RESOLUTION_FAILED: 0.20,
    FailureReason.PAYMENT_CANCELLED: 0.15,
}
_SALARY_CYCLE_LIFT = 0.30
_BANK_UNHEALTHY_PENALTY = {"high": 0.45, "medium": 0.20, "low": 0.0}

_REASON_TO_SOURCE: dict[FailureReason, FailureSource] = {
    FailureReason.INSUFFICIENT_FUNDS: FailureSource.CUSTOMER,
    FailureReason.BANK_TECHNICAL_ERROR: FailureSource.BANK,
    FailureReason.GATEWAY_TECHNICAL_ERROR: FailureSource.GATEWAY,
    FailureReason.CREDIT_FAILED: FailureSource.RAZORPAY,
    FailureReason.INVALID_VPA: FailureSource.CUSTOMER,
    FailureReason.VPA_RESOLUTION_FAILED: FailureSource.RAZORPAY,
    FailureReason.PAYMENT_DECLINED: FailureSource.BANK,
    FailureReason.PAYMENT_CANCELLED: FailureSource.CUSTOMER,
    FailureReason.PAYMENT_TIMED_OUT: FailureSource.CUSTOMER,
    FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED: FailureSource.CUSTOMER,
    FailureReason.UNKNOWN: FailureSource.RAZORPAY,
}

_WINDOW_LABEL_MAP = {
    "before_10_00": WindowLabel.EARLY_MORNING,
    "13_00_to_17_00": WindowLabel.AFTERNOON,
    "after_21_30": WindowLabel.NIGHT,
}


def window_label_for(at: int) -> WindowLabel:
    w = timeutils.which_window(at)
    if w is None:
        return WindowLabel.AFTERNOON  # not expected for a legally-scheduled time; safe default only
    return _WINDOW_LABEL_MAP.get(w.label, WindowLabel.AFTERNOON)


def _outcome_draw(mandate_id: str, scheduled_at: int) -> float:
    """Deterministic pseudo-random draw in [0, 1), stable for a given
    (mandate, hour) pair regardless of which strategy or how many times it's
    evaluated — see module docstring on why this must not depend on call
    order or any global RNG state."""
    hour_bucket = scheduled_at // 3600
    h = hashlib.sha256(f"{mandate_id}:{hour_bucket}".encode()).hexdigest()
    return (int(h[:8], 16) % 10_000) / 10_000.0


def simulate_outcome(
    *,
    mandate: Mandate,
    reason: FailureReason,
    scheduled_at: int,
    npci_code: Optional[NpciResponseCode] = None,
    downtime_records: Optional[list[DowntimeRecord]] = None,
) -> bool:
    if reason == FailureReason.INVALID_VPA or npci_code == NpciResponseCode.Z8:
        return False  # structurally cannot succeed unchanged (a retry against the same amount cannot fix a
        # per-transaction ceiling or an unregistered VPA) — not even worth a draw. Any strategy that still
        # burns a retry here (a baseline, most likely) is measured as pure waste — see eval/run_eval.py.
    p = _BASE_SUCCESS_RATE.get(reason, 0.30)
    if reason == FailureReason.INSUFFICIENT_FUNDS and timeutils.to_ist(scheduled_at).day in RC.UNVERIFIED_SALARY_CYCLE_HIGH_LIQUIDITY_DAYS:
        p += _SALARY_CYCLE_LIFT
    signal = bank_health_score(mandate.payer_bank_code, scheduled_at, downtime_records)
    if signal.active_downtime_severity:
        p -= _BANK_UNHEALTHY_PENALTY.get(signal.active_downtime_severity, 0.0)
    p = min(max(p, 0.02), 0.95)
    return _outcome_draw(mandate.mandate_id, scheduled_at) < p


def build_failure_event(
    *,
    mandate: Mandate,
    reason: FailureReason,
    npci_code: Optional[NpciResponseCode],
    scheduled_at: int,
    attempt_number: int,
) -> FailureEvent:
    return FailureEvent(
        mandate_id=mandate.mandate_id,
        reason=reason,
        npci_code=npci_code,
        source=_REASON_TO_SOURCE.get(reason, FailureSource.RAZORPAY),
        amount_paise=mandate.amount_paise,
        occurred_at=scheduled_at,
        attempt_number=attempt_number,
    )


@dataclass
class ExecutionOutcome:
    attempt: Attempt
    guardrail_reason: str
    approved: bool


def execute_with_guardrail(
    *,
    mandate: Mandate,
    attempt_number: int,
    scheduled_at: int,
    root_cause_reason: FailureReason,
    root_cause_npci_code: Optional[NpciResponseCode],
    prior_terminal_reason: Optional[FailureReason],
    prior_terminal_npci_code: Optional[NpciResponseCode],
    now: int,
    downtime_records: Optional[list[DowntimeRecord]] = None,
) -> ExecutionOutcome:
    """The engine's own execution path — re-validates at the moment of
    execution against CURRENT facts (see module + validator.py docstrings)."""
    decision = validator.validate_execution(
        mandate=mandate,
        proposed_scheduled_at=scheduled_at,
        attempt_number=attempt_number,
        prior_terminal_reason=prior_terminal_reason,
        prior_terminal_npci_code=prior_terminal_npci_code,
        now=now,
    )
    label = window_label_for(scheduled_at)

    if not decision.approved:
        attempt = Attempt(
            mandate_id=mandate.mandate_id,
            attempt_number=attempt_number,
            scheduled_at=scheduled_at,
            window=label,
            executed_at=None,
            outcome="skipped",
            approval_token=None,
        )
        return ExecutionOutcome(attempt=attempt, guardrail_reason=decision.reason, approved=False)

    succeeded = simulate_outcome(
        mandate=mandate, reason=root_cause_reason, scheduled_at=scheduled_at,
        npci_code=root_cause_npci_code, downtime_records=downtime_records,
    )
    failure_event = None
    if not succeeded:
        failure_event = build_failure_event(
            mandate=mandate, reason=root_cause_reason, npci_code=root_cause_npci_code, scheduled_at=scheduled_at, attempt_number=attempt_number
        )
    attempt = Attempt(
        mandate_id=mandate.mandate_id,
        attempt_number=attempt_number,
        scheduled_at=scheduled_at,
        window=label,
        executed_at=scheduled_at,
        outcome="success" if succeeded else "failed",
        failure_event=failure_event,
        approval_token=decision.approval_token,
    )
    return ExecutionOutcome(attempt=attempt, guardrail_reason=decision.reason, approved=True)


def reactivate_subscription(mandate: Mandate) -> Mandate:
    """The ONLY function that may move a mandate's subscription from halted
    back to active. Enforces INV-15 STRUCTURALLY: arrears_paise is never
    touched here — see `collect_arrears` for the one function allowed to
    reduce it, which must always be called explicitly and separately (Build
    Spec §2.4: "returning to active does not re-collect arrears")."""
    from src.domain.enums import SubscriptionStatus

    updated_sub = mandate.subscription.model_copy(update={"status": SubscriptionStatus.ACTIVE})
    return mandate.model_copy(update={"subscription": updated_sub})


def collect_arrears(mandate: Mandate, collected_paise: int) -> Mandate:
    """The ONLY function allowed to reduce arrears_paise, and only ever via
    an explicit, separately-audited collection action — never as a
    side-effect of a status transition."""
    new_arrears = max(mandate.arrears_paise - collected_paise, 0)
    return mandate.model_copy(update={"arrears_paise": new_arrears})

"""
eval/baselines.py — B0-B3, per Build Spec Part 8.

None of these baselines call guardrails/validator.py — a baseline, by
definition, has no independent guardrail layer. Their compliance violations
are counted AFTER THE FACT by guardrails/invariants.py in eval/run_eval.py,
on exactly the same footing as the engine. That comparison — "the baseline
racks up N violations, the engine racks up zero, on the identical batch" —
is the single most persuasive artifact this submission produces.

All four strategies (B0-B3 here, plus the engine in src/orchestrator.py)
share the exact same stochastic outcome model
(src/execute/simulator.simulate_outcome), so a strategy's measured recovery
reflects scheduling quality, not differing luck on the underlying draw.

B3 is NOT implemented here. It is the engine's own allocator with both
ranking heuristics switched off — see eval/run_eval.py, which calls
`src.orchestrator.run_mandate(..., use_salary_cycle_heuristic=False,
use_bank_health_heuristic=False)` for the B3 row. This is deliberate reuse,
not an omission: B3 is defined by the Build Spec as "reason-aware, not
bank-aware", which is exactly what disabling the two heuristics produces,
and it doubles as the salary-cycle/bank-health ablation study named in
Domain Context Part 5 idea #2 — one mechanism, two required deliverables.
See DECISIONS.md ADR-008.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import Attempt, FailureEvent, Mandate, Notification
from src.execute import simulator


@dataclass
class BaselineRunResult:
    mandate: Mandate
    attempts: list[Attempt] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    final_status: str = "unknown"
    recovered_paise: int = 0


def _seed_attempt(mandate: Mandate, first_failure_event: FailureEvent) -> Attempt:
    """Every strategy starts from the same pre-existing failure — this
    attempt is excluded from invariant grading everywhere in eval/run_eval.py
    (it predates any strategy's involvement; see DECISIONS.md ADR-006/009)."""
    return Attempt(
        mandate_id=mandate.mandate_id,
        attempt_number=1,
        scheduled_at=first_failure_event.occurred_at,
        window=simulator.window_label_for(first_failure_event.occurred_at),
        executed_at=first_failure_event.occurred_at,
        outcome="failed",
        failure_event=first_failure_event,
        approval_token="tok_preexisting_attempt_1",
    )


def run_b0_no_recovery(*, mandate: Mandate, first_failure_event: FailureEvent) -> BaselineRunResult:
    """B0 — the floor. Fail once, halt. No retries, no notifications."""
    result = BaselineRunResult(mandate=mandate)
    result.attempts.append(_seed_attempt(mandate, first_failure_event))
    result.final_status = "halted"
    return result


def run_b1_naive_retry(*, mandate: Mandate, first_failure_event: FailureEvent, downtime_records=None) -> BaselineRunResult:
    """B1 — retry immediately, up to budget, ignoring windows, terminal
    codes, and notification obligations entirely. This is what an
    undisciplined retry loop actually does, and it is DELIBERATELY not
    compliance-aware: the point of B1 is to demonstrate the violations
    naive code commits, not to be a good baseline."""
    result = BaselineRunResult(mandate=mandate)
    result.attempts.append(_seed_attempt(mandate, first_failure_event))

    now = first_failure_event.occurred_at
    reason = first_failure_event.reason
    npci_code = first_failure_event.npci_code
    for attempt_number in range(2, RC.MAX_EXECUTION_ATTEMPTS_TOTAL + 1):
        retry_at = now + 3600  # fixed 1-hour offset — no window awareness, no notice, no terminal-code check
        succeeded = simulator.simulate_outcome(mandate=mandate, reason=reason, scheduled_at=retry_at, npci_code=npci_code, downtime_records=downtime_records)
        failure_event = None
        if not succeeded:
            failure_event = simulator.build_failure_event(
                mandate=mandate, reason=reason, npci_code=npci_code, scheduled_at=retry_at, attempt_number=attempt_number
            )
        result.attempts.append(Attempt(
            mandate_id=mandate.mandate_id, attempt_number=attempt_number, scheduled_at=retry_at,
            window=simulator.window_label_for(retry_at), executed_at=retry_at,
            outcome="success" if succeeded else "failed", failure_event=failure_event,
            approval_token=None,  # B1 has no guardrail layer — no token is ever minted, by design
        ))
        now = retry_at
        if succeeded:
            result.recovered_paise = mandate.amount_paise
            result.final_status = "recovered"
            return result  # B1 sends no post-debit confirmation — it ignores notification obligations, per definition

    result.final_status = "halted"
    return result


def run_b2_fixed_schedule(*, mandate: Mandate, first_failure_event: FailureEvent, downtime_records=None) -> BaselineRunResult:
    """B2 — retry at fixed offsets (+24h, +48h, +72h), window-aware (snaps
    forward to the next permitted window if the fixed offset lands inside a
    peak window) but NOT reason-aware (retries regardless of a terminal
    code) and NOT bank-aware."""
    result = BaselineRunResult(mandate=mandate)
    result.attempts.append(_seed_attempt(mandate, first_failure_event))

    reason = first_failure_event.reason
    npci_code = first_failure_event.npci_code
    for i, offset_h in enumerate((24, 48, 72)):
        attempt_number = i + 2
        candidate = first_failure_event.occurred_at + offset_h * 3600
        if not timeutils.is_permitted_execution_time(candidate):
            w = timeutils.which_window(candidate) or RC.PERMITTED_WINDOWS[0]
            candidate = timeutils.next_window_start(candidate, w)

        # Notice time is computed FROM the (possibly window-snapped)
        # candidate, not carried over from the previous iteration — this
        # guarantees the >=24h gap holds even after snapping, rather than
        # compounding a shortfall across iterations.
        notice_sent_at = candidate - RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600
        result.notifications.append(Notification(
            mandate_id=mandate.mandate_id, intervention_type="pre_debit_notice", sent_at=notice_sent_at,
            related_attempt_number=attempt_number, copy_text="[B2 fixed-schedule notice: window-aware only]",
            screened=True, screen_passed=True,
        ))

        succeeded = simulator.simulate_outcome(mandate=mandate, reason=reason, scheduled_at=candidate, npci_code=npci_code, downtime_records=downtime_records)
        failure_event = None
        if not succeeded:
            failure_event = simulator.build_failure_event(
                mandate=mandate, reason=reason, npci_code=npci_code, scheduled_at=candidate, attempt_number=attempt_number
            )
        result.attempts.append(Attempt(
            mandate_id=mandate.mandate_id, attempt_number=attempt_number, scheduled_at=candidate,
            window=simulator.window_label_for(candidate), executed_at=candidate,
            outcome="success" if succeeded else "failed", failure_event=failure_event, approval_token=None,
        ))
        if succeeded:
            result.recovered_paise = mandate.amount_paise
            result.final_status = "recovered"
            result.notifications.append(Notification(
                mandate_id=mandate.mandate_id, intervention_type="post_debit_confirmation", sent_at=candidate,
                related_attempt_number=attempt_number, copy_text="[B2 confirmation]", screened=True, screen_passed=True,
            ))
            return result
        else:
            result.notifications.append(Notification(
                mandate_id=mandate.mandate_id, intervention_type="source_aware_failure_notice", sent_at=candidate,
                related_attempt_number=attempt_number, copy_text="[B2 failure notice]", screened=True, screen_passed=True,
            ))

    result.final_status = "halted"
    return result

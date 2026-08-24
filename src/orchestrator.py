"""
src/orchestrator.py — wires stages 1-10 together for the ENGINE strategy,
across a single mandate's whole retry lifecycle.

Deliberately the ONLY module that imports from every layer (domain, classify,
policy, intervene, guardrails, execute, audit) — every other module keeps to
its own layer's imports. Baselines (eval/baselines.py) do NOT use this
orchestrator: they implement their own, simpler scheduling logic precisely so
they can be measured — including their compliance violations — against the
same invariants. That comparison is the whole point of having baselines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.audit.log import AuditLog
from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import AuditEntry, Attempt, FailureEvent, Mandate, Notification
from src.domain.enums import ActorType, InterventionType, NpciResponseCode, SubscriptionStatus
from src.execute import simulator
from src.guardrails import validator
from src.intervene import consent
from src.intervene.copy_generator import generate as generate_copy
from src.intervene.selector import select as select_intervention
from src.policy import allocator, retryability, stopping_rules
from src.policy.bank_health import DowntimeRecord


@dataclass
class MandateRunResult:
    mandate: Mandate
    attempts: list[Attempt] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    final_status: str = "unknown"
    recovered_paise: int = 0
    stopped_reason: str = ""


_REASON_EXPLANATIONS: dict[str, str] = {
    "insufficient_funds": "your account balance was insufficient at the time",
    "bank_technical_error": "a temporary issue at your bank's end",
    "gateway_technical_error": "a temporary payment gateway issue",
    "invalid_vpa": "your UPI ID needs to be re-verified",
    "vpa_resolution_failed": "a technical issue resolving your UPI ID",
    "payment_declined": "your bank declined the debit",
    "payment_cancelled": "the payment was cancelled",
    "payment_timed_out": "the payment request timed out",
    "payment_collect_request_expired": "the payment request expired before it was actioned",
    "credit_failed": "a technical issue on our side completing the credit",
    "__unknown__": "an issue we are still investigating",
}


def _build_copy_context(mandate: Mandate, failure_event: Optional[FailureEvent], scheduled_at: Optional[int], window_label: str) -> dict:
    """A superset context with a safe default for every key any template in
    intervene/copy_generator.py might reference, so `.format(**context)` can
    never KeyError regardless of which intervention type was chosen."""
    reason_value = failure_event.reason.value if failure_event else "payment_declined"
    return {
        "merchant_label": "your merchant",
        "amount_rupees": f"{mandate.amount_paise / 100:.2f}",
        "window_label": window_label,
        "date_label": timeutils.to_ist(scheduled_at).strftime("%d %b %Y") if scheduled_at else "the scheduled date",
        "failure_explanation": _REASON_EXPLANATIONS.get(reason_value, "a payment issue"),
        "next_step": "We will automatically retry within your mandate's remaining attempts.",
        "short_url_label": "your Razorpay payment link",
    }


def run_mandate(
    *,
    mandate: Mandate,
    first_failure_event: FailureEvent,
    downtime_records: Optional[list[DowntimeRecord]] = None,
    audit: Optional[AuditLog] = None,
    use_salary_cycle_heuristic: bool = True,
    use_bank_health_heuristic: bool = True,
) -> MandateRunResult:
    audit = audit if audit is not None else AuditLog()
    result = MandateRunResult(mandate=mandate)

    first_attempt = Attempt(
        mandate_id=mandate.mandate_id,
        attempt_number=1,
        scheduled_at=first_failure_event.occurred_at,
        window=simulator.window_label_for(first_failure_event.occurred_at),
        executed_at=first_failure_event.occurred_at,
        outcome="failed",
        failure_event=first_failure_event,
        # Attempt #1 already happened (that's the webhook that triggered this
        # run) before this engine had any say in it — see DECISIONS.md ADR-006
        # on why it still carries a token rather than being left empty.
        approval_token="tok_preexisting_attempt_1",
    )
    result.attempts.append(first_attempt)
    audit.record(AuditEntry(
        mandate_id=mandate.mandate_id, stage="ingest", decision="normalised",
        reason=f"initial failure ingested: reason={first_failure_event.reason.value}", actor=ActorType.DETERMINISTIC.value,
    ))

    last_failure_event = first_failure_event
    attempts_made = 1
    now = first_failure_event.occurred_at

    while True:
        # Opt-out is checked FIRST, ahead of retryability. Under a regime
        # where every debit carries a mandatory pre/post-debit notice
        # (§2.2), "opt out of contact" while an AutoPay mandate keeps
        # auto-debiting is not a coherent state to serve — the engine could
        # not legally debit without notifying, so an opt-out stops the
        # WHOLE sequence (no further notice, no further attempt), not just
        # the notification. This is what "a no ends the sequence, no
        # escalation loop" (Razorpay principle 5) means structurally rather
        # than as a slogan. See DECISIONS.md ADR-007.
        if not consent.is_contactable(mandate.customer, now):
            audit.record(AuditEntry(
                mandate_id=mandate.mandate_id, stage="stopping_rule", decision="stop",
                reason="customer has opted out; no further attempt may be scheduled because it could not be "
                       "legally notified beforehand (INV-06/INV-08)",
                actor=ActorType.DETERMINISTIC.value,
            ))
            result.stopped_reason = "customer opted out"
            break

        verdict = retryability.evaluate(last_failure_event, mandate)
        audit.record(AuditEntry(
            mandate_id=mandate.mandate_id, stage="retryability_gate", decision=verdict.verdict.value,
            reason=verdict.rationale, actor=ActorType.DETERMINISTIC.value, metadata={"spec_reference": verdict.spec_reference},
        ))

        if verdict.verdict.value != "retryable":
            # TERMINAL / INVESTIGATE / LIKELY_INTENTIONAL_NONPAYMENT: no debit
            # will ever be scheduled again for this reason. That does NOT mean
            # silence — the customer (or support) still gets exactly one
            # notice explaining what happens next, then the mandate stops.
            # This must run BEFORE any stopping-rule short-circuit, or the
            # notification never happens at all — a real bug caught by this
            # engine's own smoke test (see AI_USAGE.md).
            choice = select_intervention(verdict=verdict.verdict, attempt_number=attempts_made + 1, mandate=mandate)
            audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="intervention_selector", decision=choice.intervention_type, reason=choice.rationale, actor=choice.actor))
            copy_context = _build_copy_context(mandate, last_failure_event, None, "n/a")
            copy_result = generate_copy(intervention_type=InterventionType(choice.intervention_type), context=copy_context)
            notify_decision = validator.validate_notification(mandate=mandate, intervention_type=choice.intervention_type, now=now)
            audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="guardrail_notify", decision=str(notify_decision.approved), reason=notify_decision.reason, actor=ActorType.DETERMINISTIC.value))
            if notify_decision.approved:
                mandate.customer = consent.record_contact(mandate.customer, now)
                result.notifications.append(Notification(
                    mandate_id=mandate.mandate_id, intervention_type=choice.intervention_type, sent_at=now,
                    related_attempt_number=attempts_made + 1, copy_text=copy_result.text,
                    grace_period_days=None, screened=True, screen_passed=copy_result.screen_passed,
                ))
            audit.record(AuditEntry(
                mandate_id=mandate.mandate_id, stage="stopping_rule", decision="stop",
                reason=f"verdict is '{verdict.verdict.value}'; no further retry is legal or appropriate (see retryability_gate entry above)",
                actor=ActorType.DETERMINISTIC.value,
            ))
            result.stopped_reason = f"verdict={verdict.verdict.value}"
            break

        stop = stopping_rules.evaluate(verdict=verdict.verdict, attempts_made=attempts_made, first_failure_at=first_failure_event.occurred_at, now=now)
        if stop.should_stop:
            audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="stopping_rule", decision="stop", reason=stop.reason, actor=ActorType.DETERMINISTIC.value))
            result.stopped_reason = stop.reason
            break

        notification_carveout = mandate.mcc in RC.PRE_DEBIT_NOTIFICATION_CARVEOUT_MCCS
        earliest_legal = allocator.compute_earliest_legal_time(now=now, notification_carveout=notification_carveout)
        z7_required = last_failure_event.npci_code == NpciResponseCode.Z7
        proposal = allocator.propose_next_attempt(
            mandate=mandate, reason=last_failure_event.reason, earliest_legal_time=earliest_legal,
            z7_spacing_required=z7_required, downtime_records=downtime_records,
            use_salary_cycle_heuristic=use_salary_cycle_heuristic, use_bank_health_heuristic=use_bank_health_heuristic,
        )
        audit.record(AuditEntry(
            mandate_id=mandate.mandate_id, stage="allocator", decision=f"proposed_at:{proposal.scheduled_at}",
            reason=proposal.rationale, actor=ActorType.DETERMINISTIC.value,
        ))

        next_attempt_number = attempts_made + 1

        # verdict is guaranteed RETRYABLE here, so select_intervention always
        # returns a pre_debit_notice (with an optional grace-period nudge) —
        # see intervene/selector.py's deterministic rule table.
        choice = select_intervention(verdict=verdict.verdict, attempt_number=next_attempt_number, mandate=mandate)
        audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="intervention_selector", decision=choice.intervention_type, reason=choice.rationale, actor=choice.actor))

        if choice.grace_period_days is not None:
            grace_decision = validator.validate_grace_period(choice.grace_period_days)
            audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="guardrail_grace_period", decision=str(grace_decision.approved), reason=grace_decision.reason, actor=ActorType.DETERMINISTIC.value))
            if not grace_decision.approved:
                choice.grace_period_days = None

        copy_context = _build_copy_context(mandate, last_failure_event, proposal.scheduled_at, proposal.window_label)
        copy_result = generate_copy(intervention_type=InterventionType(choice.intervention_type), context=copy_context)


        notify_decision = validator.validate_notification(mandate=mandate, intervention_type=choice.intervention_type, now=now)
        audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="guardrail_notify", decision=str(notify_decision.approved), reason=notify_decision.reason, actor=ActorType.DETERMINISTIC.value))
        if notify_decision.approved:
            mandate.customer = consent.record_contact(mandate.customer, now)
            result.notifications.append(Notification(
                mandate_id=mandate.mandate_id, intervention_type=choice.intervention_type, sent_at=now,
                related_attempt_number=next_attempt_number, copy_text=copy_result.text,
                grace_period_days=choice.grace_period_days, screened=True, screen_passed=copy_result.screen_passed,
            ))

        # Terminal/investigate/intentional-nonpayment verdicts are handled and
        # returned from further up this loop, before a schedule is even
        # proposed — reaching this point guarantees verdict is RETRYABLE.
        outcome = simulator.execute_with_guardrail(
            mandate=mandate, attempt_number=next_attempt_number, scheduled_at=proposal.scheduled_at,
            root_cause_reason=last_failure_event.reason, root_cause_npci_code=last_failure_event.npci_code,
            prior_terminal_reason=last_failure_event.reason, prior_terminal_npci_code=last_failure_event.npci_code,
            now=proposal.scheduled_at, downtime_records=downtime_records,
        )
        audit.record(AuditEntry(
            mandate_id=mandate.mandate_id, stage="execute", decision=outcome.attempt.outcome or "skipped",
            reason=outcome.guardrail_reason, actor=ActorType.DETERMINISTIC.value,
            metadata={"approval_token": outcome.attempt.approval_token or ""},
        ))
        result.attempts.append(outcome.attempt)

        if not outcome.approved:
            # Failure Injection #8 lands here when state changed between
            # scheduling and this moment — the guardrail vetoes even though
            # the schedule was legal when it was first proposed. See FAILURES.md #8.
            result.stopped_reason = f"guardrail vetoed at execution time: {outcome.guardrail_reason}"
            break

        attempts_made += 1
        now = proposal.scheduled_at

        if outcome.attempt.outcome == "success":
            result.recovered_paise = mandate.amount_paise
            result.final_status = "recovered"
            confirm_copy = generate_copy(
                intervention_type=InterventionType.POST_DEBIT_CONFIRMATION,
                context=_build_copy_context(mandate, None, now, proposal.window_label),
            )
            confirm_decision = validator.validate_notification(mandate=mandate, intervention_type="post_debit_confirmation", now=now)
            if confirm_decision.approved:
                mandate.customer = consent.record_contact(mandate.customer, now)
                result.notifications.append(Notification(
                    mandate_id=mandate.mandate_id, intervention_type="post_debit_confirmation", sent_at=now,
                    related_attempt_number=next_attempt_number, copy_text=confirm_copy.text,
                    screened=True, screen_passed=confirm_copy.screen_passed,
                ))
            audit.record(AuditEntry(mandate_id=mandate.mandate_id, stage="outcome", decision="recovered", reason=f"attempt {next_attempt_number} succeeded", actor=ActorType.DETERMINISTIC.value))
            break

        # Failed: INV-07 requires a post-outcome notice for every executed
        # attempt, success or fail — send the source-aware failure notice,
        # budget permitting, then continue the loop with the new failure.
        failure_copy = generate_copy(
            intervention_type=InterventionType.SOURCE_AWARE_FAILURE_NOTICE,
            context=_build_copy_context(mandate, outcome.attempt.failure_event, now, proposal.window_label),
        )
        failure_notify_decision = validator.validate_notification(mandate=mandate, intervention_type="source_aware_failure_notice", now=now)
        if failure_notify_decision.approved:
            mandate.customer = consent.record_contact(mandate.customer, now)
            result.notifications.append(Notification(
                mandate_id=mandate.mandate_id, intervention_type="source_aware_failure_notice", sent_at=now,
                related_attempt_number=next_attempt_number, copy_text=failure_copy.text,
                screened=True, screen_passed=failure_copy.screen_passed,
            ))

        last_failure_event = outcome.attempt.failure_event
        mandate.consecutive_same_reason_failures += 1
        mandate.total_failures_lifetime += 1

    if result.final_status != "recovered":
        if attempts_made >= RC.MAX_EXECUTION_ATTEMPTS_TOTAL:
            result.final_status = "halted"
            mandate.subscription.status = SubscriptionStatus.HALTED
            audit.record(AuditEntry(
                mandate_id=mandate.mandate_id, stage="outcome", decision="halted",
                reason="attempt budget exhausted, matching Razorpay's 4-consecutive-failure rule (SOURCES.md §4)",
                actor=ActorType.DETERMINISTIC.value,
            ))
        else:
            result.final_status = "stopped"

    return result

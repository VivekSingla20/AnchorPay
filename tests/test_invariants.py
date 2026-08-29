"""
tests/test_invariants.py — the 15 compliance invariants, Build Spec Part 6.

Each invariant gets a PASSING construction and a VIOLATING construction,
built directly against guardrails/invariants.py's checker functions — this
is what "Tests exist and fail correctly" (Build Spec Part 12, Phase 1 gate)
means: the checks must actually distinguish compliant from non-compliant,
not just always return zero.

The final test in this file runs the real orchestrator over a batch of
constructed scenarios (one per taxonomy branch) and asserts zero violations
end-to-end — the same claim EVALUATION.md makes, verified directly rather
than only observed from a report.
"""
from __future__ import annotations

from src.audit.log import AuditLog
from src.domain import regulatory_constants as RC
from src.domain.entities import AuditEntry, Attempt, Notification
from src.domain.enums import FailureReason, NpciResponseCode, WindowLabel
from src.guardrails import invariants
from src.orchestrator import run_mandate
from tests.factories import BASE_TIME, PEAK_TIME, PERMITTED_TIME, make_failure_event, make_mandate


def test_inv01_peak_hour_execution_flagged() -> None:
    mandate = make_mandate()
    bad = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PEAK_TIME, window=WindowLabel.AFTERNOON, executed_at=PEAK_TIME, outcome="failed")
    good = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed")
    assert len(invariants.check_inv01_no_peak_execution([bad])) == 1
    assert len(invariants.check_inv01_no_peak_execution([good])) == 0


def test_inv02_max_attempts_flagged() -> None:
    mandate = make_mandate()
    attempts = [
        Attempt(mandate_id=mandate.mandate_id, attempt_number=n, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON)
        for n in range(1, 6)  # 5 > the cap of 4
    ]
    assert len(invariants.check_inv02_max_attempts(attempts)) == 1
    assert len(invariants.check_inv02_max_attempts(attempts[:4])) == 0


def test_inv03_retry_after_terminal_flagged() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.INVALID_VPA)
    terminal_event = make_failure_event(mandate, reason=FailureReason.INVALID_VPA, attempt_number=1)
    first = Attempt(mandate_id=mandate.mandate_id, attempt_number=1, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed", failure_event=terminal_event)
    illegal_retry = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME + 86400, window=WindowLabel.AFTERNOON)
    assert len(invariants.check_inv03_no_retry_on_terminal([first, illegal_retry])) == 1
    assert len(invariants.check_inv03_no_retry_on_terminal([first])) == 0


def test_inv03_z8_override_is_also_terminal() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.PAYMENT_DECLINED, root_cause_npci_code=NpciResponseCode.Z8)
    z8_event = make_failure_event(mandate, reason=FailureReason.PAYMENT_DECLINED, npci_code=NpciResponseCode.Z8)
    first = Attempt(mandate_id=mandate.mandate_id, attempt_number=1, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed", failure_event=z8_event)
    illegal_retry = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME + 86400, window=WindowLabel.AFTERNOON)
    assert len(invariants.check_inv03_no_retry_on_terminal([first, illegal_retry])) == 1


def test_inv04_status_check_too_soon_flagged() -> None:
    too_soon = [("mandate_x", BASE_TIME, BASE_TIME + 30)]  # 30s < 90s minimum
    ok = [("mandate_x", BASE_TIME, BASE_TIME + 91)]
    assert len(invariants.check_inv04_status_check_delay(too_soon)) == 1
    assert len(invariants.check_inv04_status_check_delay(ok)) == 0


def test_inv05_too_many_status_checks_flagged() -> None:
    too_many = [("mandate_x", BASE_TIME, BASE_TIME + i * 600) for i in range(4)]  # 4 calls inside 2h
    ok = [("mandate_x", BASE_TIME, BASE_TIME + i * 600) for i in range(3)]
    assert len(invariants.check_inv05_status_check_frequency(too_many)) > 0
    assert len(invariants.check_inv05_status_check_frequency(ok)) == 0


def test_inv06_missing_pre_debit_notice_flagged() -> None:
    mandate = make_mandate(mcc=4900)  # not a carve-out MCC
    attempt = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed")
    mandates_by_id = {mandate.mandate_id: mandate}
    assert len(invariants.check_inv06_pre_debit_notification([attempt], [], mandates_by_id)) == 1

    on_time_notice = Notification(mandate_id=mandate.mandate_id, intervention_type="pre_debit_notice", sent_at=PERMITTED_TIME - RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600, related_attempt_number=2)
    assert len(invariants.check_inv06_pre_debit_notification([attempt], [on_time_notice], mandates_by_id)) == 0

    late_notice = Notification(mandate_id=mandate.mandate_id, intervention_type="pre_debit_notice", sent_at=PERMITTED_TIME - 3600, related_attempt_number=2)
    assert len(invariants.check_inv06_pre_debit_notification([attempt], [late_notice], mandates_by_id)) == 1


def test_inv06_carveout_mcc_is_exempt() -> None:
    mandate = make_mandate(mcc=RC.MCC_FASTAG)
    attempt = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed")
    mandates_by_id = {mandate.mandate_id: mandate}
    assert len(invariants.check_inv06_pre_debit_notification([attempt], [], mandates_by_id)) == 0


def test_inv07_missing_post_debit_confirmation_flagged() -> None:
    mandate = make_mandate()
    attempt = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="success")
    assert len(invariants.check_inv07_post_debit_confirmation([attempt], [])) == 1
    confirmation = Notification(mandate_id=mandate.mandate_id, intervention_type="post_debit_confirmation", sent_at=PERMITTED_TIME, related_attempt_number=2)
    assert len(invariants.check_inv07_post_debit_confirmation([attempt], [confirmation])) == 0


def test_inv08_contact_after_optout_flagged() -> None:
    mandate = make_mandate(opted_out_at=BASE_TIME)
    mandates_by_id = {mandate.mandate_id: mandate}
    after = Notification(mandate_id=mandate.mandate_id, intervention_type="balance_nudge", sent_at=BASE_TIME + 1)
    before = Notification(mandate_id=mandate.mandate_id, intervention_type="balance_nudge", sent_at=BASE_TIME - 1)
    assert len(invariants.check_inv08_no_contact_after_optout([after], mandates_by_id)) == 1
    assert len(invariants.check_inv08_no_contact_after_optout([before], mandates_by_id)) == 0


def test_inv09_dark_pattern_copy_flagged() -> None:
    bad = Notification(mandate_id="m1", intervention_type="balance_nudge", sent_at=BASE_TIME, copy_text="act now!!", screened=True, screen_passed=False)
    good = Notification(mandate_id="m1", intervention_type="balance_nudge", sent_at=BASE_TIME, copy_text="your payment is due", screened=True, screen_passed=True)
    assert len(invariants.check_inv09_no_dark_pattern_copy([bad])) == 1
    assert len(invariants.check_inv09_no_dark_pattern_copy([good])) == 0


def test_inv10_grace_period_ceiling_flagged() -> None:
    bad = Notification(mandate_id="m1", intervention_type="pre_debit_notice", sent_at=BASE_TIME, grace_period_days=30)
    good = Notification(mandate_id="m1", intervention_type="pre_debit_notice", sent_at=BASE_TIME, grace_period_days=RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS[0])
    assert len(invariants.check_inv10_grace_period_ceiling([bad])) == 1
    assert len(invariants.check_inv10_grace_period_ceiling([good])) == 0


def test_inv10_pause_cycles_ceiling_flagged() -> None:
    bad = Notification(mandate_id="m1", intervention_type="cancellation_confirmation", sent_at=BASE_TIME, pause_cycles_offered=30)
    good = Notification(mandate_id="m1", intervention_type="cancellation_confirmation", sent_at=BASE_TIME, pause_cycles_offered=RC.MERCHANT_ALLOWED_PAUSE_CYCLES[0])
    assert len(invariants.check_inv10_grace_period_ceiling([bad])) == 1
    assert len(invariants.check_inv10_grace_period_ceiling([good])) == 0


def test_inv11_empty_audit_reason_flagged() -> None:
    bad = AuditEntry(mandate_id="m1", stage="allocator", decision="x", reason="   ", actor="deterministic")
    good = AuditEntry(mandate_id="m1", stage="allocator", decision="x", reason="a real reason", actor="deterministic")
    assert len(invariants.check_inv11_audit_reason_present([bad])) == 1
    assert len(invariants.check_inv11_audit_reason_present([good])) == 0


def test_inv12_pii_shaped_string_flagged() -> None:
    bad = AuditEntry(mandate_id="m1", stage="x", decision="x", reason="contact user@example.com", actor="deterministic")
    good = AuditEntry(mandate_id="m1", stage="x", decision="x", reason="no pii here", actor="deterministic")
    assert len(invariants.check_inv12_no_pii_in_logs([bad], [])) == 1
    assert len(invariants.check_inv12_no_pii_in_logs([good], [])) == 0


def test_inv14_missing_approval_token_flagged() -> None:
    mandate = make_mandate()
    no_token = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed", approval_token=None)
    with_token = Attempt(mandate_id=mandate.mandate_id, attempt_number=2, scheduled_at=PERMITTED_TIME, window=WindowLabel.AFTERNOON, executed_at=PERMITTED_TIME, outcome="failed", approval_token="tok_abc")
    assert len(invariants.check_inv14_approval_token_present([no_token])) == 1
    assert len(invariants.check_inv14_approval_token_present([with_token])) == 0


def test_inv15_silent_arrears_zeroing_flagged() -> None:
    silent = [("mandate_x", False)]
    explicit = [("mandate_x", True)]
    assert len(invariants.check_inv15_arrears_not_assumed_collected(silent)) == 1
    assert len(invariants.check_inv15_arrears_not_assumed_collected(explicit)) == 0


def test_inv15_reactivation_never_touches_arrears() -> None:
    """Direct behavioural check on the ONE function allowed to reactivate a
    subscription: arrears_paise must be numerically unchanged."""
    from src.execute.simulator import reactivate_subscription

    mandate = make_mandate(arrears_paise=12_345)
    reactivated = reactivate_subscription(mandate)
    assert reactivated.arrears_paise == 12_345
    assert reactivated.subscription.status.value == "active"


def _run_and_grade(mandate, event) -> invariants.InvariantReport:
    audit = AuditLog()
    result = run_mandate(mandate=mandate, first_failure_event=event, audit=audit)
    return invariants.run_all(
        attempts=result.attempts[1:],  # attempt #1 predates the engine — see DECISIONS.md ADR-009
        notifications=result.notifications,
        audit_entries=audit.all(),
        mandates_by_id={mandate.mandate_id: mandate},
    )


def test_engine_zero_violations_across_every_reason_branch() -> None:
    """One constructed mandate per taxonomy branch — the same claim
    EVALUATION.md reports on the full batch, verified directly here."""
    reasons = [
        FailureReason.INSUFFICIENT_FUNDS, FailureReason.BANK_TECHNICAL_ERROR, FailureReason.GATEWAY_TECHNICAL_ERROR,
        FailureReason.INVALID_VPA, FailureReason.VPA_RESOLUTION_FAILED, FailureReason.PAYMENT_DECLINED,
        FailureReason.PAYMENT_CANCELLED, FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED,
        FailureReason.PAYMENT_TIMED_OUT, FailureReason.CREDIT_FAILED, FailureReason.UNKNOWN,
    ]
    for reason in reasons:
        mandate = make_mandate(root_cause_reason=reason)
        event = make_failure_event(mandate, reason=reason)
        report = _run_and_grade(mandate, event)
        assert report.count == 0, f"engine produced violations for reason={reason.value}: {report.violations}"


def test_engine_zero_violations_with_opt_out_mid_lifecycle() -> None:
    """Failure Injection #8: opt-out arriving between scheduling and
    execution. The guardrail re-checks at send/execute time, not schedule
    time, so this must still be zero violations."""
    mandate = make_mandate(root_cause_reason=FailureReason.BANK_TECHNICAL_ERROR)
    mandate.customer.opted_out_at = BASE_TIME + 3600  # opts out an hour after the first failure, mid-sequence
    event = make_failure_event(mandate, reason=FailureReason.BANK_TECHNICAL_ERROR)
    report = _run_and_grade(mandate, event)
    assert report.count == 0

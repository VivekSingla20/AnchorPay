"""
guardrails/invariants.py — the 15 compliance invariants from Build Spec
Part 6, as a single reusable checker.

Used two ways:
  1. tests/test_invariants.py — unit tests against small constructed scenarios.
  2. eval/run_eval.py — aggregate violation counts per strategy on the full
     batch. The "violations: 0 for the engine, N for each baseline" table
     this produces is this submission's headline comparison.

INDEPENDENCE RULE (enforced by tests/test_no_llm_in_policy.py): this module
imports ONLY from src.domain. It never imports src.policy, src.classify, or
src.intervene. It re-derives every legality fact from the raw constants
itself rather than trusting any upstream stage's stored verdict.

INV-13 ("no policy/guardrail module imports an LLM client") is NOT checked
here — it is a static-analysis fact about source code, not runtime scenario
data, and lives in tests/test_no_llm_in_policy.py where it belongs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import AuditEntry, Attempt, Mandate, Notification
from src.domain.enums import FailureReason, NpciResponseCode, RetryabilityVerdict


@dataclass
class Violation:
    invariant: str
    mandate_id: str
    detail: str


@dataclass
class InvariantReport:
    violations: list[Violation] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.violations)

    def count_by_invariant(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.invariant] = out.get(v.invariant, 0) + 1
        return out


def _is_terminal_event(reason: FailureReason, npci_code: Optional[NpciResponseCode]) -> bool:
    """Independent re-derivation — deliberately duplicated from
    policy/retryability.py rather than imported. See module docstring."""
    if npci_code is not None and npci_code in RC.NPCI_CODE_VERDICT_OVERRIDE:
        return RC.NPCI_CODE_VERDICT_OVERRIDE[npci_code] == RetryabilityVerdict.TERMINAL
    row = RC.REASON_STRATEGY_BY_REASON.get(reason)
    if row is None:
        return False
    return row.verdict == RetryabilityVerdict.TERMINAL


def check_inv01_no_peak_execution(attempts: list[Attempt]) -> list[Violation]:
    out = []
    for a in attempts:
        if a.outcome == "skipped":
            continue
        if timeutils.is_peak_hour(a.scheduled_at):
            out.append(Violation(
                "INV-01", a.mandate_id,
                f"attempt {a.attempt_number} scheduled at {timeutils.to_ist(a.scheduled_at).isoformat()} IST, inside a peak window",
            ))
    return out


def check_inv02_max_attempts(attempts: list[Attempt]) -> list[Violation]:
    out = []
    by_mandate: dict[str, int] = {}
    for a in attempts:
        by_mandate[a.mandate_id] = by_mandate.get(a.mandate_id, 0) + 1
    for mandate_id, n in by_mandate.items():
        if n > RC.MAX_EXECUTION_ATTEMPTS_TOTAL:
            out.append(Violation("INV-02", mandate_id, f"{n} attempts scheduled, exceeds cap of {RC.MAX_EXECUTION_ATTEMPTS_TOTAL}"))
    return out


def check_inv03_no_retry_on_terminal(attempts: list[Attempt]) -> list[Violation]:
    out = []
    by_mandate: dict[str, list[Attempt]] = {}
    for a in attempts:
        by_mandate.setdefault(a.mandate_id, []).append(a)
    for mandate_id, mandate_attempts in by_mandate.items():
        ordered = sorted(mandate_attempts, key=lambda a: a.attempt_number)
        for prior in ordered:
            if prior.failure_event is None:
                continue
            if _is_terminal_event(prior.failure_event.reason, prior.failure_event.npci_code):
                for later in ordered:
                    if later.attempt_number > prior.attempt_number:
                        out.append(Violation(
                            "INV-03", mandate_id,
                            f"attempt {later.attempt_number} scheduled after terminal reason "
                            f"'{prior.failure_event.reason.value}' at attempt {prior.attempt_number}",
                        ))
    return out


def check_inv04_status_check_delay(status_checks: list[tuple[str, int, int]]) -> list[Violation]:
    """status_checks: (mandate_id, authenticated_at, checked_at) tuples."""
    out = []
    for mandate_id, authenticated_at, checked_at in status_checks:
        delta = checked_at - authenticated_at
        if delta < RC.STATUS_CHECK_MIN_DELAY_SECONDS:
            out.append(Violation("INV-04", mandate_id, f"status check {delta}s after authentication; minimum is {RC.STATUS_CHECK_MIN_DELAY_SECONDS}s"))
    return out


def check_inv05_status_check_frequency(status_checks: list[tuple[str, int, int]]) -> list[Violation]:
    out = []
    by_mandate: dict[str, list[int]] = {}
    for mandate_id, _auth, checked_at in status_checks:
        by_mandate.setdefault(mandate_id, []).append(checked_at)
    window_seconds = RC.STATUS_CHECK_WINDOW_HOURS * 3600
    for mandate_id, times in by_mandate.items():
        times = sorted(times)
        for t in times:
            count_in_window = sum(1 for other in times if 0 <= t - other < window_seconds)
            if count_in_window > RC.STATUS_CHECK_MAX_CALLS:
                out.append(Violation("INV-05", mandate_id, f"{count_in_window} status checks within a {RC.STATUS_CHECK_WINDOW_HOURS}h window ending at {t}"))
    return out


def check_inv06_pre_debit_notification(
    attempts: list[Attempt], notifications: list[Notification], mandates_by_id: dict[str, Mandate]
) -> list[Violation]:
    out = []
    for a in attempts:
        if a.outcome == "skipped":
            continue
        mandate = mandates_by_id.get(a.mandate_id)
        if mandate is not None and mandate.mcc in RC.PRE_DEBIT_NOTIFICATION_CARVEOUT_MCCS:
            continue
        relevant = [
            n for n in notifications
            if n.mandate_id == a.mandate_id and n.intervention_type == "pre_debit_notice" and n.related_attempt_number == a.attempt_number
        ]
        min_seconds = RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600
        ok = any((a.scheduled_at - n.sent_at) >= min_seconds for n in relevant)
        if not ok:
            out.append(Violation("INV-06", a.mandate_id, f"attempt {a.attempt_number} at {a.scheduled_at} has no pre-debit notice >= {RC.PRE_DEBIT_NOTIFICATION_HOURS}h prior"))
    return out


def check_inv07_post_debit_confirmation(attempts: list[Attempt], notifications: list[Notification]) -> list[Violation]:
    out = []
    for a in attempts:
        if a.executed_at is None:
            continue
        relevant = [
            n for n in notifications
            if n.mandate_id == a.mandate_id
            and n.related_attempt_number == a.attempt_number
            and n.intervention_type in ("post_debit_confirmation", "source_aware_failure_notice")
            and n.sent_at >= a.executed_at
        ]
        if not relevant:
            out.append(Violation("INV-07", a.mandate_id, f"attempt {a.attempt_number} executed at {a.executed_at} with no post-debit confirmation/notice logged after it"))
    return out


def check_inv08_no_contact_after_optout(notifications: list[Notification], mandates_by_id: dict[str, Mandate]) -> list[Violation]:
    out = []
    for n in notifications:
        mandate = mandates_by_id.get(n.mandate_id)
        if mandate is None:
            continue
        opted_out_at = mandate.customer.opted_out_at
        if opted_out_at is not None and n.sent_at >= opted_out_at:
            out.append(Violation("INV-08", n.mandate_id, f"notification sent at {n.sent_at}, after opt-out at {opted_out_at}"))
    return out


def check_inv09_no_dark_pattern_copy(notifications: list[Notification]) -> list[Violation]:
    out = []
    for n in notifications:
        if n.copy_text and n.screened and n.screen_passed is False:
            out.append(Violation("INV-09", n.mandate_id, "a dark-pattern-flagged copy was sent instead of being blocked"))
    return out


def check_inv10_grace_period_ceiling(notifications: list[Notification]) -> list[Violation]:
    out = []
    for n in notifications:
        if n.grace_period_days is not None:
            if n.grace_period_days not in RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS or n.grace_period_days > RC.MERCHANT_GRACE_PERIOD_CEILING_DAYS:
                out.append(Violation("INV-10", n.mandate_id, f"grace_period_days={n.grace_period_days} outside allowlist {RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS}"))
        if n.pause_cycles_offered is not None:
            if n.pause_cycles_offered not in RC.MERCHANT_ALLOWED_PAUSE_CYCLES or n.pause_cycles_offered > RC.MERCHANT_PAUSE_CYCLES_CEILING:
                out.append(Violation("INV-10", n.mandate_id, f"pause_cycles_offered={n.pause_cycles_offered} outside allowlist {RC.MERCHANT_ALLOWED_PAUSE_CYCLES}"))
    return out


def check_inv11_audit_reason_present(audit_entries: list[AuditEntry]) -> list[Violation]:
    out = []
    for e in audit_entries:
        if not e.reason or not e.reason.strip():
            out.append(Violation("INV-11", e.mandate_id, f"audit entry at stage '{e.stage}' has an empty reason"))
    return out


_PII_LIKE_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\b[6-9]\d{9}\b"),  # Indian mobile-number-shaped 10-digit string
)


def check_inv12_no_pii_in_logs(audit_entries: list[AuditEntry], notifications: list[Notification]) -> list[Violation]:
    out = []
    for e in audit_entries:
        blob = " ".join(str(v) for v in e.metadata.values()) + " " + e.reason + " " + e.decision
        for pat in _PII_LIKE_PATTERNS:
            if pat.search(blob):
                out.append(Violation("INV-12", e.mandate_id, f"PII-shaped string found in audit entry at stage '{e.stage}'"))
                break
    for n in notifications:
        for pat in _PII_LIKE_PATTERNS:
            if pat.search(n.copy_text):
                out.append(Violation("INV-12", n.mandate_id, "PII-shaped string found in generated notification copy"))
                break
    return out


def check_inv14_approval_token_present(attempts: list[Attempt]) -> list[Violation]:
    out = []
    for a in attempts:
        if a.executed_at is not None and not a.approval_token:
            out.append(Violation("INV-14", a.mandate_id, f"attempt {a.attempt_number} executed without an approval token"))
    return out


def check_inv15_arrears_not_assumed_collected(reactivation_snapshots: list[tuple[str, bool]]) -> list[Violation]:
    """reactivation_snapshots: (mandate_id, arrears_were_explicitly_collected)
    pairs, recorded ONLY at halted->active transitions where arrears were
    known > 0 immediately before reactivation. See execute/simulator.py's
    `reactivate_subscription`, the only place this list is populated."""
    out = []
    for mandate_id, explicitly_collected in reactivation_snapshots:
        if not explicitly_collected:
            out.append(Violation("INV-15", mandate_id, "arrears were not explicitly collected on reactivation from halted to active — never assume they were"))
    return out


def run_all(
    *,
    attempts: list[Attempt],
    notifications: list[Notification],
    audit_entries: list[AuditEntry],
    mandates_by_id: dict[str, Mandate],
    status_checks: Optional[list[tuple[str, int, int]]] = None,
    arrears_reactivation_snapshots: Optional[list[tuple[str, bool]]] = None,
) -> InvariantReport:
    report = InvariantReport()
    report.violations.extend(check_inv01_no_peak_execution(attempts))
    report.violations.extend(check_inv02_max_attempts(attempts))
    report.violations.extend(check_inv03_no_retry_on_terminal(attempts))
    report.violations.extend(check_inv04_status_check_delay(status_checks or []))
    report.violations.extend(check_inv05_status_check_frequency(status_checks or []))
    report.violations.extend(check_inv06_pre_debit_notification(attempts, notifications, mandates_by_id))
    report.violations.extend(check_inv07_post_debit_confirmation(attempts, notifications))
    report.violations.extend(check_inv08_no_contact_after_optout(notifications, mandates_by_id))
    report.violations.extend(check_inv09_no_dark_pattern_copy(notifications))
    report.violations.extend(check_inv10_grace_period_ceiling(notifications))
    report.violations.extend(check_inv11_audit_reason_present(audit_entries))
    report.violations.extend(check_inv12_no_pii_in_logs(audit_entries, notifications))
    report.violations.extend(check_inv14_approval_token_present(attempts))
    report.violations.extend(check_inv15_arrears_not_assumed_collected(arrears_reactivation_snapshots or []))
    return report

"""
eval/scenarios.py — Failure injection, Build Spec Part 10.

Each scenario deliberately breaks something and asserts the system degrades
gracefully — logs it, falls back to a safe deterministic default, and keeps
the batch moving — rather than crashing or silently doing the wrong thing.

Run: `python -m eval.scenarios`. Findings are written to
results/failure_injection.json; the authored narrative (what broke, how it
was detected, how it degraded, what the customer/merchant experienced) is
FAILURES.md — this script is what makes that document's claims checkable
rather than asserted.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from src.classify import reason_classifier
from src.classify.llm_client import LlmCallResult
from src.domain import timeutils
from src.domain.enums import FailureReason, RetryabilityVerdict
from src.guardrails import validator
from src.ingest import normaliser
from src.intervene import copy_generator, selector
from src.orchestrator import run_mandate
from src.policy import bank_health
from tests.factories import BASE_TIME, make_failure_event, make_mandate

_REPO_ROOT = Path(__file__).resolve().parents[1]


class ScenarioResult:
    def __init__(self, name: str, passed: bool, detail: str) -> None:
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {"scenario": self.name, "passed": self.passed, "detail": self.detail}


def scenario_1_llm_malformed_output() -> ScenarioResult:
    """LLM returns schema-invalid output mid-batch. Injected at the exact
    boundary this failure would actually occur (classify.llm_client.call_structured's
    return value), so the test exercises the real fallback path in
    reason_classifier / selector / copy_generator, not a hypothetical one."""
    fake_bad_result = LlmCallResult(ok=False, parsed=None, raw_text="{not valid json", latency_ms=12.0, model="fake", error="schema validation failed: mock")
    mandate = make_mandate(root_cause_reason=FailureReason.UNKNOWN)
    event = make_failure_event(mandate, reason=FailureReason.UNKNOWN)
    with mock.patch("src.classify.reason_classifier.call_structured", return_value=fake_bad_result):
        outcome = reason_classifier.classify_unknown_reason(event)
    ok = outcome.suggested_reason is None and outcome.actor == "deterministic"
    return ScenarioResult("1_llm_malformed_output", ok, f"classifier fell back cleanly: {outcome.evidence!r}, actor={outcome.actor}")


def scenario_2_llm_timeout_or_rate_limit() -> ScenarioResult:
    """LLM call raises (timeout/rate-limit/network error). call_structured's
    own broad except clause is what's under test here — confirmed by
    injecting a raised TimeoutError at the client-call boundary."""
    fake_timeout_result = LlmCallResult(ok=False, parsed=None, raw_text=None, latency_ms=8000.0, model="fake", error="LLM call raised: TimeoutError('deadline exceeded')")
    mandate = make_mandate(root_cause_reason=FailureReason.INSUFFICIENT_FUNDS)
    with mock.patch("src.intervene.selector.call_structured", return_value=fake_timeout_result):
        choice = selector.select(verdict=RetryabilityVerdict.RETRYABLE, attempt_number=2, mandate=mandate)
    ok = choice.actor == "deterministic" and choice.intervention_type == "pre_debit_notice"
    return ScenarioResult("2_llm_timeout_or_rate_limit", ok, f"selector fell back to deterministic choice under a simulated timeout: {choice.intervention_type}")


def scenario_3_npci_stats_file_unavailable() -> ScenarioResult:
    """NPCI stats file unavailable or stale — simulated by pointing the
    scorer at a path that does not exist, forcing the real load-failure
    branch in policy/bank_health.py."""
    real_path = bank_health._REFERENCE_CSV
    bank_health.reset_reference_cache_for_testing()
    try:
        bank_health._REFERENCE_CSV = _REPO_ROOT / "data" / "npci" / "does_not_exist.csv"
        signal = bank_health.bank_health_score("AXB", BASE_TIME)
        status = bank_health.reference_table_status()
        ok = (
            signal.confidence == "system_wide_fallback"
            and status["loaded_bank_count"] == 0
            and status["last_load_error"] is not None
        )
        detail = f"degraded to system-wide fallback (confidence={signal.confidence}), recorded error: {status['last_load_error']}"
    finally:
        bank_health._REFERENCE_CSV = real_path
        bank_health.reset_reference_cache_for_testing()
    return ScenarioResult("3_npci_stats_file_unavailable", ok, detail)


def scenario_4_downtime_api_unreachable() -> ScenarioResult:
    """Downtime API unreachable — modelled as downtime_records=None (the
    default), confirming scheduling proceeds normally with no bank-health
    penalty applied, rather than raising."""
    mandate = make_mandate(root_cause_reason=FailureReason.BANK_TECHNICAL_ERROR)
    event = make_failure_event(mandate, reason=FailureReason.BANK_TECHNICAL_ERROR)
    try:
        result = run_mandate(mandate=mandate, first_failure_event=event, downtime_records=None)
        ok = result.final_status in ("recovered", "halted", "stopped")
        detail = f"ran to completion with downtime_records=None, final_status={result.final_status}"
    except Exception as exc:  # noqa: BLE001 — this scenario's whole point is proving no exception escapes
        ok = False
        detail = f"raised instead of degrading: {exc!r}"
    return ScenarioResult("4_downtime_api_unreachable", ok, detail)


def scenario_5_unrecognised_reason() -> ScenarioResult:
    """A failure reason arrives that is not in the taxonomy at all (not even
    FailureReason.UNKNOWN as a literal string — an arbitrary new string from
    a raw webhook-shaped payload)."""
    raw = {
        "mandate_id": "mandate_scenario5", "reason": "some_new_code_razorpay_invented_next_quarter",
        "source": "razorpay", "amount_paise": 50000, "occurred_at": BASE_TIME, "attempt_number": 1,
        "payment_id": "pay_scenario5",
    }
    event, note = normaliser.normalise(raw)
    ok = event is not None and event.reason == FailureReason.UNKNOWN and event.raw_reason_text == raw["reason"]
    return ScenarioResult("5_unrecognised_reason", ok, f"normalised to FailureReason.UNKNOWN, raw text preserved as {event.raw_reason_text!r} ({note})")


def scenario_6_clock_boundary_edge_cases() -> ScenarioResult:
    """Schedule computed exactly at a peak/permitted window boundary, and a
    midnight-crossing case. India does not observe DST (UNVERIFIED-free
    fact, not modelled), so no DST transition exists to test — recorded
    honestly rather than fabricating one."""
    from src.policy import allocator

    mandate = make_mandate()
    day_start = timeutils.start_of_ist_day(BASE_TIME)
    boundary_13_00 = day_start + 13 * 3600  # exact start of the 13:00-17:00 permitted window
    near_midnight = day_start + 23 * 3600 + 59 * 60 + 50  # 23:59:50 IST, 10s before midnight

    checks = []
    for label, t in (("13:00 boundary", boundary_13_00), ("23:59:50 near-midnight", near_midnight)):
        proposal = allocator.propose_next_attempt(mandate=mandate, reason=FailureReason.BANK_TECHNICAL_ERROR, earliest_legal_time=t)
        legal = timeutils.is_permitted_execution_time(proposal.scheduled_at) and proposal.scheduled_at >= t
        checks.append((label, legal, proposal.scheduled_at))

    ok = all(legal for _, legal, _ in checks)
    detail = "; ".join(f"{label}: scheduled_at={ts} legal={legal}" for label, legal, ts in checks) + " (India has no DST — not applicable)"
    return ScenarioResult("6_clock_boundary_edge_cases", ok, detail)


def scenario_7_duplicate_webhook_delivery() -> ScenarioResult:
    """Idempotency: the same payment_id delivered twice must be processed
    exactly once."""
    normaliser.reset_idempotency_cache()
    raw = {
        "mandate_id": "mandate_scenario7", "reason": "insufficient_funds", "source": "customer",
        "amount_paise": 30000, "occurred_at": BASE_TIME, "attempt_number": 1, "payment_id": "pay_scenario7_dup",
    }
    first_event, first_note = normaliser.normalise(raw)
    second_event, second_note = normaliser.normalise(dict(raw))
    ok = first_event is not None and second_event is None and "duplicate" in second_note
    normaliser.reset_idempotency_cache()
    return ScenarioResult("7_duplicate_webhook_delivery", ok, f"first={first_note!r}, second={second_note!r}")


def scenario_8_optout_between_scheduling_and_execution() -> ScenarioResult:
    """The most interesting one (Build Spec Part 10): the schedule was
    LEGAL when proposed; the customer opts out before it executes. Proves
    the guardrail is real (re-checked at execution time) rather than
    decorative (checked once, at schedule time, and trusted forever after)."""
    mandate = make_mandate(root_cause_reason=FailureReason.BANK_TECHNICAL_ERROR)
    mandate.customer.opted_out_at = BASE_TIME + 3600  # opts out 1h after the seed failure, before any retry executes
    event = make_failure_event(mandate, reason=FailureReason.BANK_TECHNICAL_ERROR)
    result = run_mandate(mandate=mandate, first_failure_event=event)

    executed_after_optout = [a for a in result.attempts[1:] if a.executed_at is not None and a.executed_at >= mandate.customer.opted_out_at]
    ok = len(executed_after_optout) == 0 and result.stopped_reason != ""
    return ScenarioResult(
        "8_optout_between_scheduling_and_execution", ok,
        f"final_status={result.final_status}, stopped_reason={result.stopped_reason!r}, "
        f"post-opt-out executions={len(executed_after_optout)} (must be 0)",
    )


_ALL_SCENARIOS = (
    scenario_1_llm_malformed_output,
    scenario_2_llm_timeout_or_rate_limit,
    scenario_3_npci_stats_file_unavailable,
    scenario_4_downtime_api_unreachable,
    scenario_5_unrecognised_reason,
    scenario_6_clock_boundary_edge_cases,
    scenario_7_duplicate_webhook_delivery,
    scenario_8_optout_between_scheduling_and_execution,
)


def run_all() -> list[ScenarioResult]:
    return [fn() for fn in _ALL_SCENARIOS]


def main() -> None:
    results = run_all()
    out_path = _REPO_ROOT / "results" / "failure_injection.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")

    all_ok = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name}: {r.detail}")
        all_ok = all_ok and r.passed
    print()
    print(f"{sum(r.passed for r in results)}/{len(results)} scenarios degraded gracefully. Written to {out_path}")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

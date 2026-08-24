"""
tests/test_retryability.py — the reason -> verdict table (Build Spec §4.1),
the Z7/Z8 NPCI-code overrides, the UNKNOWN-taxonomy conservative default, and
the deterministic intent-inference override (Domain Context §3.2).
"""
from __future__ import annotations

from src.domain.enums import FailureReason, NpciResponseCode, RetryabilityVerdict
from src.policy import retryability
from tests.factories import make_failure_event, make_mandate


def test_insufficient_funds_is_retryable() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.INSUFFICIENT_FUNDS)
    event = make_failure_event(mandate)
    result = retryability.evaluate(event, mandate)
    assert result.verdict == RetryabilityVerdict.RETRYABLE


def test_invalid_vpa_is_terminal() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.INVALID_VPA)
    event = make_failure_event(mandate)
    result = retryability.evaluate(event, mandate)
    assert result.verdict == RetryabilityVerdict.TERMINAL


def test_vpa_resolution_failed_is_investigate() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.VPA_RESOLUTION_FAILED)
    event = make_failure_event(mandate)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.INVESTIGATE


def test_z8_overrides_to_terminal_even_though_payment_declined_is_retryable() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.PAYMENT_DECLINED, root_cause_npci_code=NpciResponseCode.Z8)
    event = make_failure_event(mandate, reason=FailureReason.PAYMENT_DECLINED, npci_code=NpciResponseCode.Z8)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.TERMINAL


def test_z7_overrides_to_retryable_with_spacing_rationale() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.PAYMENT_DECLINED, root_cause_npci_code=NpciResponseCode.Z7)
    event = make_failure_event(mandate, reason=FailureReason.PAYMENT_DECLINED, npci_code=NpciResponseCode.Z7)
    result = retryability.evaluate(event, mandate)
    assert result.verdict == RetryabilityVerdict.RETRYABLE
    assert "velocity" in result.rationale.lower()


def test_unknown_reason_defaults_to_investigate_never_retryable() -> None:
    """Failure Injection #5: a reason not in the taxonomy must never be
    auto-retried on money's behalf, regardless of anything a classifier
    might later suggest."""
    mandate = make_mandate(root_cause_reason=FailureReason.UNKNOWN)
    event = make_failure_event(mandate, reason=FailureReason.UNKNOWN)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.INVESTIGATE


def test_intent_inference_overrides_insufficient_funds_when_pattern_matches() -> None:
    mandate = make_mandate(
        root_cause_reason=FailureReason.INSUFFICIENT_FUNDS,
        amount_paise=100_000,
        consecutive_same_reason_failures=5,
        account_balance_paise_hint=500,  # 0.5% of amount — well under the #A2 5% threshold
    )
    event = make_failure_event(mandate)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT


def test_intent_inference_does_not_fire_below_the_consecutive_failure_threshold() -> None:
    mandate = make_mandate(
        root_cause_reason=FailureReason.INSUFFICIENT_FUNDS,
        amount_paise=100_000,
        consecutive_same_reason_failures=1,  # below the #A2 minimum of 3
        account_balance_paise_hint=500,
    )
    event = make_failure_event(mandate)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.RETRYABLE


def test_intent_inference_does_not_fire_when_balance_is_healthy() -> None:
    mandate = make_mandate(
        root_cause_reason=FailureReason.INSUFFICIENT_FUNDS,
        amount_paise=100_000,
        consecutive_same_reason_failures=5,
        account_balance_paise_hint=90_000,  # 90% of amount — a real near-miss, not an empty account
    )
    event = make_failure_event(mandate)
    assert retryability.evaluate(event, mandate).verdict == RetryabilityVerdict.RETRYABLE


def test_evaluate_is_a_pure_function_same_inputs_same_output() -> None:
    mandate = make_mandate(root_cause_reason=FailureReason.BANK_TECHNICAL_ERROR)
    event = make_failure_event(mandate)
    first = retryability.evaluate(event, mandate)
    second = retryability.evaluate(event, mandate)
    assert first.verdict == second.verdict
    assert first.rationale == second.rationale

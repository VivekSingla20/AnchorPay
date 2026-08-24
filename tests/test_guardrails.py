"""
tests/test_guardrails.py — the independent validation layer (Stage 8):
guardrails/validator.py and guardrails/dark_pattern_screen.py.
"""
from __future__ import annotations

from src.domain import regulatory_constants as RC
from src.domain.enums import FailureReason
from src.guardrails import dark_pattern_screen, validator
from src.intervene.copy_generator import _TEMPLATES
from tests.factories import BASE_TIME, PEAK_TIME, PERMITTED_TIME, make_mandate


def test_validate_execution_rejects_peak_hour() -> None:
    mandate = make_mandate()
    decision = validator.validate_execution(
        mandate=mandate, proposed_scheduled_at=PEAK_TIME, attempt_number=2,
        prior_terminal_reason=None, prior_terminal_npci_code=None, now=BASE_TIME,
    )
    assert not decision.approved
    assert decision.approval_token is None


def test_validate_execution_rejects_beyond_attempt_cap() -> None:
    mandate = make_mandate()
    decision = validator.validate_execution(
        mandate=mandate, proposed_scheduled_at=PERMITTED_TIME, attempt_number=RC.MAX_EXECUTION_ATTEMPTS_TOTAL + 1,
        prior_terminal_reason=None, prior_terminal_npci_code=None, now=BASE_TIME,
    )
    assert not decision.approved


def test_validate_execution_rejects_retry_on_terminal_reason() -> None:
    mandate = make_mandate()
    decision = validator.validate_execution(
        mandate=mandate, proposed_scheduled_at=PERMITTED_TIME, attempt_number=2,
        prior_terminal_reason=FailureReason.INVALID_VPA, prior_terminal_npci_code=None, now=BASE_TIME,
    )
    assert not decision.approved


def test_validate_execution_approves_and_mints_a_token_when_legal() -> None:
    mandate = make_mandate()
    decision = validator.validate_execution(
        mandate=mandate, proposed_scheduled_at=PERMITTED_TIME, attempt_number=2,
        prior_terminal_reason=FailureReason.INSUFFICIENT_FUNDS, prior_terminal_npci_code=None, now=BASE_TIME,
    )
    assert decision.approved
    assert decision.approval_token and decision.approval_token.startswith("tok_")


def test_validate_notification_rejects_after_optout() -> None:
    mandate = make_mandate(opted_out_at=BASE_TIME)
    decision = validator.validate_notification(mandate=mandate, intervention_type="balance_nudge", now=BASE_TIME + 1)
    assert not decision.approved


def test_validate_notification_never_blocks_regulatory_mandatory_types_on_contact_budget() -> None:
    """A discretionary same-day second contact IS blocked; the two
    regulation-mandated notice types never are — this is the exact
    conflict this engine's own smoke test caught (see AI_USAGE.md)."""
    mandate = make_mandate()
    mandate.customer.last_contacted_at = BASE_TIME  # already contacted once today

    discretionary = validator.validate_notification(mandate=mandate, intervention_type="balance_nudge", now=BASE_TIME + 60)
    assert not discretionary.approved

    mandatory_pre = validator.validate_notification(mandate=mandate, intervention_type="pre_debit_notice", now=BASE_TIME + 60)
    assert mandatory_pre.approved
    mandatory_post = validator.validate_notification(mandate=mandate, intervention_type="post_debit_confirmation", now=BASE_TIME + 60)
    assert mandatory_post.approved
    mandatory_failure = validator.validate_notification(mandate=mandate, intervention_type="source_aware_failure_notice", now=BASE_TIME + 60)
    assert mandatory_failure.approved


def test_validate_grace_period_enforces_allowlist_and_ceiling() -> None:
    for days in RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS:
        assert validator.validate_grace_period(days).approved
    assert not validator.validate_grace_period(RC.MERCHANT_GRACE_PERIOD_CEILING_DAYS + 1).approved
    assert not validator.validate_grace_period(0).approved


def test_dark_pattern_screen_flags_each_category() -> None:
    examples = {
        "false_urgency": "Act now — this offer expires in 10 minutes!",
        "fabricated_scarcity": "Only 2 slots remaining today.",
        "confirm_shaming": "No, I don't want to save money.",
        "bait_and_switch": "This is free* — terms apply*.",
        "drip_pricing": "Additional fees may apply at checkout.",
        "subscription_traps": "Auto-renews, cancel anytime* — hidden cancellation.",
    }
    for category, text in examples.items():
        result = dark_pattern_screen.screen(text)
        assert not result.passed, f"expected '{category}' example to be flagged: {text!r}"
        assert result.flagged_category == category


def test_dark_pattern_screen_passes_factual_copy() -> None:
    result = dark_pattern_screen.screen("Your payment of Rs 500.00 is scheduled for 13:00-17:00 on 24 Aug 2026. Reply STOP to opt out.")
    assert result.passed


def test_every_deterministic_template_passes_the_dark_pattern_screen() -> None:
    """copy_generator.py's docstring promises this holds — enforced here so
    it can never silently regress when a template is edited."""
    sample_context = {
        "merchant_label": "your merchant", "amount_rupees": "500.00", "window_label": "13:00-17:00",
        "date_label": "24 Aug 2026", "failure_explanation": "a payment issue",
        "next_step": "We will automatically retry within your mandate's remaining attempts.",
        "short_url_label": "your Razorpay payment link",
    }
    for intervention_type, template in _TEMPLATES.items():
        text = template.format(**sample_context) if template else ""
        result = dark_pattern_screen.screen(text)
        assert result.passed, f"template for {intervention_type} fails its own dark-pattern screen: {text!r}"

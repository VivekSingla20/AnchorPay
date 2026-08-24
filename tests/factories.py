"""
tests/factories.py — shared, minimal, valid construction helpers for tests.

Not a conftest.py fixture module on purpose: these are plain factory
functions (not pytest-injected fixtures) because most tests need several
DIFFERENT variations in the same test function (e.g. "a terminal-reason
mandate" vs "a retryable one"), which reads more clearly as
`make_mandate(root_cause_reason=...)` than as a pile of fixture parameters.
"""
from __future__ import annotations

from typing import Optional

from src.domain import timeutils
from src.domain.entities import Customer, FailureEvent, Mandate, Subscription
from src.domain.enums import ConsentState, FailureReason, FailureSource, NpciResponseCode, SubscriptionStatus

# An arbitrary but FIXED unix timestamp used across tests for determinism —
# never `time.time()` in a test. (Resolves to 2026-12-23 10:40 IST; the exact
# date doesn't matter, only that it's fixed and reproducible.)
BASE_TIME = 1_798_002_600

# IST-aware reference times, computed properly via timeutils rather than raw
# UTC modulo arithmetic (which silently ignores the +05:30 offset and was a
# real bug caught by this suite's first run — see AI_USAGE.md).
_BASE_DAY_START = timeutils.start_of_ist_day(BASE_TIME)
PEAK_TIME = _BASE_DAY_START + 11 * 3600       # 11:00 IST — inside 10:00-13:00 peak window
PERMITTED_TIME = _BASE_DAY_START + 14 * 3600  # 14:00 IST — inside the 13:00-17:00 permitted window


def make_mandate(
    *,
    amount_paise: int = 50_000,
    mcc: int = 4900,
    payer_bank_code: str = "AXB",
    arrears_paise: int = 0,
    consecutive_same_reason_failures: int = 0,
    account_balance_paise_hint: Optional[int] = None,
    root_cause_reason: FailureReason = FailureReason.INSUFFICIENT_FUNDS,
    root_cause_npci_code: Optional[NpciResponseCode] = None,
    opted_out_at: Optional[int] = None,
) -> Mandate:
    customer = Customer(
        consent_state=ConsentState.OPTED_OUT if opted_out_at else ConsentState.GRANTED,
        opted_out_at=opted_out_at,
    )
    subscription = Subscription(
        customer_id=customer.id,
        status=SubscriptionStatus.PENDING,
        current_start=BASE_TIME - 30 * 86400,
        current_end=BASE_TIME,
        charge_at=BASE_TIME,
        start_at=BASE_TIME - 60 * 86400,
        created_at=BASE_TIME - 60 * 86400,
    )
    return Mandate(
        subscription=subscription,
        customer=customer,
        amount_paise=amount_paise,
        mcc=mcc,
        payer_bank_code=payer_bank_code,
        arrears_paise=arrears_paise,
        consecutive_same_reason_failures=consecutive_same_reason_failures,
        account_balance_paise_hint=account_balance_paise_hint,
        root_cause_reason=root_cause_reason,
        root_cause_npci_code=root_cause_npci_code,
    )


def make_failure_event(
    mandate: Mandate,
    *,
    reason: Optional[FailureReason] = None,
    npci_code: Optional[NpciResponseCode] = None,
    occurred_at: int = BASE_TIME,
    attempt_number: int = 1,
    source: FailureSource = FailureSource.CUSTOMER,
) -> FailureEvent:
    return FailureEvent(
        mandate_id=mandate.mandate_id,
        reason=reason if reason is not None else mandate.root_cause_reason,
        npci_code=npci_code if npci_code is not None else mandate.root_cause_npci_code,
        source=source,
        amount_paise=mandate.amount_paise,
        occurred_at=occurred_at,
        attempt_number=attempt_number,
    )

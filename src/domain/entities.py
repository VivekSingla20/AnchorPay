"""
Domain entities, as Pydantic v2 models.

`Subscription` field names mirror Razorpay's real payload shape exactly
(Build Spec §2.4; re-confirmed live 24 Aug 2026 — SOURCES.md §4). `Mandate`,
`FailureEvent`, `Attempt`, `AuditEntry` are this engine's own internal
representations — not literal Razorpay object shapes — but their sub-fields
(`reason`, `source`, `step`, `mcc`, `amount`) reuse Razorpay's naming
deliberately, so nothing is renamed without reason.

Amounts are integers in paise throughout (Build Spec §2.4: "Amounts are
integers in paise"). Timestamps are Unix epoch integers (UTC).

No name/email/phone field exists anywhere in this module. INV-12 ("no PII in
any log") is guaranteed structurally — there is no PII to leak — rather than
by a redaction step that could be forgotten. See LIMITATIONS.md.
"""
from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.domain.enums import (
    ConsentState,
    FailureReason,
    FailureSource,
    NpciResponseCode,
    SubscriptionStatus,
    WindowLabel,
)


def _new_id(prefix: str) -> str:
    """Razorpay-style prefixed ids (sub_, pay_, cust_, ...) — format-matching
    for realism, not cryptographically meaningful."""
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


class Customer(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("cust"))
    consent_state: ConsentState = ConsentState.NOT_YET_ASKED
    opted_out_at: Optional[int] = None
    last_contacted_at: Optional[int] = None
    contacts_today: int = 0


class Subscription(BaseModel):
    """Mirrors Razorpay's real subscription entity field-for-field."""

    id: str = Field(default_factory=lambda: _new_id("sub"))
    entity: str = "subscription"
    plan_id: str = Field(default_factory=lambda: _new_id("plan"))
    customer_id: str
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    current_start: int
    current_end: int
    ended_at: Optional[int] = None
    quantity: int = 1
    notes: dict = Field(default_factory=dict)
    charge_at: int
    start_at: int
    end_at: Optional[int] = None
    auth_attempts: int = 0
    total_count: int = 12
    paid_count: int = 0
    remaining_count: int = 12
    customer_notify: bool = True
    created_at: int
    expire_by: Optional[int] = None
    short_url: Optional[str] = None
    has_scheduled_changes: bool = False
    change_scheduled_at: Optional[int] = None
    source: str = "api"
    offer_id: Optional[str] = None


class Mandate(BaseModel):
    """This engine's own aggregate: a Subscription plus the payment-rail
    facts the scheduler needs (payer bank, amount, MCC, arrears). Razorpay's
    Subscription entity does not itself expose a payer bank or MCC — these
    are join keys this engine requires, documented as such rather than
    disguised as a Razorpay field."""

    mandate_id: str = Field(default_factory=lambda: _new_id("mandate"))
    subscription: Subscription
    customer: Customer
    amount_paise: int
    mcc: int
    payer_bank_code: str
    billing_cycle_position: int = 1
    arrears_paise: int = 0  # unpaid amount carried from prior halted cycles — never auto-collected, see INV-15
    consecutive_same_reason_failures: int = 0
    total_failures_lifetime: int = 0
    account_balance_paise_hint: Optional[int] = None  # generator's synthetic truth, for intent inference only
    # The failure mode this mandate's history is generated around. Simulation
    # simplification (ASSUMPTIONS.md #A8): within one retry episode, the
    # underlying cause is held constant — a real mandate could in principle
    # fail with a DIFFERENT reason on a later attempt, but modelling that
    # would require a full per-attempt causal model this project does not
    # have real data to calibrate, so it is out of scope (LIMITATIONS.md).
    root_cause_reason: FailureReason
    root_cause_npci_code: Optional[NpciResponseCode] = None
    # Generator-only ground truth for eval (precision/recall of intent inference).
    # NEVER read by anything under src/policy or src/guardrails — enforced by
    # tests/test_no_llm_in_policy.py's field-usage grep.
    ground_truth_intent_label: Optional[Literal["genuine_failure", "intentional_nonpayment"]] = None

    @field_validator("amount_paise")
    @classmethod
    def _amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_paise must be positive")
        return v


class FailureEvent(BaseModel):
    """A single failed execution attempt, normalised from a webhook-shaped
    payload. `reason` / `source` / `step` / `description` naming mirrors
    Razorpay's real error object anatomy (Build Spec §2.5)."""

    id: str = Field(default_factory=lambda: _new_id("evt"))
    mandate_id: str
    payment_id: str = Field(default_factory=lambda: _new_id("pay"))
    reason: FailureReason
    npci_code: Optional[NpciResponseCode] = None
    source: FailureSource
    step: str = "payment_authentication"
    description: str = ""
    amount_paise: int
    occurred_at: int
    attempt_number: int
    # Failure Injection #5 ("a reason arrives that is not in the taxonomy"):
    # when reason == UNKNOWN, the original unrecognised string is preserved
    # here for the classifier to attempt, and for audit.
    raw_reason_text: Optional[str] = None

    @field_validator("amount_paise")
    @classmethod
    def _amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_paise must be positive")
        return v


class Attempt(BaseModel):
    mandate_id: str
    attempt_number: int
    scheduled_at: int
    window: WindowLabel
    executed_at: Optional[int] = None
    outcome: Optional[Literal["success", "failed", "skipped"]] = None
    failure_event: Optional[FailureEvent] = None
    # INV-14: no attempt may execute without one. Only guardrails/validator.py
    # may mint this (see ApprovalToken in that module) — the executor refuses
    # to run an attempt whose token is None or fails re-verification.
    approval_token: Optional[str] = None


class Notification(BaseModel):
    """An out-of-band customer contact — pre-debit notice, post-debit
    confirmation, balance nudge, etc. Logged independently of Attempt so
    INV-06/07/08 (notification timing/consent invariants) can be checked
    without conflating "we contacted the customer" with "we executed a
    debit", which are different obligations under §2.2."""

    mandate_id: str
    intervention_type: str  # an enums.InterventionType value
    sent_at: int
    related_attempt_number: Optional[int] = None
    copy_text: str = ""
    grace_period_days: Optional[int] = None
    pause_cycles_offered: Optional[int] = None
    screened: bool = False
    screen_passed: Optional[bool] = None


class AuditEntry(BaseModel):
    """Append-only. Every pipeline stage writes one of these, including
    refusals and vetoes (Build Spec §5.2). INV-11 requires a reason on every
    entry; INV-12 (no PII) holds structurally because nothing upstream ever
    carries PII to begin with."""

    timestamp: int = Field(default_factory=lambda: int(time.time()))
    mandate_id: str
    stage: str
    decision: str
    reason: str
    actor: str  # an enums.ActorType value, kept as str here to avoid a needless import cycle
    approval_token: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

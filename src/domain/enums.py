"""
Domain enumerations.

Every value here is either (a) a literal string taken verbatim from a
Razorpay/NPCI source (see SOURCES.md), or (b) an internal decision-taxonomy
value invented for this engine's own policy layer. Each enum's docstring says
which. Only kind (a) is a "fact" defensible by citation; kind (b) is this
engine's own design and is defensible by reasoning, documented in
DECISIONS.md.

This module has zero internal dependencies by design — regulatory_constants.py
and entities.py both import from here, never the reverse.
"""
from __future__ import annotations

from enum import Enum


class SubscriptionStatus(str, Enum):
    """Razorpay subscription lifecycle states, verbatim.
    Source: Build Spec §2.4; re-confirmed live 24 Aug 2026 (SOURCES.md §4)."""

    CREATED = "created"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PENDING = "pending"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"
    PAUSED = "paused"


class FailureReason(str, Enum):
    """Razorpay UPI error `reason` values — a closed set of 10, verbatim.
    Source: Build Spec §2.5; re-confirmed live 24 Aug 2026 (SOURCES.md §3).

    UNKNOWN is NOT a Razorpay value. It is this engine's own sentinel, used
    only to exercise Failure Injection scenario 5 ("a failure reason arrives
    that is not in the taxonomy"). Never emit it as if it were a real
    Razorpay reason.
    """

    INSUFFICIENT_FUNDS = "insufficient_funds"
    BANK_TECHNICAL_ERROR = "bank_technical_error"
    GATEWAY_TECHNICAL_ERROR = "gateway_technical_error"
    CREDIT_FAILED = "credit_failed"
    INVALID_VPA = "invalid_vpa"
    VPA_RESOLUTION_FAILED = "vpa_resolution_failed"
    PAYMENT_DECLINED = "payment_declined"
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_TIMED_OUT = "payment_timed_out"
    PAYMENT_COLLECT_REQUEST_EXPIRED = "payment_collect_request_expired"
    UNKNOWN = "__unknown__"


class NpciResponseCode(str, Enum):
    """NPCI response codes that can co-occur with a Razorpay `reason`.
    Source: Razorpay blog 'Tackling UPI Payment Failures', Build Spec §2.5."""

    Z9 = "Z9"    # insufficient funds
    U28 = "U28"  # customer's bank is down
    U30 = "U30"  # debit failed - bank down or debit issue
    U69 = "U69"  # collect request expired
    Z7 = "Z7"    # too many transactions in an interval set by customer's bank
    Z8 = "Z8"    # per-transaction limit exceeded, set by customer's bank


class FailureSource(str, Enum):
    """Razorpay's `source` field: who/what caused the failure.
    Source: Build Spec §2.5."""

    CUSTOMER = "customer"
    BANK = "bank"
    GATEWAY = "gateway"
    NETWORK = "network"
    RAZORPAY = "razorpay"


class RetryabilityVerdict(str, Enum):
    """Internal policy taxonomy emitted by src/policy/retryability.py.
    NOT a Razorpay/NPCI value — this engine's own decision space.

    Five buckets rather than a boolean because 'retryable' alone can't
    express intent-inference (§3.2 Domain Context) or a terminal case that
    isn't the customer's fault (vpa_resolution_failed, credit_failed)."""

    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    NEEDS_CUSTOMER_ACTION = "needs_customer_action"
    INVESTIGATE = "investigate"
    LIKELY_INTENTIONAL_NONPAYMENT = "likely_intentional_nonpayment"


class InterventionType(str, Enum):
    """Enumerated out-of-band actions. The intervention selector (LLM-assisted,
    with a deterministic fallback) picks ONE of these given context — it
    never invents a new action. This closure is what makes INV-10-style
    "no action outside the allowlist" reasoning possible for interventions
    too, not just discounts."""

    PRE_DEBIT_NOTICE = "pre_debit_notice"
    POST_DEBIT_CONFIRMATION = "post_debit_confirmation"
    BALANCE_NUDGE = "balance_nudge"
    SOURCE_AWARE_FAILURE_NOTICE = "source_aware_failure_notice"
    ALTERNATE_RAIL_SUGGESTION = "alternate_rail_suggestion"
    CANCELLATION_CONFIRMATION = "cancellation_confirmation"
    ESCALATE_TO_SUPPORT = "escalate_to_support"
    NO_ACTION = "no_action"


class ConsentState(str, Enum):
    GRANTED = "granted"
    OPTED_OUT = "opted_out"
    NOT_YET_ASKED = "not_yet_asked"


class WindowLabel(str, Enum):
    """Which of the three NPCI-permitted daily execution windows an attempt
    was scheduled into. Source: Build Spec §2.1."""

    EARLY_MORNING = "before_10_00"
    AFTERNOON = "13_00_to_17_00"
    NIGHT = "after_21_30"


class WebhookEvent(str, Enum):
    """Razorpay subscription/invoice/payment webhook event names, verbatim.
    Source: Build Spec §2.4."""

    SUBSCRIPTION_AUTHENTICATED = "subscription.authenticated"
    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    SUBSCRIPTION_CHARGED = "subscription.charged"
    SUBSCRIPTION_PENDING = "subscription.pending"
    SUBSCRIPTION_HALTED = "subscription.halted"
    SUBSCRIPTION_COMPLETED = "subscription.completed"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    SUBSCRIPTION_PAUSED = "subscription.paused"
    SUBSCRIPTION_RESUMED = "subscription.resumed"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PARTIALLY_PAID = "invoice.partially_paid"
    INVOICE_EXPIRED = "invoice.expired"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_AUTHORIZED = "payment.authorized"


class ActorType(str, Enum):
    """Who/what made a decision, recorded on every audit entry. Lets the
    eval harness mechanically report 'how many decisions were LLM vs
    deterministic vs LLM-fallback' without re-deriving it from logs."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    LLM_FALLBACK = "llm_fallback_deterministic"
    HUMAN_OPERATOR = "human_operator"


class StrategyName(str, Enum):
    """The four baselines plus the engine itself. Used as a column key
    throughout eval/ so every report lines them up identically."""

    B0_NO_RECOVERY = "B0_no_recovery"
    B1_NAIVE_RETRY = "B1_naive_retry"
    B2_FIXED_SCHEDULE = "B2_fixed_schedule"
    B3_REASON_AWARE = "B3_reason_aware"
    ENGINE = "engine"

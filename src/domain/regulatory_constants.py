"""
Regulatory and platform constants — the compliance spine of this system.

RULE: every constant here carries its source. Nothing in this file is a
guess (Build Spec §0.1 — the three-tier fact system). Tier A facts are used
verbatim; Tier B facts are marked with their verification status; anything
this engine invented itself (no regulation says this number) is prefixed
`UNVERIFIED_` and explained in ASSUMPTIONS.md. See SOURCES.md for full
citations.

ENFORCED BY TEST: tests/test_no_llm_in_policy.py greps this module (and every
module in src/policy, src/guardrails) for an LLM client import. This module
must stay pure data — a constant that requires judgement to compute does not
belong here.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain.enums import FailureReason, FailureSource, NpciResponseCode, RetryabilityVerdict

# ---------------------------------------------------------------------------
# §2.1 NPCI "Guidelines on usage of UPI and API", circular dated 21 May 2025,
# effective 1 August 2025.
# Tier A. Corroborated in this session by two independent secondary sources
# (Singhania & Co./Mondaq; CAalley citing Economic Times) — see SOURCES.md §1.
# This is the single most important constraint set in the whole system.
# ---------------------------------------------------------------------------

SOURCE_NPCI_API_GUIDELINES_2025 = (
    "NPCI 'Guidelines on usage of Unified Payments Interface (UPI) and "
    "Application Programming Interface (API)', circular dated 21 May 2025, "
    "effective 1 August 2025. Corroborated via Singhania & Co./Mondaq and "
    "CAalley (citing Economic Times), 28 May 2025. See SOURCES.md §1."
)


@dataclass(frozen=True)
class TimeWindow:
    """A half-open [start, end) clock-time window in IST, within one calendar
    day. end_hour may be 24 to mean 'through midnight' — this is arithmetic
    on hour/minute ints, never a real datetime.time(24, 0), which Python
    would reject."""

    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    label: str

    def _as_minutes(self) -> tuple[int, int]:
        return (
            self.start_hour * 60 + self.start_minute,
            self.end_hour * 60 + self.end_minute,
        )

    def contains_minute_of_day(self, minute_of_day: int) -> bool:
        lo, hi = self._as_minutes()
        return lo <= minute_of_day < hi


# Peak hours: AutoPay mandate EXECUTION is prohibited inside these.
# Verbatim: "10:00–13:00 and 17:00–21:30 IST".
PEAK_WINDOWS: tuple[TimeWindow, ...] = (
    TimeWindow(10, 0, 13, 0, "10:00-13:00"),
    TimeWindow(17, 0, 21, 30, "17:00-21:30"),
)

# The three permitted execution windows, authored explicitly (not derived as
# PEAK_WINDOWS' runtime complement) so the invariant test and the allocator
# both read the exact same literal list — removes an entire class of
# off-by-one bugs a derived complement could introduce silently.
# Verbatim: "before 10:00, 13:00-17:00, after 21:30".
PERMITTED_WINDOWS: tuple[TimeWindow, ...] = (
    TimeWindow(0, 0, 10, 0, "before_10_00"),
    TimeWindow(13, 0, 17, 0, "13_00_to_17_00"),
    TimeWindow(21, 30, 24, 0, "after_21_30"),
)

MAX_EXECUTION_ATTEMPTS_TOTAL = 4  # "maximum 1 attempt + 3 retries", verbatim
MAX_RETRIES = 3

STATUS_CHECK_MIN_DELAY_SECONDS = 90
STATUS_CHECK_MAX_CALLS = 3
STATUS_CHECK_WINDOW_HOURS = 2

BALANCE_ENQUIRY_DAILY_CAP_PER_APP = 50
LINKED_ACCOUNT_LISTING_DAILY_CAP_PER_APP = 25

# ---------------------------------------------------------------------------
# §2.2 RBI Digital Payments - E-Mandate Framework, 2026
# Circular RBI/DPSS/2026-27/396, dated 21 April 2026.
# Tier A per Build Spec Part 2's own instruction to use it verbatim; NOTE
# this session did not independently re-fetch the primary circular (see
# SOURCES.md §2, LIMITATIONS.md) — flagged honestly rather than silently
# treated as re-verified.
# ---------------------------------------------------------------------------

SOURCE_RBI_EMANDATE_FRAMEWORK_2026 = (
    "RBI 'Digital Payments - E-Mandate Framework, 2026', Circular "
    "RBI/DPSS/2026-27/396, dated 21 April 2026. Tier B: not independently "
    "re-fetched this session. See SOURCES.md §2 and LIMITATIONS.md."
)

PRE_DEBIT_NOTIFICATION_HOURS = 24
NO_AFA_THRESHOLD_PAISE = 15_000 * 100
NO_AFA_ENHANCED_THRESHOLD_PAISE = 1_00_000 * 100

# MCCs eligible for the ENHANCED (Rs 1,00,000) AFA threshold apply to
# "insurance premiums, mutual fund SIPs, credit card bills" per source
# prose. Only MCC 6211 (securities brokers and dealers) was given as an
# explicit MCC number anywhere in the sourced material (Domain Context
# §2.3). Encoding ONLY 6211 here — rather than guessing MCC numbers for
# "insurance" or "credit card bills" — is a deliberately conservative
# subset. See ASSUMPTIONS.md #A5.
ENHANCED_AFA_MCCS = frozenset({6211})

# NPCI notification, 23 September 2024: pre-debit notification is not
# required for auto-replenishment of NETC FASTag / RuPay NCMC under UPI
# AutoPay. Source: Build Spec §2.2.
MCC_FASTAG = 4784
MCC_RUPAY_NCMC = 7412
PRE_DEBIT_NOTIFICATION_CARVEOUT_MCCS = frozenset({MCC_FASTAG, MCC_RUPAY_NCMC})

# ---------------------------------------------------------------------------
# §2.3 Scale and failure-rate figures. Used ONLY as generator-calibration
# targets and README context — never asserted as a per-record ground truth.
# ---------------------------------------------------------------------------
SOURCE_NPCI_OC_149 = "NPCI Circular OC-149, June 2022."
SYSTEM_WIDE_TECHNICAL_DECLINE_TARGET_PCT = 1.0  # "<1%"
SYSTEM_WIDE_BUSINESS_DECLINE_TARGET_PCT = 5.0  # "<5%"
SOURCE_BUSINESS_STANDARD_20M_REVOCATIONS = (
    "Business Standard, Ajinkya Kawale, 7 Sept 2025: ~20 million AutoPay "
    "mandates revoked monthly on insufficient balance; ~74% average business "
    "decline rate across top 50 banks. Domain Context §2.1. NOTE the "
    "article's own caveat: this figure conflates execution failures with "
    "deliberate user cancellations — see ASSUMPTIONS.md #A2."
)

# ---------------------------------------------------------------------------
# §2.4 Razorpay subscription state machine.
# Tier A, re-confirmed live 24 Aug 2026 — see SOURCES.md §4.
# ---------------------------------------------------------------------------
SOURCE_RAZORPAY_SUBSCRIPTION_STATES = (
    "Razorpay Docs, 'Subscriptions States', re-fetched and confirmed "
    "verbatim 24 Aug 2026, including the exact quote: 'once the Subscription "
    "moves back to the active state, the previous charges will not be "
    "re-attempted. Only future billing cycles are charged automatically.' "
    "See SOURCES.md §4."
)
CONSECUTIVE_FAILURES_TO_HALT = 4  # matches NPCI's 1+3 exactly - see DECISIONS.md ADR-002

# ---------------------------------------------------------------------------
# §2.5 Failure taxonomy -> strategy mapping. Data, not code branches, so a
# non-engineer can review it directly. Source: Build Spec §4.1, cross-checked
# against the live Razorpay UPI Error Codes page (SOURCES.md §3).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReasonStrategy:
    reason: FailureReason
    source: FailureSource
    verdict: RetryabilityVerdict
    rationale: str
    spec_reference: str


REASON_STRATEGY_TABLE: tuple[ReasonStrategy, ...] = (
    ReasonStrategy(
        FailureReason.INSUFFICIENT_FUNDS,
        FailureSource.CUSTOMER,
        RetryabilityVerdict.RETRYABLE,
        "Balance is time-varying; timing (not persistence) is the lever. "
        "See the salary-cycle heuristic in policy/allocator.py.",
        "Build Spec Part 4.1 row 1 (insufficient_funds / Z9)",
    ),
    ReasonStrategy(
        FailureReason.BANK_TECHNICAL_ERROR,
        FailureSource.BANK,
        RetryabilityVerdict.RETRYABLE,
        "Transient; the bank-health signal should drive window choice, not "
        "a blind next-slot retry.",
        "Build Spec Part 4.1 row 2 (bank_technical_error / U28 / U30)",
    ),
    ReasonStrategy(
        FailureReason.GATEWAY_TECHNICAL_ERROR,
        FailureSource.GATEWAY,
        RetryabilityVerdict.RETRYABLE,
        "Transient, gateway-side.",
        "Build Spec Part 4.1 row 3",
    ),
    ReasonStrategy(
        FailureReason.INVALID_VPA,
        FailureSource.CUSTOMER,
        RetryabilityVerdict.TERMINAL,
        "Requires customer re-registration on the UPI app. Retrying cannot "
        "succeed and wastes a share of the 4-attempt budget.",
        "Build Spec Part 4.1 row 6",
    ),
    ReasonStrategy(
        FailureReason.VPA_RESOLUTION_FAILED,
        FailureSource.RAZORPAY,
        RetryabilityVerdict.INVESTIGATE,
        "Razorpay's own docs direct this to technical support, not to a "
        "customer action or an automatic retry.",
        "Build Spec Part 4.1 row 7",
    ),
    ReasonStrategy(
        FailureReason.PAYMENT_CANCELLED,
        FailureSource.CUSTOMER,
        RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT,
        "Customer affirmatively backed out. Spec calls this a 'judgment' "
        "case; this engine's judgment (documented in DECISIONS.md ADR-003) "
        "is to treat an affirmative cancel as an intent signal by default "
        "and route to cancellation-confirmation rather than to chase it — "
        "consistent with 'a no ends the sequence, no escalation loop'.",
        "Build Spec Part 4.1 row 8 — judgment call, see DECISIONS.md ADR-003",
    ),
    ReasonStrategy(
        FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED,
        FailureSource.CUSTOMER,
        RetryabilityVerdict.RETRYABLE,
        "A timing/attention problem, not a funds problem.",
        "Build Spec Part 4.1 row 9 (payment_collect_request_expired / U69)",
    ),
    ReasonStrategy(
        FailureReason.PAYMENT_DECLINED,
        FailureSource.BANK,
        RetryabilityVerdict.RETRYABLE,
        "Debit failed; cause may be transient.",
        "Build Spec Part 4.1 row 10",
    ),
    ReasonStrategy(
        FailureReason.CREDIT_FAILED,
        FailureSource.RAZORPAY,
        RetryabilityVerdict.INVESTIGATE,
        "Distinguish from a debit failure; not on the standard debit-retry "
        "path per Razorpay's docs.",
        "Build Spec Part 4.1 row 11",
    ),
    ReasonStrategy(
        FailureReason.PAYMENT_TIMED_OUT,
        FailureSource.CUSTOMER,
        RetryabilityVerdict.RETRYABLE,
        "NOT explicitly in Build Spec §4.1's table. Judgment call: "
        "Razorpay's own next-step text for this reason is identical to "
        "payment_collect_request_expired ('Customer Exceeded Payment Time "
        "Limit'), so it is modelled the same way. This is an inference, not "
        "a source-given mapping — see DECISIONS.md ADR-004.",
        "Not in Build Spec §4.1 - DECISIONS.md ADR-004",
    ),
)

REASON_STRATEGY_BY_REASON: dict[FailureReason, ReasonStrategy] = {
    row.reason: row for row in REASON_STRATEGY_TABLE
}

# Z7/Z8 are NPCI response codes that co-occur with a `reason` (usually
# payment_declined or bank_technical_error) rather than being reasons
# themselves. They OVERRIDE the table-driven verdict above when present.
# Source: Build Spec §4.1 rows 4-5.
NPCI_CODE_VERDICT_OVERRIDE: dict[NpciResponseCode, RetryabilityVerdict] = {
    NpciResponseCode.Z7: RetryabilityVerdict.RETRYABLE,  # "yes, with spacing"
    NpciResponseCode.Z8: RetryabilityVerdict.TERMINAL,  # "No, not unchanged" - structural per-txn ceiling
}
# Z7 requires spacing between attempts because retrying immediately
# re-triggers the same velocity limit. Enforced in policy/allocator.py, not
# here — this module stays pure data.
Z7_MIN_SPACING_HOURS = 4  # UNVERIFIED: no source gives a number for Z7 spacing;
# 4h is this engine's own conservative choice (comfortably wider than any
# single permitted window). See ASSUMPTIONS.md #A6.

# ---------------------------------------------------------------------------
# Razorpay Agent Studio's nine published principles, named exactly, for the
# agent manifest and README. Source: Build Spec §2.7.
# ---------------------------------------------------------------------------
SOURCE_RAZORPAY_AGENT_PRINCIPLES = (
    "Razorpay, 'Agent Studio: Principles, Guardrails, and Merchant Control', "
    "30 March 2026. See Build Spec §2.7."
)
AGENT_STUDIO_PRINCIPLES: tuple[str, ...] = (
    "merchant_always_in_control",
    "no_invented_prices_or_discounts",
    "verified_first_party_data_only",
    "every_action_validated_before_execution",
    "consent_rules_on_customer_communication",
    "no_false_urgency_no_dark_patterns",
    "transparent_pricing_and_cost",
    "certification_and_accountability",
    "data_privacy_and_compliance",
)

# ---------------------------------------------------------------------------
# §6.6 Dark-pattern screen vocabulary. Source: India's Guidelines for
# Prevention and Regulation of Dark Patterns, 2023, referenced by Razorpay
# Agent Studio principle 6 (Build Spec §1 row 6, §6.6). Kept as data so the
# screen's coverage is reviewable without reading code.
# ---------------------------------------------------------------------------
SOURCE_DARK_PATTERNS_GUIDELINES_2023 = (
    "Guidelines for Prevention and Regulation of Dark Patterns, 2023 "
    "(Government of India / CCPA), as referenced by Razorpay Agent Studio "
    "principle 6. See Build Spec §1 principle 6 and §6.6."
)
DARK_PATTERN_CATEGORIES: tuple[str, ...] = (
    "false_urgency",
    "confirm_shaming",
    "bait_and_switch",
    "drip_pricing",
    "subscription_traps",
    "fabricated_scarcity",
)

# ---------------------------------------------------------------------------
# UNVERIFIED modelling assumptions - this engine's OWN choices, not sourced
# from any regulation. Full rationale + sensitivity notes: ASSUMPTIONS.md.
# Naming convention (UNVERIFIED_ prefix) makes these grep-able and impossible
# to confuse with a sourced constant above.
# ---------------------------------------------------------------------------
UNVERIFIED_MAX_CONTACTS_PER_MANDATE_PER_DAY = 1  # ASSUMPTIONS.md #A1
UNVERIFIED_INTENT_MIN_CONSECUTIVE_SAME_REASON_FAILURES = 3  # ASSUMPTIONS.md #A2
UNVERIFIED_INTENT_MAX_BALANCE_TO_AMOUNT_RATIO = 0.05  # ASSUMPTIONS.md #A2
UNVERIFIED_SALARY_CYCLE_HIGH_LIQUIDITY_DAYS = frozenset({1, 2, 3, 28, 29, 30, 31})  # ASSUMPTIONS.md #A3
UNVERIFIED_STOPPING_RULE_MAX_DAYS_SINCE_FIRST_FAILURE = 21  # ASSUMPTIONS.md #A4

# Razorpay Agent Studio principle 2 ("agents don't set prices or invent
# discounts... selected from a merchant-configured allowlist with a hard
# ceiling") applied to the one goodwill lever this engine supports: a short
# grace period before a stalled mandate is routed to cancellation-
# confirmation. The selector (src/intervene/selector.py, LLM-assisted) may
# only ever pick a value from this tuple — never compute or invent one.
# INV-10 asserts this ceiling holds. See ASSUMPTIONS.md #A7.
MERCHANT_ALLOWED_GRACE_PERIOD_DAYS: tuple[int, ...] = (1, 2, 3)
MERCHANT_GRACE_PERIOD_CEILING_DAYS = 3

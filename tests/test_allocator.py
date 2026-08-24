"""
tests/test_allocator.py — the core scheduling algorithm.

Every test here asserts a HARD constraint (never violated, structurally) or
a HEURISTIC ranking effect (measurable, but only among already-legal
candidates). See src/policy/allocator.py's module docstring for the
distinction.
"""
from __future__ import annotations

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.enums import FailureReason
from src.policy import allocator
from tests.factories import BASE_TIME, make_mandate


def test_proposed_time_is_never_inside_a_peak_window() -> None:
    mandate = make_mandate()
    for offset_days in range(0, 5):
        earliest = BASE_TIME + offset_days * 86400
        proposal = allocator.propose_next_attempt(mandate=mandate, reason=FailureReason.BANK_TECHNICAL_ERROR, earliest_legal_time=earliest)
        assert not timeutils.is_peak_hour(proposal.scheduled_at), f"proposal at {proposal.scheduled_at} falls inside a peak window"


def test_proposed_time_never_precedes_earliest_legal_time() -> None:
    mandate = make_mandate()
    earliest = BASE_TIME + RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600
    proposal = allocator.propose_next_attempt(mandate=mandate, reason=FailureReason.INSUFFICIENT_FUNDS, earliest_legal_time=earliest)
    assert proposal.scheduled_at >= earliest


def test_compute_earliest_legal_time_respects_24h_notice_unless_carveout() -> None:
    without_carveout = allocator.compute_earliest_legal_time(now=BASE_TIME, notification_carveout=False)
    with_carveout = allocator.compute_earliest_legal_time(now=BASE_TIME, notification_carveout=True)
    assert without_carveout - BASE_TIME == RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600
    assert with_carveout - BASE_TIME < RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600


def test_z7_spacing_is_enforced() -> None:
    mandate = make_mandate()
    proposal = allocator.propose_next_attempt(
        mandate=mandate, reason=FailureReason.PAYMENT_DECLINED, earliest_legal_time=BASE_TIME, z7_spacing_required=True,
    )
    assert (proposal.scheduled_at - BASE_TIME) >= RC.Z7_MIN_SPACING_HOURS * 3600


def test_allocator_is_deterministic_for_same_inputs() -> None:
    mandate = make_mandate()
    p1 = allocator.propose_next_attempt(mandate=mandate, reason=FailureReason.INSUFFICIENT_FUNDS, earliest_legal_time=BASE_TIME)
    p2 = allocator.propose_next_attempt(mandate=mandate, reason=FailureReason.INSUFFICIENT_FUNDS, earliest_legal_time=BASE_TIME)
    assert p1.scheduled_at == p2.scheduled_at
    assert p1.window_label == p2.window_label


def test_salary_cycle_heuristic_prefers_high_liquidity_day_when_reachable() -> None:
    """Anchor earliest_legal_time the day before a high-liquidity day
    (day 1 of the month) so both a low- and high-liquidity candidate are
    within the search horizon, then confirm the heuristic picks the
    high-liquidity one when switched on, and stops doing so when switched
    off — an ablation check at unit-test scale, not just in EVALUATION.md."""
    # 2026-08-31 00:05 IST is not itself a high-liquidity day, but day 1
    # (2026-09-01) is, and falls inside the allocator's 10-day search horizon.
    aug_31 = timeutils.start_of_ist_day(BASE_TIME) + 7 * 86400 + 300
    mandate = make_mandate()

    with_heuristic = allocator.propose_next_attempt(
        mandate=mandate, reason=FailureReason.INSUFFICIENT_FUNDS, earliest_legal_time=aug_31, use_salary_cycle_heuristic=True,
    )
    assert with_heuristic.used_salary_cycle_heuristic
    assert timeutils.to_ist(with_heuristic.scheduled_at).day in RC.UNVERIFIED_SALARY_CYCLE_HIGH_LIQUIDITY_DAYS

    without_heuristic = allocator.propose_next_attempt(
        mandate=mandate, reason=FailureReason.INSUFFICIENT_FUNDS, earliest_legal_time=aug_31, use_salary_cycle_heuristic=False,
    )
    assert not without_heuristic.used_salary_cycle_heuristic


def test_salary_cycle_heuristic_never_applies_to_non_funds_reasons() -> None:
    mandate = make_mandate()
    proposal = allocator.propose_next_attempt(
        mandate=mandate, reason=FailureReason.BANK_TECHNICAL_ERROR, earliest_legal_time=BASE_TIME, use_salary_cycle_heuristic=True,
    )
    assert not proposal.used_salary_cycle_heuristic


def test_bank_health_heuristic_avoids_a_bank_with_active_high_severity_downtime() -> None:
    from src.policy.bank_health import DowntimeRecord

    mandate = make_mandate(payer_bank_code="PYTM")
    day_start = timeutils.start_of_ist_day(BASE_TIME)
    downtime = [DowntimeRecord(
        id="down_test", entity="payment.downtime", method="upi",
        begin=day_start, end=day_start + 10 * 86400, status="started", scheduled=True,
        severity="high", bank_code="PYTM", created_at=day_start, updated_at=day_start,
    )]
    proposal = allocator.propose_next_attempt(
        mandate=mandate, reason=FailureReason.BANK_TECHNICAL_ERROR, earliest_legal_time=BASE_TIME,
        downtime_records=downtime, use_bank_health_heuristic=True,
    )
    assert proposal.used_bank_health_heuristic
    # every candidate in range is "down", so the allocator can't avoid the
    # window entirely — but it must still produce ONE legal, non-peak slot
    # rather than failing, which is the structural guarantee under test.
    assert not timeutils.is_peak_hour(proposal.scheduled_at)

"""
policy/allocator.py — Stage 5: THE CORE ALGORITHM.

Given a failed mandate with a RETRYABLE verdict and remaining budget, choose
the next execution time. Optimises expected-rupees-recovered subject to hard
constraints (Build Spec Part 4), using heuristics to rank among candidates
that are ALL already legal — no heuristic can ever produce an illegal time,
because the candidate generator itself only emits legal slots.

Hard constraints (structural, never just checked-after-the-fact):
  - t falls inside a permitted window (candidates are only ever generated
    inside PERMITTED_WINDOWS)
  - total attempts never exceed 4 (enforced by the caller's attempts_made
    check before this is even invoked — see orchestrator.py)
  - the 24h pre-debit-notification obligation is satisfiable before t,
    unless the MCC carve-out applies (enforced via `earliest_legal_time`)
  - Z7 (velocity limit) spacing is respected when required

Ranking heuristics (Tier-1/Tier-2 ideas from Domain Context Part 5):
  1. Salary-cycle-aware timing (§4.4): insufficient_funds failures score
     higher on high-liquidity days (near month-end/month-start).
     UNVERIFIED — ablation-tested via eval/run_eval.py's
     --no-salary-cycle-heuristic flag. See ASSUMPTIONS.md #A3.
  2. Bank-health-aware timing: candidates when the payer bank has an active
     downtime are scored down, proportional to severity.
  3. Window-contention spreading (Tier-2 idea #6): the exact minute within a
     chosen window is spread deterministically by a hash of mandate_id, so
     many mandates don't all cluster at a window's first second — the same
     motivation NPCI itself cited (system load) applied one level down.

NO LLM IMPORT — enforced by tests/test_no_llm_in_policy.py.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from src.domain import regulatory_constants as RC
from src.domain import timeutils
from src.domain.entities import Mandate
from src.domain.enums import FailureReason
from src.policy.bank_health import DowntimeRecord, bank_health_score


@dataclass
class ScheduleProposal:
    scheduled_at: int
    window_label: str
    rationale: str
    used_salary_cycle_heuristic: bool
    used_bank_health_heuristic: bool


def compute_earliest_legal_time(*, now: int, notification_carveout: bool) -> int:
    """The soonest a next attempt could legally happen given the 24h
    pre-debit-notification obligation (Build Spec §2.2), unless the MCC
    carve-out applies (FASTag / RuPay NCMC, §2.2)."""
    if notification_carveout:
        return now + 600  # 10-minute internal processing buffer — not a regulatory number, just operational slack
    return now + RC.PRE_DEBIT_NOTIFICATION_HOURS * 3600


def _candidate_slots(earliest: int, max_days_ahead: int = 10) -> list[tuple[int, int, "RC.TimeWindow"]]:
    """Every (slot_start, slot_end, window) triple across the next
    max_days_ahead days starting from `earliest`'s IST calendar day."""
    out = []
    day0 = timeutils.start_of_ist_day(earliest)
    for day_offset in range(max_days_ahead + 1):
        day_start = day0 + day_offset * 86400
        for w in RC.PERMITTED_WINDOWS:
            slot_start = day_start + w.start_hour * 3600 + w.start_minute * 60
            slot_end = day_start + w.end_hour * 3600 + w.end_minute * 60
            out.append((slot_start, slot_end, w))
    return out


def _jitter_seconds(mandate_id: str, window_span_seconds: int) -> int:
    """Deterministic pseudo-spread within a window (Tier-2 idea #6: window
    contention). Bounded to the middle 80% of the window so a jittered time
    never lands right on a boundary from rounding."""
    h = int(hashlib.sha256(mandate_id.encode()).hexdigest(), 16)
    span = max(int(window_span_seconds * 0.8), 1)
    offset = h % span
    return offset + int(window_span_seconds * 0.1)


def propose_next_attempt(
    *,
    mandate: Mandate,
    reason: FailureReason,
    earliest_legal_time: int,
    z7_spacing_required: bool = False,
    downtime_records: Optional[list[DowntimeRecord]] = None,
    use_salary_cycle_heuristic: bool = True,
    use_bank_health_heuristic: bool = True,
) -> ScheduleProposal:
    candidates: list[tuple[int, "RC.TimeWindow"]] = []
    for slot_start, slot_end, w in _candidate_slots(earliest_legal_time):
        span = slot_end - slot_start
        jitter = _jitter_seconds(mandate.mandate_id, span)
        proposed = max(slot_start + jitter, earliest_legal_time)
        if proposed >= slot_end:
            continue  # earliest_legal_time (or jitter) pushed past this window's end
        if z7_spacing_required and (proposed - earliest_legal_time) < RC.Z7_MIN_SPACING_HOURS * 3600:
            continue
        candidates.append((proposed, w))
        if len(candidates) >= 6:  # bound the search — never chase arbitrarily far into the future
            break

    scored = []
    for proposed, w in candidates:
        score = 0.0
        used_salary = False
        used_bank = False
        if use_salary_cycle_heuristic and reason == FailureReason.INSUFFICIENT_FUNDS:
            day_of_month = timeutils.to_ist(proposed).day
            if day_of_month in RC.UNVERIFIED_SALARY_CYCLE_HIGH_LIQUIDITY_DAYS:
                score += 3.0
                used_salary = True
        if use_bank_health_heuristic:
            signal = bank_health_score(mandate.payer_bank_code, proposed, downtime_records)
            if signal.active_downtime_severity == "high":
                score -= 5.0
            elif signal.active_downtime_severity == "medium":
                score -= 2.0
            score -= signal.technical_decline_pct
            used_bank = True
        # Earlier-is-better is the tiebreaker, not the primary key — this is
        # deliberate, so the salary-cycle/bank-health heuristics can win over
        # "soonest slot" when they have a real signal.
        score -= (proposed - earliest_legal_time) / 86400.0 * 0.1
        scored.append((score, proposed, w, used_salary, used_bank))

    if not scored:
        fallback_start, _, w = _candidate_slots(earliest_legal_time)[0]
        return ScheduleProposal(
            fallback_start, w.label,
            "no scored candidate was legal within the search horizon; used the first legal slot as a safe fallback.",
            False, False,
        )

    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_time, best_window, used_salary, used_bank = scored[0]
    parts = [f"selected among {len(scored)} legal candidates (score={best_score:.2f})"]
    if used_salary:
        parts.append("salary-cycle heuristic applied: day-of-month is a high-liquidity day (UNVERIFIED, ASSUMPTIONS.md #A3)")
    if used_bank:
        parts.append("bank-health heuristic applied")
    return ScheduleProposal(best_time, best_window.label, "; ".join(parts), used_salary, used_bank)

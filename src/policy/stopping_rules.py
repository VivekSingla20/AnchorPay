"""
policy/stopping_rules.py — the explicit "when to stop and revoke rather than
continue" logic Build Spec Part 4 demands by name. Deterministic.

Chasing a mandate forever is a failure mode, not thoroughness. Every
strategy in this codebase (baselines included, via eval/baselines.py) is
required to consult this before scheduling another attempt.

NO LLM IMPORT — enforced by tests/test_no_llm_in_policy.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain import regulatory_constants as RC
from src.domain.enums import RetryabilityVerdict


@dataclass
class StopDecision:
    should_stop: bool
    reason: str


def evaluate(
    *,
    verdict: RetryabilityVerdict,
    attempts_made: int,
    first_failure_at: int,
    now: int,
) -> StopDecision:
    if verdict in (
        RetryabilityVerdict.TERMINAL,
        RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT,
        RetryabilityVerdict.INVESTIGATE,
    ):
        return StopDecision(
            True,
            f"verdict is '{verdict.value}'; scheduling a further retry would be either "
            f"illegal (terminal), against the consent principle (likely intentional "
            f"non-payment — a 'no' ends the sequence), or premature (needs investigation "
            f"before any further automatic action).",
        )
    if attempts_made >= RC.MAX_EXECUTION_ATTEMPTS_TOTAL:
        return StopDecision(
            True,
            f"attempt budget exhausted ({attempts_made}/{RC.MAX_EXECUTION_ATTEMPTS_TOTAL}); "
            f"the subscription moves to halted, matching Razorpay's own 4-consecutive-"
            f"failure rule (SOURCES.md §4) and NPCI's 1+3 cap (SOURCES.md §1).",
        )
    days_elapsed = (now - first_failure_at) / 86400
    if days_elapsed > RC.UNVERIFIED_STOPPING_RULE_MAX_DAYS_SINCE_FIRST_FAILURE:
        return StopDecision(
            True,
            f"{days_elapsed:.1f} days since the first failure exceeds the "
            f"{RC.UNVERIFIED_STOPPING_RULE_MAX_DAYS_SINCE_FIRST_FAILURE}-day stopping rule "
            f"(ASSUMPTIONS.md #A4) — revoking rather than chasing indefinitely.",
        )
    return StopDecision(False, "within attempt budget, verdict, and time bounds; scheduling may continue.")

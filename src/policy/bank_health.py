"""
policy/bank_health.py — Stage 4: the bank health signal h(b, t).

`DowntimeRecord` mirrors Razorpay's real Downtime API response schema
field-for-field (SOURCES.md §5), so wiring in the real
`GET /v1/payments/downtimes` endpoint later is a data-source swap, not a
schema rewrite.

Per-bank technical/business decline baselines come from
data/npci/bank_health_reference.csv — real NPCI bank codes, percentages
calibrated to the confirmed system-wide OC-149 targets (see
data/npci/README.md and SOURCES.md §6 for exactly what is and isn't
independently verified in that file).

NO LLM IMPORT — enforced by tests/test_no_llm_in_policy.py.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.domain import regulatory_constants as RC

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_CSV = _REPO_ROOT / "data" / "npci" / "bank_health_reference.csv"


@dataclass(frozen=True)
class DowntimeRecord:
    """Field-for-field match to Razorpay's `GET /v1/payments/downtimes`
    response items (SOURCES.md §5). `bank_code` here corresponds to the real
    schema's `instrument.bank`."""

    id: str
    entity: str
    method: str  # "card" | "netbanking" | "upi"
    begin: int
    end: Optional[int]
    status: str  # "scheduled" | "started" | "updated"
    scheduled: bool
    severity: str  # "high" | "medium" | "low"
    bank_code: str
    created_at: int
    updated_at: int

    def is_active_at(self, at: int) -> bool:
        if at < self.begin:
            return False
        if self.end is None:
            return self.status in ("started", "updated")
        return at <= self.end


@dataclass(frozen=True)
class BankHealthSignal:
    bank_code: str
    technical_decline_pct: float
    business_decline_pct: float
    active_downtime_severity: Optional[str]
    confidence: str  # "calibrated_synthetic" | "system_wide_fallback"


_REFERENCE_CACHE: Optional[dict[str, dict[str, float]]] = None
_LAST_LOAD_ERROR: Optional[str] = None  # Failure Injection #3 visibility — see reference_table_status()


def reset_reference_cache_for_testing() -> None:
    """Test/scenario-only: forces the next call to re-read from disk,
    instead of the file being read exactly once per process."""
    global _REFERENCE_CACHE, _LAST_LOAD_ERROR
    _REFERENCE_CACHE = None
    _LAST_LOAD_ERROR = None


def reference_table_status() -> dict:
    """Failure Injection #3 ('NPCI stats file unavailable or stale'):
    exposes whether the last load succeeded, so a caller (or this project's
    failure-injection scenario runner) can confirm the system degraded
    gracefully instead of merely hoping it did."""
    return {"loaded_bank_count": len(_REFERENCE_CACHE or {}), "last_load_error": _LAST_LOAD_ERROR}


def _load_reference_table() -> dict[str, dict[str, float]]:
    """Never raises. A missing, unreadable, or malformed reference file
    degrades to an EMPTY table — every bank then falls through
    `bank_health_score`'s existing 'unknown bank code' path to the
    confirmed system-wide OC-149 targets (SYSTEM_WIDE_TECHNICAL_DECLINE_TARGET_PCT
    / SYSTEM_WIDE_BUSINESS_DECLINE_TARGET_PCT), rather than crashing the
    batch or silently scheduling with no bank-health signal at all. The
    degradation is recorded in _LAST_LOAD_ERROR for
    `reference_table_status()` / FAILURES.md #3 to report — found by
    deliberately renaming the CSV and re-running, not by inspection alone.
    """
    global _REFERENCE_CACHE, _LAST_LOAD_ERROR
    if _REFERENCE_CACHE is not None:
        return _REFERENCE_CACHE
    table: dict[str, dict[str, float]] = {}
    try:
        with open(_REFERENCE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                table[row["bank_code"]] = {
                    "technical_decline_pct": float(row["technical_decline_pct"]),
                    "business_decline_pct": float(row["business_decline_pct"]),
                }
        if not table:
            raise ValueError("reference CSV parsed but contained zero rows")
    except (OSError, ValueError, KeyError) as exc:
        _LAST_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        table = {}
    _REFERENCE_CACHE = table
    return table


def _severity_rank(sev: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(sev, 0)


def bank_health_score(
    bank_code: str,
    at: int,
    downtime_records: Optional[list[DowntimeRecord]] = None,
) -> BankHealthSignal:
    table = _load_reference_table()
    row = table.get(bank_code)
    if row is None:
        # Unknown bank code: fall back to the confirmed system-wide OC-149
        # targets rather than guessing a bank-specific number.
        row = {
            "technical_decline_pct": RC.SYSTEM_WIDE_TECHNICAL_DECLINE_TARGET_PCT,
            "business_decline_pct": RC.SYSTEM_WIDE_BUSINESS_DECLINE_TARGET_PCT,
        }
        confidence = "system_wide_fallback"
    else:
        confidence = "calibrated_synthetic"

    active_severity: Optional[str] = None
    for rec in downtime_records or []:
        if rec.bank_code == bank_code and rec.method == "upi" and rec.is_active_at(at):
            if active_severity is None or _severity_rank(rec.severity) > _severity_rank(active_severity):
                active_severity = rec.severity

    return BankHealthSignal(
        bank_code=bank_code,
        technical_decline_pct=row["technical_decline_pct"],
        business_decline_pct=row["business_decline_pct"],
        active_downtime_severity=active_severity,
        confidence=confidence,
    )


def is_bank_healthy_enough(signal: BankHealthSignal) -> bool:
    if signal.active_downtime_severity == "high":
        return False
    return signal.technical_decline_pct <= (RC.SYSTEM_WIDE_TECHNICAL_DECLINE_TARGET_PCT * 3)

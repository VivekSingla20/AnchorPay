"""
ingest/npci_stats.py — NPCI bank-health data ingestion.

Thin, explicit loader over data/npci/bank_health_reference.csv. Kept
separate from policy/bank_health.py's internal scoring cache so eval/run_eval.py
can report INGESTION facts (row count, which banks, provenance) independently
of the SCORING function. See that CSV's header comment and SOURCES.md §6 for
exactly what is real vs calibrated-synthetic in this table.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_CSV = _REPO_ROOT / "data" / "npci" / "bank_health_reference.csv"


@dataclass(frozen=True)
class BankHealthRow:
    bank_code: str
    bank_name: str
    technical_decline_pct: float
    business_decline_pct: float
    data_provenance: str  # "confirmed_live_fetch" | "calibrated_synthetic_extension"


def load_all() -> list[BankHealthRow]:
    """Never raises (Failure Injection #3: 'NPCI stats file unavailable or
    stale'). A missing/unreadable/malformed file degrades to an empty list —
    `summary()` then honestly reports zero banks loaded instead of the
    ingestion step crashing the whole eval run."""
    rows: list[BankHealthRow] = []
    try:
        with open(_REFERENCE_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(
                    BankHealthRow(
                        bank_code=row["bank_code"],
                        bank_name=row["bank_name"],
                        technical_decline_pct=float(row["technical_decline_pct"]),
                        business_decline_pct=float(row["business_decline_pct"]),
                        data_provenance=row["data_provenance"],
                    )
                )
    except (OSError, ValueError, KeyError):
        return []
    return rows


def summary() -> dict:
    rows = load_all()
    confirmed = [r for r in rows if r.data_provenance == "confirmed_live_fetch"]
    synthetic = [r for r in rows if r.data_provenance != "confirmed_live_fetch"]
    return {
        "total_banks": len(rows),
        "confirmed_live_fetch_banks": len(confirmed),
        "calibrated_synthetic_banks": len(synthetic),
        "source": "SOURCES.md §6",
    }

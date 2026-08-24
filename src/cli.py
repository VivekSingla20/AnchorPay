"""
src/cli.py — the minimal interface (Build Spec Part 5.1 stage 11 / Part 12
phase 11: "Minimal. Enough to run a demo and view the audit trail. Do not
spend more than 15% of total effort here.").

Three commands, no web framework, no extra dependencies:

  python -m src.cli list [--split train|heldout] [--limit N]
      Lists mandates from the generated batch.

  python -m src.cli explain <mandate_id> [--split train|heldout]
      Runs the ENGINE on one mandate and prints its full, plain-English
      decision trail (audit/log.py's explain()) plus the final outcome —
      this is the "explain this decision" view: click a mandate, see why.

  python -m src.cli compare <mandate_id> [--split train|heldout]
      Runs EVERY strategy (B0-B3, engine) on the same mandate side by side —
      final status, rupees recovered, and compliance violations for each.
      This is the single view that makes the headline comparison concrete
      for one real record, not just an aggregate table.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from data.generate import read_jsonl
from eval import baselines
from src.audit.log import AuditLog
from src.guardrails import invariants
from src.orchestrator import run_mandate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data"


def _load(split: str):
    filename = "mandates_train.jsonl" if split == "train" else "mandates_heldout.jsonl"
    return read_jsonl(_DATA_DIR / filename)


def _find(records, mandate_id: str):
    for mandate, event in records:
        if mandate.mandate_id == mandate_id:
            return mandate, event
    return None, None


def cmd_list(args: argparse.Namespace) -> None:
    records = _load(args.split)
    print(f"{'mandate_id':30s} {'reason':32s} {'amount (Rs)':>12s} {'mcc':>6s} {'bank':>6s}")
    for mandate, event in records[: args.limit]:
        print(f"{mandate.mandate_id:30s} {event.reason.value:32s} {mandate.amount_paise/100:12,.2f} {mandate.mcc:>6d} {mandate.payer_bank_code:>6s}")
    print(f"\n({len(records)} total in the {args.split} split)")


def cmd_explain(args: argparse.Namespace) -> None:
    records = _load(args.split)
    mandate, event = _find(records, args.mandate_id)
    if mandate is None:
        print(f"No mandate {args.mandate_id!r} found in the {args.split} split.")
        raise SystemExit(1)

    audit = AuditLog()
    result = run_mandate(mandate=mandate, first_failure_event=event, audit=audit)

    print(audit.explain(mandate.mandate_id))
    print()
    print(f"Final status: {result.final_status}")
    print(f"Rupees recovered: {result.recovered_paise / 100:,.2f} of {mandate.amount_paise / 100:,.2f} at risk")
    print(f"Attempts made (excluding the pre-existing seed failure): {max(len(result.attempts) - 1, 0)}")
    print(f"Notifications sent: {len(result.notifications)}")

    report = invariants.run_all(
        attempts=result.attempts[1:], notifications=result.notifications,
        audit_entries=audit.all(), mandates_by_id={mandate.mandate_id: mandate},
    )
    print(f"Compliance violations: {report.count}")


def cmd_compare(args: argparse.Namespace) -> None:
    records = _load(args.split)
    mandate, event = _find(records, args.mandate_id)
    if mandate is None:
        print(f"No mandate {args.mandate_id!r} found in the {args.split} split.")
        raise SystemExit(1)

    print(f"Mandate {mandate.mandate_id} — reason={event.reason.value}, amount=Rs{mandate.amount_paise/100:,.2f}, mcc={mandate.mcc}, bank={mandate.payer_bank_code}")
    print(f"{'Strategy':20s} {'Status':12s} {'Recovered (Rs)':>16s} {'Attempts':>9s} {'Violations':>11s}")

    strategies = {
        "B0_no_recovery": lambda m: baselines.run_b0_no_recovery(mandate=m, first_failure_event=event),
        "B1_naive_retry": lambda m: baselines.run_b1_naive_retry(mandate=m, first_failure_event=event),
        "B2_fixed_schedule": lambda m: baselines.run_b2_fixed_schedule(mandate=m, first_failure_event=event),
        "B3_reason_aware": lambda m: run_mandate(mandate=m, first_failure_event=event, use_salary_cycle_heuristic=False, use_bank_health_heuristic=False),
        "engine": lambda m: run_mandate(mandate=m, first_failure_event=event),
    }
    for name, fn in strategies.items():
        m = mandate.model_copy(deep=True)
        r = fn(m)
        report = invariants.run_all(
            attempts=r.attempts[1:], notifications=r.notifications,
            audit_entries=[], mandates_by_id={m.mandate_id: m},
        )
        attempts_made = max(len(r.attempts) - 1, 0)
        print(f"{name:20s} {r.final_status:12s} {r.recovered_paise/100:16,.2f} {attempts_made:9d} {report.count:11d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="UPI AutoPay Mandate Recovery Engine — minimal demo interface.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List mandates from the generated batch.")
    p_list.add_argument("--split", choices=["train", "heldout"], default="train")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_explain = sub.add_parser("explain", help="Run the engine on one mandate and print its full decision trail.")
    p_explain.add_argument("mandate_id")
    p_explain.add_argument("--split", choices=["train", "heldout"], default="train")
    p_explain.set_defaults(func=cmd_explain)

    p_compare = sub.add_parser("compare", help="Run every strategy on one mandate, side by side.")
    p_compare.add_argument("mandate_id")
    p_compare.add_argument("--split", choices=["train", "heldout"], default="train")
    p_compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

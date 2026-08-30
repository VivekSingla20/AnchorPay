"""
src/cli.py — the minimal interface (Build Spec Part 5.1 stage 11 / Part 12
phase 11: "Minimal. Enough to run a demo and view the audit trail. Do not
spend more than 15% of total effort here.").

  python -m src.cli list [--split train|heldout] [--limit N]
      Lists mandates from the generated batch.

  python -m src.cli explain <mandate_id> [--split train|heldout] [--review-first]
      Runs the ENGINE on one mandate and prints its full, plain-English
      decision trail (audit/log.py's explain()) plus the final outcome —
      this is the "explain this decision" view: click a mandate, see why.
      --review-first holds the final execution for human approval instead
      of running it (Razorpay principle 1) — see `approve` below.

  python -m src.cli compare <mandate_id> [--split train|heldout]
      Runs EVERY strategy (B0-B3, engine) on the same mandate side by side —
      final status, rupees recovered, and compliance violations for each.

  python -m src.cli approve <mandate_id> [--split ...] [--confirm-irreversible]
      Re-runs a mandate that was held under --review-first. An irreversible
      action (an execution — money moves) refuses to proceed without
      --confirm-irreversible; a reversible one (a notification) does not
      need it. This is principle 1's "irreversible actions require double
      confirmation", made literal rather than decorative.

  python -m src.cli kill <mandate_id>
      One-tap kill switch (Razorpay principle 1): persists to
      results/killed_mandates.json. EVERY future run of list/explain/
      compare/approve/the eval harness refuses to schedule or execute
      anything further for this mandate, checked ahead of even opt-out.

  python -m src.cli revive <mandate_id>
      Reverses a kill — an explicit operator action, never automatic.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from data.generate import read_jsonl
from eval import baselines
from src.audit import kill_switch
from src.audit.log import AuditLog
from src.guardrails import invariants
from src.intervene import escalation_brief
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
    result = run_mandate(
        mandate=mandate, first_failure_event=event, audit=audit,
        kill_switch_ids=kill_switch.load_killed_mandate_ids(), review_first=args.review_first,
    )

    print(audit.explain(mandate.mandate_id))

    if result.pending_approval is not None:
        p = result.pending_approval
        print(f"\n[PENDING APPROVAL — {'IRREVERSIBLE' if p.irreversible else 'reversible'}] {p.description}")
        confirm_hint = " --confirm-irreversible" if p.irreversible else ""
        print(f"Run: python -m src.cli approve {mandate.mandate_id} --split {args.split}{confirm_hint}")
        return

    escalated_entry = next(
        (e for e in audit.all() if e.stage == "intervention_selector" and e.decision == "escalate_to_support"), None
    )
    if escalated_entry is not None:
        brief_text, actor = escalation_brief.generate(
            mandate_id=mandate.mandate_id, reason_value=event.reason.value,
            amount_rupees=mandate.amount_paise / 100, gate_rationale=escalated_entry.reason,
        )
        print(f"\nEscalation brief for support (actor: {actor}): {brief_text}")

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


def cmd_approve(args: argparse.Namespace) -> None:
    records = _load(args.split)
    mandate, event = _find(records, args.mandate_id)
    if mandate is None:
        print(f"No mandate {args.mandate_id!r} found in the {args.split} split.")
        raise SystemExit(1)

    audit = AuditLog()
    probe = run_mandate(
        mandate=mandate.model_copy(deep=True), first_failure_event=event,
        kill_switch_ids=kill_switch.load_killed_mandate_ids(), review_first=True,
    )
    if probe.pending_approval is None:
        print("Nothing is pending approval for this mandate right now — it either already finished or was never held.")
        return
    if probe.pending_approval.irreversible and not args.confirm_irreversible:
        print(f"REFUSED: {probe.pending_approval.description} is IRREVERSIBLE (money moves). "
              f"Re-run with --confirm-irreversible to approve it.")
        raise SystemExit(1)

    result = run_mandate(
        mandate=mandate, first_failure_event=event, audit=audit,
        kill_switch_ids=kill_switch.load_killed_mandate_ids(), review_first=False,
    )
    print(audit.explain(mandate.mandate_id))
    print(f"\nApproved and executed. Final status: {result.final_status}, recovered Rs {result.recovered_paise/100:,.2f}")


def cmd_kill(args: argparse.Namespace) -> None:
    kill_switch.kill_mandate(args.mandate_id)
    print(f"Killed {args.mandate_id}. No future run will schedule or execute anything further for it.")


def cmd_revive(args: argparse.Namespace) -> None:
    kill_switch.revive_mandate(args.mandate_id)
    print(f"Revived {args.mandate_id}. Normal processing resumes on the next run.")


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
    p_explain.add_argument("--review-first", action="store_true", help="Hold the final execution for human approval instead of running it.")
    p_explain.set_defaults(func=cmd_explain)

    p_compare = sub.add_parser("compare", help="Run every strategy on one mandate, side by side.")
    p_compare.add_argument("mandate_id")
    p_compare.add_argument("--split", choices=["train", "heldout"], default="train")
    p_compare.set_defaults(func=cmd_compare)

    p_approve = sub.add_parser("approve", help="Approve a mandate held under --review-first.")
    p_approve.add_argument("mandate_id")
    p_approve.add_argument("--split", choices=["train", "heldout"], default="train")
    p_approve.add_argument("--confirm-irreversible", action="store_true", help="Required to approve an irreversible (money-moving) action.")
    p_approve.set_defaults(func=cmd_approve)

    p_kill = sub.add_parser("kill", help="One-tap kill switch: stop all future action for this mandate.")
    p_kill.add_argument("mandate_id")
    p_kill.set_defaults(func=cmd_kill)

    p_revive = sub.add_parser("revive", help="Reverse a kill.")
    p_revive.add_argument("mandate_id")
    p_revive.set_defaults(func=cmd_revive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

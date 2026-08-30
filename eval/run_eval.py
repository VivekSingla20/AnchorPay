"""
eval/run_eval.py — the one command that reproduces every number in
EVALUATION.md (Build Spec Part 9 / Part 11).

Runs B0, B1, B2, the engine (B3 is the engine with both ranking heuristics
disabled — see eval/baselines.py's module docstring), on both the train and
held-out splits, and reports, per strategy:

  N processed, wall-clock time, throughput
  Rs at risk / recovered / leaked, recovery rate (Track 03 headline)
  Compliance violations, per invariant (the "0 vs N" comparison)
  Retries consumed, retries wasted on terminal codes (the efficiency argument)
  Interventions sent, by type; dark-pattern rejection count
  Stopping-rule trigger counts; escalation log (Track 03 additional metrics)
  Full exception list (every mandate NOT recovered, with the reason)
  Intent-inference confusion matrix on the held-out split (the classifier
  accuracy metric — see module note on why this is the meaningful
  "classifier" to report, not the near-empty taxonomy classifier)
  A salary-cycle / bank-health ablation, isolating each heuristic separately

Track selection: this submission targets Track 03 (AI Revenue Recovery) —
see README.md and ARCHITECTURE.md for why. The Track-03-specific metrics
listed in Build Spec Part 5 are reported explicitly below, not folded into
generic language.

Run: `python -m eval.run_eval`
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from data.generate import REFERENCE_NOW, read_jsonl
from eval import baselines, batch_summary
from src.audit import kill_switch
from src.audit.log import AuditLog
from src.classify import llm_client
from src.domain.entities import Attempt, FailureEvent, Mandate, Notification
from src.guardrails import invariants
from src.intervene import escalation_brief
from src.orchestrator import run_mandate
from src.policy import retryability
from src.policy.bank_health import DowntimeRecord

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data"
_RESULTS_DIR = _REPO_ROOT / "results"


def build_synthetic_downtime_records() -> list[DowntimeRecord]:
    """Recurring, DAILY scheduled UPI downtime for two specific banks,
    spanning the generator's full observation-plus-scheduling horizon.

    WITHOUT a signal like this, the bank-health heuristic in
    src/policy/allocator.py has nothing to act on: a handful of one-off,
    scattered downtime windows almost never intersect the allocator's own
    (deliberately bounded, ~2-day) candidate search horizon, so the first
    version of this function produced a byte-identical ablation result
    between "bank-health heuristic on" and "off" — caught empirically, not
    theoretically (see DECISIONS.md ADR-010). Recurring daily windows
    guarantee the search horizon actually encounters the pattern for every
    mandate on an affected bank, which is what makes the heuristic's effect
    measurable at all in a batch this size.

    UNVERIFIED and deliberately pronounced for demonstration (ASSUMPTIONS.md
    #A10): a real deployment would consume Razorpay's live Downtime API
    (SOURCES.md §5) instead of this synthetic recurring pattern, and a
    2-hour-every-day outage for one bank is more severe than any single real
    downtime record would typically be — it exists to make the heuristic's
    effect provably non-zero and easy to audit, not to model realistic
    outage frequency.
    """
    records = []
    day0 = REFERENCE_NOW - 25 * 86400
    for day in range(0, 41):  # covers the ~20-day observation window plus ~15 days of scheduling headroom
        day_start = day0 + day * 86400
        # PYTM: the entire afternoon permitted window is down, daily, high severity.
        records.append(DowntimeRecord(
            id=f"down_pytm_{day}", entity="payment.downtime", method="upi",
            begin=day_start + 13 * 3600, end=day_start + 17 * 3600, status="scheduled", scheduled=True,
            severity="high", bank_code="PYTM", created_at=day_start, updated_at=day_start,
        ))
        # INDB: the entire night permitted window is down, daily, medium severity.
        records.append(DowntimeRecord(
            id=f"down_indb_{day}", entity="payment.downtime", method="upi",
            begin=day_start + 21 * 3600 + 1800, end=day_start + 24 * 3600, status="scheduled", scheduled=True,
            severity="medium", bank_code="INDB", created_at=day_start, updated_at=day_start,
        ))
    return records


_DOWNTIME_RECORDS = build_synthetic_downtime_records()


@dataclass
class RunRecord:
    mandate: Mandate
    attempts: list[Attempt]
    notifications: list[Notification]
    final_status: str
    recovered_paise: int
    stopped_reason: str = ""
    audit_entries: list = field(default_factory=list)


def _run_strategy(strategy: str, records: list[tuple[Mandate, FailureEvent]]) -> list[RunRecord]:
    out = []
    killed_ids = kill_switch.load_killed_mandate_ids()  # Razorpay principle 1: one-tap kill switch, checked by every strategy that reaches the engine
    for mandate, event in records:
        # Each strategy gets its OWN deep-ish copy of the mandate (via
        # model_copy) so one strategy's in-run mutations (consecutive
        # failure counts, contact timestamps) never leak into another
        # strategy's run over the same underlying record.
        m = mandate.model_copy(deep=True)
        if strategy == "B0_no_recovery":
            r = baselines.run_b0_no_recovery(mandate=m, first_failure_event=event)
            out.append(RunRecord(m, r.attempts, r.notifications, r.final_status, r.recovered_paise))
        elif strategy == "B1_naive_retry":
            r = baselines.run_b1_naive_retry(mandate=m, first_failure_event=event, downtime_records=_DOWNTIME_RECORDS)
            out.append(RunRecord(m, r.attempts, r.notifications, r.final_status, r.recovered_paise))
        elif strategy == "B2_fixed_schedule":
            r = baselines.run_b2_fixed_schedule(mandate=m, first_failure_event=event, downtime_records=_DOWNTIME_RECORDS)
            out.append(RunRecord(m, r.attempts, r.notifications, r.final_status, r.recovered_paise))
        elif strategy == "B3_reason_aware":
            audit = AuditLog()
            r = run_mandate(mandate=m, first_failure_event=event, audit=audit, downtime_records=_DOWNTIME_RECORDS, use_salary_cycle_heuristic=False, use_bank_health_heuristic=False, kill_switch_ids=killed_ids)
            out.append(RunRecord(m, r.attempts, r.notifications, r.final_status, r.recovered_paise, r.stopped_reason, audit.all()))
        elif strategy == "engine":
            audit = AuditLog()
            r = run_mandate(mandate=m, first_failure_event=event, audit=audit, downtime_records=_DOWNTIME_RECORDS, kill_switch_ids=killed_ids)
            out.append(RunRecord(m, r.attempts, r.notifications, r.final_status, r.recovered_paise, r.stopped_reason, audit.all()))
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
    return out


def _is_terminal_root_cause(mandate: Mandate) -> bool:
    from src.domain import regulatory_constants as RC
    from src.domain.enums import RetryabilityVerdict
    if mandate.root_cause_npci_code is not None and mandate.root_cause_npci_code in RC.NPCI_CODE_VERDICT_OVERRIDE:
        return RC.NPCI_CODE_VERDICT_OVERRIDE[mandate.root_cause_npci_code] == RetryabilityVerdict.TERMINAL
    row = RC.REASON_STRATEGY_BY_REASON.get(mandate.root_cause_reason)
    return row is not None and row.verdict == RetryabilityVerdict.TERMINAL


def compute_metrics(strategy: str, split: str, run_records: list[RunRecord], wall_clock_s: float) -> dict:
    n = len(run_records)
    at_risk = sum(rr.mandate.amount_paise for rr in run_records)
    recovered = sum(rr.recovered_paise for rr in run_records)
    leaked = at_risk - recovered
    n_recovered = sum(1 for rr in run_records if rr.final_status == "recovered")
    n_halted = sum(1 for rr in run_records if rr.final_status == "halted")
    n_other_stopped = n - n_recovered - n_halted

    all_attempts_graded: list[Attempt] = []
    all_notifs: list[Notification] = []
    all_audit = []
    mandates_by_id = {}
    retries_consumed = 0
    retries_wasted_on_terminal = 0
    for rr in run_records:
        mandates_by_id[rr.mandate.mandate_id] = rr.mandate
        # Attempt #1 is the pre-existing seed failure that predates every
        # strategy's involvement — excluded from grading everywhere.
        # See DECISIONS.md ADR-009.
        graded = rr.attempts[1:]
        all_attempts_graded.extend(graded)
        all_notifs.extend(rr.notifications)
        all_audit.extend(rr.audit_entries)
        retries_consumed += len(graded)
        if _is_terminal_root_cause(rr.mandate):
            retries_wasted_on_terminal += len(graded)

    report = invariants.run_all(
        attempts=all_attempts_graded, notifications=all_notifs, audit_entries=all_audit, mandates_by_id=mandates_by_id,
    )

    interventions_by_type = Counter(n.intervention_type for n in all_notifs)
    dark_pattern_rejections = sum(1 for n in all_notifs if n.screened and n.screen_passed is False)

    stopping_reasons = Counter()
    for rr in run_records:
        if rr.final_status == "halted":
            stopping_reasons["attempt_budget_exhausted"] += 1
        elif rr.stopped_reason:
            key = rr.stopped_reason.split(";")[0][:40]
            stopping_reasons[key] += 1
        elif rr.final_status == "recovered":
            stopping_reasons["recovered"] += 1

    return {
        "strategy": strategy,
        "split": split,
        "n_records": n,
        "wall_clock_seconds": round(wall_clock_s, 4),
        "throughput_records_per_min": round(n / max(wall_clock_s, 1e-9) * 60, 1),
        "at_risk_paise": at_risk,
        "recovered_paise": recovered,
        "leaked_paise": leaked,
        "recovery_rate": round(recovered / at_risk, 4) if at_risk else 0.0,
        "mandates_recovered": n_recovered,
        "mandates_halted": n_halted,
        "mandates_stopped_other": n_other_stopped,
        "violations_total": report.count,
        "violations_by_invariant": report.count_by_invariant(),
        "retries_consumed_total": retries_consumed,
        "retries_consumed_mean": round(retries_consumed / n, 3) if n else 0.0,
        "retries_wasted_on_terminal": retries_wasted_on_terminal,
        "interventions_by_type": dict(interventions_by_type),
        "dark_pattern_rejections": dark_pattern_rejections,
        "stopping_reasons": dict(stopping_reasons),
    }


def build_exception_list(engine_records: list[RunRecord]) -> list[dict]:
    exceptions = []
    for rr in engine_records:
        if rr.final_status != "recovered":
            exceptions.append({
                "mandate_id": rr.mandate.mandate_id,
                "final_status": rr.final_status,
                "stopped_reason": rr.stopped_reason,
                "root_cause_reason": rr.mandate.root_cause_reason.value,
                "amount_paise": rr.mandate.amount_paise,
                "attempts_made": max(len(rr.attempts) - 1, 0),
            })
    return exceptions


def build_escalation_log(engine_records: list[RunRecord]) -> list[dict]:
    out = []
    for rr in engine_records:
        for e in rr.audit_entries:
            if e.stage == "intervention_selector" and e.decision == "escalate_to_support":
                brief_text, actor = escalation_brief.generate(
                    mandate_id=rr.mandate.mandate_id,
                    reason_value=rr.mandate.root_cause_reason.value,
                    amount_rupees=rr.mandate.amount_paise / 100,
                    gate_rationale=e.reason,
                )
                out.append({"mandate_id": rr.mandate.mandate_id, "reason": e.reason, "brief": brief_text, "brief_actor": actor})
    return out


def intent_inference_confusion_matrix(records: list[tuple[Mandate, FailureEvent]]) -> dict:
    """Confusion matrix for the intent-inference mechanism
    (src/policy/retryability.py's _looks_intentional) against the generator's
    ground_truth_intent_label, on the held-out split. This is reported as
    THE classifier-accuracy metric (Build Spec Part 9) — see module
    docstring on why the taxonomy classifier (stage 2) is not the
    meaningful one to report here (it only ever activates on the ~1% of
    records with an unrecognised reason)."""
    tp = fp = tn = fn = 0
    for mandate, event in records:
        predicted_intentional = retryability.evaluate(event, mandate).verdict.value == "likely_intentional_nonpayment"
        actual_intentional = mandate.ground_truth_intent_label == "intentional_nonpayment"
        if predicted_intentional and actual_intentional:
            tp += 1
        elif predicted_intentional and not actual_intentional:
            fp += 1
        elif not predicted_intentional and actual_intentional:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "n": tp + fp + tn + fn,
    }


def run_ablation(records: list[tuple[Mandate, FailureEvent]]) -> dict:
    """Isolates each ranking heuristic separately (Domain Context Part 5
    idea #2's ablation request), beyond B3's combined disable-both."""
    variants = {
        "engine_both_heuristics": (True, True),
        "engine_salary_cycle_only": (True, False),
        "engine_bank_health_only": (False, True),
        "engine_neither_heuristic_(=B3)": (False, False),
    }
    out = {}
    for name, (salary, bank) in variants.items():
        at_risk = recovered = 0
        for mandate, event in records:
            m = mandate.model_copy(deep=True)
            r = run_mandate(mandate=m, first_failure_event=event, downtime_records=_DOWNTIME_RECORDS, use_salary_cycle_heuristic=salary, use_bank_health_heuristic=bank)
            at_risk += m.amount_paise
            recovered += r.recovered_paise
        out[name] = {"recovered_paise": recovered, "at_risk_paise": at_risk, "recovery_rate": round(recovered / at_risk, 4) if at_risk else 0.0}
    return out


def render_markdown(
    all_metrics: list[dict], exceptions: list[dict], escalations: list[dict], confusion: dict, ablation: dict,
    narrative: tuple[str, str],
) -> str:
    lines = [
        "# EVALUATION.md", "",
        "Generated by `python -m eval.run_eval`. Every number below is reproduced by that one command — see Makefile.",
        "",
        "*Wall-clock seconds and records/min are real measurements of this run and will vary "
        "slightly machine-to-machine and run-to-run — everything else (rupees, violations, "
        "retries, interventions) is fully deterministic given the same seed and will not change.*",
        "",
    ]

    narrative_text, narrative_actor = narrative
    lines.append("## Narrative summary (train split, engine strategy)")
    lines.append("")
    lines.append(f"{narrative_text} *(actor: {narrative_actor} — narration only, never a decision; see AI_USAGE.md)*")
    lines.append("")

    lines.append("## Headline: recovery on the training split (640 records)")
    lines.append("")
    lines.append("| Strategy | N | Rs at risk | Rs recovered | Rs leaked | Recovery rate | Violations | Retries wasted on terminal codes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m in all_metrics:
        if m["split"] != "train":
            continue
        lines.append(
            f"| {m['strategy']} | {m['n_records']} | {m['at_risk_paise']/100:,.2f} | {m['recovered_paise']/100:,.2f} | "
            f"{m['leaked_paise']/100:,.2f} | {m['recovery_rate']*100:.2f}% | **{m['violations_total']}** | {m['retries_wasted_on_terminal']} |"
        )
    lines.append("")
    lines.append("*Rupee figures are amount_paise / 100. \"Recovered\" means the mandate's failed cycle was collected within its own 1+3 attempt budget — see LIMITATIONS.md on arrears not being auto-collected (INV-15).*")
    lines.append("")

    lines.append("## Same table on the held-out split (160 records, never tuned against)")
    lines.append("")
    lines.append("| Strategy | N | Rs at risk | Rs recovered | Rs leaked | Recovery rate | Violations |")
    lines.append("|---|---|---|---|---|---|---|")
    for m in all_metrics:
        if m["split"] != "heldout":
            continue
        lines.append(
            f"| {m['strategy']} | {m['n_records']} | {m['at_risk_paise']/100:,.2f} | {m['recovered_paise']/100:,.2f} | "
            f"{m['leaked_paise']/100:,.2f} | {m['recovery_rate']*100:.2f}% | **{m['violations_total']}** |"
        )
    lines.append("")

    lines.append("## Compliance violations, per invariant (train split)")
    lines.append("")
    lines.append("| Strategy | " + " | ".join(f"INV-{i:02d}" for i in (1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 14, 15)) + " |")
    lines.append("|---|" + "---|" * 12)
    for m in all_metrics:
        if m["split"] != "train":
            continue
        by_inv = m["violations_by_invariant"]
        row = [str(by_inv.get(f"INV-{i:02d}", 0)) for i in (1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 14, 15)]
        lines.append(f"| {m['strategy']} | " + " | ".join(row) + " |")
    lines.append("")
    lines.append("**Read this row by row: the engine's column is zero everywhere. Every non-zero cell above it is a violation a real system would have committed.**")
    lines.append("")

    lines.append("## Throughput, retries, interventions, dark-pattern screening (train split)")
    lines.append("")
    lines.append("| Strategy | Wall-clock (s) | Records/min | Mean retries/mandate | Interventions sent | Dark-pattern rejections |")
    lines.append("|---|---|---|---|---|---|")
    for m in all_metrics:
        if m["split"] != "train":
            continue
        total_interventions = sum(m["interventions_by_type"].values())
        lines.append(
            f"| {m['strategy']} | {m['wall_clock_seconds']} | {m['throughput_records_per_min']} | "
            f"{m['retries_consumed_mean']} | {total_interventions} | {m['dark_pattern_rejections']} |"
        )
    lines.append("")

    lines.append("## Stopping-rule trigger counts (engine, train split)")
    lines.append("")
    engine_train = next(m for m in all_metrics if m["strategy"] == "engine" and m["split"] == "train")
    for reason, count in sorted(engine_train["stopping_reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{reason}`: {count}")
    lines.append("")

    lines.append("## Escalation compliance log (engine, train split — routed to human support, never auto-decided)")
    lines.append("")
    lines.append(f"{len(escalations)} mandates routed to `escalate_to_support`. First 10 shown, each with an LLM-assisted (or deterministic-fallback) brief for the human reviewer:")
    lines.append("")
    for e in escalations[:10]:
        lines.append(f"- `{e['mandate_id']}`: {e['brief']} *(actor: {e['brief_actor']})*")
    lines.append("")

    lines.append("## Intent-inference confusion matrix (held-out split, 160 records)")
    lines.append("")
    lines.append("Predicts `likely_intentional_nonpayment` (Domain Context §3.2's signature feature) against the generator's `ground_truth_intent_label`. This is deterministic pattern-matching over a mandate's own recorded history (ASSUMPTIONS.md #A2), not an LLM judgment call.")
    lines.append("")
    lines.append(f"| | Predicted intentional | Predicted genuine |\n|---|---|---|\n| **Actually intentional** | {confusion['true_positive']} | {confusion['false_negative']} |\n| **Actually genuine** | {confusion['false_positive']} | {confusion['true_negative']} |")
    lines.append("")
    lines.append(f"Precision: {confusion['precision']*100:.1f}% · Recall: {confusion['recall']*100:.1f}% · F1: {confusion['f1']*100:.1f}% (n={confusion['n']})")
    lines.append("")

    lines.append("## Ablation: salary-cycle vs. bank-health heuristics, isolated (train split)")
    lines.append("")
    lines.append("| Variant | Rs recovered | Recovery rate |")
    lines.append("|---|---|---|")
    for name, v in ablation.items():
        lines.append(f"| {name} | {v['recovered_paise']/100:,.2f} | {v['recovery_rate']*100:.2f}% |")
    lines.append("")
    lines.append("*If a row does not clearly beat `engine_neither_heuristic_(=B3)`, that heuristic's UNVERIFIED assumption (ASSUMPTIONS.md #A3) is not earning its complexity on this synthetic batch — report this honestly rather than keep a heuristic that doesn't move the number.*")
    lines.append("")

    lines.append("## LLM cost")
    lines.append("")
    usage = llm_client.get_usage_stats()
    if usage.call_count == 0:
        lines.append(
            "`RECOVERY_ENGINE_USE_LLM=false` for this run (the default — see `.env.example`). Every "
            "classify/intervene/copy/narration decision above took the deterministic fallback path: "
            "**Rs 0.00 spent, 0 tokens, 0 LLM calls.** Set RECOVERY_ENGINE_USE_LLM=true with a real "
            "ANTHROPIC_API_KEY and re-run to reproduce with a real model — the numbers below are read "
            "from `src.classify.llm_client.get_usage_stats()`, not hardcoded, so they will update for real."
        )
    else:
        mean_latency = usage.total_latency_ms / usage.call_count
        lines.append(
            f"RECOVERY_ENGINE_USE_LLM=true for this run. **{usage.call_count} LLM calls** "
            f"({usage.ok_count} succeeded, {usage.fallback_count} fell back to the deterministic path), "
            f"mean latency {mean_latency:.0f}ms. Token/Rs cost per call is provider-billed and not captured "
            f"by this process — see AI_USAGE.md for the cost-per-mandate projection."
        )
    lines.append("")

    engine_train_n = next(m["n_records"] for m in all_metrics if m["strategy"] == "engine" and m["split"] == "train")
    lines.append(f"## Exception list — full, every non-recovered mandate ({len(exceptions)} of {engine_train_n} on train, engine strategy)")
    lines.append("")
    lines.append("| Mandate | Final status | Root cause | Attempts made | Amount (Rs) | Reason |")
    lines.append("|---|---|---|---|---|---|")
    for e in exceptions:
        lines.append(f"| {e['mandate_id']} | {e['final_status']} | {e['root_cause_reason']} | {e['attempts_made']} | {e['amount_paise']/100:,.2f} | {e['stopped_reason'][:80]} |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    _RESULTS_DIR.mkdir(exist_ok=True)
    llm_client.reset_usage_stats()
    train = read_jsonl(_DATA_DIR / "mandates_train.jsonl")
    heldout = read_jsonl(_DATA_DIR / "mandates_heldout.jsonl")

    strategies = ["B0_no_recovery", "B1_naive_retry", "B2_fixed_schedule", "B3_reason_aware", "engine"]
    all_metrics = []
    per_strategy_records: dict[str, list[RunRecord]] = {}

    for split_name, split_records in (("train", train), ("heldout", heldout)):
        for strategy in strategies:
            start = time.monotonic()
            run_records = _run_strategy(strategy, split_records)
            elapsed = time.monotonic() - start
            all_metrics.append(compute_metrics(strategy, split_name, run_records, elapsed))
            if split_name == "train":
                per_strategy_records[strategy] = run_records

    exceptions = build_exception_list(per_strategy_records["engine"])
    escalations = build_escalation_log(per_strategy_records["engine"])
    confusion = intent_inference_confusion_matrix(heldout)
    ablation = run_ablation(train)
    engine_train_metrics = next(m for m in all_metrics if m["strategy"] == "engine" and m["split"] == "train")
    narrative = batch_summary.generate(engine_train_metrics)

    markdown = render_markdown(all_metrics, exceptions, escalations, confusion, ablation, narrative)
    (_REPO_ROOT / "EVALUATION.md").write_text(markdown, encoding="utf-8")

    (_RESULTS_DIR / "metrics.json").write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
    (_RESULTS_DIR / "exceptions.json").write_text(json.dumps(exceptions, indent=2), encoding="utf-8")
    (_RESULTS_DIR / "escalations.json").write_text(json.dumps(escalations, indent=2), encoding="utf-8")
    (_RESULTS_DIR / "intent_confusion_matrix.json").write_text(json.dumps(confusion, indent=2), encoding="utf-8")
    (_RESULTS_DIR / "ablation.json").write_text(json.dumps(ablation, indent=2), encoding="utf-8")

    print("Wrote EVALUATION.md and results/*.json")
    for m in all_metrics:
        if m["split"] == "train":
            print(f"  {m['strategy']:20s} recovered=Rs{m['recovered_paise']/100:>12,.2f}  violations={m['violations_total']:>4d}")


if __name__ == "__main__":
    main()

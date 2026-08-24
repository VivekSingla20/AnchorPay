"""
data/generate.py — synthetic mandate book generator.

Produces a seeded, reproducible batch of failed-UPI-AutoPay-mandate records:
a Mandate (nested Subscription + Customer) paired with the FailureEvent that
triggers this engine's pipeline. Writes an 80/20 train/held-out split to
JSONL, mirroring Razorpay's real field names (Build Spec §2.4/§2.5).

EVERY distributional choice below is a modelling assumption, not an
empirical fact, cross-referenced to its ASSUMPTIONS.md entry. The only REAL
inputs are: the failure-reason taxonomy (closed set, Build Spec §2.5), the
real NPCI bank codes/names in data/npci/bank_health_reference.csv
(SOURCES.md §6), and the real MCC codes and their approximate volume
ranking (Domain Context §2.3).

Run: `python -m data.generate --seed 42 --count 800`
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from src.domain import timeutils
from src.domain.entities import Customer, FailureEvent, Mandate, Subscription
from src.domain.enums import ConsentState, FailureReason, FailureSource, NpciResponseCode, SubscriptionStatus

IST = timezone(timedelta(hours=5, minutes=30))
# Fixed reference point so generation is reproducible regardless of the real
# wall-clock date `make eval` happens to run on — deliberately never
# `time.time()`. Chosen to match this project's documented compile date.
REFERENCE_NOW = int(datetime(2026, 8, 24, 9, 0, 0, tzinfo=IST).timestamp())

_REPO_ROOT = Path(__file__).resolve().parents[1]

# --- MCC distribution (Domain Context §2.3 — real, ranked MCCs) -----------
# UNVERIFIED weighting (ASSUMPTIONS.md #A9): the CODES are real and ranked;
# the exact PROPORTIONS assigned within this synthetic book are this
# engine's own choice, picked to (a) plausibly reflect recurring-billing use
# cases and (b) guarantee both AFA-threshold branches (Rs 15,000 general,
# Rs 1,00,000 enhanced) and both notification carve-outs (FASTag/NCMC) are
# exercised in every generated batch.
_MCC_WEIGHTS: dict[int, float] = {
    4900: 0.16,  # utilities
    4814: 0.14,  # telecom
    5816: 0.16,  # digital goods / games (subscriptions)
    6211: 0.10,  # securities brokers/dealers — enhanced AFA ceiling
    7322: 0.06,  # debt collection agencies
    5912: 0.05,  # drug stores / pharmacies
    5411: 0.05,  # groceries / supermarkets
    5462: 0.02,  # bakeries
    4784: 0.10,  # NETC FASTag — notification carve-out
    7412: 0.06,  # RuPay NCMC — notification carve-out
    5311: 0.04,  # department stores
    5262: 0.06,  # online marketplaces
}

# --- Failure reason distribution -------------------------------------------
# UNVERIFIED weighting (ASSUMPTIONS.md #A9): insufficient_funds dominates,
# consistent with the ~74% average business-decline rate and the 20M/month
# revocation figure (Domain Context §2.1), both attributed primarily to
# insufficient balance. Remaining mass is spread to exercise every branch of
# the reason -> strategy table at least once per batch, including a 1% slice
# of FailureReason.UNKNOWN for Failure Injection #5 realism.
_REASON_WEIGHTS: dict[FailureReason, float] = {
    FailureReason.INSUFFICIENT_FUNDS: 0.52,
    FailureReason.BANK_TECHNICAL_ERROR: 0.12,
    FailureReason.GATEWAY_TECHNICAL_ERROR: 0.06,
    FailureReason.PAYMENT_DECLINED: 0.10,
    FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED: 0.05,
    FailureReason.PAYMENT_TIMED_OUT: 0.04,
    FailureReason.INVALID_VPA: 0.04,
    FailureReason.VPA_RESOLUTION_FAILED: 0.02,
    FailureReason.CREDIT_FAILED: 0.02,
    FailureReason.PAYMENT_CANCELLED: 0.02,
    FailureReason.UNKNOWN: 0.01,
}

# Weighting note (ASSUMPTIONS.md #A9): Axis Bank and Yes Bank are named as
# the top PSP banks by volume (Domain Context §2.2) — weighted highest here.
_BANK_WEIGHTS: dict[str, float] = {
    "AXB": 0.14, "YES": 0.12, "YBS": 0.06, "SBI": 0.12, "HDF": 0.10,
    "ICIC": 0.10, "KKBK": 0.06, "BOB": 0.06, "PNB": 0.05, "UOB": 0.04,
    "CNB": 0.04, "IDFB": 0.03, "INDB": 0.03, "FDRL": 0.02, "PYTM": 0.02, "YOM": 0.01,
}


def _weighted_choice(rng: np.random.Generator, weights: dict):
    keys = list(weights.keys())
    probs = np.array(list(weights.values()), dtype=float)
    probs = probs / probs.sum()
    idx = rng.choice(len(keys), p=probs)
    return keys[idx]


def _sample_amount_paise(rng: np.random.Generator) -> int:
    bucket = rng.choice(["small", "medium", "large"], p=[0.55, 0.30, 0.15])
    if bucket == "small":
        rupees = rng.uniform(99, 2000)
    elif bucket == "medium":
        rupees = rng.uniform(3000, 25000)  # straddles the Rs 15,000 general AFA threshold
    else:
        rupees = rng.uniform(40000, 150000)  # straddles the Rs 1,00,000 enhanced AFA threshold
    return int(round(rupees * 100))


def _npci_code_for(reason: FailureReason, rng: np.random.Generator) -> Optional[NpciResponseCode]:
    if reason == FailureReason.INSUFFICIENT_FUNDS:
        return NpciResponseCode.Z9 if rng.random() < 0.8 else None
    if reason == FailureReason.BANK_TECHNICAL_ERROR:
        return NpciResponseCode.U28 if rng.random() < 0.5 else NpciResponseCode.U30
    if reason == FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED:
        return NpciResponseCode.U69 if rng.random() < 0.7 else None
    if reason == FailureReason.PAYMENT_DECLINED:
        draw = rng.random()
        if draw < 0.12:
            return NpciResponseCode.Z8  # terminal — structural per-transaction ceiling
        if draw < 0.22:
            return NpciResponseCode.Z7  # velocity limit — retryable with spacing
        return None
    return None


def _sample_intent_profile(rng: np.random.Generator, reason: FailureReason, amount_paise: int) -> tuple[int, Optional[int], str]:
    """Returns (consecutive_same_reason_failures, account_balance_paise_hint,
    ground_truth_intent_label). ~12% of insufficient_funds mandates are
    generated as the TechnoFino 'empty account as a cancel button' pattern
    (Domain Context §3.2) — UNVERIFIED proportion, ASSUMPTIONS.md #A2."""
    if reason == FailureReason.INSUFFICIENT_FUNDS and rng.random() < 0.12:
        consecutive = int(rng.integers(3, 7))
        balance_hint = int(amount_paise * rng.uniform(0.0, 0.05))
        return consecutive, balance_hint, "intentional_nonpayment"
    consecutive = int(rng.integers(0, 3))
    balance_hint = int(amount_paise * rng.uniform(0.05, 1.2)) if rng.random() < 0.5 else None
    return consecutive, balance_hint, "genuine_failure"


_SOURCE_FOR_REASON: dict[FailureReason, FailureSource] = {
    FailureReason.INSUFFICIENT_FUNDS: FailureSource.CUSTOMER,
    FailureReason.BANK_TECHNICAL_ERROR: FailureSource.BANK,
    FailureReason.GATEWAY_TECHNICAL_ERROR: FailureSource.GATEWAY,
    FailureReason.CREDIT_FAILED: FailureSource.RAZORPAY,
    FailureReason.INVALID_VPA: FailureSource.CUSTOMER,
    FailureReason.VPA_RESOLUTION_FAILED: FailureSource.RAZORPAY,
    FailureReason.PAYMENT_DECLINED: FailureSource.BANK,
    FailureReason.PAYMENT_CANCELLED: FailureSource.CUSTOMER,
    FailureReason.PAYMENT_TIMED_OUT: FailureSource.CUSTOMER,
    FailureReason.PAYMENT_COLLECT_REQUEST_EXPIRED: FailureSource.CUSTOMER,
    FailureReason.UNKNOWN: FailureSource.RAZORPAY,
}

_UNKNOWN_RAW_TEXTS = (
    "issuer_unavailable_retry_later",
    "risk_block_temp",
    "customer_device_offline",
    "unspecified_gateway_state",
)


def _det_id(rng: np.random.Generator, prefix: str) -> str:
    """A deterministic id drawn from the SEEDED generator, in the same
    `prefix_<14 hex chars>` shape as entities.py's own `_new_id`. Every
    entity's default id factory calls `uuid.uuid4()`, which reads OS entropy
    and is NOT reproducible — relying on those defaults here silently broke
    `--seed` reproducibility (same content, different ids every run), caught
    by tests/test_generate.py. This is the fix: the generator controls every
    id it hands out, explicitly, instead of accepting entity defaults."""
    return f"{prefix}_{rng.bytes(7).hex()}"


def generate_one(rng: np.random.Generator, index: int) -> tuple[Mandate, FailureEvent]:
    mcc = int(_weighted_choice(rng, _MCC_WEIGHTS))
    amount_paise = _sample_amount_paise(rng)
    reason = _weighted_choice(rng, _REASON_WEIGHTS)
    npci_code = _npci_code_for(reason, rng)
    bank_code = str(_weighted_choice(rng, _BANK_WEIGHTS))
    consecutive, balance_hint, intent_label = _sample_intent_profile(rng, reason, amount_paise)

    billing_cycle_position = int(rng.integers(1, 25))
    arrears_paise = int(amount_paise * rng.uniform(0.5, 2.0)) if rng.random() < 0.20 else 0

    # Spread failures over the last ~20 days AND across the full 24h clock —
    # a fixed same-time-of-day generator would make every peak/permitted-
    # window scenario identical across the whole batch, which is both
    # unrealistic and a poor test of window-aware scheduling.
    day_offset_seconds = int(rng.integers(0, 20)) * 86400
    seconds_into_day = int(rng.integers(0, 86400))
    day_start_ist = timeutils.start_of_ist_day(REFERENCE_NOW - day_offset_seconds)
    occurred_at = day_start_ist + seconds_into_day
    current_start = occurred_at - billing_cycle_position * 30 * 86400
    created_at = current_start - 5 * 86400

    opted_out = rng.random() < 0.08
    opted_out_at = occurred_at - int(rng.integers(1, 30)) * 86400 if opted_out else None

    customer = Customer(
        id=_det_id(rng, "cust"),
        consent_state=ConsentState.OPTED_OUT if opted_out else ConsentState.GRANTED,
        opted_out_at=opted_out_at,
    )
    subscription = Subscription(
        id=_det_id(rng, "sub"),
        plan_id=_det_id(rng, "plan"),
        customer_id=customer.id,
        status=SubscriptionStatus.PENDING,  # this mandate has an active failure — Razorpay moves active->pending on the first unsuccessful auto-charge
        current_start=current_start,
        current_end=current_start + 30 * 86400,
        charge_at=occurred_at,
        start_at=created_at,
        created_at=created_at,
        total_count=24,
        paid_count=max(billing_cycle_position - 1, 0),
        remaining_count=max(24 - billing_cycle_position, 0),
    )
    mandate = Mandate(
        mandate_id=_det_id(rng, "mandate"),
        subscription=subscription,
        customer=customer,
        amount_paise=amount_paise,
        mcc=mcc,
        payer_bank_code=bank_code,
        billing_cycle_position=billing_cycle_position,
        arrears_paise=arrears_paise,
        consecutive_same_reason_failures=consecutive,
        total_failures_lifetime=consecutive,
        account_balance_paise_hint=balance_hint,
        ground_truth_intent_label=intent_label,
        root_cause_reason=reason,
        root_cause_npci_code=npci_code,
    )

    raw_reason_text = None
    if reason == FailureReason.UNKNOWN:
        raw_reason_text = str(rng.choice(_UNKNOWN_RAW_TEXTS))

    failure_event = FailureEvent(
        id=_det_id(rng, "evt"),
        payment_id=_det_id(rng, "pay"),
        mandate_id=mandate.mandate_id,
        reason=reason,
        npci_code=npci_code,
        source=_SOURCE_FOR_REASON.get(reason, FailureSource.RAZORPAY),
        amount_paise=amount_paise,
        occurred_at=occurred_at,
        attempt_number=1,
        raw_reason_text=raw_reason_text,
        description=f"synthetic record #{index}",
    )
    return mandate, failure_event


def generate_batch(seed: int, count: int) -> list[tuple[Mandate, FailureEvent]]:
    rng = np.random.default_rng(seed)
    return [generate_one(rng, i) for i in range(count)]


def write_jsonl(records: list[tuple[Mandate, FailureEvent]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for mandate, event in records:
            row = {"mandate": mandate.model_dump(mode="json"), "failure_event": event.model_dump(mode="json")}
            f.write(json.dumps(row) + "\n")


def read_jsonl(path: Path) -> list[tuple[Mandate, FailureEvent]]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append((Mandate.model_validate(row["mandate"]), FailureEvent.model_validate(row["failure_event"])))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic UPI AutoPay mandate book.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=800)
    parser.add_argument("--out-dir", type=str, default=str(_REPO_ROOT / "data"))
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    args = parser.parse_args()

    records = generate_batch(args.seed, args.count)
    split_rng = np.random.default_rng(args.seed + 1)  # independent draw so the split isn't entangled with record content
    indices = np.arange(len(records))
    split_rng.shuffle(indices)
    n_holdout = int(len(records) * args.holdout_fraction)
    holdout_idx = set(indices[:n_holdout].tolist())

    train = [r for i, r in enumerate(records) if i not in holdout_idx]
    holdout = [r for i, r in enumerate(records) if i in holdout_idx]

    out_dir = Path(args.out_dir)
    write_jsonl(train, out_dir / "mandates_train.jsonl")
    write_jsonl(holdout, out_dir / "mandates_heldout.jsonl")
    print(f"Generated {len(records)} records (seed={args.seed}): {len(train)} train, {len(holdout)} held-out.")
    print(f"Written to {out_dir / 'mandates_train.jsonl'} and {out_dir / 'mandates_heldout.jsonl'}")


if __name__ == "__main__":
    main()

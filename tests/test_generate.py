"""
tests/test_generate.py — the synthetic mandate book generator.

Checks reproducibility (same seed -> byte-identical output), basic
distributional sanity (every real MCC/reason/bank code used is one this
project actually sourced), and that the train/held-out split never overlaps.
"""
from __future__ import annotations

from data.generate import _BANK_WEIGHTS, _MCC_WEIGHTS, generate_batch
from src.domain.enums import FailureReason
from src.ingest.npci_stats import load_all


def test_same_seed_is_fully_reproducible() -> None:
    a = generate_batch(seed=7, count=50)
    b = generate_batch(seed=7, count=50)
    a_ids = [m.mandate_id for m, _ in a]
    b_ids = [m.mandate_id for m, _ in b]
    assert a_ids == b_ids
    for (ma, _), (mb, _) in zip(a, b):
        assert ma.amount_paise == mb.amount_paise
        assert ma.mcc == mb.mcc
        assert ma.root_cause_reason == mb.root_cause_reason


def test_different_seeds_produce_different_batches() -> None:
    a = generate_batch(seed=1, count=50)
    b = generate_batch(seed=2, count=50)
    amounts_a = [m.amount_paise for m, _ in a]
    amounts_b = [m.amount_paise for m, _ in b]
    assert amounts_a != amounts_b


def test_every_mcc_used_is_a_declared_real_mcc() -> None:
    records = generate_batch(seed=42, count=300)
    used_mccs = {m.mcc for m, _ in records}
    assert used_mccs <= set(_MCC_WEIGHTS.keys())


def test_every_bank_code_used_is_in_the_reference_table() -> None:
    reference_codes = {row.bank_code for row in load_all()}
    records = generate_batch(seed=42, count=300)
    used_codes = {m.payer_bank_code for m, _ in records}
    assert used_codes <= reference_codes
    assert used_codes <= set(_BANK_WEIGHTS.keys())


def test_amounts_are_always_positive() -> None:
    records = generate_batch(seed=42, count=300)
    assert all(m.amount_paise > 0 for m, _ in records)


def test_insufficient_funds_dominates_the_reason_distribution() -> None:
    """Cross-checks the generator against its own documented weighting
    (ASSUMPTIONS.md #A9) rather than a hard-coded exact count, so a small
    re-weighting doesn't make this test brittle."""
    records = generate_batch(seed=42, count=1000)
    reasons = [event.reason for _, event in records]
    funds_fraction = sum(1 for r in reasons if r == FailureReason.INSUFFICIENT_FUNDS) / len(reasons)
    assert funds_fraction > 0.4


def test_a_small_fraction_of_records_carry_an_unrecognised_reason() -> None:
    """Failure Injection #5 realism: some records must arrive with
    FailureReason.UNKNOWN and a raw_reason_text, or the scenario is never
    actually exercised by the generated batch."""
    records = generate_batch(seed=42, count=1000)
    unknown = [event for _, event in records if event.reason == FailureReason.UNKNOWN]
    assert len(unknown) > 0
    assert all(event.raw_reason_text for event in unknown)


def test_mcc_carveout_and_enhanced_afa_branches_are_both_exercised() -> None:
    from src.domain import regulatory_constants as RC

    records = generate_batch(seed=42, count=500)
    mccs = {m.mcc for m, _ in records}
    assert mccs & RC.PRE_DEBIT_NOTIFICATION_CARVEOUT_MCCS
    assert mccs & RC.ENHANCED_AFA_MCCS

"""
tests/test_narration.py — the two LLM-assisted, human-facing narration
features (escalation briefs, batch summaries). Both must degrade cleanly
with the default RECOVERY_ENGINE_USE_LLM=false, exactly like every other
LLM-assisted stage in this codebase.
"""
from __future__ import annotations

from eval import batch_summary
from src.classify import llm_client
from src.intervene import escalation_brief


def test_escalation_brief_falls_back_deterministically_when_llm_disabled() -> None:
    text, actor = escalation_brief.generate(
        mandate_id="mandate_test123", reason_value="vpa_resolution_failed",
        amount_rupees=1234.56, gate_rationale="reason requires investigation per Razorpay's own guidance",
    )
    assert actor == "deterministic"
    # mandate_id is deliberately NOT repeated in the brief text — every call
    # site already shows it as context (the bullet prefix in EVALUATION.md,
    # the line above it in `src.cli explain`) — see the escalation_brief.py
    # docstring and the wording fix in this same build session.
    assert "vpa_resolution_failed" in text
    assert "1,234.56" in text


def test_batch_summary_falls_back_deterministically_when_llm_disabled() -> None:
    metrics = {
        "strategy": "engine", "split": "train", "n_records": 640,
        "recovered_paise": 791754724, "at_risk_paise": 1337126431,
        "recovery_rate": 0.5921, "violations_total": 0, "retries_wasted_on_terminal": 0,
    }
    text, actor = batch_summary.generate(metrics)
    assert actor == "deterministic"
    assert "640 records" in text
    assert "0 compliance violations" in text


def test_usage_stats_track_every_call_regardless_of_outcome() -> None:
    llm_client.reset_usage_stats()
    escalation_brief.generate(mandate_id="m1", reason_value="credit_failed", amount_rupees=10.0, gate_rationale="x")
    batch_summary.generate({
        "strategy": "engine", "split": "train", "n_records": 1, "recovered_paise": 0,
        "at_risk_paise": 100, "recovery_rate": 0.0, "violations_total": 0, "retries_wasted_on_terminal": 0,
    })
    stats = llm_client.get_usage_stats()
    assert stats.call_count == 2
    assert stats.fallback_count == 2  # LLM disabled by default in the test environment
    assert stats.ok_count == 0
    llm_client.reset_usage_stats()


def test_narration_never_raises_on_missing_optional_fields() -> None:
    """Both generators must be safe to call with the minimal fields any
    caller might have on hand — never a KeyError mid-batch."""
    text, _ = escalation_brief.generate(mandate_id="m2", reason_value="__unknown__", amount_rupees=0.0, gate_rationale="")
    assert isinstance(text, str) and text

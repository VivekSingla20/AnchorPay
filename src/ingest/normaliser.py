"""
ingest/normaliser.py — Stage 1: deterministic normaliser.

Converts a raw, webhook-shaped payload (a plain dict — exactly what a
Razorpay `payment.failed` webhook body looks like) into a canonical
FailureEvent. Deliberately tolerant of malformed/unexpected input: this is
where Failure Injection #5 (a reason not in the taxonomy) and #7 (duplicate
webhook delivery) are handled structurally, not as an afterthought.

NO LLM IMPORT. This is deterministic parsing, not judgment.
"""
from __future__ import annotations

from typing import Optional

from src.domain.entities import FailureEvent
from src.domain.enums import FailureReason, FailureSource, NpciResponseCode

_SEEN_PAYMENT_IDS: set[str] = set()  # idempotency guard - Failure Injection #7


def reset_idempotency_cache() -> None:
    """Call between independent batch runs (tests, eval strategies) so one
    run's payment ids don't falsely dedupe against another's."""
    _SEEN_PAYMENT_IDS.clear()


def normalise(raw: dict) -> tuple[Optional[FailureEvent], str]:
    """Returns (event_or_None, note).

    event is None when this payload is a duplicate delivery of an
    already-seen payment_id (Failure Injection #7): the correct behaviour is
    to silently acknowledge and do nothing, not to double-process a failure
    and potentially double-schedule a retry.
    """
    payment_id = raw.get("payment_id") or raw.get("id")
    if payment_id and payment_id in _SEEN_PAYMENT_IDS:
        return None, f"duplicate webhook delivery for {payment_id} - ignored (idempotent)"
    if payment_id:
        _SEEN_PAYMENT_IDS.add(payment_id)

    raw_reason = raw.get("reason", "")
    try:
        reason = FailureReason(raw_reason)
    except ValueError:
        # Failure Injection #5: a reason arrives that is not in the taxonomy.
        reason = FailureReason.UNKNOWN

    raw_npci = raw.get("npci_code")
    npci_code = None
    if raw_npci:
        try:
            npci_code = NpciResponseCode(raw_npci)
        except ValueError:
            npci_code = None  # not fatal - `reason` remains primary per Build Spec §2.5

    raw_source = raw.get("source", "razorpay")
    try:
        source = FailureSource(raw_source)
    except ValueError:
        source = FailureSource.RAZORPAY  # conservative default - never guess "customer"

    event_kwargs: dict = dict(
        mandate_id=raw["mandate_id"],
        reason=reason,
        npci_code=npci_code,
        source=source,
        step=raw.get("step", "payment_authentication"),
        description=raw.get("description", ""),
        amount_paise=int(raw["amount_paise"]),
        occurred_at=int(raw["occurred_at"]),
        attempt_number=int(raw.get("attempt_number", 1)),
        raw_reason_text=raw_reason if reason == FailureReason.UNKNOWN else None,
    )
    if payment_id:
        event_kwargs["payment_id"] = payment_id

    return FailureEvent(**event_kwargs), "normalised"

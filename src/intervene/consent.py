"""
intervene/consent.py — consent / contact-budget bookkeeping.

Deterministic. Not "policy" in the retry-scheduling sense, but still
money-and-contact-adjacent, so it keeps the same no-judgment-calls posture:
it only reads and updates RECORDED state (an explicit opt-out event), it
never infers consent from behaviour (e.g. it never treats "customer hasn't
opened three emails" as an implied opt-out — that would be a judgment call
this engine deliberately does not make).
"""
from __future__ import annotations

from src.domain.entities import Customer
from src.domain.enums import ConsentState


def record_opt_out(customer: Customer, at: int) -> Customer:
    return customer.model_copy(update={"opted_out_at": at, "consent_state": ConsentState.OPTED_OUT})


def record_contact(customer: Customer, at: int) -> Customer:
    return customer.model_copy(update={"last_contacted_at": at, "contacts_today": customer.contacts_today + 1})


def reset_daily_contact_counter(customer: Customer) -> Customer:
    return customer.model_copy(update={"contacts_today": 0})


def is_contactable(customer: Customer, at: int) -> bool:
    if customer.opted_out_at is not None and at >= customer.opted_out_at:
        return False
    return True

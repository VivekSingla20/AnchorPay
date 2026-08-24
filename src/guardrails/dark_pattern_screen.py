"""
guardrails/dark_pattern_screen.py — part of Stage 8, the independent
guardrail layer.

Deterministic pattern screen for generated notification copy, applied AFTER
an LLM (or the deterministic fallback template) drafts text and BEFORE it is
allowed to send. Can veto. Every rejection is logged with the offending span
(Build Spec §6.6: "Rejections are a feature — report the count.").

Screens for the six categories named in India's Guidelines for Prevention and
Regulation of Dark Patterns, 2023, as referenced by Razorpay Agent Studio
principle 6 (Build Spec §1 row 6, §6.6): false urgency, confirm shaming,
bait and switch, drip pricing, subscription traps, fabricated scarcity.

Each pattern is deliberately narrow (regex over actual dunning-copy phrasing)
rather than a broad semantic ban, to keep the false-positive rate on
genuinely factual copy low. Extend this list; do not loosen an existing
entry without a test proving it still blocks the original case.

INDEPENDENCE RULE: imports only src.domain. Never imports
src.intervene.copy_generator — screening logic must not know how the text
was produced, only what it says.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.domain.regulatory_constants import DARK_PATTERN_CATEGORIES


@dataclass
class ScreenResult:
    passed: bool
    flagged_category: Optional[str]
    offending_span: Optional[str]
    detail: str


_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "false_urgency",
        r"\b(hurry|act now|last chance|final notice|expires? (today|in \d+ ?(minutes?|hours?))|"
        r"don'?t miss out|running out of time)\b",
    ),
    (
        "fabricated_scarcity",
        r"\b(only \d+ (left|spots?|slots?)|limited (spots?|slots?|seats?) (remaining|left)|almost gone)\b",
    ),
    (
        "confirm_shaming",
        r"\b(no,? i don'?t (want|care)|i (prefer|choose) to (lose|miss|pay more)|"
        r"only fools|you'?ll regret|don'?t be (the one who|left behind))\b",
    ),
    (
        "bait_and_switch",
        r"(\bfree\*|terms apply\*|\*conditions apply|not actually free)",
    ),
    (
        "drip_pricing",
        r"\b(additional fees? (apply|may apply) at checkout|price shown excludes|"
        r"plus applicable (fees|charges) \(disclosed later\))\b",
    ),
    (
        "subscription_traps",
        r"\b(auto-renews?,? cancel anytime\*|hidden cancellation|"
        r"cancellation (link|option) (unavailable|hidden)|can'?t find (the )?cancel button)\b",
    ),
)
_COMPILED = tuple((cat, re.compile(pat, re.IGNORECASE)) for cat, pat in _PATTERNS)

assert {cat for cat, _ in _PATTERNS} <= set(DARK_PATTERN_CATEGORIES), (
    "every screened category must be declared in regulatory_constants.DARK_PATTERN_CATEGORIES"
)


def screen(copy_text: str) -> ScreenResult:
    for category, pattern in _COMPILED:
        m = pattern.search(copy_text)
        if m:
            return ScreenResult(
                passed=False,
                flagged_category=category,
                offending_span=m.group(0),
                detail=f"matched dark-pattern category '{category}'",
            )
    return ScreenResult(passed=True, flagged_category=None, offending_span=None, detail="no dark-pattern match")

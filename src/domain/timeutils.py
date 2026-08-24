"""
Pure calendar/timezone arithmetic. No judgment, no LLM, no policy decision —
just IST conversion and window membership.

Shared by src/policy/allocator.py AND src/guardrails/invariants.py +
validator.py precisely BECAUSE it carries no judgment: both sides
re-implementing this would just duplicate identical arithmetic. What must
never be shared is a DECISION (a chosen schedule, a chosen verdict) — those
are always independently re-derived. See ARCHITECTURE.md, "Independence of
the guardrail layer".
"""
from __future__ import annotations

import datetime as dt

from src.domain.regulatory_constants import PEAK_WINDOWS, PERMITTED_WINDOWS, TimeWindow

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def to_ist(unix_ts: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(unix_ts, tz=dt.timezone.utc).astimezone(IST)


def minute_of_day_ist(unix_ts: int) -> int:
    d = to_ist(unix_ts)
    return d.hour * 60 + d.minute


def is_peak_hour(unix_ts: int) -> bool:
    m = minute_of_day_ist(unix_ts)
    return any(w.contains_minute_of_day(m) for w in PEAK_WINDOWS)


def is_permitted_execution_time(unix_ts: int) -> bool:
    m = minute_of_day_ist(unix_ts)
    return any(w.contains_minute_of_day(m) for w in PERMITTED_WINDOWS)


def which_window(unix_ts: int) -> TimeWindow | None:
    m = minute_of_day_ist(unix_ts)
    for w in PERMITTED_WINDOWS:
        if w.contains_minute_of_day(m):
            return w
    return None


def start_of_ist_day(unix_ts: int) -> int:
    d = to_ist(unix_ts)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def next_window_start(unix_ts: int, window: TimeWindow) -> int:
    """The next unix timestamp at/after unix_ts that falls at the start of
    the given window (same day if not yet passed, else next day)."""
    day_start = start_of_ist_day(unix_ts)
    candidate = day_start + (window.start_hour * 3600 + window.start_minute * 60)
    if candidate < unix_ts:
        candidate += 24 * 3600
    return candidate

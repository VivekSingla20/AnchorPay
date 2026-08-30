"""
audit/kill_switch.py — Razorpay Agent Studio principle 1: "one-tap kill
switch". A persisted, cross-invocation stop list: once a mandate_id is
killed, EVERY future run (CLI, eval harness) checks it first and refuses to
schedule or execute anything further for that mandate — checked at the very
top of the orchestrator loop, ahead of even opt-out, because a kill switch
is an operator-level override that must win over everything else.
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KILL_SWITCH_FILE = _REPO_ROOT / "results" / "killed_mandates.json"


def load_killed_mandate_ids() -> set[str]:
    """Never raises. A missing or corrupt file degrades to an empty set
    (nothing killed) rather than crashing a batch run — the same posture as
    every other Failure Injection scenario in this project. A real
    deployment would alert loudly on a corrupt kill-switch file rather than
    silently proceed; see LIMITATIONS.md."""
    if not _KILL_SWITCH_FILE.exists():
        return set()
    try:
        return set(json.loads(_KILL_SWITCH_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def kill_mandate(mandate_id: str) -> None:
    ids = load_killed_mandate_ids()
    ids.add(mandate_id)
    _KILL_SWITCH_FILE.parent.mkdir(exist_ok=True)
    _KILL_SWITCH_FILE.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def revive_mandate(mandate_id: str) -> None:
    """Reverses a kill — an operator's own action, never automatic."""
    ids = load_killed_mandate_ids()
    ids.discard(mandate_id)
    _KILL_SWITCH_FILE.parent.mkdir(exist_ok=True)
    _KILL_SWITCH_FILE.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")

"""
audit/log.py — Stage 10: append-only audit trail.

Every pipeline stage writes an AuditEntry here, including refusals and
vetoes (Build Spec §5.2: "Every stage emits to the audit log"). This is what
makes the "explain this decision" view possible for any mandate in the
batch, and what INV-11/INV-12/INV-14 check against.
"""
from __future__ import annotations

from pathlib import Path

from src.domain.entities import AuditEntry


class AuditLog:
    """In-memory during a run; can be flushed to JSONL for the audit-trail
    viewer (Build Spec Part 12 phase 11 gate: "Audit trail viewable")."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    def all(self) -> list[AuditEntry]:
        return list(self._entries)

    def for_mandate(self, mandate_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.mandate_id == mandate_id]

    def explain(self, mandate_id: str) -> str:
        """Plain-English decision trail for one mandate, in order."""
        entries = sorted(self.for_mandate(mandate_id), key=lambda e: e.timestamp)
        if not entries:
            return f"No audit history for {mandate_id}."
        lines = [f"Decision trail for {mandate_id}:"]
        for e in entries:
            lines.append(f"  [{e.stage}] {e.decision} - {e.reason} (actor: {e.actor})")
        return "\n".join(lines)

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self._entries:
                f.write(e.model_dump_json() + "\n")

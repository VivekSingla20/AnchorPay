"""
scripts/secret_scan.py — a small, dependency-free secret scanner for CI.

Deliberately custom rather than a third-party GitHub Action: this project's
own anti-hallucination discipline (docs/02-BUILD-SPEC.md Part 0) means not
citing/depending on an external tool's exact name, version, or behaviour
without having verified it directly. A ~40-line regex scan over tracked
files is fully within this project's own control to read, test, and defend
line-by-line — which is the same "defensibility test" (Build Spec §0.4)
applied to tooling, not just product code.

Exit code 0 = clean. Exit code 1 = at least one match found (fails CI).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Deliberately narrow, named patterns — each one independently explainable,
# rather than one broad "looks like a secret" heuristic nobody can defend.
_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("Generic private key header", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("Razorpay live key id", re.compile(r"rzp_live_[A-Za-z0-9]{10,}")),
    (
        "Hardcoded secret-shaped assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{16,}['\"]"),
    ),
)

# .env.example intentionally documents variable NAMES with empty/placeholder
# values — never flag it. A real .env is git-ignored and should never be a
# tracked file in the first place.
_EXCLUDED_FILES = {".env.example"}


def _tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files"], cwd=_REPO_ROOT, capture_output=True, text=True, check=True)
    return [_REPO_ROOT / line for line in result.stdout.splitlines() if line.strip()]


def scan() -> list[str]:
    findings: list[str] = []
    for path in _tracked_files():
        if path.name in _EXCLUDED_FILES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in _PATTERNS:
            m = pattern.search(text)
            if m:
                findings.append(f"{path.relative_to(_REPO_ROOT)}: possible {label} ({m.group(0)[:12]}...)")
    return findings


def main() -> None:
    findings = scan()
    if findings:
        print("Secret scan FAILED:")
        for f in findings:
            print(f"  - {f}")
        raise SystemExit(1)
    print("Secret scan OK: no matches across tracked files.")


if __name__ == "__main__":
    main()

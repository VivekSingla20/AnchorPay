"""
tests/test_no_llm_in_policy.py — INV-13: no policy or guardrail module ever
imports an LLM client. Static analysis over source text/AST, not runtime
behaviour — the invariant is about what a file IMPORTS, which is true
regardless of what any particular test run happens to execute.

Build Spec §5.2: "Stages 3, 4, 5, 8 contain no LLM calls. Ever. Assert this
in a test that greps the modules for the client import." This is that test.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GUARDED_DIRS = [_REPO_ROOT / "src" / "policy", _REPO_ROOT / "src" / "guardrails"]
_FORBIDDEN_MODULE_PREFIXES = ("anthropic", "openai", "src.classify", "src.intervene")


def _all_py_files() -> list[Path]:
    files: list[Path] = []
    for d in _GUARDED_DIRS:
        files.extend(sorted(d.rglob("*.py")))
    return files


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_guarded_dirs_are_not_empty() -> None:
    """A vacuously-passing parametrized test (zero files collected) would be
    worse than no test — guards against a path typo silently making INV-13
    always pass without ever checking anything."""
    assert len(_all_py_files()) >= 5


@pytest.mark.parametrize("path", _all_py_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_no_llm_import(path: Path) -> None:
    imported = _imported_modules(path)
    for forbidden in _FORBIDDEN_MODULE_PREFIXES:
        matches = {m for m in imported if m == forbidden or m.startswith(forbidden + ".")}
        assert not matches, (
            f"{path.relative_to(_REPO_ROOT)} imports forbidden module(s) {matches} — "
            f"policy/guardrail code must stay LLM-free (INV-13)"
        )


@pytest.mark.parametrize("path", _all_py_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_ground_truth_label_never_referenced(path: Path) -> None:
    """`Mandate.ground_truth_intent_label` is generator-only eval ground
    truth. If a policy/guardrail module ever reads it, the intent-inference
    accuracy metric in EVALUATION.md would be measuring a system that cheats
    off its own answer key."""
    text = path.read_text(encoding="utf-8")
    assert "ground_truth_intent_label" not in text, (
        f"{path.relative_to(_REPO_ROOT)} references ground_truth_intent_label — "
        f"this must never influence a policy/guardrail decision"
    )

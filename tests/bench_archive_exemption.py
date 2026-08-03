"""
Benchmark: the hot tier actually ages.

The archive exemption ("high relevance stays hot") is only meaningful if it
sits ABOVE every default relevance. It did not: the miner mints auto-captured
decisions at a hardcoded 7 and the exemption was `>= 7`, so every one of them
was born permanently exempt. On the reference store that left 231 decisions
untouched for 2+ weeks and still un-archivable, and the hot tier grew without
bound — which looked like a missing consolidator but was two constants
colliding.

What must hold:
  1. A memory at the AUTO-CAPTURE default (7) that has gone stale is
     archivable. This is the regression.
  2. A memory at the MANUAL default (5) that has gone stale is archivable.
  3. A deliberately-promoted memory (8+) is exempt however stale it gets.
  4. Freshly-accessed memories are never archived, at any relevance.
  5. Rules and mistakes are never archived by age, at any relevance.
  6. The exemption stays above every default that exists in the codebase —
     if someone raises a default to 8, this test fails rather than silently
     restoring immortality.

Run: python tests/bench_archive_exemption.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.tools.memory import (
    ARCHIVE_EXEMPT_RELEVANCE,
    MemoryEntry,
    MemoryStore,
)

_fails = []

AUTO_DECISION_RELEVANCE = 7  # extractors.py / work_tracker.py mint at this
MANUAL_REMEMBER_RELEVANCE = 5  # handlers.py remember default


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _entry(store, *, category, relevance, stale_days):
    e = MemoryEntry(content=f"{category} r{relevance} d{stale_days}", category=category)
    e.relevance = relevance
    e.last_accessed = time.time() - stale_days * 86400
    return store._is_archivable(e)


def test_defaults_age_out():
    print("Memories at a DEFAULT relevance age out once stale:")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        s = MemoryStore()
        check(
            "auto-captured decision (7) archivable after 30d idle  <-- the regression",
            _entry(s, category="decision", relevance=AUTO_DECISION_RELEVANCE, stale_days=30),
        )
        check(
            "manual remember (5) archivable after 30d idle",
            _entry(s, category="discovery", relevance=MANUAL_REMEMBER_RELEVANCE, stale_days=30),
        )
        check(
            "fresh decision (7, 1d idle) stays hot",
            not _entry(s, category="decision", relevance=AUTO_DECISION_RELEVANCE, stale_days=1),
        )


def test_promoted_stays_hot():
    print("Deliberately promoted memories stay hot forever:")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        s = MemoryStore()
        check(
            "relevance 8 exempt at 30d",
            not _entry(s, category="discovery", relevance=8, stale_days=30),
        )
        check(
            "relevance 10 exempt at 999d",
            not _entry(s, category="discovery", relevance=10, stale_days=999),
        )


def test_protected_categories():
    print("Protected categories never age out:")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        s = MemoryStore()
        for cat in ("rule", "mistake", "lesson"):
            check(
                f"{cat} never archived by age (999d, relevance 1)",
                not _entry(s, category=cat, relevance=1, stale_days=999),
            )


def test_exemption_stays_above_every_default():
    """The property that actually prevents the bug from coming back."""
    print("Exemption threshold sits above every default in the codebase:")
    check(
        f"exemption ({ARCHIVE_EXEMPT_RELEVANCE}) > auto-capture default ({AUTO_DECISION_RELEVANCE})",
        ARCHIVE_EXEMPT_RELEVANCE > AUTO_DECISION_RELEVANCE,
    )
    check(
        f"exemption ({ARCHIVE_EXEMPT_RELEVANCE}) > manual default ({MANUAL_REMEMBER_RELEVANCE})",
        ARCHIVE_EXEMPT_RELEVANCE > MANUAL_REMEMBER_RELEVANCE,
    )
    # Read the real mint sites rather than trusting the copies above. Parsed
    # with ast, not regex: kwargs appear in either order, so "nearest preceding
    # category=" silently mis-attributes a call that passes relevance first.
    # Only categories that age by relevance count -- rule/mistake/lesson are
    # exempt by CATEGORY before relevance is consulted.
    import ast
    from pathlib import Path

    PROTECTED = {"rule", "mistake", "lesson"}
    root = Path(__file__).resolve().parent.parent / "claude_engram"
    minted: dict = {}
    for f in (root / "mining" / "extractors.py", root / "tools" / "work_tracker.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {
                k.arg: k.value
                for k in node.keywords
                if k.arg and isinstance(k.value, ast.Constant)
            }
            if "relevance" not in kw:
                continue
            cat = kw["category"].value if "category" in kw else "?"
            if cat not in PROTECTED:
                minted.setdefault(cat, set()).add(kw["relevance"].value)
    flat = sorted({r for rs in minted.values() for r in rs})
    check(
        f"every age-eligible mint relevance {flat} is below the exemption "
        f"(by category: { {k: sorted(v) for k, v in minted.items()} })",
        bool(flat) and all(r < ARCHIVE_EXEMPT_RELEVANCE for r in flat),
    )


if __name__ == "__main__":
    print("=" * 60)
    print("Archive Exemption Benchmark")
    print("=" * 60)
    test_defaults_age_out()
    test_promoted_stays_hot()
    test_protected_categories()
    test_exemption_stays_above_every_default()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

"""
Benchmark: path-aware mistake relevance.

Guards the fix that stops cross-version / cross-directory false positives — a
V7 mistake (or an auth/middleware.py mistake) must not fire on a V8 (or
api/middleware.py) edit just because the basename matches — while preserving
genuine relevance (same path, relative form, bare locator, full-path-in-text,
specific filename mentioned in the memory).

Run: python tests/bench_path_relevance.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.tools.memory import _file_match_score as S

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


V8 = "E:/workspace/chappie/V8/cortex/core/training/losses/__init__.py"
V7 = "E:/workspace/chappie/V7/cortex/core/training/losses/__init__.py"
ENG_V8 = "E:/workspace/chappie/V8/cortex/mind/imagination/engine.py"
ENG_V7 = "E:/workspace/chappie/V7/cortex/mind/imagination/engine.py"

GATE = 0.5  # injection threshold used by get_scored_memories

if __name__ == "__main__":
    print("=" * 60)
    print("Path-Aware Mistake Relevance Benchmark")
    print("=" * 60)

    print("Cross-version / cross-dir false positives are rejected:")
    check("V7 full-path related does NOT match V8 edit", S(V8, [V7], "") < GATE)
    check(
        "V7 path in content does NOT match V8 __init__.py",
        S(V8, [], f"import from '{V7}'") < GATE,
    )
    check(
        "bare __init__.py related does NOT match (generic)",
        S(V8, ["__init__.py"], "") < GATE,
    )
    check(
        "__init__.py name-drop in content does NOT match (generic)",
        S(V8, [], "see __init__.py") < GATE,
    )
    check(
        "engine.py V7 full path does NOT match V8 engine.py",
        S(ENG_V8, [ENG_V7], "") < GATE,
    )
    check(
        "unrelated file does not match",
        S(V8, ["E:/other/proj/server.py"], "server crash") == 0.0,
    )

    print("Genuine relevance is preserved:")
    check("same V8 full path matches", S(V8, [V8], "") == 1.0)
    check(
        "relative V8 path (suffix of edit) matches",
        S(V8, ["V8/cortex/core/training/losses/__init__.py"], "") == 1.0,
    )
    check("full path in content matches", S(V8, [], f"error in {V8}") >= GATE)
    check(
        "bare engine.py related matches engine.py edit",
        S(ENG_V8, ["engine.py"], "") >= GATE,
    )
    check(
        "specific filename in content matches",
        S(ENG_V8, [], "touched engine.py earlier") >= GATE,
    )

    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

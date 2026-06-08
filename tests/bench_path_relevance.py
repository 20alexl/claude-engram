"""
Benchmark: path-aware mistake relevance.

Guards the fix that stops cross-version / cross-directory false positives — a
service-a mistake (or an auth/middleware.py mistake) must not fire on a
service-b (or api/middleware.py) edit just because the basename matches — while
preserving genuine relevance (same path, relative form, bare locator,
full-path-in-text, specific filename mentioned in the memory).

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


SVC_B = "/repo/service-b/myapp/core/training/losses/__init__.py"
SVC_A = "/repo/service-a/myapp/core/training/losses/__init__.py"
ENG_B = "/repo/service-b/myapp/imagination/engine.py"
ENG_A = "/repo/service-a/myapp/imagination/engine.py"

GATE = 0.5  # injection threshold used by get_scored_memories

if __name__ == "__main__":
    print("=" * 60)
    print("Path-Aware Mistake Relevance Benchmark")
    print("=" * 60)

    print("Cross-version / cross-dir false positives are rejected:")
    check("service-a full-path related does NOT match service-b edit", S(SVC_B, [SVC_A], "") < GATE)
    check(
        "service-a path in content does NOT match service-b __init__.py",
        S(SVC_B, [], f"import from '{SVC_A}'") < GATE,
    )
    check(
        "bare __init__.py related does NOT match (generic)",
        S(SVC_B, ["__init__.py"], "") < GATE,
    )
    check(
        "__init__.py name-drop in content does NOT match (generic)",
        S(SVC_B, [], "see __init__.py") < GATE,
    )
    check(
        "engine.py service-a full path does NOT match service-b engine.py",
        S(ENG_B, [ENG_A], "") < GATE,
    )
    check(
        "unrelated file does not match",
        S(SVC_B, ["/other/proj/server.py"], "server crash") == 0.0,
    )

    print("Genuine relevance is preserved:")
    check("same service-b full path matches", S(SVC_B, [SVC_B], "") == 1.0)
    check(
        "relative service-b path (suffix of edit) matches",
        S(SVC_B, ["service-b/myapp/core/training/losses/__init__.py"], "") == 1.0,
    )
    check("full path in content matches", S(SVC_B, [], f"error in {SVC_B}") >= GATE)
    check(
        "bare engine.py related matches engine.py edit",
        S(ENG_B, ["engine.py"], "") >= GATE,
    )
    check(
        "specific filename in content matches",
        S(ENG_B, [], "touched engine.py earlier") >= GATE,
    )

    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

#!/usr/bin/env python3
"""
Benchmark: injection outcome feedback loop (Capability 6).

Verifies the OutcomeLog correlation: each test outcome is attributed to the
injection kinds that preceded it in the SAME session (cross-session isolation),
plus persistence and formatting. Synthetic — runs anywhere.

Usage:
    python tests/bench_outcomes.py
"""
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.mining.outcomes import OutcomeLog, format_reflection

fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        fails.append(name)


print("=" * 70)
print("Injection Outcome Loop Benchmark")
print("=" * 70)

p = Path(tempfile.mkdtemp(prefix="oc_")) / "outcomes.json"
log = OutcomeLog(p)
# session A: ctx+precheck -> pass ; then ctx -> fail
log.record_injection("a.py", ["context", "precheck"], "A")
log.record_outcome(True, "A")
log.record_injection("b.py", ["context"], "A")
log.record_outcome(False, "A")
# session B: blast -> pass  (must not be attributed to A)
log.record_injection("c.py", ["blast"], "B")
log.record_outcome(True, "B")
r = log.reflect()
pk = r["per_kind"]

print("\n--- 1. Correlation ---")
check("total injections", r["total_injections"] == 4)
check("outcomes tally", r["outcomes"] == {"pass": 2, "fail": 1})
check("context injected x2", pk["context"]["injected"] == 2)
check(
    "context preceded 1 pass + 1 fail",
    pk["context"]["before_pass"] == 1 and pk["context"]["before_fail"] == 1,
)
check(
    "precheck preceded only pass",
    pk["precheck"]["before_pass"] == 1 and pk["precheck"]["before_fail"] == 0,
)
check(
    "blast preceded only pass",
    pk["blast"]["before_pass"] == 1 and pk["blast"]["before_fail"] == 0,
)

print("\n--- 2. Cross-session isolation ---")
# B's outcome must not have bumped A-only kinds (precheck stays at 1 pass, 0 fail)
check(
    "session B isolated from A kinds",
    pk["precheck"]["before_pass"] == 1
    and "blast" not in (set(pk) - {"blast", "context", "precheck"}),
)
check("blast not double-counted", pk["blast"]["injected"] == 1)

print("\n--- 3. Persistence ---")
log.save()
log2 = OutcomeLog(p)
r2 = log2.reflect()
check(
    "reload reflects same",
    r2["total_injections"] == 4 and r2["outcomes"] == {"pass": 2, "fail": 1},
)

print("\n--- 4. Formatting ---")
txt = format_reflection(r)
check("format names kinds", "context" in txt and "precheck" in txt and "blast" in txt)
check("format shows pre-pass rate", "pre-pass" in txt)
check(
    "empty -> friendly message",
    format_reflection({"events": 0}).startswith("No injection outcomes"),
)

print("\n--- 5. Empty / no-kinds guards ---")
empty = OutcomeLog(Path(tempfile.mkdtemp(prefix="oc2_")) / "e.json")
empty.record_injection("x.py", [], "Z")  # no kinds -> ignored
check("no-kind injection ignored", empty.reflect()["total_injections"] == 0)

print("\n" + "=" * 70)
print(
    f"RESULTS: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}"
)
print("=" * 70)
sys.exit(1 if fails else 0)

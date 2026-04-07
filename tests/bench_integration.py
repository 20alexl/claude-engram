#!/usr/bin/env python3
"""
Integration Benchmark Suite — runs all 6 product-level benchmarks.

These test what Claude Engram actually does, not just search retrieval:
  1. Decision capture precision/recall (220+ prompts)
  2. Injection relevance (scored memory surfacing)
  3. Compaction survival (rules/mistakes survive context compression)
  4. Error auto-capture (pattern extraction + noise filtering)
  5. Multi-project scoping (sub-project isolation + workspace inheritance)
  6. Edit loop detection (spiral detection with test context)

Usage:
    python tests/bench_integration.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_all():
    print("=" * 60)
    print("Claude Engram — Integration Benchmark Suite")
    print("=" * 60)
    print()

    results = {}
    t0 = time.time()

    # 1. Decision Capture
    print("\n" + "#" * 60)
    print("# 1. Decision Capture")
    print("#" * 60)
    try:
        import bench_decision_capture_v2
        from claude_engram.hooks.remind import _score_decision_intent
        r, p, f1 = bench_decision_capture_v2.run_scorer(_score_decision_intent, "Regex Scorer", 0.45)
        results["Decision Capture (Regex)"] = f"F1={f1:.1f}%"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Decision Capture"] = "ERROR"

    # 2. Injection Relevance
    print("\n" + "#" * 60)
    print("# 2. Injection Relevance")
    print("#" * 60)
    try:
        import bench_injection_relevance
        passed, total = bench_injection_relevance.run_benchmark()
        results["Injection Relevance"] = f"{passed}/{total} passed"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Injection Relevance"] = "ERROR"

    # 3. Compaction Survival
    print("\n" + "#" * 60)
    print("# 3. Compaction Survival")
    print("#" * 60)
    try:
        import bench_compaction_survival
        passed, total = bench_compaction_survival.run_benchmark()
        results["Compaction Survival"] = f"{passed}/{total} passed"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Compaction Survival"] = "ERROR"

    # 4. Error Auto-Capture
    print("\n" + "#" * 60)
    print("# 4. Error Auto-Capture")
    print("#" * 60)
    try:
        import bench_error_capture
        correct, total = bench_error_capture.run_benchmark()
        results["Error Auto-Capture"] = f"{correct}/{total} correct"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Error Auto-Capture"] = "ERROR"

    # 5. Multi-Project Scoping
    print("\n" + "#" * 60)
    print("# 5. Multi-Project Scoping")
    print("#" * 60)
    try:
        import bench_multi_project
        passed, total = bench_multi_project.run_benchmark()
        results["Multi-Project Scoping"] = f"{passed}/{total} passed"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Multi-Project Scoping"] = "ERROR"

    # 6. Edit Loop Detection
    print("\n" + "#" * 60)
    print("# 6. Edit Loop Detection")
    print("#" * 60)
    try:
        import bench_edit_loop
        passed, total = bench_edit_loop.run_benchmark()
        results["Edit Loop Detection"] = f"{passed}/{total} passed"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["Edit Loop Detection"] = "ERROR"

    elapsed = time.time() - t0

    # Summary
    print("\n" + "=" * 60)
    print("INTEGRATION BENCHMARK SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        print(f"  {name:<30} {result}")
    print(f"\n  Total time: {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    run_all()

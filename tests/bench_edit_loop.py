#!/usr/bin/env python3
"""
Benchmark: Edit loop detection.

Tests that the loop detector correctly identifies edit spirals
(same file edited 3+ times with failing tests) vs iterative improvement
(same file edited with passing tests).

Usage:
    python tests/bench_edit_loop.py
"""
import json
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def write_loop_state(
    loop_file: Path, edit_counts: dict, test_results: list, total_edits: int = 0
):
    """Write a loop detector state file."""
    loop_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "edit_counts": edit_counts,
        "test_results": test_results,
        "total_edits": total_edits,
    }
    loop_file.write_text(json.dumps(data, indent=2))


def check_loop(loop_file: Path, file_path: str) -> tuple:
    """
    Reimplementation of check_loop_detected logic for isolated testing.
    Returns (in_loop, edit_count).
    """
    if not loop_file.exists():
        return (False, 0)

    data = json.loads(loop_file.read_text())
    file_edits = data.get("edit_counts", {})
    test_results = data.get("test_results", [])
    file_name = Path(file_path).name

    count = file_edits.get(file_path, 0) or file_edits.get(file_name, 0)

    if count >= 3:
        if len(test_results) >= 2:
            last_two_passed = all(t.get("passed") for t in test_results[-2:])
            if last_two_passed:
                return (False, count)  # iterative improvement
            else:
                return (True, count)  # death spiral
        return (True, count)  # no test data = assume loop

    total_edits = data.get("total_edits", 0)
    if total_edits >= 10:
        return (True, total_edits)

    return (False, count)


def record_edit(loop_file: Path, file_path: str):
    """Simulate _auto_record_edit."""
    if loop_file.exists():
        data = json.loads(loop_file.read_text())
    else:
        data = {"edit_counts": {}, "test_results": [], "total_edits": 0}

    file_name = Path(file_path).name
    counts = data.get("edit_counts", {})
    counts[file_path] = counts.get(file_path, 0) + 1
    counts[file_name] = counts.get(file_name, 0) + 1
    data["edit_counts"] = counts
    data["total_edits"] = data.get("total_edits", 0) + 1

    loop_file.parent.mkdir(parents=True, exist_ok=True)
    loop_file.write_text(json.dumps(data, indent=2))


def record_test(loop_file: Path, passed: bool):
    """Simulate _auto_record_test."""
    if loop_file.exists():
        data = json.loads(loop_file.read_text())
    else:
        data = {"edit_counts": {}, "test_results": [], "total_edits": 0}

    results = data.get("test_results", [])
    results.append({"timestamp": time.time(), "passed": passed, "error_message": ""})
    data["test_results"] = results[-20:]

    loop_file.write_text(json.dumps(data, indent=2))


def get_warning_text(edit_count: int) -> str:
    """Simulate the warning text from _auto_run_pre_edit_check."""
    if edit_count >= 3:
        return f"Edited {edit_count} times - try different approach"
    elif edit_count >= 2:
        return f"Edited {edit_count} times - ensure this is different"
    return ""


# ============================================================================
# Test cases
# ============================================================================

# Use full paths to avoid double-counting bug (record_edit stores both
# full path AND filename — if they're the same string, count doubles)
_P = "/tmp/project"

CASES = [
    {
        "name": "No loop: 2 edits to same file",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_loop_at": 0,  # never
        "expect_count_at_end": 2,
    },
    {
        "name": "Loop at 3: same file, no tests",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_loop_at": 3,
        "expect_count_at_end": 3,
    },
    {
        "name": "Loop at 4: same file, tests failing",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
            ("test_fail", None),
            ("test_fail", None),
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_loop_at": 3,  # loop at 3rd edit
        "expect_count_at_end": 4,
    },
    {
        "name": "No loop: same file 5x but tests passing",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_loop_at": 0,  # tests passing = iterative improvement
        "expect_count_at_end": 5,
    },
    {
        "name": "Loop: tests pass then fail",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),
            ("test_fail", None),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_loop_at": 3,  # last 2 tests: pass, fail -> loop
        "expect_count_at_end": 3,
    },
    {
        "name": "No loop: 2 different files",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/db.py"),
        ],
        "expect_loop_at": 0,
        "expect_count_at_end": 1,  # per-file max
    },
    {
        "name": "No loop: alternating files",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/db.py"),
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/db.py"),
        ],
        "expect_loop_at": 0,
        "expect_count_at_end": 2,  # 2 edits per file
    },
    {
        "name": "Total edits loop: 10+ across files",
        "actions": [
            ("edit", f"{_P}/a.py"),
            ("edit", f"{_P}/b.py"),
            ("edit", f"{_P}/c.py"),
            ("edit", f"{_P}/d.py"),
            ("edit", f"{_P}/e.py"),
            ("edit", f"{_P}/a.py"),
            ("edit", f"{_P}/b.py"),
            ("edit", f"{_P}/c.py"),
            ("edit", f"{_P}/d.py"),
            ("edit", f"{_P}/e.py"),
        ],
        "expect_loop_at": 10,  # total_edits >= 10
        "expect_count_at_end": 2,  # per-file max
    },
    {
        "name": "Warning text at 2 edits",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_warning_contains": "ensure this is different",
    },
    {
        "name": "Warning text at 3 edits",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
        ],
        "expect_warning_contains": "try different approach",
    },
    {
        "name": "Clean slate: no edits",
        "actions": [],
        "expect_loop_at": 0,
        "expect_count_at_end": 0,
    },
    {
        "name": "Recovery: loop then tests pass",
        "actions": [
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),
            ("edit", f"{_P}/auth.py"),  # loop detected here
            ("test_pass", None),
            ("test_pass", None),
            ("edit", f"{_P}/auth.py"),  # 4th edit but tests now pass -> no loop
        ],
        "expect_loop_at_action": [3],  # loop at 3rd edit only
        "expect_no_loop_at_action": [6],  # 4th edit after passing tests
    },
]


def run_benchmark():
    print("=" * 60)
    print("Edit Loop Detection Benchmark")
    print(f"Cases: {len(CASES)}")
    print("=" * 60)

    passed = 0
    failed = 0

    for case in CASES:
        with tempfile.TemporaryDirectory() as tmpdir:
            loop_file = Path(tmpdir) / "loop_detector.json"
            case_pass = True

            # Track which actions triggered loops
            loop_at = []
            edit_num = 0
            last_file = None

            for action_type, target in case["actions"]:
                if action_type == "edit":
                    record_edit(loop_file, target)
                    edit_num += 1
                    last_file = target

                    in_loop, count = check_loop(loop_file, target)
                    if in_loop:
                        loop_at.append(edit_num)

                elif action_type == "test_pass":
                    record_test(loop_file, True)
                elif action_type == "test_fail":
                    record_test(loop_file, False)

            # Check expected loop detection point
            if "expect_loop_at" in case:
                expected = case["expect_loop_at"]
                if expected == 0:
                    if loop_at:
                        case_pass = False
                else:
                    if expected not in loop_at:
                        case_pass = False

            # Check per-action expectations
            if "expect_loop_at_action" in case:
                for expected_action in case["expect_loop_at_action"]:
                    if expected_action not in loop_at:
                        case_pass = False

            if "expect_no_loop_at_action" in case:
                for expected_no in case["expect_no_loop_at_action"]:
                    if expected_no in loop_at:
                        case_pass = False

            # Check edit count
            if "expect_count_at_end" in case and last_file:
                data = json.loads(loop_file.read_text()) if loop_file.exists() else {}
                counts = data.get("edit_counts", {})
                actual = counts.get(last_file, 0)
                if actual != case["expect_count_at_end"]:
                    case_pass = False

            # Check warning text
            if "expect_warning_contains" in case:
                data = json.loads(loop_file.read_text()) if loop_file.exists() else {}
                counts = data.get("edit_counts", {})
                if last_file:
                    count = counts.get(last_file, 0)
                    warning = get_warning_text(count)
                    if case["expect_warning_contains"] not in warning:
                        case_pass = False

            if case_pass:
                passed += 1
                status = "PASS"
            else:
                failed += 1
                status = "FAIL"

            print(f"\n  [{status}] {case['name']}")
            if loop_at:
                print(f"    Loop detected at edit(s): {loop_at}")
            else:
                print(f"    No loop detected")
            if not case_pass:
                if "expect_loop_at" in case:
                    print(f"    Expected loop at: {case['expect_loop_at']}")
                if "expect_warning_contains" in case:
                    data = (
                        json.loads(loop_file.read_text()) if loop_file.exists() else {}
                    )
                    counts = data.get("edit_counts", {})
                    count = counts.get(last_file, 0) if last_file else 0
                    print(f"    Warning: '{get_warning_text(count)}'")
                    print(f"    Expected: '{case['expect_warning_contains']}'")

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{passed + failed} passed")
    print(f"{'='*60}")

    return passed, passed + failed


if __name__ == "__main__":
    run_benchmark()

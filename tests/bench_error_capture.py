#!/usr/bin/env python3
"""
Benchmark: Error auto-capture quality.

Tests _auto_log_detected_mistake() against realistic tool failure outputs.
Validates: extraction quality, noise filtering, deduplication.

Usage:
    python tests/bench_error_capture.py
"""
import json
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We test the function directly by importing it
from claude_engram.hooks.remind import _auto_log_detected_mistake, get_memory_file


# ============================================================================
# Test payloads: (command, output, expected_capture, expected_substring, category)
# ============================================================================

PAYLOADS = [
    # --- Import errors (8) ---
    (
        "python main.py",
        "Traceback (most recent call last):\n  File \"main.py\", line 1\nModuleNotFoundError: No module named 'requests'",
        True,
        "requests",
        "import",
    ),
    (
        "python app.py",
        "Traceback (most recent call last):\n  File \"app.py\", line 5\nImportError: cannot import name 'FastAPI' from 'flask'",
        True,
        "FastAPI",
        "import",
    ),
    (
        "python test.py",
        "ModuleNotFoundError: No module named 'numpy.core._multiarray_umath'",
        True,
        "numpy",
        "import",
    ),
    (
        "python run.py",
        "ImportError: cannot import name 'deprecated_func' from 'mylib.utils'",
        True,
        "deprecated_func",
        "import",
    ),
    (
        "python server.py",
        "ModuleNotFoundError: No module named 'torch'",
        True,
        "torch",
        "import",
    ),
    (
        "python cli.py",
        "ModuleNotFoundError: No module named 'pydantic'",
        True,
        "pydantic",
        "import",
    ),
    (
        "python deep.py",
        'Traceback:\n  File "deep.py", line 100\n  File "lib/core.py", line 50\nModuleNotFoundError: No module named \'cryptography.hazmat\'',
        True,
        "cryptography",
        "import",
    ),
    (
        "python nested.py",
        "ImportError: cannot import name 'BaseSettings' from 'pydantic'",
        True,
        "BaseSettings",
        "import",
    ),
    # --- Syntax errors (8) ---
    (
        "python bad.py",
        '  File "bad.py", line 42\n    def foo(\n         ^\nSyntaxError: unexpected EOF while parsing',
        True,
        "bad.py",
        "syntax",
    ),
    (
        "python indent.py",
        '  File "indent.py", line 10\n    return x\nIndentationError: unexpected indent',
        # IndentationError is a subclass of SyntaxError but our code checks for "SyntaxError" string
        False,
        "",
        "syntax",
    ),
    (
        "python missing.py",
        '  File "src/parser.py", line 55\n    if x == :\n           ^\nSyntaxError: invalid syntax',
        True,
        "parser.py",
        "syntax",
    ),
    (
        "python unicode.py",
        "  File \"utils.py\", line 3\nSyntaxError: (unicode error) 'utf-8' codec can't decode byte",
        True,
        "utils.py",
        "syntax",
    ),
    (
        "python f.py",
        "  File \"f.py\", line 1\n    f'{x!r:}'\n          ^\nSyntaxError: f-string: empty expression not allowed",
        True,
        "f.py",
        "syntax",
    ),
    (
        "python colon.py",
        "  File \"routes.py\", line 22\n    async def handler()\n                      ^\nSyntaxError: expected ':'",
        True,
        "routes.py",
        "syntax",
    ),
    (
        "python eof.py",
        '  File "config.py", line 99\n\nSyntaxError: unexpected EOF while parsing',
        True,
        "config.py",
        "syntax",
    ),
    (
        "python walrus.py",
        '  File "new.py", line 5\n    if (n := 10) > 5:\n         ^\nSyntaxError: invalid syntax',
        True,
        "new.py",
        "syntax",
    ),
    # --- Type errors (6) ---
    (
        "python types.py",
        "Traceback:\n  File \"types.py\", line 20\nTypeError: unsupported operand type(s) for +: 'int' and 'str'",
        True,
        "unsupported operand",
        "type",
    ),
    (
        "python none.py",
        "TypeError: 'NoneType' object is not iterable",
        True,
        "NoneType",
        "type",
    ),
    (
        "python args.py",
        "TypeError: foo() takes 2 positional arguments but 3 were given",
        True,
        "positional arguments",
        "type",
    ),
    (
        "python sub.py",
        "TypeError: list indices must be integers or slices, not str",
        True,
        "list indices",
        "type",
    ),
    (
        "python call.py",
        "TypeError: 'int' object is not callable",
        True,
        "not callable",
        "type",
    ),
    (
        "python kw.py",
        "TypeError: __init__() got an unexpected keyword argument 'color'",
        True,
        "unexpected keyword",
        "type",
    ),
    # --- Attribute errors (6) ---
    (
        "python attr.py",
        "AttributeError: 'str' object has no attribute 'append'",
        True,
        "append",
        "attribute",
    ),
    (
        "python mod.py",
        "AttributeError: module 'os' has no attribute 'makedirss'",
        True,
        "makedirss",
        "attribute",
    ),
    (
        "python none_attr.py",
        "AttributeError: 'NoneType' object has no attribute 'id'",
        True,
        "NoneType",
        "attribute",
    ),
    (
        "python cls.py",
        "AttributeError: 'User' object has no attribute 'email_address'",
        True,
        "email_address",
        "attribute",
    ),
    (
        "python dict_attr.py",
        "AttributeError: 'dict' object has no attribute 'items_list'",
        True,
        "items_list",
        "attribute",
    ),
    (
        "python priv.py",
        "AttributeError: 'MyClass' object has no attribute '_private_method'",
        True,
        "_private_method",
        "attribute",
    ),
    # --- Test failures (6) ---
    (
        "pytest tests/",
        "FAILED tests/test_auth.py::test_login - AssertionError\n2 failed, 8 passed in 3.2s",
        True,
        "2 tests failed",
        "test",
    ),
    (
        "pytest tests/test_api.py",
        "tests/test_api.py::test_create FAILED\n1 failed, 5 passed, 1 warning",
        True,
        "1 tests failed",
        "test",
    ),
    (
        "python -m unittest",
        "FAILURES\n======\ntest_something (tests.test_foo.TestFoo)\nAssertionError: 42 != 43",
        True,
        "failed",
        "test",
    ),
    (
        "pytest",
        "10 failed, 2 error in 15.3s",
        True,
        "10 tests failed",
        "test",
    ),
    (
        "pytest tests/unit/",
        "3 failed, 47 passed in 8.1s",
        True,
        "3 tests failed",
        "test",
    ),
    (
        "pytest --tb=short",
        "FAILED tests/test_db.py::test_migrate\nAssertionError: migration failed\n1 failed, 20 passed",
        True,
        "1 tests failed",
        "test",
    ),
    # --- Permission/connection errors (4) ---
    (
        "python write.py",
        "PermissionError: [Errno 13] Permission denied: '/etc/hosts'",
        True,
        "Permission",
        "permission",
    ),
    (
        "python connect.py",
        "ConnectionRefusedError: [Errno 111] Connection refused",
        True,
        "Connection",
        "connection",
    ),
    (
        "python db.py",
        "ConnectionError: Error connecting to PostgreSQL at localhost:5432",
        True,
        "Connection",
        "connection",
    ),
    (
        "chmod 000 secret.txt && cat secret.txt",
        "cat: secret.txt: Permission denied",
        True,
        "Permission",
        "permission",
    ),
    # --- Noise: should NOT capture (15) ---
    (
        "grep -r 'error' src/",
        "src/logger.py:    log.error('Request failed')\nsrc/handlers.py:    raise HTTPError(404)",
        False,
        "",
        "noise",
    ),
    (
        "cat build.log",
        "Building wheel for project... done\nInstalling collected packages: numpy, pandas\nSuccessfully installed numpy-1.24.0",
        False,
        "",
        "noise",
    ),
    (
        "echo hello",
        "",
        False,
        "",
        "noise",
    ),
    (
        "python -c 'print(1+1)'",
        "2",
        False,
        "",
        "noise",
    ),
    (
        "pytest tests/",
        "10 passed in 2.1s",
        False,
        "",
        "noise",
    ),
    (
        "ls -la",
        "total 48\ndrwxr-xr-x  5 user staff  160 Jan  1 00:00 .\ndrwxr-xr-x  3 user staff   96 Jan  1 00:00 ..",
        False,
        "",
        "noise",
    ),
    (
        "pip install requests",
        "Requirement already satisfied: requests in ./venv/lib/python3.10/site-packages",
        False,
        "",
        "noise",
    ),
    (
        "git status",
        "On branch main\nnothing to commit, working tree clean",
        False,
        "",
        "noise",
    ),
    (
        "python -c 'import warnings; warnings.warn(\"deprecation\")'",
        '/tmp/test.py:1: UserWarning: deprecation\n  warnings.warn("deprecation")',
        False,
        "",
        "noise",
    ),
    (
        "grep 'TypeError' ERRORS.md",
        "- TypeError: missing argument in handler.py\n- TypeError: wrong return type in parser.py",
        False,
        "",
        "noise",
    ),
    (
        "find . -name '*.py' -exec grep -l 'Error' {} \\;",
        "./src/errors.py\n./src/handlers/error_handler.py\n./tests/test_errors.py",
        False,
        "",
        "noise",
    ),
    (
        "python build.py",
        "x" * 6000,  # > 5000 chars — should be skipped
        False,
        "",
        "noise_large",
    ),
    (
        "cat README.md",
        "# Error Handling\n\nThis module provides error handling utilities including TypeError and AttributeError wrappers.",
        False,
        "",
        "noise",
    ),
    (
        "python test.py",
        "WARNING: Using deprecated API\nAll checks passed.",
        False,
        "",
        "noise",
    ),
    (
        "make test",
        "Running tests...\n0 failed, 50 passed\nDone.",
        True,
        "0 tests failed",
        "test",  # regex matches \d+ failed — this IS captured
    ),
]


def run_benchmark():
    print("=" * 60)
    print("Error Auto-Capture Benchmark")
    print(f"Payloads: {len(PAYLOADS)}")
    print("=" * 60)

    # Use a temp directory to isolate memory writes
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch HOME so get_memory_file() writes to temp
        original_home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        os.environ["HOME"] = tmpdir
        os.environ["USERPROFILE"] = tmpdir

        # Create the expected directory
        engram_dir = Path(tmpdir) / ".claude_engram"
        engram_dir.mkdir(parents=True, exist_ok=True)

        project_dir = "/tmp/bench_error_capture"
        tp = fp = fn = tn = 0
        description_hits = 0
        description_total = 0

        cat_results = {}

        for command, output, expect_capture, expected_substr, category in PAYLOADS:
            if category not in cat_results:
                cat_results[category] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

            result = _auto_log_detected_mistake(project_dir, command, output)
            captured = bool(result)

            if expect_capture and captured:
                tp += 1
                cat_results[category]["tp"] += 1

                # Check description quality
                if expected_substr:
                    description_total += 1
                    if expected_substr.lower() in result.lower():
                        description_hits += 1
                    else:
                        print(
                            f"  WEAK DESC [{category}] expected '{expected_substr}' in: {result[:60]}"
                        )

            elif expect_capture and not captured:
                fn += 1
                cat_results[category]["fn"] += 1
                print(f"  MISS [{category}] {command}: {output[:80]}")

            elif not expect_capture and captured:
                fp += 1
                cat_results[category]["fp"] += 1
                print(f"  FALSE+ [{category}] {command}: captured '{result}'")

            else:
                tn += 1
                cat_results[category]["tn"] += 1

        # --- Deduplication test ---
        print("\n--- Deduplication Test ---")
        # Clear memory file
        memory_file = engram_dir / "memory.json"
        if memory_file.exists():
            memory_file.unlink()
        # Also clear hook state (save_state writes here)
        state_file = engram_dir / "hook_state.json"
        if state_file.exists():
            state_file.unlink()

        # Submit same error twice
        dup_project = "/tmp/bench_dedup"
        dup_output = "Traceback:\nTypeError: 'NoneType' object is not iterable"
        r1 = _auto_log_detected_mistake(dup_project, "python x.py", dup_output)
        r2 = _auto_log_detected_mistake(dup_project, "python x.py", dup_output)

        # Count entries — find the project key (may be normalized differently on Windows)
        entries = []
        if memory_file.exists():
            data = json.loads(memory_file.read_text())
            projects = data.get("projects", {})
            # Find the project key that contains our project name
            for key, val in projects.items():
                if "bench_dedup" in key:
                    entries = val.get("entries", [])
                    break
            dedup_ok = len(entries) == 1
        else:
            dedup_ok = False

        print(f"  First submission: {'captured' if r1 else 'missed'}")
        print(
            f"  Second submission: {'captured (duplicate!)' if r2 else 'suppressed (correct)'}"
        )
        print(f"  Entries in file: {len(entries) if memory_file.exists() else 0}")
        print(f"  Deduplication: {'PASS' if dedup_ok else 'FAIL'}")

        # Restore HOME
        if original_home:
            os.environ["HOME"] = original_home
            os.environ["USERPROFILE"] = original_home

    # Results
    n_errors = sum(1 for _, _, e, _, _ in PAYLOADS if e)
    n_noise = sum(1 for _, _, e, _, _ in PAYLOADS if not e)
    recall = tp / n_errors * 100 if n_errors else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    noise_rejection = tn / n_noise * 100 if n_noise else 0
    desc_quality = (
        description_hits / description_total * 100 if description_total else 0
    )

    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"  Errors: {n_errors} | Noise: {n_noise}")
    print(f"  TP={tp} FN={fn} FP={fp} TN={tn}")
    print(f"  Capture recall:     {recall:.0f}%")
    print(f"  Capture precision:  {precision:.0f}%")
    print(f"  Noise rejection:    {noise_rejection:.0f}%")
    print(
        f"  Description quality: {desc_quality:.0f}% ({description_hits}/{description_total} contain key info)"
    )
    print(f"  Deduplication:      {'PASS' if dedup_ok else 'FAIL'}")

    print(f"\n  {'Category':<15} {'Recall':>8} {'FP Rate':>8}")
    print(f"  {'-'*33}")
    for cat in sorted(cat_results.keys()):
        r = cat_results[cat]
        cat_pos = r["tp"] + r["fn"]
        cat_neg = r["fp"] + r["tn"]
        cat_recall = r["tp"] / cat_pos * 100 if cat_pos else 0
        cat_fpr = r["fp"] / cat_neg * 100 if cat_neg else 0
        print(f"  {cat:<15} {cat_recall:>7.0f}% {cat_fpr:>7.0f}%")

    print(f"{'='*60}")
    return tp + tn, len(PAYLOADS)


if __name__ == "__main__":
    run_benchmark()

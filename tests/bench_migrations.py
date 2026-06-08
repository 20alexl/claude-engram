"""
Benchmark: data migrations + the file-ref extractor fix.

Covers the idempotent migration harness (handoff-history seeding + related_files
re-extraction) and the extract_file_refs fix that captures full paths. All on a
temp storage dir — the real ~/.claude_engram is untouched.

Run: python tests/bench_migrations.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram import migrations as M
from claude_engram.tools.memory import extract_file_refs

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def test_extractor():
    print("extract_file_refs (the root #5 fix):")
    check(
        "captures relative path with dirs",
        "service-a/myapp/x.py" in extract_file_refs("import from service-a/myapp/x.py"),
    )
    check(
        "captures Windows drive path",
        "C:/ws/service-b/engine.py"
        in extract_file_refs("err in C:/ws/service-b/engine.py at line 3"),
    )
    check(
        "captures bare basename when no dir",
        "middleware.py" in extract_file_refs("fix middleware.py now"),
    )
    check(
        "never returns a bare extension token",
        "py" not in extract_file_refs("a.py and b.py changed"),
    )


def test_migrations():
    print("migrations (hermetic temp storage):")
    with tempfile.TemporaryDirectory() as td:
        storage = Path(td)
        h = "abc12345"
        (storage / "projects" / h).mkdir(parents=True)
        (storage / "checkpoints").mkdir(parents=True)
        (storage / "manifest.json").write_text(
            json.dumps({"version": "v3", "projects": {"e:/ws/proj": {"hash": h}}})
        )
        mem = {
            "entries": [
                {
                    "id": "m1",
                    "content": "ImportError: cannot import X from 'e:/ws/proj/service-a/core/__init__.py'",
                    "related_files": ["__init__.py"],
                },
                {
                    "id": "m2",
                    "content": "no files referenced here",
                    "related_files": [],
                },
            ]
        }
        (storage / "projects" / h / "memory.json").write_text(json.dumps(mem))
        (storage / "projects" / h / "latest_handoff.json").write_text(
            json.dumps(
                {
                    "created": 111,
                    "summary": "old manual handoff",
                    "next_steps": ["do x"],
                }
            )
        )

        mem_file = storage / "projects" / h / "memory.json"

        # Cheap-only run: seeds handoff history, leaves heavy pending.
        r1 = M.run(storage_dir=str(storage), include_heavy=False)
        check("cheap step applied", "0.5.0:seed_handoff_history" in r1["applied"])
        check("heavy reported pending", r1["pending_heavy"] is True)
        check(
            "handoff history seeded",
            (storage / "projects" / h / "handoff_history.json").exists(),
        )
        seeded = json.loads(
            (storage / "projects" / h / "handoff_history.json").read_text()
        )
        check(
            "seeded history preserves the old handoff",
            seeded["handoffs"][0]["summary"] == "old manual handoff",
        )
        check(
            "related_files untouched by cheap run",
            json.loads(mem_file.read_text())["entries"][0]["related_files"]
            == ["__init__.py"],
        )

        # Heavy run: upgrades related_files to full paths.
        r2 = M.run(storage_dir=str(storage), include_heavy=True)
        check("heavy step applied", "0.5.0:reextract_related_files" in r2["applied"])
        m1 = json.loads(mem_file.read_text())["entries"][0]
        check(
            "related_files upgraded to full path",
            any(f.endswith("service-a/core/__init__.py") for f in m1["related_files"]),
        )
        check(
            "bare __init__.py dropped (covered by full path)",
            "__init__.py" not in m1["related_files"],
        )

        # Idempotency.
        r3 = M.run(storage_dir=str(storage), include_heavy=True)
        check("idempotent — nothing re-applied", r3["applied"] == [])
        check(
            "heavy_pending false after full migration",
            M.heavy_pending(storage_dir=str(storage)) is False,
        )

    # Fresh install (no manifest) is a clean no-op.
    with tempfile.TemporaryDirectory() as td2:
        r4 = M.run(storage_dir=td2, include_heavy=False)
        check(
            "fresh install is a no-op",
            r4["applied"] == [] and r4["pending_heavy"] is False,
        )
        check(
            "fresh install: heavy not pending",
            M.heavy_pending(storage_dir=td2) is False,
        )


if __name__ == "__main__":
    print("=" * 60)
    print("Migrations + Extractor Benchmark")
    print("=" * 60)
    test_extractor()
    test_migrations()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

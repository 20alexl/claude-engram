#!/usr/bin/env python3
"""
Benchmark: Compaction survival.

Tests that rules and mistakes survive the PreCompact -> PostCompact cycle.
Validates the core promise: your critical context isn't lost when Claude's
context window compresses.

Usage:
    python tests/bench_compaction_survival.py
"""
import json
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def seed_memory_file(memory_file: Path, project_path: str, entries: list):
    """Write a memory.json with the given entries for a project."""
    norm_path = project_path.replace("\\", "/").rstrip("/")
    data = {
        "version": 2,
        "global": [],
        "projects": {
            norm_path: {
                "project_path": norm_path,
                "project_name": Path(project_path).name,
                "entries": entries,
                "recent_searches": [],
                "last_updated": time.time(),
            }
        },
    }
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(json.dumps(data, indent=2))


def load_memory_entries(memory_file: Path, project_path: str) -> list:
    """Read entries from memory.json for a project."""
    if not memory_file.exists():
        return []
    data = json.loads(memory_file.read_text())
    norm_path = project_path.replace("\\", "/").rstrip("/")
    project = data.get("projects", {}).get(norm_path, {})
    return project.get("entries", [])


def make_entry(content, category="discovery", relevance=5):
    """Create a memory entry dict."""
    import hashlib

    return {
        "id": hashlib.md5(content.encode()).hexdigest()[:12],
        "content": content,
        "category": category,
        "source": "test",
        "relevance": relevance,
        "created_at": time.time(),
        "last_accessed": time.time(),
        "access_count": 1,
        "tags": [category] if category in ("rule", "mistake") else [],
        "related_files": [],
    }


# ============================================================================
# Test cases
# ============================================================================

CASES = [
    {
        "name": "Rules survive compaction",
        "entries": [
            make_entry("Always use parameterized queries", "rule", 9),
            make_entry("Never commit secrets to the repo", "rule", 9),
            make_entry("Always run tests before committing", "rule", 9),
            make_entry("Project uses React 18", "discovery", 5),
            make_entry("API uses REST", "discovery", 4),
        ],
        "expect_survive": ["parameterized", "secrets", "tests before"],
        "expect_category": "rule",
    },
    {
        "name": "Mistakes survive compaction",
        "entries": [
            make_entry("MISTAKE: forgot to validate input", "mistake", 9),
            make_entry("MISTAKE: migration broke production", "mistake", 9),
            make_entry("MISTAKE: committed .env file", "mistake", 9),
            make_entry("Database uses PostgreSQL", "discovery", 6),
            make_entry("Frontend uses Tailwind", "discovery", 4),
        ],
        "expect_survive": ["validate input", "migration broke", ".env file"],
        "expect_category": "mistake",
    },
    {
        "name": "Rules and mistakes both survive (mixed)",
        "entries": [
            make_entry("Always validate input at boundaries", "rule", 9),
            make_entry("MISTAKE: SQL injection in search", "mistake", 9),
            make_entry("DECISION: use FastAPI", "decision", 7),
            make_entry("Project uses monorepo", "discovery", 4),
            make_entry("CI on GitHub Actions", "context", 3),
        ],
        "expect_survive": ["validate input", "SQL injection"],
        "expect_category": None,  # mixed
    },
    {
        "name": "Empty project doesn't crash",
        "entries": [],
        "expect_survive": [],
        "expect_category": None,
    },
    {
        "name": "Discoveries do NOT appear in critical inject",
        "entries": [
            make_entry("Project uses Docker", "discovery", 6),
            make_entry("API versioned at /v2/", "discovery", 5),
            make_entry("Always use type hints", "rule", 9),
        ],
        "expect_survive": ["type hints"],
        "expect_not_survive_alone": [
            "Docker",
            "/v2/",
        ],  # discoveries shouldn't be in rules/mistakes
        "expect_category": "rule",
    },
    {
        "name": "High-relevance entries preserved",
        "entries": [
            make_entry("Critical rule: never delete production data", "rule", 10),
            make_entry("Low-priority note about formatting", "context", 2),
        ],
        "expect_survive": ["never delete production"],
        "expect_category": "rule",
    },
]


def simulate_compaction(memory_file: Path, project_path: str) -> dict:
    """
    Simulate PreCompact + PostCompact cycle.

    PreCompact: reads memory, saves checkpoint (rules + mistakes)
    PostCompact: re-reads memory, extracts rules + mistakes for re-injection
    """
    norm_path = project_path.replace("\\", "/").rstrip("/")

    # === PreCompact phase ===
    # Load all entries
    entries = load_memory_entries(memory_file, project_path)

    # Save checkpoint (what PreCompact does)
    checkpoint = {
        "timestamp": time.time(),
        "project": project_path,
        "total_entries": len(entries),
        "rules": [e for e in entries if e.get("category") == "rule"],
        "mistakes": [e for e in entries if e.get("category") == "mistake"],
    }

    # === PostCompact phase ===
    # Re-read memory (simulates what PostCompact does)
    entries_after = load_memory_entries(memory_file, project_path)

    # Extract rules and mistakes for re-injection
    rules = [e["content"] for e in entries_after if e.get("category") == "rule"]
    mistakes = [e["content"] for e in entries_after if e.get("category") == "mistake"]
    decisions = [e["content"] for e in entries_after if e.get("category") == "decision"]

    # Build the re-injection text (what PostCompact outputs)
    lines = []
    if rules:
        lines.append("Rules:")
        for r in rules[:5]:
            lines.append(f"  - {r[:100]}")
    if mistakes:
        lines.append("Past mistakes:")
        for m in mistakes[:5]:
            lines.append(f"  - {m[:100]}")

    reinject_text = "\n".join(lines)

    return {
        "checkpoint": checkpoint,
        "reinject_text": reinject_text,
        "rules_found": rules,
        "mistakes_found": mistakes,
        "decisions_found": decisions,
        "total_entries_before": len(entries),
        "total_entries_after": len(entries_after),
    }


def run_benchmark():
    print("=" * 60)
    print("Compaction Survival Benchmark")
    print("=" * 60)

    passed = 0
    failed = 0

    for case in CASES:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_file = Path(tmpdir) / "memory.json"
            project_path = "/tmp/bench_compact_project"

            # Seed memory
            seed_memory_file(memory_file, project_path, case["entries"])

            # Simulate compaction
            result = simulate_compaction(memory_file, project_path)

            # Check expected survivors
            all_survived_text = " ".join(
                result["rules_found"] + result["mistakes_found"]
            ).lower()

            case_pass = True

            # Check expected survivors
            for expected in case.get("expect_survive", []):
                if expected.lower() not in all_survived_text:
                    case_pass = False
                    break

            # Check that discoveries don't leak into rules/mistakes list
            for should_not in case.get("expect_not_survive_alone", []):
                if should_not.lower() in all_survived_text:
                    # It's in rules+mistakes but shouldn't be (it's a discovery)
                    # Only fail if it's NOT also a rule/mistake
                    is_rule_or_mistake = any(
                        should_not.lower() in e["content"].lower()
                        for e in case["entries"]
                        if e["category"] in ("rule", "mistake")
                    )
                    if not is_rule_or_mistake:
                        case_pass = False

            # Check entry count consistency
            if result["total_entries_before"] != result["total_entries_after"]:
                case_pass = False

            if case_pass:
                passed += 1
                status = "PASS"
            else:
                failed += 1
                status = "FAIL"

            print(f"\n  [{status}] {case['name']}")
            print(
                f"    Entries: {result['total_entries_before']} before, {result['total_entries_after']} after"
            )
            print(f"    Rules survived: {len(result['rules_found'])}")
            print(f"    Mistakes survived: {len(result['mistakes_found'])}")
            if result["reinject_text"]:
                # Show first 2 lines of reinject
                preview = result["reinject_text"].split("\n")[:3]
                print(f"    Reinject preview: {' | '.join(preview)}")

            if not case_pass:
                missing = [
                    e
                    for e in case.get("expect_survive", [])
                    if e.lower() not in all_survived_text
                ]
                if missing:
                    print(f"    MISSING: {missing}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{passed + failed} passed")
    print("=" * 60)

    return passed, passed + failed


if __name__ == "__main__":
    run_benchmark()

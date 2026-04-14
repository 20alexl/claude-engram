"""
Benchmark: Memory scoring precision.

Tests whether the right memory ranks #1 when editing a file.
Simulates a project with diverse memories and checks that file-relevant
memories are surfaced over irrelevant ones.
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.tools.memory import MemoryStore, HotMemoryReader


def setup_test_project(m: MemoryStore, project: str):
    """Create a realistic project with diverse memories."""
    memories = [
        # Auth-related
        (
            "Auth uses JWT tokens validated in middleware",
            "discovery",
            8,
            ["auth", "security"],
            ["auth/middleware.py"],
        ),
        (
            "MISTAKE: removed session check from auth, broke all routes",
            "mistake",
            9,
            ["auth", "mistake"],
            ["auth/middleware.py"],
        ),
        (
            "Auth tokens expire after 24 hours",
            "discovery",
            6,
            ["auth"],
            ["auth/tokens.py"],
        ),
        # Database-related
        (
            "Database uses PostgreSQL with pgbouncer connection pooling",
            "discovery",
            7,
            ["database"],
            ["db/pool.py"],
        ),
        (
            "MISTAKE: migration failed because column was NOT NULL without default",
            "mistake",
            9,
            ["database", "mistake"],
            ["db/migrations.py"],
        ),
        (
            "Always use parameterized queries",
            "rule",
            9,
            ["database", "security", "rule"],
            ["db/queries.py"],
        ),
        # Frontend-related
        (
            "React components use strict TypeScript",
            "discovery",
            6,
            ["frontend"],
            ["src/App.tsx"],
        ),
        (
            "DECISION: use Tailwind instead of styled-components",
            "decision",
            7,
            ["frontend", "decision"],
            ["src/styles/"],
        ),
        # API-related
        (
            "API rate limiting is 100 req/min per user",
            "discovery",
            5,
            ["api"],
            ["api/routes.py"],
        ),
        (
            "MISTAKE: forgot to validate request body in POST /users",
            "mistake",
            9,
            ["api", "mistake"],
            ["api/routes.py"],
        ),
        # General
        ("Project uses monorepo with turborepo", "discovery", 4, [], []),
        ("CI runs on GitHub Actions", "context", 3, [], [".github/workflows/"]),
        ("Always run tests before committing", "rule", 9, ["testing", "rule"], []),
    ]

    for content, category, relevance, tags, files in memories:
        m.remember_discovery(
            project,
            content,
            category=category,
            relevance=relevance,
            tags=tags,
            related_files=files,
        )


def test_scoring_precision():
    """Test that the right memory ranks #1 for each file context."""
    m = MemoryStore()
    project = "/tmp/bench_scoring"

    setup_test_project(m, project)

    test_cases = [
        # (file_path, tags, expected_keyword_in_top_result)
        ("auth/middleware.py", ["auth"], "auth"),
        ("db/migrations.py", ["database"], "migration"),
        ("db/queries.py", ["database"], "parameterized"),
        ("api/routes.py", ["api"], "api"),
        ("src/App.tsx", ["frontend"], "react"),
        ("auth/tokens.py", ["auth"], "auth"),
    ]

    passed = 0
    total = len(test_cases)

    print("=== Scoring Precision Benchmark ===\n")

    for file_path, tags, expected_keyword in test_cases:
        results = m.score_and_rank(
            project,
            {"file_path": file_path, "tags": tags},
            limit=3,
        )

        if results:
            top_entry, top_score = results[0]
            top_content = top_entry.content.lower()
            hit = expected_keyword.lower() in top_content

            if hit:
                passed += 1
                status = "PASS"
            else:
                status = "FAIL"

            print(f"  [{status}] {file_path}")
            print(f"    Top: ({top_score:.3f}) {top_entry.content[:70]}")
            if not hit:
                print(f"    Expected keyword: '{expected_keyword}'")
        else:
            print(f"  [FAIL] {file_path} — no results")

    print(f"\nPrecision: {passed}/{total} ({passed*100//total}%)")

    # Also test HotMemoryReader gives same results
    reader = HotMemoryReader()
    reader_match = 0
    for file_path, tags, expected_keyword in test_cases:
        results = reader.get_scored_memories(
            project, {"file_path": file_path, "tags": tags}, limit=1
        )
        if results and expected_keyword.lower() in results[0]["content"].lower():
            reader_match += 1

    print(f"HotMemoryReader agreement: {reader_match}/{total}")

    # Cleanup
    m.forget_project(project)
    return passed, total


def test_category_bonus():
    """Test that rules and mistakes rank higher than discoveries."""
    m = MemoryStore()
    project = "/tmp/bench_bonus"

    # Same file, different categories
    m.remember_discovery(
        project,
        "Auth handler processes requests",
        category="discovery",
        relevance=5,
        related_files=["auth.py"],
    )
    m.remember_discovery(
        project,
        "MISTAKE: auth handler crashed on empty token",
        category="mistake",
        relevance=5,
        related_files=["auth.py"],
    )
    m.remember_discovery(
        project,
        "Always validate tokens in auth handler",
        category="rule",
        relevance=5,
        related_files=["auth.py"],
    )

    results = m.score_and_rank(project, {"file_path": "auth.py"}, limit=3)

    print("\n=== Category Bonus Benchmark ===\n")
    for entry, score in results:
        print(f"  ({score:.3f}) [{entry.category}] {entry.content[:60]}")

    # Rule should be #1, mistake #2, discovery #3
    categories = [entry.category for entry, _ in results]
    expected = ["rule", "mistake", "discovery"]
    match = categories == expected

    print(f"\nOrder: {categories}")
    print(f"Expected: {expected}")
    print(f"Result: {'PASS' if match else 'FAIL'}")

    m.forget_project(project)
    return 1 if match else 0, 1


def test_parent_inheritance():
    """Test that workspace memories are visible from sub-projects."""
    m = MemoryStore()

    # Workspace-level rule
    m.remember_discovery(
        "/tmp/workspace",
        "Always run linter before commit",
        category="rule",
        relevance=9,
    )
    # Sub-project memory
    m.remember_discovery(
        "/tmp/workspace/backend",
        "Backend uses FastAPI",
        category="discovery",
        relevance=7,
        related_files=["main.py"],
    )

    reader = HotMemoryReader()
    results = reader.get_scored_memories(
        "/tmp/workspace/backend", {"file_path": "main.py"}, limit=5
    )
    contents = [r["content"] for r in results]

    print("\n=== Parent Inheritance Benchmark ===\n")
    has_workspace = any("linter" in c for c in contents)
    has_subproject = any("FastAPI" in c for c in contents)

    print(f"  Workspace rule visible: {has_workspace}")
    print(f"  Sub-project memory visible: {has_subproject}")
    print(f"  Result: {'PASS' if (has_workspace and has_subproject) else 'FAIL'}")

    m.forget_project("/tmp/workspace")
    m.forget_project("/tmp/workspace/backend")
    return 1 if (has_workspace and has_subproject) else 0, 1


def test_token_efficiency():
    """Measure tokens per response for common operations."""
    from claude_engram.schema import MiniClaudeResponse, WorkLog

    print("\n=== Token Efficiency Benchmark ===\n")

    cases = [
        ("Simple success", MiniClaudeResponse(status="success", reasoning="Done")),
        (
            "Memory search (3)",
            MiniClaudeResponse(
                status="success",
                reasoning="Found 3",
                data={
                    "memories": [
                        {
                            "id": "a",
                            "content": "Auth uses JWT",
                            "relevance": 8,
                            "tags": ["auth"],
                        },
                        {
                            "id": "b",
                            "content": "DB uses Postgres",
                            "relevance": 6,
                            "tags": ["db"],
                        },
                        {
                            "id": "c",
                            "content": "MISTAKE: broke CI",
                            "relevance": 9,
                            "tags": ["mistake"],
                        },
                    ]
                },
            ),
        ),
        (
            "Archive status",
            MiniClaudeResponse(
                status="success",
                reasoning="Hot: 12 | Archive: 5",
                data={"hot": 12, "archive": 5, "categories": {"rule": 3, "mistake": 4}},
            ),
        ),
        (
            "Error",
            MiniClaudeResponse(
                status="failed",
                reasoning="Project not found",
                work_log=WorkLog(what_failed=["lookup"]),
            ),
        ),
    ]

    for name, response in cases:
        output = response.to_formatted_string()
        tokens = len(output) // 4  # rough estimate
        print(f"  {name}: {len(output)} chars, ~{tokens} tokens")

    print()


if __name__ == "__main__":
    total_passed = 0
    total_tests = 0

    p, t = test_scoring_precision()
    total_passed += p
    total_tests += t

    p, t = test_category_bonus()
    total_passed += p
    total_tests += t

    p, t = test_parent_inheritance()
    total_passed += p
    total_tests += t

    test_token_efficiency()

    print(f"=== TOTAL: {total_passed}/{total_tests} benchmarks passed ===")

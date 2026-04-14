#!/usr/bin/env python3
"""
Benchmark: Injection relevance.

Tests whether the scoring formula surfaces the RIGHT memories before edits.
This validates the core product behavior — not just search, but contextual
injection based on file match, tags, recency, category bonuses.

Usage:
    python tests/bench_injection_relevance.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_engram.tools.memory import MemoryStore, HotMemoryReader


# ============================================================================
# Memory seeds: (content, category, relevance, tags, related_files)
# ============================================================================

MEMORY_SEEDS = [
    # --- Auth domain (8) ---
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
        "Auth tokens expire after 24 hours by default",
        "discovery",
        6,
        ["auth"],
        ["auth/tokens.py"],
    ),
    (
        "Always check token expiry before processing requests",
        "rule",
        9,
        ["auth", "rule"],
        ["auth/middleware.py"],
    ),
    (
        "DECISION: use bcrypt for password hashing over argon2",
        "decision",
        7,
        ["auth", "security"],
        ["auth/passwords.py"],
    ),
    (
        "Auth rate limiting: 5 failed attempts locks account",
        "discovery",
        5,
        ["auth"],
        ["auth/rate_limit.py"],
    ),
    (
        "MISTAKE: forgot to hash password before storing",
        "mistake",
        9,
        ["auth"],
        ["auth/passwords.py"],
    ),
    (
        "OAuth2 flow uses PKCE for mobile clients",
        "discovery",
        6,
        ["auth", "oauth"],
        ["auth/oauth.py"],
    ),
    # --- Database domain (8) ---
    (
        "Database uses PostgreSQL with pgbouncer pooling",
        "discovery",
        7,
        ["database"],
        ["db/pool.py"],
    ),
    (
        "MISTAKE: migration failed, column NOT NULL without default",
        "mistake",
        9,
        ["database", "mistake"],
        ["db/migrations.py"],
    ),
    (
        "Always use parameterized queries to prevent SQL injection",
        "rule",
        9,
        ["database", "security", "rule"],
        ["db/queries.py"],
    ),
    (
        "Connection pool size is 20 for production",
        "discovery",
        5,
        ["database"],
        ["db/pool.py"],
    ),
    (
        "DECISION: use Alembic for migrations over raw SQL",
        "decision",
        7,
        ["database"],
        ["db/migrations.py"],
    ),
    (
        "Database indices on user_id and created_at columns",
        "discovery",
        4,
        ["database"],
        ["db/models.py"],
    ),
    (
        "Always wrap multi-table updates in transactions",
        "rule",
        8,
        ["database", "rule"],
        ["db/queries.py"],
    ),
    (
        "MISTAKE: N+1 query in user list endpoint",
        "mistake",
        8,
        ["database", "api"],
        ["db/queries.py", "api/users.py"],
    ),
    # --- API domain (7) ---
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
        ["api/routes.py", "api/users.py"],
    ),
    (
        "Always return proper error codes with messages",
        "rule",
        8,
        ["api", "rule"],
        ["api/routes.py"],
    ),
    (
        "API versioning uses URL prefix /v1/, /v2/",
        "discovery",
        6,
        ["api"],
        ["api/routes.py"],
    ),
    (
        "DECISION: use FastAPI over Flask for new endpoints",
        "decision",
        7,
        ["api"],
        ["api/routes.py"],
    ),
    (
        "Pagination defaults to 20 items per page",
        "discovery",
        4,
        ["api"],
        ["api/pagination.py"],
    ),
    (
        "API health check at /health returns service status",
        "discovery",
        3,
        ["api"],
        ["api/health.py"],
    ),
    # --- Frontend domain (7) ---
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
        ["frontend", "css"],
        ["src/styles/"],
    ),
    (
        "MISTAKE: forgot SSR hydration mismatch check",
        "mistake",
        8,
        ["frontend"],
        ["src/App.tsx"],
    ),
    (
        "Use React.memo for expensive list renders",
        "rule",
        7,
        ["frontend", "rule"],
        ["src/components/"],
    ),
    (
        "Frontend state managed with Zustand",
        "discovery",
        5,
        ["frontend", "state"],
        ["src/store.ts"],
    ),
    (
        "MISTAKE: bundled devDependencies in production build",
        "mistake",
        7,
        ["frontend"],
        ["package.json"],
    ),
    (
        "Dark mode toggle stored in localStorage",
        "discovery",
        3,
        ["frontend"],
        ["src/theme.ts"],
    ),
    # --- CI/CD domain (5) ---
    ("CI runs on GitHub Actions", "discovery", 4, ["ci"], [".github/workflows/ci.yml"]),
    (
        "Always run tests before deploying",
        "rule",
        9,
        ["ci", "testing", "rule"],
        [".github/workflows/"],
    ),
    (
        "Deploy uses blue-green strategy",
        "discovery",
        5,
        ["ci", "deploy"],
        [".github/workflows/deploy.yml"],
    ),
    (
        "MISTAKE: CI passed but deploy failed due to missing env var",
        "mistake",
        8,
        ["ci"],
        [".github/workflows/deploy.yml"],
    ),
    (
        "Docker images tagged with git SHA",
        "discovery",
        4,
        ["ci", "docker"],
        ["Dockerfile"],
    ),
    # --- Config/general (5) ---
    ("Project uses monorepo with turborepo", "discovery", 4, [], []),
    ("Always run linter before committing", "rule", 9, ["rule"], []),
    (
        "Log format is structured JSON",
        "discovery",
        3,
        ["logging"],
        ["config/logging.py"],
    ),
    (
        "MISTAKE: committed .env file with production secrets",
        "mistake",
        10,
        ["security"],
        [".env", ".gitignore"],
    ),
    (
        "Environment variables loaded from .env via python-dotenv",
        "discovery",
        5,
        ["config"],
        ["config/settings.py"],
    ),
]


# ============================================================================
# Test cases: (file_path, tags, must_contain_keywords, must_not_contain_keywords, description)
# ============================================================================

TEST_CASES = [
    # --- Exact file match (rules/mistakes rank higher than discoveries) ---
    (
        "auth/middleware.py",
        ["auth"],
        ["session check", "token expiry"],  # mistake + rule for this file
        ["PostgreSQL", "React", "Tailwind"],
        "exact file: auth middleware (mistakes+rules dominate)",
    ),
    (
        "db/queries.py",
        ["database"],
        ["parameterized", "SQL injection"],  # rule for this exact file
        ["React", "OAuth", "Tailwind"],
        "exact file: db queries",
    ),
    (
        "db/migrations.py",
        ["database"],
        ["migration", "NOT NULL"],  # mistake for this exact file
        ["JWT", "React"],
        "exact file: db migrations",
    ),
    (
        "api/routes.py",
        ["api"],
        ["validate"],  # mistake about validation is top priority
        ["JWT", "React"],
        "exact file: api routes (mistakes first)",
    ),
    (
        "src/App.tsx",
        ["frontend"],
        ["React", "hydration"],
        ["PostgreSQL", "migration", "parameterized"],
        "exact file: frontend app",
    ),
    # --- Same directory (no exact file match) ---
    (
        "auth/sessions.py",
        ["auth"],
        ["auth"],  # should pick up auth/* memories (rules+mistakes dominate)
        ["React", "PostgreSQL"],
        "same dir: auth sessions",
    ),
    (
        "db/models.py",
        ["database"],
        [
            "migration"
        ],  # mistakes/rules for db/ ranked higher than discovery about indices
        ["React", "OAuth"],
        "same dir: db models (rules dominate over discoveries)",
    ),
    (
        "api/middleware.py",
        ["api"],
        ["validate"],  # api mistake ranks high
        ["React"],
        "same dir: api middleware",
    ),
    # --- Category bonus: rule > mistake > discovery ---
    (
        "auth/middleware.py",
        ["auth"],
        ["Always check token"],  # rule should rank highest
        [],
        "category bonus: rule ranks top for auth",
    ),
    # --- Cross-domain isolation ---
    (
        "src/components/Button.tsx",
        ["frontend"],
        [],
        ["PostgreSQL", "migration", "SQL injection"],
        "isolation: frontend file should NOT surface db memories",
    ),
    (
        "db/pool.py",
        ["database"],
        [],
        ["React", "Tailwind", "SSR hydration"],
        "isolation: db file should NOT surface frontend memories",
    ),
    # --- General rules surface when relevant ---
    (
        "auth/handler.py",
        ["auth"],
        ["auth"],  # auth-specific should dominate
        ["React", "Tailwind"],
        "auth file gets auth memories, not frontend",
    ),
    (
        "src/App.tsx",
        ["frontend"],
        ["React"],  # frontend-specific should dominate
        ["PostgreSQL", "migration"],
        "frontend file gets frontend memories, not db",
    ),
    # --- Tag-only relevance ---
    (
        "services/auth_service.py",
        ["auth", "security"],
        ["auth"],
        ["React", "Tailwind"],
        "tag match: new path but auth tags",
    ),
    # --- No relevant memories ---
    (
        "scripts/deploy.sh",
        ["devops"],
        [],
        [],
        "low relevance: deploy script has few matches",
    ),
]


def run_benchmark():
    m = MemoryStore()
    project = "/tmp/bench_injection"

    # Clean slate
    m.forget_project(project)

    # Seed memories
    print("Seeding memories...")
    for content, category, relevance, tags, files in MEMORY_SEEDS:
        m.remember_discovery(
            project,
            content,
            category=category,
            relevance=relevance,
            tags=tags,
            related_files=files,
            auto_embed=False,
        )

    # Try embedding if available
    try:
        m.embed_all_memories(project)
        print("  Embeddings generated")
    except Exception:
        print("  No embeddings (AllMiniLM not available)")

    print(f"  {len(MEMORY_SEEDS)} memories stored\n")

    # Run test cases
    print("=" * 60)
    print("Injection Relevance Benchmark")
    print("=" * 60)

    passed = 0
    failed = 0
    total_must_contain = 0
    found_must_contain = 0
    total_must_not = 0
    clean_must_not = 0

    for file_path, tags, must_contain, must_not_contain, desc in TEST_CASES:
        results = m.score_and_rank(
            project,
            {"file_path": file_path, "tags": tags},
            limit=3,
        )

        top_contents = " | ".join(
            f"[{e.category}] {e.content[:50]}" for e, s in results
        )
        all_text = " ".join(e.content.lower() for e, _ in results)

        # Check must-contain keywords
        contains_ok = True
        for kw in must_contain:
            total_must_contain += 1
            if kw.lower() in all_text:
                found_must_contain += 1
            else:
                contains_ok = False

        # Check must-not-contain keywords
        excludes_ok = True
        for kw in must_not_contain:
            total_must_not += 1
            if kw.lower() not in all_text:
                clean_must_not += 1
            else:
                excludes_ok = False

        case_pass = contains_ok and excludes_ok
        if case_pass:
            passed += 1
            status = "PASS"
        else:
            failed += 1
            status = "FAIL"

        print(f"\n  [{status}] {desc}")
        print(f"    File: {file_path}")
        print(f"    Top 3: {top_contents}")
        if not contains_ok:
            missing = [kw for kw in must_contain if kw.lower() not in all_text]
            print(f"    MISSING: {missing}")
        if not excludes_ok:
            leaked = [kw for kw in must_not_contain if kw.lower() in all_text]
            print(f"    LEAKED: {leaked}")

    # HotMemoryReader agreement test
    print("\n" + "-" * 60)
    print("HotMemoryReader Agreement")
    print("-" * 60)

    reader = HotMemoryReader()
    agreements = 0
    reader_total = 0

    for file_path, tags, must_contain, _, desc in TEST_CASES:
        if not must_contain:
            continue
        reader_total += 1

        reader_results = reader.get_scored_memories(
            project,
            {"file_path": file_path, "tags": tags},
            limit=3,
        )
        reader_text = " ".join(r["content"].lower() for r in reader_results)

        # Check if reader gets at least one must-contain keyword
        if any(kw.lower() in reader_text for kw in must_contain):
            agreements += 1

    reader_agreement = agreements / reader_total * 100 if reader_total else 0
    print(f"  Agreement: {agreements}/{reader_total} ({reader_agreement:.0f}%)")

    # Cleanup
    m.forget_project(project)

    # Summary
    contain_rate = (
        found_must_contain / total_must_contain * 100 if total_must_contain else 0
    )
    exclude_rate = clean_must_not / total_must_not * 100 if total_must_not else 0

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Cases:     {passed}/{passed + failed} passed")
    print(
        f"  Contain:   {found_must_contain}/{total_must_contain} keywords found ({contain_rate:.0f}%)"
    )
    print(
        f"  Exclude:   {clean_must_not}/{total_must_not} keywords excluded ({exclude_rate:.0f}%)"
    )
    print(f"  Reader:    {reader_agreement:.0f}% agreement with MemoryStore")
    print("=" * 60)

    return passed, passed + failed


if __name__ == "__main__":
    run_benchmark()

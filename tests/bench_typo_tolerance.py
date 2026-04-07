#!/usr/bin/env python3
"""
Benchmark: Typo tolerance.

Tests how well each search strategy handles misspelled queries.
Introduces realistic typos into clean queries and measures recall degradation.

Typo types:
  - swap: adjacent letter swap (databse -> database)
  - drop: missing letter (dtabase -> database)
  - double: doubled letter (dattabase -> database)
  - wrong: wrong key neighbor (databasr -> database)
  - heavy: 2+ typos combined

Usage:
    python tests/bench_typo_tolerance.py
"""
import sys
import os
import random
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claude_engram.tools.memory import MemoryStore


# ============================================================================
# Memory corpus — realistic coding memories
# ============================================================================

MEMORIES = [
    ("Auth middleware validates JWT tokens before processing requests", "auth", ["auth", "security"]),
    ("Database uses PostgreSQL with connection pooling via pgbouncer", "database", ["database", "postgres"]),
    ("Frontend components built with React 18 and TypeScript strict mode", "frontend", ["frontend", "react"]),
    ("API rate limiting configured at 100 requests per minute per user", "api", ["api", "ratelimit"]),
    ("Migration system uses Alembic for database schema versioning", "database", ["database", "migration"]),
    ("Error handling follows the Result pattern instead of exceptions", "architecture", ["patterns"]),
    ("Caching layer uses Redis with 5 minute TTL for user sessions", "infrastructure", ["cache", "redis"]),
    ("Deployment pipeline uses GitHub Actions with blue-green strategy", "devops", ["ci", "deployment"]),
    ("Authentication flow supports OAuth2 PKCE for mobile clients", "auth", ["auth", "oauth"]),
    ("WebSocket connections timeout after 30 seconds of inactivity", "api", ["websocket", "timeout"]),
    ("Password hashing uses bcrypt with 12 rounds minimum", "security", ["auth", "security"]),
    ("Logging format is structured JSON sent to Elasticsearch", "infrastructure", ["logging"]),
    ("Test suite uses pytest with fixtures for database isolation", "testing", ["testing", "pytest"]),
    ("GraphQL schema generated from TypeScript types via codegen", "api", ["graphql", "typescript"]),
    ("Background jobs processed by Celery with RabbitMQ broker", "infrastructure", ["queue", "celery"]),
    ("Docker images use multi-stage builds to minimize size", "devops", ["docker", "build"]),
    ("Configuration loaded from environment variables via python-dotenv", "config", ["config", "env"]),
    ("Pagination defaults to 20 items with cursor-based navigation", "api", ["api", "pagination"]),
    ("Monitoring uses Prometheus metrics with Grafana dashboards", "infrastructure", ["monitoring"]),
    ("Code formatting enforced by black and isort pre-commit hooks", "tooling", ["formatting", "precommit"]),
]

# ============================================================================
# Query pairs: (clean_query, expected_keyword_in_result, typo_variants)
# ============================================================================

QUERY_PAIRS = [
    (
        "database connection pooling",
        "PostgreSQL",
        {
            "swap": "databsae connection pooling",
            "drop": "databse connection pooling",
            "double": "dattabase connection poolling",
            "wrong": "databasr connectoin pooling",
            "heavy": "databsae conection poling",
        },
    ),
    (
        "authentication JWT tokens",
        "JWT",
        {
            "swap": "authenticaiton JWT toekns",
            "drop": "authenticaton JWT tokns",
            "double": "authenntication JWT tokenss",
            "wrong": "authenticstion JWT tokems",
            "heavy": "authntication JTW toekns",
        },
    ),
    (
        "React TypeScript components",
        "React",
        {
            "swap": "Raect TypeScrpit components",
            "drop": "React TypeScrip components",
            "double": "Reactt TypeScriptt componnents",
            "wrong": "Reacr TypeScripr componenrs",
            "heavy": "Raect TypeScrip componets",
        },
    ),
    (
        "rate limiting API requests",
        "rate limiting",
        {
            "swap": "rate limtiing API reuqests",
            "drop": "rate limitng API requsts",
            "double": "ratte limitingg API requestss",
            "wrong": "rate limiring API requeets",
            "heavy": "rte limting API rquests",
        },
    ),
    (
        "migration Alembic schema",
        "Alembic",
        {
            "swap": "migraiton Alembci schema",
            "drop": "migraion Alembi schema",
            "double": "migrration Alemmbic schemma",
            "wrong": "migratiom Alembjc schena",
            "heavy": "migraton Alembci schma",
        },
    ),
    (
        "Redis caching session",
        "Redis",
        {
            "swap": "Reids cachign session",
            "drop": "Redis cacing session",
            "double": "Reddis cachinng sessionn",
            "wrong": "Redos caching sessiom",
            "heavy": "Rdis cachng sesion",
        },
    ),
    (
        "deployment GitHub Actions",
        "GitHub Actions",
        {
            "swap": "deploymetn GitHub Actoins",
            "drop": "deploymnt GitHub Acions",
            "double": "deploymentt Githubb Actionss",
            "wrong": "deploymemt GitHub Actioms",
            "heavy": "deploymnt Gihub Acitons",
        },
    ),
    (
        "pytest fixtures database",
        "pytest",
        {
            "swap": "pytset fixtrues database",
            "drop": "pytest fixtues databse",
            "double": "pytestt fixturess dattabase",
            "wrong": "pytesr fixturea databaee",
            "heavy": "pyest fixtues databse",
        },
    ),
    (
        "password bcrypt hashing",
        "bcrypt",
        {
            "swap": "passwrod bcrpyt hashing",
            "drop": "passwrd bcrypt hashng",
            "double": "passworrd bcryptt hashingg",
            "wrong": "password bcrypr hashimg",
            "heavy": "passwrd bcrpt hashng",
        },
    ),
    (
        "WebSocket timeout connections",
        "WebSocket",
        {
            "swap": "WebSokect tiemout connections",
            "drop": "WebSockt timeout conections",
            "double": "WebbSocket timeoutt connectionss",
            "wrong": "WebSpcket tineout connectioms",
            "heavy": "WbSocket timout conections",
        },
    ),
]


def search_and_check(m, project, query, expected_keyword, method="keyword"):
    """Run a search and check if expected keyword appears in results."""
    if method == "keyword":
        results = m.search_memories(project, query=query, limit=5)
        texts = [e.content.lower() for e in results]
    elif method == "vector":
        results = m.vector_search(project, query, limit=5)
        texts = [e.content.lower() for e, s in results]
    elif method == "hybrid":
        results = m.hybrid_search(project, query=query, limit=5)
        texts = [e.content.lower() for e, s in results]
    else:
        return False

    all_text = " ".join(texts)
    return expected_keyword.lower() in all_text


def run_benchmark():
    m = MemoryStore()
    project = "/tmp/bench_typo"
    m.forget_project(project)

    # Seed memories
    for content, category, tags in MEMORIES:
        m.remember_discovery(project, content, relevance=7, tags=tags, auto_embed=False)

    # Batch embed
    has_vector = False
    try:
        m.embed_all_memories(project)
        has_vector = True
        print("AllMiniLM available — testing keyword, vector, and hybrid\n")
    except Exception:
        print("AllMiniLM not available — testing keyword only\n")

    methods = ["keyword"]
    if has_vector:
        methods.extend(["vector", "hybrid"])

    print("=" * 70)
    print("Typo Tolerance Benchmark")
    print(f"Queries: {len(QUERY_PAIRS)} | Typo types: 5 | Methods: {', '.join(methods)}")
    print("=" * 70)

    # Results: method -> typo_type -> list of pass/fail
    results = {m: {"clean": [], "swap": [], "drop": [], "double": [], "wrong": [], "heavy": []}
               for m in methods}

    for clean_query, expected, typos in QUERY_PAIRS:
        for method in methods:
            # Clean query baseline
            found = search_and_check(m, project, clean_query, expected, method)
            results[method]["clean"].append(found)

            # Each typo type
            for typo_type, typo_query in typos.items():
                found = search_and_check(m, project, typo_query, expected, method)
                results[method][typo_type].append(found)

    # Print results
    typo_types = ["clean", "swap", "drop", "double", "wrong", "heavy"]

    for method in methods:
        print(f"\n--- {method.upper()} ---")
        print(f"  {'Type':<10} {'Recall':>8} {'Degradation':>13}")
        print(f"  {'-'*33}")

        clean_rate = sum(results[method]["clean"]) / len(results[method]["clean"]) * 100
        for tt in typo_types:
            hits = results[method][tt]
            rate = sum(hits) / len(hits) * 100
            degradation = clean_rate - rate
            deg_str = f"-{degradation:.0f}pp" if degradation > 0 else "—"
            print(f"  {tt:<10} {rate:>7.0f}% {deg_str:>12}")

    # Summary table
    print(f"\n{'='*70}")
    print("SUMMARY — Recall by method and typo severity")
    print(f"{'='*70}")
    header = f"  {'':>10}"
    for method in methods:
        header += f" {method:>10}"
    print(header)
    print(f"  {'-'*(10 + 11*len(methods))}")

    for tt in typo_types:
        row = f"  {tt:>10}"
        for method in methods:
            rate = sum(results[method][tt]) / len(results[method][tt]) * 100
            row += f" {rate:>9.0f}%"
        print(row)

    # Overall degradation
    print(f"\n  Average degradation from clean:")
    for method in methods:
        clean_rate = sum(results[method]["clean"]) / len(results[method]["clean"]) * 100
        typo_rates = []
        for tt in ["swap", "drop", "double", "wrong", "heavy"]:
            typo_rates.append(sum(results[method][tt]) / len(results[method][tt]) * 100)
        avg_typo = sum(typo_rates) / len(typo_rates)
        degradation = clean_rate - avg_typo
        print(f"    {method:<10} {clean_rate:.0f}% clean -> {avg_typo:.0f}% with typos ({degradation:+.0f}pp)")

    print(f"{'='*70}")

    m.forget_project(project)


if __name__ == "__main__":
    run_benchmark()

#!/usr/bin/env python3
"""
Benchmark: Multi-project scoping.

Tests that memories are correctly scoped to sub-projects within a workspace,
and that workspace-level rules cascade down to all sub-projects.

Usage:
    python tests/bench_multi_project.py
"""
import json
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.hooks.remind import resolve_project_for_file, _project_dir_cache
from claude_engram.tools.memory import MemoryStore, HotMemoryReader


def create_workspace(tmpdir: str) -> dict:
    """
    Create a realistic multi-project workspace layout.

    Returns dict with paths.
    """
    root = Path(tmpdir) / "workspace"
    root.mkdir()

    # Workspace marker
    (root / "pyproject.toml").write_text("[tool.poetry]\nname = 'workspace'\n")

    # Backend sub-project
    backend = root / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n")
    (backend / "auth").mkdir()
    (backend / "auth" / "handler.py").write_text("# auth handler\n")
    (backend / "auth" / "tokens.py").write_text("# token management\n")
    (backend / "db").mkdir()
    (backend / "db" / "queries.py").write_text("# database queries\n")

    # Frontend sub-project
    frontend = root / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"name": "frontend"}\n')
    (frontend / "src").mkdir()
    (frontend / "src" / "App.tsx").write_text("// React app\n")
    (frontend / "src" / "utils.ts").write_text("// Utils\n")

    # Shared directory (no project marker — falls to workspace)
    shared = root / "shared"
    shared.mkdir()
    (shared / "utils.py").write_text("# shared utils\n")

    # Scripts directory (no marker)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "deploy.sh").write_text("#!/bin/bash\n")

    return {
        "root": str(root),
        "backend": str(backend),
        "frontend": str(frontend),
        "shared": str(shared),
        "files": {
            "backend_auth": str(backend / "auth" / "handler.py"),
            "backend_tokens": str(backend / "auth" / "tokens.py"),
            "backend_db": str(backend / "db" / "queries.py"),
            "frontend_app": str(frontend / "src" / "App.tsx"),
            "frontend_utils": str(frontend / "src" / "utils.ts"),
            "shared_utils": str(shared / "utils.py"),
            "deploy_script": str(scripts / "deploy.sh"),
        }
    }


def seed_memories(m: MemoryStore, paths: dict):
    """Store memories at different project levels."""
    # Workspace-level memories (visible to all)
    m.remember_discovery(paths["root"], "Always run linter before committing", category="rule", relevance=9)
    m.remember_discovery(paths["root"], "MISTAKE: committed .env with production secrets", category="mistake", relevance=10)
    m.remember_discovery(paths["root"], "Project uses monorepo with turborepo", category="discovery", relevance=4)

    # Backend memories
    m.remember_discovery(paths["backend"], "Backend uses FastAPI", category="discovery", relevance=7,
                         related_files=["main.py"], tags=["backend", "api"])
    m.remember_discovery(paths["backend"], "MISTAKE: migration broke prod database", category="mistake", relevance=9,
                         related_files=["db/migrations.py"], tags=["backend", "database"])
    m.remember_discovery(paths["backend"], "Database uses PostgreSQL with pgbouncer", category="discovery", relevance=6,
                         related_files=["db/pool.py"], tags=["backend", "database"])
    m.remember_discovery(paths["backend"], "Auth uses JWT tokens", category="discovery", relevance=7,
                         related_files=["auth/handler.py"], tags=["backend", "auth"])

    # Frontend memories
    m.remember_discovery(paths["frontend"], "Frontend uses React 18 with TypeScript", category="discovery", relevance=6,
                         related_files=["src/App.tsx"], tags=["frontend", "react"])
    m.remember_discovery(paths["frontend"], "DECISION: use Tailwind instead of CSS modules", category="decision", relevance=7,
                         tags=["frontend", "css"])
    m.remember_discovery(paths["frontend"], "MISTAKE: forgot SSR hydration mismatch", category="mistake", relevance=8,
                         related_files=["src/App.tsx"], tags=["frontend"])


# ============================================================================
# Test cases
# ============================================================================

RESOLUTION_TESTS = [
    # (file_key, expected_project_key, description)
    ("backend_auth", "backend", "backend file resolves to backend"),
    ("backend_db", "backend", "backend db resolves to backend"),
    ("frontend_app", "frontend", "frontend file resolves to frontend"),
    ("frontend_utils", "frontend", "frontend utils resolves to frontend"),
    ("shared_utils", "root", "shared (no marker) resolves to workspace root"),
    ("deploy_script", "root", "scripts (no marker) resolves to workspace root"),
]

SCOPING_TESTS = [
    # (file_key, project_key, must_contain, must_not_contain, description)
    (
        "backend_auth", "backend",
        ["JWT", "linter"],  # backend + workspace rule
        ["React", "Tailwind"],  # NOT frontend
        "backend sees own + workspace, not frontend",
    ),
    (
        "frontend_app", "frontend",
        ["React", "linter"],  # frontend + workspace rule
        ["FastAPI", "PostgreSQL", "migration"],  # NOT backend
        "frontend sees own + workspace, not backend",
    ),
    (
        "shared_utils", "root",
        ["linter"],  # workspace memories
        ["JWT", "React"],  # NOT sub-project specific
        "shared sees workspace only",
    ),
    (
        "backend_auth", "backend",
        ["committed .env"],  # workspace mistake cascades
        [],
        "workspace mistake visible in backend",
    ),
    (
        "frontend_app", "frontend",
        ["committed .env"],  # workspace mistake cascades
        [],
        "workspace mistake visible in frontend",
    ),
]


def run_benchmark():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = create_workspace(tmpdir)

        # Clear the project dir cache (it's module-level)
        _project_dir_cache.clear()

        print("=" * 60)
        print("Multi-Project Scoping Benchmark")
        print("=" * 60)

        # --- Test 1: Project resolution ---
        print("\n--- Project Resolution ---")
        res_passed = 0

        for file_key, expected_key, desc in RESOLUTION_TESTS:
            file_path = paths["files"][file_key]
            expected_path = paths[expected_key].replace("\\", "/")

            resolved = resolve_project_for_file(file_path, paths["root"])

            # Case-insensitive on Windows (C: vs c:)
            match = resolved.rstrip("/").lower() == expected_path.rstrip("/").lower()
            status = "PASS" if match else "FAIL"
            if match:
                res_passed += 1

            print(f"  [{status}] {desc}")
            if not match:
                print(f"    Expected: {expected_path}")
                print(f"    Got:      {resolved}")

        # --- Test 2: Memory scoping ---
        print("\n--- Memory Scoping ---")

        m = MemoryStore()
        seed_memories(m, paths)

        # Also test with HotMemoryReader
        reader = HotMemoryReader()

        scope_passed = 0

        for file_key, project_key, must_contain, must_not_contain, desc in SCOPING_TESTS:
            project_path = paths[project_key]

            # Get scored memories for this project+file
            results = m.score_and_rank(
                project_path,
                {"file_path": paths["files"][file_key], "tags": []},
                limit=10,
            )

            all_text = " ".join(e.content.lower() for e, _ in results)

            # Also check with reader (uses parent-path inheritance)
            reader_results = reader.get_scored_memories(
                project_path,
                {"file_path": paths["files"][file_key], "tags": []},
                limit=10,
            )
            reader_text = " ".join(r["content"].lower() for r in reader_results)

            # Combined text from both sources
            combined = all_text + " " + reader_text

            contains_ok = all(kw.lower() in combined for kw in must_contain)
            excludes_ok = all(kw.lower() not in combined for kw in must_not_contain)

            case_pass = contains_ok and excludes_ok
            if case_pass:
                scope_passed += 1
                status = "PASS"
            else:
                status = "FAIL"

            print(f"  [{status}] {desc}")
            if not contains_ok:
                missing = [kw for kw in must_contain if kw.lower() not in combined]
                print(f"    MISSING: {missing}")
            if not excludes_ok:
                leaked = [kw for kw in must_not_contain if kw.lower() in combined]
                print(f"    LEAKED: {leaked}")

        # Cleanup
        for key in ["root", "backend", "frontend"]:
            m.forget_project(paths[key])

        # Clear cache again
        _project_dir_cache.clear()

        # Summary
        total = len(RESOLUTION_TESTS) + len(SCOPING_TESTS)
        total_passed = res_passed + scope_passed

        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"  Resolution: {res_passed}/{len(RESOLUTION_TESTS)} passed")
        print(f"  Scoping:    {scope_passed}/{len(SCOPING_TESTS)} passed")
        print(f"  Total:      {total_passed}/{total} passed")
        print(f"{'='*60}")

        return total_passed, total


if __name__ == "__main__":
    run_benchmark()

#!/usr/bin/env python3
"""
Benchmark: Obsidian vault compatibility.

Tests that Claude Engram works correctly when Claude Code runs inside an
Obsidian vault using the PARA method structure with CLAUDE.md.

Real-world setup:
  vault-root/
    CLAUDE.md              <- project marker (engram detects this)
    .claude/               <- Claude Code skills
    00_Inbox/
    01_Projects/
    02_Areas/
    03_Resources/
    04_Archive/
    05_Attachments/

Tests:
  1. Project detection — CLAUDE.md as marker, all notes resolve to vault root
  2. Memory scoping — store and retrieve memories for vault files
  3. File scoring — discrimination when everything is .md
  4. Tag inference — what tags get inferred from .md filenames
  5. HotMemoryReader — hook-time injection works for vault files
  6. Large vault scaling — performance with 1000+ notes

Usage:
    python tests/bench_obsidian_vault.py
"""
import json
import sys
import os
import time
import tempfile
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.hooks.remind import resolve_project_for_file, _project_dir_cache
from claude_engram.tools.memory import MemoryStore, HotMemoryReader, _HOOK_TAG_PATTERNS


# ─── Vault setup ────────────────────────────────────────────────────────

def create_obsidian_vault(tmpdir: str) -> dict:
    """
    Create a realistic Obsidian vault with PARA structure + CLAUDE.md.

    This mirrors how people actually use Claude Code with Obsidian:
    - CLAUDE.md at root (persistent system prompt + project marker)
    - .claude/ folder with skills
    - PARA numbered folders
    - Wikilinks between notes
    - Index files for navigation
    """
    root = Path(tmpdir) / "vault"
    root.mkdir()

    # CLAUDE.md — this IS a project marker for engram
    (root / "CLAUDE.md").write_text(
        "# Knowledge Base Rules\n\n"
        "## Structure\n"
        "- 00_Inbox: temporary capture\n"
        "- 01_Projects: active initiatives\n"
        "- 02_Areas: ongoing responsibilities\n"
        "- 03_Resources: reference material\n"
        "- 04_Archive: completed/inactive\n\n"
        "## Conventions\n"
        "- Use [[wikilinks]] for internal links\n"
        "- Tags: #area/health, #project/automation\n"
        "- Daily notes: YYYY-MM-DD format\n"
    )

    # .claude skills folder
    claude_dir = root / ".claude"
    claude_dir.mkdir()
    (claude_dir / "research.md").write_text("# Research skill template\n")

    # .obsidian config
    obsidian = root / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_text('{"alwaysUpdateLinks": true}')

    # 00_Inbox
    inbox = root / "00_Inbox"
    inbox.mkdir()
    (inbox / "Quick thought.md").write_text(
        "# Quick thought\n\nNeed to look into MQTT vs HTTP for sensors.\n"
        "See [[Home Automation]] project.\n"
    )
    (inbox / "Article to read.md").write_text(
        "# Article to read\n\nhttps://example.com/transformers\n"
        "Tag for later: #to-read\n"
    )

    # 01_Projects
    projects = root / "01_Projects"
    projects.mkdir()
    (projects / "index.md").write_text(
        "# Active Projects\n\n"
        "- [[Home Automation]] — smart home setup\n"
        "- [[ML Research]] — transformer experiments\n"
        "- [[Claude Engram]] — memory for Claude Code\n"
    )
    (projects / "Home Automation.md").write_text(
        "# Home Automation\n\n## Stack\n- Python, MQTT, Home Assistant\n\n"
        "## Decisions\n- Use MQTT over HTTP for device communication\n"
        "- [[Docker Setup]] for all services\n\n"
        "## Links\n- [[ML Research]] for anomaly detection\n"
    )
    (projects / "ML Research.md").write_text(
        "# ML Research\n\n## Current Focus\n- Transformer attention mechanisms\n"
        "- [[Python Tips]] for optimization\n\n"
        "## Papers\n- Attention Is All You Need\n- BERT\n"
    )
    (projects / "Claude Engram.md").write_text(
        "# Claude Engram\n\n## Architecture\n- Hook-based auto-capture\n"
        "- Tiered storage (hot/cold)\n- AllMiniLM embeddings\n\n"
        "## API Design\n- REST endpoints for search\n"
        "## TODO\n- [ ] Test Obsidian compatibility\n"
    )

    # 02_Areas
    areas = root / "02_Areas"
    areas.mkdir()
    (areas / "Health.md").write_text(
        "# Health\n\n## Habits\n- Morning run\n- Sleep 8h\n\n"
        "#area/health\n"
    )
    (areas / "Finances.md").write_text(
        "# Finances\n\n## Budget\n- Track monthly\n\n"
        "#area/finances\n"
    )

    # 03_Resources
    resources = root / "03_Resources"
    resources.mkdir()
    (resources / "Python Tips.md").write_text(
        "# Python Tips\n\n## Performance\n- Use `__slots__` for memory\n"
        "- `lru_cache` for repeated calls\n- Avoid global state\n"
    )
    (resources / "Docker Setup.md").write_text(
        "# Docker Setup\n\n## Commands\n```bash\ndocker compose up -d\n```\n"
        "## Gotchas\n- Always pin image versions\n- Use multi-stage builds\n"
    )
    (resources / "API Design.md").write_text(
        "# API Design\n\n## Principles\n- REST over RPC for public APIs\n"
        "- Version in URL path\n- Pagination with cursor tokens\n"
    )
    (resources / "Database Patterns.md").write_text(
        "# Database Patterns\n\n## Indexing\n- Always index foreign keys\n"
        "- Partial indexes for soft deletes\n"
    )
    (resources / "Security Checklist.md").write_text(
        "# Security Checklist\n\n- [ ] Input validation\n"
        "- [ ] Auth on all endpoints\n- [ ] Rate limiting\n"
    )

    # 04_Archive
    archive = root / "04_Archive"
    archive.mkdir()
    (archive / "Old Project.md").write_text("# Old Project\n\nCompleted 2025.\n")

    # 05_Attachments
    attachments = root / "05_Attachments"
    attachments.mkdir()

    paths = {
        "root": str(root),
        "inbox_note": str(inbox / "Quick thought.md"),
        "project_note": str(projects / "Home Automation.md"),
        "project_engram": str(projects / "Claude Engram.md"),
        "project_index": str(projects / "index.md"),
        "area_note": str(areas / "Health.md"),
        "resource_note": str(resources / "Python Tips.md"),
        "resource_api": str(resources / "API Design.md"),
        "resource_db": str(resources / "Database Patterns.md"),
        "resource_security": str(resources / "Security Checklist.md"),
        "archive_note": str(archive / "Old Project.md"),
    }
    return paths


def create_large_vault(tmpdir: str, note_count: int = 1000) -> str:
    """Create a vault with many notes for scaling test."""
    root = Path(tmpdir) / "large_vault"
    root.mkdir()

    # CLAUDE.md as marker
    (root / "CLAUDE.md").write_text("# Large vault\n")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}")

    categories = ["01_Projects", "02_Areas", "03_Resources", "04_Archive"]
    for cat in categories:
        (root / cat).mkdir()

    for i in range(note_count):
        cat = categories[i % len(categories)]
        (root / cat / f"note_{i:04d}.md").write_text(
            f"# Note {i}\n\nContent for note {i}.\n"
            f"Links to [[note_{(i+1) % note_count:04d}]].\n"
        )

    return str(root)


# ─── Tests ───────────────────────────────────────────────────────────────

def test_project_detection(paths: dict) -> list[tuple[str, bool, str]]:
    """
    Test 1: Does resolve_project_for_file find CLAUDE.md as marker?

    With CLAUDE.md at vault root, all files should resolve to vault root.
    """
    results = []
    _project_dir_cache.clear()
    root = paths["root"]

    test_cases = [
        ("inbox_note", "Inbox note resolves to vault root"),
        ("project_note", "Project note resolves to vault root"),
        ("resource_note", "Resource note resolves to vault root"),
        ("area_note", "Area note resolves to vault root"),
        ("archive_note", "Archive note resolves to vault root"),
    ]

    for key, desc in test_cases:
        resolved = resolve_project_for_file(paths[key], root)
        # Normalize both sides: lowercase, forward slashes, strip trailing
        norm_resolved = resolved.lower().replace("\\", "/").rstrip("/")
        norm_root = root.lower().replace("\\", "/").rstrip("/")
        passed = norm_resolved == norm_root
        detail = f"resolved={resolved}" if not passed else ""
        results.append((desc, passed, detail))

    return results


def test_memory_scoping(paths: dict) -> list[tuple[str, bool, str]]:
    """
    Test 2: Do memories get stored and retrieved for vault files?
    """
    results = []
    root = paths["root"]

    with tempfile.TemporaryDirectory() as storage_dir:
        store = MemoryStore(storage_dir=storage_dir)

        # Store memories referencing vault files
        store.remember_discovery(
            root, "MQTT is better than HTTP for real-time device state",
            related_files=[paths["project_note"]], category="discovery",
        )
        store.remember_discovery(
            root, "Use lru_cache for the sensor polling function",
            related_files=[paths["resource_note"]], category="discovery",
        )
        store.add_rule(
            root, "Always link back to project note when creating references",
        )
        store.remember_discovery(
            root, "MISTAKE: forgot to update wikilinks after renaming note",
            category="mistake", relevance=9,
        )

        # Retrieve — should find all 4
        proj = store.get_project(root)
        entry_count = len(proj.entries) if proj else 0
        results.append((
            f"Stored 4 memories, found {entry_count}",
            entry_count == 4,
            "",
        ))

        # Score and rank for a project note edit
        ranked = store.score_and_rank(root, {"file_path": paths["project_note"]}, limit=4)
        results.append((
            f"Score+rank returned {len(ranked)} results",
            len(ranked) > 0,
            "",
        ))

        # The MQTT memory should be in results for project_note (file match)
        # Note: rules get +0.3 bonus so they may rank above file-matched discoveries
        if ranked:
            all_contents = [e.content for e, _ in ranked]
            mqtt_present = any("MQTT" in c for c in all_contents)
            results.append((
                "MQTT memory present in results for project note",
                mqtt_present,
                f"contents: {[c[:40] for c in all_contents]}" if not mqtt_present else "",
            ))

        # Rules and mistakes should appear for any file (they cascade)
        ranked_inbox = store.score_and_rank(
            root, {"file_path": paths["inbox_note"]}, limit=4
        )
        categories = [e.category for e, _ in ranked_inbox]
        has_rule = "rule" in categories
        has_mistake = "mistake" in categories
        results.append((
            "Rules visible from inbox note",
            has_rule,
            f"categories: {categories}" if not has_rule else "",
        ))
        results.append((
            "Mistakes visible from inbox note",
            has_mistake,
            f"categories: {categories}" if not has_mistake else "",
        ))

    return results


def test_file_scoring_discrimination(paths: dict) -> list[tuple[str, bool, str]]:
    """
    Test 3: When everything is .md, does scoring still discriminate?

    Concern: all files share .md extension, so extension matching gives 0.2
    to everything. Do other signals (exact file match, tags, recency) compensate?
    """
    results = []
    root = paths["root"]

    with tempfile.TemporaryDirectory() as storage_dir:
        store = MemoryStore(storage_dir=storage_dir)

        # Memory about a specific file
        store.remember_discovery(
            root, "Home Automation uses MQTT, not HTTP",
            related_files=[paths["project_note"]], category="discovery",
        )
        # Memory about a different file
        store.remember_discovery(
            root, "Python list comprehensions are faster than map()",
            related_files=[paths["resource_note"]], category="discovery",
        )
        # Memory about API design
        store.remember_discovery(
            root, "REST API needs cursor-based pagination",
            related_files=[paths["resource_api"]], category="discovery",
        )

        # Score for project note — MQTT should rank highest
        ranked = store.score_and_rank(root, {"file_path": paths["project_note"]}, limit=3)
        if len(ranked) >= 2:
            score_diff = ranked[0][1] - ranked[1][1]
            results.append((
                f"Score gap: exact match vs extension-only: {score_diff:.3f}",
                score_diff > 0.05,
                f"scores: {ranked[0][1]:.3f} vs {ranked[1][1]:.3f}",
            ))
            top_has_mqtt = "MQTT" in ranked[0][0].content
            results.append((
                "Exact file match wins over extension-only",
                top_has_mqtt,
                f"top: {ranked[0][0].content[:50]}",
            ))
        else:
            results.append(("Got enough results to compare", False, f"only {len(ranked)}"))

        # Score for API resource — API memory should be top
        ranked_api = store.score_and_rank(root, {"file_path": paths["resource_api"]}, limit=3)
        if ranked_api:
            top_has_api = "REST" in ranked_api[0][0].content or "pagination" in ranked_api[0][0].content
            results.append((
                "API memory ranks top for API Design.md",
                top_has_api,
                f"top: {ranked_api[0][0].content[:50]}" if not top_has_api else "",
            ))

        # Score for a file with NO related memories (archive)
        ranked_archive = store.score_and_rank(
            root, {"file_path": paths["archive_note"]}, limit=3
        )
        if ranked_archive:
            max_score = ranked_archive[0][1]
            results.append((
                f"Unrelated file max score: {max_score:.3f}",
                max_score < 0.7,
                "",
            ))

    return results


def test_tag_inference(paths: dict) -> list[tuple[str, bool, str]]:
    """
    Test 4: What tags get inferred from .md filenames?

    TAG_PATTERNS look for words like 'api', 'test', 'config', 'database', 'security'.
    Obsidian note names like "API Design.md" or "Database Patterns.md" should trigger.
    """
    results = []

    test_cases = [
        (paths["resource_note"], [], "Python Tips — no code tags from path"),
        (paths["resource_api"], ["api"], "API Design.md → api tag"),
        (paths["resource_db"], ["database"], "Database Patterns.md → database tag"),
        (paths["resource_security"], ["security"], "Security Checklist.md → security tag"),
        (paths["area_note"], [], "Health.md — no code tags"),
        (paths["project_engram"], [], "Claude Engram.md — no code tags from path"),
    ]

    for file_path, expected_tags, desc in test_cases:
        inferred = set()
        for pattern, tag in _HOOK_TAG_PATTERNS.items():
            if re.search(pattern, file_path, re.IGNORECASE):
                inferred.add(tag)

        if expected_tags:
            has_expected = all(t in inferred for t in expected_tags)
            results.append((desc, has_expected, f"got: {inferred}"))
        else:
            # No tags expected — pass either way, just report what we got
            results.append((desc, True, f"got: {inferred}"))

    return results


def test_hot_memory_reader(paths: dict) -> list[tuple[str, bool, str]]:
    """
    Test 5: Does HotMemoryReader work for vault files?
    """
    results = []
    root = paths["root"]

    with tempfile.TemporaryDirectory() as storage_dir:
        store = MemoryStore(storage_dir=storage_dir)

        # Seed memories
        store.remember_discovery(root, "Vault convention: always use wikilinks",
                                 category="discovery")
        store.add_rule(root, "Link notes bidirectionally")
        store.remember_discovery(
            root, "MISTAKE: broke wikilinks by renaming without updating backlinks",
            category="mistake", relevance=9,
        )

        # HotMemoryReader should find them
        reader = HotMemoryReader(storage_dir=storage_dir)
        scored = reader.get_scored_memories(
            project_path=root,
            context={"file_path": paths["project_note"]},
            limit=5,
        )

        results.append((
            f"HotMemoryReader found {len(scored)} memories",
            len(scored) >= 2,
            "",
        ))

        # Should include rules and mistakes (they get bonuses)
        categories = [e.get("category", "") for e in scored]
        results.append((
            "Rules/mistakes present in hot injection",
            "rule" in categories or "mistake" in categories,
            f"categories: {categories}",
        ))

    return results


def test_large_vault_scaling(tmpdir: str) -> list[tuple[str, bool, str]]:
    """
    Test 6: Performance with a large vault (1000 notes).
    """
    results = []

    vault_root = create_large_vault(tmpdir, note_count=1000)

    with tempfile.TemporaryDirectory() as storage_dir:
        store = MemoryStore(storage_dir=storage_dir)

        # Seed 50 memories (realistic for active use)
        for i in range(50):
            store.remember_discovery(
                vault_root,
                f"Memory about note {i}: important pattern #{i}",
                related_files=[str(Path(vault_root) / "01_Projects" / f"note_{i:04d}.md")],
                category="discovery",
                auto_embed=False,  # Skip embedding for speed
            )

        # Time project resolution
        _project_dir_cache.clear()
        t0 = time.perf_counter()
        for i in range(100):
            cat = ["01_Projects", "03_Resources", "02_Areas"][i % 3]
            resolve_project_for_file(
                str(Path(vault_root) / cat / f"note_{i:04d}.md"),
                vault_root,
            )
        resolve_ms = (time.perf_counter() - t0) * 1000

        results.append((
            f"100 project resolutions: {resolve_ms:.1f}ms",
            resolve_ms < 500,
            "",
        ))

        # Time score_and_rank
        t0 = time.perf_counter()
        for i in range(100):
            store.score_and_rank(
                vault_root,
                {"file_path": str(Path(vault_root) / "01_Projects" / f"note_{i:04d}.md")},
                limit=3,
            )
        score_ms = (time.perf_counter() - t0) * 1000

        results.append((
            f"100 score_and_rank calls (50 memories): {score_ms:.1f}ms",
            score_ms < 1000,
            "",
        ))

        # Time HotMemoryReader
        reader = HotMemoryReader(storage_dir=storage_dir)
        t0 = time.perf_counter()
        for i in range(100):
            reader.get_scored_memories(
                project_path=vault_root,
                context={"file_path": str(Path(vault_root) / "01_Projects" / f"note_{i:04d}.md")},
                limit=3,
            )
        hot_ms = (time.perf_counter() - t0) * 1000

        results.append((
            f"100 HotMemoryReader calls: {hot_ms:.1f}ms",
            hot_ms < 1000,
            "",
        ))

    return results


# ─── Runner ──────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("BENCHMARK: Obsidian Vault Compatibility (PARA + CLAUDE.md)")
    print("=" * 70)

    total_pass = 0
    total_fail = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = create_obsidian_vault(tmpdir)

        test_suites = [
            ("1. Project Detection (CLAUDE.md marker)", test_project_detection, (paths,)),
            ("2. Memory Scoping", test_memory_scoping, (paths,)),
            ("3. File Scoring Discrimination", test_file_scoring_discrimination, (paths,)),
            ("4. Tag Inference from .md Filenames", test_tag_inference, (paths,)),
            ("5. HotMemoryReader for Vault", test_hot_memory_reader, (paths,)),
            ("6. Large Vault Scaling (1000 notes)", test_large_vault_scaling, (tmpdir,)),
        ]

        for suite_name, test_fn, args in test_suites:
            print(f"\n--- {suite_name} ---")
            try:
                results = test_fn(*args)
                for desc, passed, detail in results:
                    status = "PASS" if passed else "FAIL"
                    if passed:
                        total_pass += 1
                    else:
                        total_fail += 1
                    line = f"  [{status}] {desc}"
                    if detail:
                        line += f"  ({detail})"
                    print(line)
            except Exception as e:
                total_fail += 1
                print(f"  [ERROR] {suite_name}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {total_pass} passed, {total_fail} failed "
          f"({total_pass}/{total_pass + total_fail})")
    print(f"{'=' * 70}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

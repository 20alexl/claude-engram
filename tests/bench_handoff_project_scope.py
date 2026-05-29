"""
Benchmark: HANDOFF.md project-scoping + handoff candidate-dir scoping.

Guards the v0.6.x fixes that made handoffs project-aware instead of leaking
across a multi-project workspace:
  HANDOFF.md (the human-readable companion):
    1. The body is stamped with **Project:** <path>.
    2. A project-scoped copy is written beside the project's ring
       (projects/<hash>/HANDOFF.md), in addition to the global mirror.
    3. Two projects do not clobber each other's HANDOFF.md.
    4. An unregistered project (_project_hash_dir -> None) degrades to the
       global mirror only (no crash).
    5. create_handoff's response points markdown_file at the project copy.
  Candidate-dir resolution (checkpoint_list / get_by_index scoping):
    6. A registered project resolves to its OWN ring and EXCLUDES the global
       catch-all (so a merged list/index no longer surfaces other projects).
    7. An unregistered project still falls back to the global dir.

Run: python tests/bench_handoff_project_scope.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.hooks import remind
from claude_engram.tools.context_guard import ContextGuard

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def test_project_scoped_handoff_md():
    print("Project-scoped HANDOFF.md (stamp + per-project copy + no clobber):")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        storage = tmp / "checkpoints"

        # Map each project path to its own hash dir; contain the ring writes in
        # tmp by also redirecting the global handoff dir. Patching the names on
        # `remind` is sufficient: both _write_handoff_md and create_handoff
        # import them from remind at call time.
        proj_dirs = {
            "E:/ws/projA": tmp / "projects" / "aaaa1111",
            "E:/ws/projB": tmp / "projects" / "bbbb2222",
        }
        remind._project_hash_dir = lambda p: proj_dirs.get(p)
        remind._global_handoff_dir = lambda: storage

        cg = ContextGuard(storage_dir=storage)

        cg.create_handoff(
            summary="Alpha work summary",
            next_steps=["do A1", "do A2"],
            context_needed=["docs/a.md"],
            warnings=["watch out A"],
            project_path="E:/ws/projA",
        )

        global_md = storage / "HANDOFF.md"
        a_md = proj_dirs["E:/ws/projA"] / "HANDOFF.md"
        check("global HANDOFF.md written", global_md.exists())
        check("project-scoped HANDOFF.md written", a_md.exists())

        a_text = a_md.read_text(encoding="utf-8")
        check("project stamp present in project copy", "**Project:** E:/ws/projA" in a_text)
        check("summary present in project copy", "Alpha work summary" in a_text)
        check("warnings section present", "## Warnings" in a_text and "watch out A" in a_text)

        # Second project must not clobber the first project's file.
        cg.create_handoff(
            summary="Beta work summary",
            next_steps=["do B1"],
            context_needed=[],
            warnings=[],
            project_path="E:/ws/projB",
        )
        b_md = proj_dirs["E:/ws/projB"] / "HANDOFF.md"
        check("projB HANDOFF.md written", b_md.exists())
        check("projA HANDOFF.md NOT clobbered by projB",
              "Alpha work summary" in a_md.read_text(encoding="utf-8"))
        check("global mirror reflects the latest handoff (projB)",
              "Beta work summary" in global_md.read_text(encoding="utf-8"))

        # create_handoff response should point markdown_file at the project copy.
        r = cg.create_handoff(
            summary="Gamma", next_steps=["g"], context_needed=[], warnings=[],
            project_path="E:/ws/projA",
        )
        check("response markdown_file points at the project copy",
              r.data.get("markdown_file") == str(a_md))


def test_unregistered_project_degrades_to_global():
    print("Unregistered project -> global-only (no crash):")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        storage = tmp / "checkpoints"
        remind._project_hash_dir = lambda p: None  # nothing registered
        remind._global_handoff_dir = lambda: storage
        cg = ContextGuard(storage_dir=storage)
        r = cg.create_handoff(
            summary="Orphan", next_steps=["x"], context_needed=[], warnings=[],
            project_path="E:/ws/unknown",
        )
        global_md = storage / "HANDOFF.md"
        check("global HANDOFF.md written for unregistered project", global_md.exists())
        check("stamp still present when global-only",
              "**Project:** E:/ws/unknown" in global_md.read_text(encoding="utf-8"))
        check("markdown_file falls back to global",
              r.data.get("markdown_file") == str(global_md))


def test_candidate_dirs_scoping():
    print("Candidate-dir scoping (registered drops global catch-all; unregistered falls back):")
    from claude_engram.hooks import paths
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        key = paths._normalize_path("E:/ws/projA")
        # Redirect storage + manifest so _handoff_candidate_dirs sees exactly
        # one registered project (projA -> aaaa1111).
        paths.get_engram_storage_dir = lambda: tmp
        paths._get_manifest = lambda: {"projects": {key: {"hash": "aaaa1111"}}}
        glob = tmp / "checkpoints"
        own = tmp / "projects" / "aaaa1111"

        dirs = paths._handoff_candidate_dirs("E:/ws/projA")
        check("registered project resolves to its own ring", own in dirs)
        check("registered project EXCLUDES the global catch-all", glob not in dirs)

        dirs2 = paths._handoff_candidate_dirs("E:/ws/unknown")
        check("unregistered project falls back to global only", dirs2 == [glob])


if __name__ == "__main__":
    print("=" * 60)
    print("HANDOFF.md Project-Scoping Benchmark")
    print("=" * 60)
    test_project_scoped_handoff_md()
    test_unregistered_project_degrades_to_global()
    test_candidate_dirs_scoping()
    print("-" * 60)
    print(f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}")
    sys.exit(1 if _fails else 0)

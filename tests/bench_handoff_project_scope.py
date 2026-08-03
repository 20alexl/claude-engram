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
    8. A query also sees DESCENDANT rings but never a sibling's — without
       this, a restore at the workspace root silently returned an hours-stale
       root entry while the real checkpoint sat in a sub-project ring.

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
        check(
            "project stamp present in project copy",
            "**Project:** E:/ws/projA" in a_text,
        )
        check("summary present in project copy", "Alpha work summary" in a_text)
        check(
            "warnings section present",
            "## Warnings" in a_text and "watch out A" in a_text,
        )

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
        check(
            "projA HANDOFF.md NOT clobbered by projB",
            "Alpha work summary" in a_md.read_text(encoding="utf-8"),
        )
        check(
            "global mirror reflects the latest handoff (projB)",
            "Beta work summary" in global_md.read_text(encoding="utf-8"),
        )

        # create_handoff response should point markdown_file at the project copy.
        r = cg.create_handoff(
            summary="Gamma",
            next_steps=["g"],
            context_needed=[],
            warnings=[],
            project_path="E:/ws/projA",
        )
        check(
            "response markdown_file points at the project copy",
            (r.data or {}).get("markdown_file") == str(a_md),
        )


def test_unregistered_project_degrades_to_global():
    print("Unregistered project -> global-only (no crash):")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        storage = tmp / "checkpoints"
        remind._project_hash_dir = lambda p: None  # nothing registered
        remind._global_handoff_dir = lambda: storage
        cg = ContextGuard(storage_dir=storage)
        r = cg.create_handoff(
            summary="Orphan",
            next_steps=["x"],
            context_needed=[],
            warnings=[],
            project_path="E:/ws/unknown",
        )
        global_md = storage / "HANDOFF.md"
        check("global HANDOFF.md written for unregistered project", global_md.exists())
        check(
            "stamp still present when global-only",
            "**Project:** E:/ws/unknown" in global_md.read_text(encoding="utf-8"),
        )
        check(
            "markdown_file falls back to global",
            (r.data or {}).get("markdown_file") == str(global_md),
        )


def test_candidate_dirs_scoping():
    print(
        "Candidate-dir scoping (registered drops global catch-all; unregistered falls back):"
    )
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


def test_descendant_rings_in_scope():
    """A query must see rings BENEATH it, not just its own and its ancestors'.

    The regression: a restore at the workspace root could only read the root
    ring, so when the session's real final checkpoint was saved under
    workspace/chappie/V11 the call returned an hours-stale root entry AND
    reported success. Siblings must stay out — that is what made the global
    catch-all unusable as an always-on candidate.
    """
    print("Descendant ring scoping (the silent-stale-restore regression):")
    from claude_engram.hooks import paths
    from claude_engram import handoff_store as hs

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        reg = {
            "E:/ws": "root0000",
            "E:/ws/app": "app11111",
            "E:/ws/app/api": "api22222",
            "E:/ws/other": "othr3333",
        }
        paths.get_engram_storage_dir = lambda: tmp
        paths._get_manifest = lambda: {
            "projects": {
                paths._normalize_path(p): {"hash": h} for p, h in reg.items()
            }
        }
        d = {p: tmp / "projects" / h for p, h in reg.items()}
        for path in d.values():
            path.mkdir(parents=True, exist_ok=True)

        root_dirs = paths._handoff_candidate_dirs("E:/ws")
        check("root query includes its own ring", d["E:/ws"] in root_dirs)
        check("root query includes a nested descendant", d["E:/ws/app/api"] in root_dirs)
        check("root query includes a direct descendant", d["E:/ws/app"] in root_dirs)

        api_dirs = paths._handoff_candidate_dirs("E:/ws/app/api")
        check("leaf query excludes its sibling-branch", d["E:/ws/other"] not in api_dirs)
        check("leaf query still cascades to ancestors", d["E:/ws"] in api_dirs)

        # End-to-end: the stale-restore scenario itself.
        now = 1_700_000_000.0
        hs.write_handoff(
            {
                "kind": "manual",
                "summary": "stale root checkpoint",
                "task_description": "stale root checkpoint",
                "created": now - 7200,  # 2h older
                "project_path": "E:/ws",
            },
            [d["E:/ws"]],
        )
        hs.write_handoff(
            {
                "kind": "manual",
                "summary": "the real final checkpoint",
                "task_description": "the real final checkpoint",
                "created": now,
                "project_path": "E:/ws/app/api",
            },
            [d["E:/ws/app/api"]],
        )
        latest = hs.read_latest(paths._handoff_candidate_dirs("E:/ws"))
        check(
            "root restore returns the newest checkpoint, not the stale root one",
            latest is not None
            and latest.get("summary") == "the real final checkpoint",
        )
        other = hs.read_latest(paths._handoff_candidate_dirs("E:/ws/other"))
        check(
            "a sibling project never sees the descendant's checkpoint",
            other is None or other.get("summary") != "the real final checkpoint",
        )


if __name__ == "__main__":
    print("=" * 60)
    print("HANDOFF.md Project-Scoping Benchmark")
    print("=" * 60)
    test_project_scoped_handoff_md()
    test_unregistered_project_degrades_to_global()
    test_candidate_dirs_scoping()
    test_descendant_rings_in_scope()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

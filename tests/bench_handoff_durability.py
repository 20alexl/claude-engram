"""
Benchmark: handoff durability — ring buffer, promotion guard, walk-up reads.

Guards the fixes for the three handoff bugs:
  1. Single overwritable slot   -> capped ring buffer, retrievable by index
  2. Trivial auto buries rich    -> promotion guard + skip-trivial-auto
  3. Wrong (global) handoff       -> nearest-project-first walk-up resolution

Plus the wiring through ContextGuard (manual handoff survives a later stop)
and the duplicate-summary formatting nit.

Run: python tests/bench_handoff_durability.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram import handoff_store as hs

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def test_store_logic():
    print("Store logic (ring + promotion guard + index):")
    with tempfile.TemporaryDirectory() as td:
        proj, glob = Path(td) / "proj", Path(td) / "global"

        r = hs.write_handoff(
            {
                "kind": "auto",
                "summary": "Session stopped. 0 files edited.",
                "next_steps": ["Review what was in progress"],
            },
            [proj, glob],
        )
        check(
            "trivial auto-handoff is skipped (not written)",
            r["skipped"] and not (proj / hs.LATEST_FILENAME).exists(),
        )

        hs.write_handoff(
            {
                "kind": "auto",
                "summary": "Edited 3 files",
                "files_in_progress": ["a.py", "b.py"],
                "decisions": ["use X"],
            },
            [proj, glob],
        )
        check(
            "substantive auto-handoff is recorded", (proj / hs.LATEST_FILENAME).exists()
        )

        hs.write_handoff(
            {
                "kind": "manual",
                "summary": "Block 1-4 research handoff",
                "next_steps": ["finish processor split"],
                "context_needed": ["docs/x.md"],
            },
            [proj, glob],
        )
        check(
            "manual handoff promoted to latest",
            hs.read_latest([proj, glob])["kind"] == "manual",
        )

        # The core #2 regression: trivial auto after a manual must NOT clobber it.
        hs.write_handoff(
            {
                "kind": "auto",
                "summary": "Session stopped. 0 files edited.",
                "next_steps": ["Review what was in progress"],
            },
            [proj, glob],
        )
        check(
            "manual survives a later trivial auto (no clobber)",
            hs.read_latest([proj, glob])["kind"] == "manual",
        )

        hist = hs.read_history([proj, glob])
        check("history retains both substantive handoffs", len(hist) == 2)
        check("history newest-first", hist[0]["summary"].startswith("Block 1-4"))
        check(
            "older handoff retrievable by index",
            hs.get_by_index([proj, glob], 1)["summary"] == "Edited 3 files",
        )

        capdir = Path(td) / "cap"
        for i in range(30):
            hs.write_handoff(
                {"kind": "manual", "summary": f"h{i}", "next_steps": [f"s{i}"]},
                [capdir],
                history_limit=20,
            )
        check("ring buffer capped at limit", len(hs._load_history(capdir)) == 20)


def test_walkup_and_wiring():
    print("Walk-up resolution + ContextGuard wiring:")
    from claude_engram.hooks import remind
    from claude_engram.tools.context_guard import ContextGuard

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        remind.get_engram_storage_dir = lambda: tmp  # redirect storage to temp
        proj = str(tmp / "projA")
        cg = ContextGuard(storage_dir=tmp / "checkpoints")

        cg.create_handoff(
            summary="Block 1-4 research handoff",
            next_steps=["finish processor split"],
            context_needed=["docs/x.md"],
            warnings=[],
            project_path=proj,
        )
        hs.write_handoff(
            {
                "kind": "auto",
                "summary": "Session stopped. 0 files edited.",
                "next_steps": ["Review what was in progress"],
            },
            [remind._project_hash_dir(proj), remind._global_handoff_dir()],
        )

        txt = cg.get_handoff(project_path=proj).to_formatted_string()
        check(
            "manual handoff survives auto via ContextGuard", "research handoff" in txt
        )
        check(
            "summary printed exactly once (dup-summary nit fixed)",
            txt.count("Block 1-4 research handoff") == 1,
        )

        # v0.8.5 contract: a later substantive auto contends only for the
        # latest POINTER (which the fresh manual keeps) — it never enters the
        # history ring. Per-turn Stop autos used to evict real checkpoints
        # from the 20-slot FIFO within one session.
        hs.write_handoff(
            {
                "kind": "auto",
                "summary": "Edited engine.py",
                "files_in_progress": ["engine.py"],
                "decisions": ["use GLA"],
            },
            [remind._project_hash_dir(proj), remind._global_handoff_dir()],
        )
        check(
            "manual still latest after substantive auto",
            cg.get_handoff(project_path=proj, index=0).reasoning.count(
                "research handoff"
            )
            == 1,
        )
        r1 = cg.get_handoff(project_path=proj, index=1)
        check(
            "substantive auto does NOT occupy a ring index (pointer-only)",
            not (r1.status == "success" and "engine.py" in r1.reasoning),
        )

        # A second MANUAL does ring-append: index=1 reaches the older manual.
        cg.create_handoff(
            summary="Second manual handoff",
            next_steps=["continue"],
            context_needed=[],
            warnings=[],
            project_path=proj,
        )
        r0 = cg.get_handoff(project_path=proj, index=0)
        r1 = cg.get_handoff(project_path=proj, index=1)
        check(
            "newest manual at index 0",
            r0.status == "success" and "Second manual handoff" in r0.reasoning,
        )
        check(
            "older manual reachable at index=1",
            r1.status == "success" and "research handoff" in r1.reasoning,
        )

        # With no manual in scope, the newest auto is still restorable via the
        # latest-pointer fold-in (the auto fallback survives the new contract).
        auto_ring = tmp / "autoOnlyRing"
        hs.write_handoff(
            {
                "kind": "auto",
                "summary": "auto-only fallback",
                "files_in_progress": ["z.py"],
            },
            [auto_ring],
        )
        got = hs.read_latest([auto_ring]) or {}
        check(
            "auto-only ring still restorable via pointer",
            got.get("summary") == "auto-only fallback",
        )

        # Nearest project beats the shared global slot (#3).
        proj2 = tmp / "p2"
        hs.write_handoff({"kind": "manual", "summary": "GLOBAL"}, [tmp / "checkpoints"])
        hs.write_handoff({"kind": "manual", "summary": "PROJ2-OWN"}, [proj2])
        check(
            "nearest project beats global",
            hs.read_latest([proj2, tmp / "checkpoints"])["summary"] == "PROJ2-OWN",
        )


if __name__ == "__main__":
    print("=" * 60)
    print("Handoff Durability Benchmark")
    print("=" * 60)
    test_store_logic()
    test_walkup_and_wiring()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

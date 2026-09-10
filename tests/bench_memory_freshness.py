"""
Benchmark: the memory store sees what another process wrote.

The MCP server is one long-lived MemoryStore; hooks and the CLI are others.
Before this fix the server served the copy it took at first touch and, on
its next save, wrote that copy back over whatever the others had written
since -- observed as a delete-by-id "not found" after a CLI re-seed
(2026-09-09), and, unobserved but implied, lost writes.

What must hold:
  1. A second store instance sees rules the first one saved (baseline).
  2. A rule added by the second instance is visible to the FIRST, already
     loaded, instance on its next read, without a restart.
  3. The first instance can delete that rule by id, and the second sees the
     deletion on its next read.
  4. A save by a stale-looking instance does not clobber the other writer's
     entries (the reload happens before the write).
  5. A project registered by another instance after this one started is
     found (the manifest is re-read when it changed on disk).
  6. Nothing is re-read when nothing changed (the stamp matches).

Run: venv/Scripts/python.exe tests/bench_memory_freshness.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _rule_ids(store, proj):
    # add_rule appends " (Reason: …)" to the content; compare the rule text.
    return {r.id: r.content.split(" (Reason:")[0] for r in store.get_rules(proj)}


def main():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        from claude_engram.tools.memory import MemoryStore

        proj = str(Path(td) / "proj-a")
        Path(proj).mkdir()

        print("two stores over one storage dir:")
        a = MemoryStore(td)
        a.remember_project(proj, summary="a")
        ok, _ = a.add_rule(proj, "Rule one from A", reason="bench")
        check("A adds a rule", ok)

        b = MemoryStore(td)
        check("B sees A's rule (baseline)", "Rule one from A" in _rule_ids(b, proj).values())

        ok, _ = b.add_rule(proj, "Rule two from B", reason="bench")
        check("B adds a rule", ok)
        ids_a = _rule_ids(a, proj)
        check("A, already loaded, sees B's rule on its next read", "Rule two from B" in ids_a.values())

        two_id = next(i for i, c in ids_a.items() if c == "Rule two from B")
        ok, msg = a.delete_memory(proj, two_id)
        check(f"A deletes B's rule by id ({msg[:40]})", ok)
        check("B sees the deletion", "Rule two from B" not in _rule_ids(b, proj).values())

        print("no clobber:")
        ok, _ = b.add_rule(proj, "Rule three from B", reason="bench")
        a.add_rule(proj, "Rule four from A", reason="bench")
        final = set(_rule_ids(MemoryStore(td), proj).values())
        check("both writers' rules survive on disk", {"Rule three from B", "Rule four from A"} <= final)
        check("the deleted one stayed deleted", "Rule two from B" not in final)

        print("manifest refresh:")
        proj2 = str(Path(td) / "proj-b")
        Path(proj2).mkdir()
        b.remember_project(proj2, summary="b")
        b.add_rule(proj2, "Rule in the new project", reason="bench")
        check("A finds a project B registered after A started", a.get_project(proj2) is not None)
        check("...with its rule", "Rule in the new project" in _rule_ids(a, proj2).values())
        # B's save of proj2 fell back to "all loaded projects" (no dirty mark)
        # and used to rewrite proj-a from B's older copy, dropping A's rule.
        on_disk = set(_rule_ids(MemoryStore(td), proj).values())
        check("B's write to another project did not clobber A's rule", "Rule four from A" in on_disk)

        print("mutation on a stale base merges instead of losing a write:")
        c = MemoryStore(td)
        c.get_project(proj)  # loaded now
        a.add_rule(proj, "Rule five from A", reason="bench")  # disk moves on
        c_proj = c._projects[c._normalize_path(proj)]
        c_proj.summary = "touched by C on a stale base"
        c._dirty_projects.add(c._normalize_path(proj))
        c._save()
        on_disk = set(_rule_ids(MemoryStore(td), proj).values())
        check("C's stale-base save kept A's newer rule", "Rule five from A" in on_disk)
        _p = MemoryStore(td).get_project(proj)
        check("...and C's own change landed", _p is not None and _p.summary == "touched by C on a stale base")

        print("stamps:")
        norm = a._normalize_path(proj)
        a.get_project(proj)  # sync after C's write
        stamp_before = a._project_stamps.get(norm)
        a.get_project(proj)
        check("a read with nothing changed keeps the stamp", a._project_stamps.get(norm) == stamp_before and stamp_before is not None)
        check("the stamp is (mtime_ns, size)", isinstance(stamp_before, tuple) and len(stamp_before) == 2)

        os.environ.pop("CLAUDE_ENGRAM_DIR", None)
    print()
    if _fails:
        print(f"FAILED: {len(_fails)}")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

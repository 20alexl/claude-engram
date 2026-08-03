"""
Benchmark: consolidation never destroys a memory.

memory(consolidate) merges a tag group into one LLM-written digest and keeps
the 5 highest-relevance originals. The other members used to be DELETED --
`proj.entries` was reassigned without them and nothing wrote them anywhere
else. That is unrecoverable, and it contradicts the rule the rest of the store
follows: nothing is lost without review.

It bit hardest exactly where consolidation is most tempting. Auto-captured
decisions are all minted at the same relevance, so "keep the top 5 by
relevance" degenerates to "keep whichever 5 come first", and a single
dry_run=False call on a 200-strong group would have dropped ~195 memories for
good.

What must hold:
  1. Every member that is not kept is ARCHIVED, not deleted.
  2. hot_before == hot_after + archived (nothing evaporates).
  3. An archived member is retrievable by id and restorable.
  4. The digest itself lands in the hot tier.
  5. Rules and mistakes are never fed to consolidation in the first place.

Run: python tests/bench_consolidate_safety.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.tools.memory import MemoryStore

_fails = []


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _hot(store, project):
    """Hot entries, with an explicit failure if the project vanished."""
    proj = store.get_project(project)
    assert proj is not None, f"project {project} missing"
    return proj.entries


class FakeLLM:
    """Deterministic stand-in: consolidation must not need a live Ollama."""

    def generate(self, prompt, system=None, temperature=0.1):
        return {"success": True, "response": "Digest of the group's decisions."}


def test_consolidation_archives_rather_than_deletes():
    print("Consolidation archives the members it drops:")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        m = MemoryStore()
        p = "E:/ws/proj"

        # 12 same-relevance decisions in one tag group (the real-world shape:
        # every auto-captured decision carries an identical relevance).
        for i in range(12):
            m.remember_discovery(
                p,
                f"DECISION: use approach {i} because reason {i}",
                source="test",
                relevance=7,
                category="decision",
                tags=["decision"],
            )
        # Protected categories that must never be consolidated.
        m.remember_discovery(p, "RULE: always do X", source="test", relevance=9,
                             category="rule", tags=["decision"])
        m.remember_discovery(p, "MISTAKE: broke Y", source="test", relevance=8,
                             category="mistake", tags=["decision"])

        hot_before = len(_hot(m, p))
        ids_before = {e.id for e in _hot(m, p)}

        report = m.consolidate_memories(p, llm_client=FakeLLM(), dry_run=False)
        done = report.get("consolidated", [])
        check("a group was consolidated", bool(done))

        hot_now = _hot(m, p)
        hot_after = len(hot_now)
        hot_ids = {e.id for e in hot_now}

        m._load_archive()
        arc = m._archive_projects.get(m._normalize_path(p))
        arc_ids = {e.id for e in arc.entries} if arc else set()

        gone = ids_before - hot_ids
        check(
            f"every dropped member is in the archive ({len(gone)} dropped)",
            bool(gone) and gone <= arc_ids,
        )
        check(
            "nothing evaporated: hot_before == hot_after - digest + archived",
            hot_before == (hot_after - 1) + len(gone),
        )
        check(
            "the digest is in the hot tier",
            any(e.source == "consolidation" for e in hot_now),
        )

        # An archived member survives a round trip.
        victim = sorted(gone)[0]
        ok = m.restore_from_archive(p, victim)
        restored = ok[0] if isinstance(ok, tuple) else ok
        check("an archived member restores by id", bool(restored))
        check(
            "restored member is hot again",
            victim in {e.id for e in _hot(m, p)},
        )


def test_protected_categories_never_consolidated():
    print("Rules and mistakes are never merged away:")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_ENGRAM_DIR"] = td
        m = MemoryStore()
        p = "E:/ws/proj2"
        for i in range(12):
            m.remember_discovery(p, f"RULE number {i}", source="test", relevance=9,
                                 category="rule", tags=["shared"])
        for i in range(12):
            m.remember_discovery(p, f"MISTAKE number {i}", source="test", relevance=8,
                                 category="mistake", tags=["shared"])
        before = {e.id for e in _hot(m, p)}
        m.consolidate_memories(p, llm_client=FakeLLM(), dry_run=False)
        after = {e.id for e in _hot(m, p)}
        check("no rule or mistake was removed", before <= after)


if __name__ == "__main__":
    print("=" * 60)
    print("Consolidation Safety Benchmark")
    print("=" * 60)
    test_consolidation_archives_rather_than_deletes()
    test_protected_categories_never_consolidated()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

"""
Benchmark: one name per concept on the ring record.

Every ring record used to carry BOTH vocabularies -- the checkpoint one
(pending_steps, files_involved, handoff_warnings, handoff_context_needed,
key_decisions, timestamp) and the handoff one (next_steps, files_in_progress,
warnings, context_needed, decisions, created). Across the 129 stored records
that had both, the two were byte-identical in every case, so the checkpoint
twin is no longer written.

`task_description` is NOT part of that collapse and this bench pins that:
`summary` carries the HANDOFF NOTE, which differed from the task title in 110
of those 129 records. Merging them would lose one.

What must hold:
  1. A newly saved record carries the canonical name and NOT its twin.
  2. task_description AND summary both survive, and keep different values
     when a handoff_summary was given.
  3. A collapsed record renders IDENTICALLY to a legacy dual-vocabulary one,
     through both the SessionStart banner and checkpoint_restore -- this is
     what makes the change migration-free for records already on disk.
  4. Handoff-shaped records (only the handoff vocabulary, no checkpoint
     fields) render their pending-steps and decisions lines. Two readers used
     to check only the checkpoint name with no fallback, so those lines were
     silently missing for such records.

Run: python tests/bench_ring_vocabulary.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_engram.hooks import remind
from claude_engram.hooks.remind import _format_restored_context
from claude_engram.tools.context_guard import ContextGuard

_fails = []

TWINS = [
    ("pending_steps", "next_steps"),
    ("files_involved", "files_in_progress"),
    ("handoff_warnings", "warnings"),
    ("handoff_context_needed", "context_needed"),
    ("key_decisions", "decisions"),
    ("timestamp", "created"),
]


def check(name, cond):
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    if not cond:
        _fails.append(name)


def _save(cg, **kw):
    """Save a checkpoint and return the record that landed in the ring."""
    import json

    cg.save_checkpoint(
        task_description=kw.get("task_description", "Migrating auth to OAuth2"),
        current_step=kw.get("current_step", "Step 3: token refresh"),
        completed_steps=kw.get("completed_steps", ["Step 1", "Step 2"]),
        pending_steps=kw.get("pending_steps", ["Step 3", "Step 4"]),
        files_involved=kw.get("files_involved", ["auth.py", "oauth.py"]),
        key_decisions=kw.get("key_decisions", ["use authlib"]),
        blockers=None,
        project_path=kw.get("project_path", "E:/ws/proj"),
        handoff_summary=kw.get("handoff_summary"),
        handoff_context_needed=kw.get("handoff_context_needed", ["docs/oauth.md"]),
        handoff_warnings=kw.get("handoff_warnings", ["don't touch legacy auth"]),
    )
    ring = Path(kw["ring_dir"]) / "handoff_history.json"
    return json.loads(ring.read_text(encoding="utf-8"))["handoffs"][-1]


def test_written_record_has_one_name_per_concept():
    print("A saved record carries the canonical name only:")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        storage = tmp / "checkpoints"
        proj = tmp / "projects" / "aaaa1111"
        remind._project_hash_dir = lambda p: proj
        remind._global_handoff_dir = lambda: storage
        cg = ContextGuard(storage_dir=storage)

        rec = _save(cg, ring_dir=proj, handoff_summary="OAuth2 60% done")

        for old, new in TWINS:
            check(f"{new} kept, {old} dropped", new in rec and old not in rec)
        check(
            "task_description survives the collapse",
            rec.get("task_description") == "Migrating auth to OAuth2",
        )
        check(
            "summary is the handoff note, NOT the task title",
            rec.get("summary") == "OAuth2 60% done"
            and rec["summary"] != rec["task_description"],
        )
        check(
            "values carried over intact",
            rec.get("next_steps") == ["Step 3", "Step 4"]
            and rec.get("decisions") == ["use authlib"]
            and rec.get("warnings") == ["don't touch legacy auth"],
        )


def _legacy(rec):
    """Re-add the checkpoint-vocabulary twins, as records on disk still have."""
    out = dict(rec)
    for old, new in TWINS:
        out[old] = rec.get(new)
    return out


def test_collapsed_renders_like_legacy():
    """The migration-free property: readers must not be able to tell."""
    print("Collapsed vs legacy dual-vocabulary record render identically:")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        storage = tmp / "checkpoints"
        proj = tmp / "projects" / "bbbb2222"
        remind._project_hash_dir = lambda p: proj
        remind._global_handoff_dir = lambda: storage
        cg = ContextGuard(storage_dir=storage)

        new_rec = _save(cg, ring_dir=proj, handoff_summary="OAuth2 60% done")
        old_rec = _legacy(new_rec)

        check(
            "SessionStart banner is byte-identical",
            _format_restored_context(new_rec) == _format_restored_context(old_rec),
        )

        def restored(entry):
            import claude_engram.handoff_store as hs

            saved = hs.read_latest
            hs.read_latest = lambda *a, **k: entry
            try:
                return cg.restore_checkpoint(None, project_path="E:/ws/proj")
            finally:
                hs.read_latest = saved

        new_out, old_out = restored(new_rec), restored(old_rec)
        check(
            "checkpoint_restore says exactly the same thing",
            new_out.reasoning == old_out.reasoning,
        )
        # NOT identical text, and the collapsed one is the correct half: the
        # response passes the whole record as `data`, and to_formatted_string
        # renders every list in it -- so a dual-vocabulary record printed each
        # list TWICE, once per name. Nothing is lost by the collapse, only the
        # repeat is gone.
        new_lines = new_out.to_formatted_string().splitlines()
        old_lines = old_out.to_formatted_string().splitlines()
        check(
            "collapsed loses no line the legacy record had",
            set(new_lines) <= set(old_lines),
        )
        check(
            "legacy repeated its lists; collapsed does not",
            len(old_lines) > len(new_lines)
            and len(old_lines) - len(set(old_lines)) > len(new_lines) - len(set(new_lines)),
        )


def test_handoff_shaped_record_renders_fully():
    """Records written by create_handoff carry ONLY the handoff vocabulary."""
    print("Handoff-shaped record (no checkpoint fields) renders every line:")
    entry = {
        "kind": "manual",
        "created": 1_700_000_000.0,
        "summary": "OAuth2 migration 60% done",
        "next_steps": ["refresh tokens", "add tests"],
        "decisions": ["use authlib", "drop legacy path"],
        "warnings": ["don't touch legacy auth"],
        "files_in_progress": ["auth.py"],
        "project_path": "E:/ws/proj",
    }
    banner = "\n".join(_format_restored_context(entry))
    check("banner shows Pending (was skipped: no fallback)", "Pending: 2 steps" in banner)
    check("banner shows Next", "Next:" in banner)
    check("banner shows Warnings", "Warnings:" in banner)

    with tempfile.TemporaryDirectory() as td:
        cg = ContextGuard(storage_dir=Path(td) / "checkpoints")
        import claude_engram.handoff_store as hs

        saved = hs.read_latest
        hs.read_latest = lambda *a, **k: entry
        try:
            out = cg.restore_checkpoint(None, project_path="E:/ws/proj")
            text = out.to_formatted_string()
        finally:
            hs.read_latest = saved
    check(
        "restore shows Key decisions (was skipped: no fallback)",
        "**Key decisions:** 2 recorded" in text,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("Ring Vocabulary Benchmark")
    print("=" * 60)
    test_written_record_has_one_name_per_concept()
    test_collapsed_renders_like_legacy()
    test_handoff_shaped_record_renders_fully()
    print("-" * 60)
    print(
        f"RESULTS: {'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + str(_fails)}"
    )
    sys.exit(1 if _fails else 0)

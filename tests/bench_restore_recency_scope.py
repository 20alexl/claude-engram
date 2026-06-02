"""Regression: checkpoint restore/list pick the newest DELIBERATE (manual)
checkpoint across the resolved candidate scope.

Guards two failures at once:
  - a stale ancestor manual must not win (the chappie/V9 -> chappie
    "ready for pretrain v3" bug): a newer manual outranks an older one;
  - a routine auto "Session stopped" must not bury a deliberate checkpoint.
Run: venv/Scripts/python.exe tests/bench_restore_recency_scope.py
"""
import json, time, tempfile
from pathlib import Path
from claude_engram import handoff_store as hs


def _write(d, history, latest):
    d.mkdir(parents=True, exist_ok=True)
    (d / hs.HISTORY_FILENAME).write_text(json.dumps({"handoffs": history}))
    if latest is not None:
        (d / hs.LATEST_FILENAME).write_text(json.dumps(latest))


def run():
    now = time.time()
    stale = {"summary": "ready for pretrain v3", "kind": "manual", "created": now - 368 * 3600}
    fresh = {"summary": "HONEST RESET", "kind": "manual", "created": now - 1 * 3600}
    mid = {"summary": "interim auto", "kind": "auto", "created": now - 50 * 3600}
    noise = {"summary": "Session stopped. 2 files edited", "kind": "auto", "created": now - 0.2 * 3600}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        near = root / "chappie"   # nearest candidate, stale manual latest pointer
        far = root / "workspace"  # later candidate; noise is chronologically newest
        _write(near, [stale], stale)
        _write(far, [mid, fresh, noise], fresh)
        dirs = [near, far]

        latest = hs.read_latest(dirs)
        assert latest["summary"] == "HONEST RESET", (
            "newest manual must beat BOTH an older manual and a newer auto; "
            f"got {latest['summary']!r}"
        )
        assert hs.read_ordered(dirs)[0]["summary"] == "HONEST RESET", "index 0 must match restore"
        assert hs.get_by_index(dirs, 0)["summary"] == "HONEST RESET"

        summaries = [h["summary"] for h in hs.read_ordered(dirs)]
        assert "ready for pretrain v3" in summaries, "older manual stays reachable"
        assert "Session stopped. 2 files edited" in summaries, "newer auto stays reachable"

        # SessionStart's 48h guard still excludes a stale-only scope
        assert hs.read_latest([near], max_age_hours=48) is None

        # Fallback: a scope with NO manual returns the newest of any kind
        autos = root / "autos"
        _write(autos, [mid, noise], noise)
        a = hs.read_latest([autos])
        assert a["summary"] == "Session stopped. 2 files edited", (
            f"no manual in scope -> newest overall; got {a['summary']!r}"
        )

    print("PASS bench_restore_recency_scope: newest-manual beats older-manual AND newer-auto; "
          "index0==restore; history reachable; max_age guard intact; auto-only fallback = newest")


if __name__ == "__main__":
    run()

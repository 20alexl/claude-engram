"""
Idempotent, version-stamped data migrations for Claude Engram.

Why: schema and behaviour evolve between releases, but a user's local data
must keep working across a plain ``git pull`` with no manual steps. Each
migration step is applied at most once (tracked by id in
``manifest.json -> migrations_applied``) and is safe to re-run.

How it runs:
- The SessionStart hook calls ``run(include_heavy=False)``: cheap steps inline
  (fast, within the hook budget), then ``spawn_background()`` if a heavy step
  is still pending.
- ``install.py`` (the documented update path) and
  ``python -m claude_engram.migrations`` call the locked runner with
  ``include_heavy=True``: everything, synchronously.

Steps are forward-only. A step that raises is left pending and retried next
run. Nothing here re-mines or re-embeds — that is unnecessary for any current
migration and would be wasteful.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def _storage(storage_dir=None) -> Path:
    return (
        Path(storage_dir).expanduser()
        if storage_dir
        else Path.home() / ".claude_engram"
    )


def _manifest_path(storage: Path) -> Path:
    return storage / "manifest.json"


def _load_manifest(storage: Path) -> dict:
    p = _manifest_path(storage)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_manifest(storage: Path, manifest: dict) -> None:
    p = _manifest_path(storage)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(p)


def _project_dirs(storage: Path, manifest: dict) -> list[Path]:
    dirs = []
    for info in manifest.get("projects", {}).values():
        h = info.get("hash")
        if h:
            dirs.append(storage / "projects" / h)
    return dirs


# ── Migration steps ────────────────────────────────────────────────────────
# Each entry: (id, heavy, fn(storage, manifest)). Ids are stable forever.


def _seed_handoff_history(storage: Path, manifest: dict) -> None:
    """Seed handoff_history.json from a pre-existing single-slot
    latest_handoff.json so the prior handoff is preserved once the ring starts
    rotating, and history is populated for every project immediately on
    upgrade (not just on the next write)."""
    from claude_engram import handoff_store as hs

    for d in _project_dirs(storage, manifest) + [storage / "checkpoints"]:
        hist_f, latest_f = d / hs.HISTORY_FILENAME, d / hs.LATEST_FILENAME
        if hist_f.exists() or not latest_f.exists():
            continue
        latest = hs._read_json(latest_f)
        if latest:
            latest.setdefault("kind", "manual" if latest.get("next_steps") else "auto")
            hs._atomic_write(hist_f, {"handoffs": [latest]})


def _reextract_related_files(storage: Path, manifest: dict) -> None:
    """Upgrade existing memories' related_files from basenames to full paths
    using the fixed extractor, so historical mistakes gain directory context
    (sharpens cross-version relevance). Merges with existing refs, then drops a
    bare basename when a full path that covers it is present. Idempotent."""
    from claude_engram.tools.memory import extract_file_refs

    for pdir in _project_dirs(storage, manifest):
        mem_file = pdir / "memory.json"
        if not mem_file.exists():
            continue
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        changed = False
        for entry in data.get("entries", []):
            extracted = set(extract_file_refs(entry.get("content", "") or ""))
            if not extracted:
                continue
            original = set(entry.get("related_files", []) or [])
            merged = original | extracted
            covered = {
                f.replace("\\", "/").rsplit("/", 1)[-1]
                for f in merged
                if "/" in f.replace("\\", "/")
            }
            pruned = {
                f
                for f in merged
                if not ("/" not in f.replace("\\", "/") and f in covered)
            }
            if pruned != original:
                entry["related_files"] = sorted(pruned)
                changed = True

        if changed:
            tmp = mem_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(mem_file)


def _redate_downrank_stale_consolidations(storage: Path, manifest: dict) -> None:
    """Old consolidated memories were minted with no date and inherited the
    group's max relevance, so a stale "[Consolidated from N] ... X is complete"
    summary could keep dominating injection as if still true (the bug since
    fixed in the consolidator). Retroactively stamp such entries with their
    creation date (staleness becomes visible) and cap relevance at 8 (a
    point-in-time blob shouldn't outrank a fresh, specific memory). Targets only
    the old UN-dated marker, so it's non-destructive and idempotent — a re-dated
    entry no longer matches."""
    import re
    import time

    undated = re.compile(r"^\[Consolidated from (\d+) memories\]")
    cap = 8

    for pdir in _project_dirs(storage, manifest):
        mem_file = pdir / "memory.json"
        if not mem_file.exists():
            continue
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        changed = False
        for entry in data.get("entries", []):
            content = entry.get("content", "") or ""
            m = undated.match(content)
            if not m:
                continue
            ca = entry.get("created_at", 0) or 0
            if ca:
                stamp = time.strftime("%Y-%m-%d", time.localtime(ca))
                entry["content"] = content.replace(
                    f"[Consolidated from {m.group(1)} memories]",
                    f"[Consolidated {stamp} from {m.group(1)} memories]",
                    1,
                )
                changed = True
            rel = entry.get("relevance")
            if isinstance(rel, int) and rel > cap:
                entry["relevance"] = cap
                changed = True

        if changed:
            tmp = mem_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(mem_file)


def _provably_fixed(content: str, idx) -> bool:
    """The mistake's error can be shown to be resolved against the CURRENT
    code index: the missing module now resolves, the missing name is now
    exported, the missing attribute now exists on that class."""
    import re as _re

    m = _re.search(r"Module '([^']+)' not found", content)
    if m and idx is not None:
        mod = m.group(1)
        try:
            if idx.is_module(mod) or idx.is_package_prefix(mod):
                return True
        except Exception:
            pass
    m = _re.search(r"cannot import '([^']+)' from '([^']+)'", content)
    if m and idx is not None:
        name, mod = m.group(1), m.group(2)
        try:
            rec = idx.by_dotted(mod) or {}
            if (
                name in rec.get("exports", [])
                or name in rec.get("classes", {})
                or name in rec.get("functions", {})
            ):
                return True
        except Exception:
            pass
    m = _re.search(r"'(\w+)' object has no attribute '(\w+)'", content)
    if m and idx is not None:
        cls, attr = m.group(1), m.group(2)
        try:
            for dotted in idx.resolve_symbol(cls):
                rec = idx.by_dotted(dotted) or {}
                ci = rec.get("classes", {}).get(cls, {})
                if attr in ci.get("methods", {}) or attr in ci.get("attrs", []):
                    return True
        except Exception:
            pass
    return False


def _modernize_mistake_store(storage: Path, manifest: dict) -> None:
    """One-time mistake-store modernization (v0.8.4). Two sweeps, both
    archive (never delete), both skip manual ``work_tracker`` entries:

    1. Entries carrying only the legacy in-place ``archived_at`` flag
       (the old acknowledge_mistake) move into archive.json for real.
    2. Machine-written mistakes (auto-detected / session_mining / no
       source) that are PROVABLY fixed against the current code index —
       the module now resolves, the class now has that attribute — are
       archived. The recurring ones worth keeping recur; the fixed ones
       were pure banner noise.

    Raw-JSON on purpose: cheap steps run inline in the SessionStart hook,
    where importing the pydantic store is too slow.
    """
    import time as _time

    from claude_engram.mining.code_index import resolve_code_index

    machine = ("", "auto-detected", "session_mining")
    archive_file = storage / "archive.json"
    try:
        archive = (
            json.loads(archive_file.read_text(encoding="utf-8"))
            if archive_file.exists()
            else {"version": 2, "projects": {}}
        )
    except Exception:
        archive = {"version": 2, "projects": {}}
    archive.setdefault("projects", {})
    archive_changed = False

    for norm, info in manifest.get("projects", {}).items():
        pdir = storage / "projects" / info.get("hash", "")
        mem_file = pdir / "memory.json"
        if not mem_file.exists():
            continue
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries = data.get("entries", [])
        idx = None
        try:
            idx = resolve_code_index(norm, str(storage))
        except Exception:
            pass

        keep, moved = [], []
        now = _time.time()
        for e in entries:
            if e.get("category") != "mistake":
                keep.append(e)
                continue
            if e.get("archived_at"):
                moved.append(e)
                continue
            if (e.get("source") or "") not in machine:
                keep.append(e)
                continue
            if _provably_fixed(e.get("content", ""), idx):
                e["archived_at"] = now
                moved.append(e)
                continue
            keep.append(e)

        if not moved:
            continue
        bucket = archive["projects"].setdefault(
            norm,
            {
                "project_path": norm,
                "project_name": Path(norm).name,
                "entries": [],
            },
        )
        have = {x.get("id") for x in bucket.get("entries", [])}
        for e in moved:
            if e.get("id") not in have:
                bucket.setdefault("entries", []).append(e)
        archive_changed = True

        data["entries"] = keep
        tmp = mem_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(mem_file)

    if archive_changed:
        tmp = archive_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(archive, indent=2), encoding="utf-8")
        tmp.replace(archive_file)


STEPS = [
    ("0.5.0:seed_handoff_history", False, _seed_handoff_history),
    ("0.5.0:reextract_related_files", True, _reextract_related_files),
    (
        "0.7.0:redate_downrank_consolidations",
        False,
        _redate_downrank_stale_consolidations,
    ),
    ("0.8.4:modernize_mistake_store", False, _modernize_mistake_store),
]


# ── Runner ───────────────────────────────────────────────────────────────────


def heavy_pending(storage_dir=None) -> bool:
    """True if a heavy step still needs to run (and there is data to migrate)."""
    storage = _storage(storage_dir)
    if not _manifest_path(storage).exists():
        return False
    applied = set(_load_manifest(storage).get("migrations_applied", []))
    return any(heavy and sid not in applied for sid, heavy, _ in STEPS)


def run(storage_dir=None, include_heavy: bool = False) -> dict:
    """Apply pending migrations. Cheap steps always run; heavy steps run only
    when include_heavy=True (otherwise left pending). Idempotent."""
    storage = _storage(storage_dir)
    report = {"applied": [], "errors": [], "pending_heavy": False}

    # Fresh install (no manifest yet) has no data to migrate; don't create one.
    if not _manifest_path(storage).exists():
        return report

    manifest = _load_manifest(storage)
    applied = set(manifest.get("migrations_applied", []))
    changed = False
    for sid, heavy, fn in STEPS:
        if sid in applied:
            continue
        if heavy and not include_heavy:
            report["pending_heavy"] = True
            continue
        try:
            fn(storage, manifest)
            applied.add(sid)
            report["applied"].append(sid)
            changed = True
        except Exception as e:  # leave pending; retry next run
            report["errors"].append(f"{sid}: {e}")

    if changed:
        manifest["migrations_applied"] = sorted(applied)
        _save_manifest(storage, manifest)
    return report


# ── Background spawn + lock (for the heavy step off the hook hot path) ───────

_LOCK = Path("~/.claude_engram/migration.lock").expanduser()


def _is_pid_alive(pid: int) -> bool:
    try:
        if platform.system() == "Windows":
            import ctypes

            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if h:
                k.CloseHandle(h)
                return True
            return False
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False


def _locked() -> bool:
    if not _LOCK.exists():
        return False
    try:
        if _is_pid_alive(int(_LOCK.read_text().strip())):
            return True
        _LOCK.unlink(missing_ok=True)
    except (ValueError, OSError):
        _LOCK.unlink(missing_ok=True)
    return False


def spawn_background(storage_dir=None) -> bool:
    """Spawn this module detached to run heavy migrations without blocking the
    SessionStart hook. No-op if one is already running. Fire-and-forget."""
    if _locked():
        return False
    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        cmd = [sys.executable, "-m", "claude_engram.migrations", "--heavy"]
        if storage_dir:
            cmd += ["--storage", str(storage_dir)]
        subprocess.Popen(cmd, **kwargs)
        return True
    except Exception:
        return False


def migrate(storage_dir=None, include_heavy: bool = True) -> dict:
    """Locked entry point for synchronous full migration (install.py, CLI)."""
    if include_heavy:
        if _locked():
            return {
                "applied": [],
                "errors": ["migration already running"],
                "pending_heavy": True,
            }
        _LOCK.parent.mkdir(parents=True, exist_ok=True)
        _LOCK.write_text(str(os.getpid()))
    try:
        return run(storage_dir, include_heavy=include_heavy)
    finally:
        if include_heavy:
            _LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Claude Engram data migrations")
    ap.add_argument("--heavy", action="store_true", help="Run heavy steps too")
    ap.add_argument("--storage", default=None, help="Storage dir override")
    args = ap.parse_args()
    print(json.dumps(migrate(args.storage, include_heavy=args.heavy), indent=2))

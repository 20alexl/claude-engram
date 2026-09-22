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
from typing import Any

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


def _reattribute_pooled(storage: Path, manifest: dict) -> None:
    """Move mined mistakes and decisions to the sub-project their files name
    (v0.8.36, rule corrected in v0.8.37). Sessions run from a workspace root
    mined everything into the root store; a sub-project's own store stayed
    empty while the root pooled every sibling's tracebacks. Heavy: uses the
    pydantic store (delete + re-add, keeping id, timestamps and flags), so it
    runs in the background, never inline in a hook. Idempotent: an entry whose
    files resolve to its own project does not move.

    Destinations are restricted to the manifest's own projects (v0.8.37).
    Marker-walking alone routed files under a git worktree
    (``<proj>/.scratch/stack/<wt>``, whose ``.git`` FILE is a marker) to the
    worktree, so trade-lab's and kaggriculture's errors ended up listed as
    claude-engram's own."""
    from claude_engram.hooks.paths import target_project_for_files
    from claude_engram.tools.memory import MemoryStore

    store = MemoryStore(storage_dir=str(storage))
    projects = list(manifest.get("projects", {}).keys())
    norm = {store._normalize_path(p): p for p in projects}

    def _root_of(p: str) -> str:
        # The topmost registered ancestor: entries are routed from the
        # workspace root so a traceback filed under the wrong sibling can
        # still move to the sibling its text names.
        cur = store._normalize_path(p)
        best = cur
        while True:
            parent = str(Path(cur).parent).replace("\\", "/")
            if parent == cur:
                break
            if parent.lower() in {k.lower() for k in norm}:
                best = parent
            cur = parent
        return best

    moved = 0
    for src in projects:
        proj = store.get_project(src)
        if proj is None:
            continue
        root = _root_of(src)
        for entry in list(proj.entries):
            if entry.category not in ("mistake", "decision") or not entry.related_files:
                continue
            if entry.source not in (None, "", "session_mining", "auto-detected"):
                continue  # a person's own entry stays where they put it
            dst = target_project_for_files(
                root,
                list(entry.related_files),
                entry.content,
                known_projects=projects,
            )
            if not dst or store._normalize_path(dst) == store._normalize_path(src):
                continue
            if store._normalize_path(dst) == store._normalize_path(root) and store._normalize_path(src) != store._normalize_path(root):
                continue  # no sub-project evidence: a sub-project's entry never falls back to the root
            if not Path(dst).is_dir():
                continue
            ok, _ = store.delete_memory(src, entry.id)
            if not ok:
                continue
            store.remember_discovery(
                dst,
                entry.content,
                source=entry.source,
                relevance=entry.relevance,
                tags=list(entry.tags),
                related_files=list(entry.related_files),
                category=entry.category,
                auto_embed=False,
            )
            dproj = store.get_project(dst)
            if dproj is not None and dproj.entries:
                new = dproj.entries[-1]
                new.id = entry.id
                new.created_at = entry.created_at
                new.last_accessed = entry.last_accessed
                new.access_count = entry.access_count
                new.archived_at = entry.archived_at
                new.cluster_id = None
                store._dirty_projects.add(store._normalize_path(dst))
            moved += 1
    if moved:
        store._save()
    _log(f"reattribute_pooled: moved {moved} mined entries to the projects their files name")


def _log(msg: str) -> None:
    try:
        print(f"[migrations] {msg}", file=sys.stderr)
    except Exception:
        pass


def _drop_worktree_projects(storage: Path, manifest: dict) -> None:
    """Unregister projects that were never projects: a git worktree or a
    path inside a scratch/vendor dir, registered because its `.git` file or
    marker made the resolver stop there (eleven `trade-lab/.scratch/*-wt`
    entries with empty stores, 2026-09-11). Since 0.8.39 the resolver maps
    those to the main repository, so the entries can never be reached
    again. Only an EMPTY store is dropped; a store with entries is left
    for a person (moved nothing, deleted nothing). The store directory is
    moved under ``_unregistered/`` in the storage dir, never removed."""
    from claude_engram.hooks.paths import canonical_project_root, _normalize_path

    projects = manifest.get("projects")
    if not isinstance(projects, dict):
        return
    for path in list(projects):
        info = projects.get(path) or {}
        try:
            norm = _normalize_path(str(path))
            if canonical_project_root(norm) == norm:
                continue  # a real project
            hdir = storage / "projects" / str(info.get("hash") or "")
            if hdir.is_dir():
                mem = hdir / "memory.json"
                if mem.is_file():
                    data = json.loads(mem.read_text(encoding="utf-8"))
                    values = data.values() if isinstance(data, dict) else []
                    if any(isinstance(v, list) and v for v in values):
                        _log(f"kept {path}: its store has entries")
                        continue
                parked = storage / "_unregistered"
                parked.mkdir(parents=True, exist_ok=True)
                target = parked / hdir.name
                if not target.exists():
                    hdir.rename(target)
            del projects[path]
            _log(f"unregistered {path} (worktree or scratch path; empty store)")
        except Exception as e:
            _log(f"skip {path}: {e}")


def _prune_junk_decisions(storage: Path, manifest: dict) -> None:
    """Archive (never delete) machine-captured decisions that do not have
    the shape of one: questions, acknowledgements, counts, status lines,
    fragments. The miner's semantic tier stored anything above a bare
    cosine and its question filter was dead code, so one week put 636 such
    entries into a workspace store (2026-09-22). The same gate now guards
    both capture paths (mining/decision_gate.py); this applies it to what
    is already on disk. Manual entries (work_tracker, the memory tool) are
    never touched; archived entries stay restorable by id."""
    import time as _time

    from claude_engram.mining.decision_gate import looks_like_correction, looks_like_decision

    machine = ("session_mining", "auto-prompt")
    archive_file = storage / "archive.json"
    try:
        archive = json.loads(archive_file.read_text(encoding="utf-8")) if archive_file.exists() else {"version": 2, "projects": {}}
    except Exception:
        archive = {"version": 2, "projects": {}}
    archive.setdefault("projects", {})
    archive_changed = False
    total_moved = 0

    for norm, info in manifest.get("projects", {}).items():
        mem_file = storage / "projects" / str(info.get("hash", "")) / "memory.json"
        if not mem_file.exists():
            continue
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        keep, moved = [], []
        now = _time.time()
        for e in data.get("entries", []):
            if e.get("category") != "decision" or (e.get("source") or "") not in machine or e.get("archived_at"):
                keep.append(e)
                continue
            content = str(e.get("content") or "")
            is_pref = content.lstrip().upper().startswith("USER PREFERENCE")
            ok = looks_like_correction(content) if is_pref else looks_like_decision(content)
            if ok:
                keep.append(e)
            else:
                e["archived_at"] = now
                moved.append(e)
        if not moved:
            continue
        bucket = archive["projects"].setdefault(norm, {"project_path": norm, "project_name": Path(norm).name, "entries": []})
        have = {x.get("id") for x in bucket.get("entries", [])}
        for e in moved:
            if e.get("id") not in have:
                bucket.setdefault("entries", []).append(e)
        archive_changed = True
        total_moved += len(moved)
        data["entries"] = keep
        tmp = mem_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(mem_file)
        _log(f"{Path(norm).name}: archived {len(moved)} machine-captured decisions without the shape of one")

    if archive_changed:
        tmp = archive_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(archive, indent=2), encoding="utf-8")
        tmp.replace(archive_file)
    _log(f"prune_junk_decisions: {total_moved} archived")


STEPS = [
    ("0.5.0:seed_handoff_history", False, _seed_handoff_history),
    ("0.5.0:reextract_related_files", True, _reextract_related_files),
    (
        "0.7.0:redate_downrank_consolidations",
        False,
        _redate_downrank_stale_consolidations,
    ),
    ("0.8.4:modernize_mistake_store", False, _modernize_mistake_store),
    # Re-run under 0.8.37: the routing rule changed (registered projects only,
    # never a worktree or vendor dir), so the 0.8.36 pass has to be redone.
    ("0.8.37:reattribute_pooled", True, _reattribute_pooled),
    ("0.8.40:drop_worktree_projects", False, _drop_worktree_projects),
    ("0.8.46:prune_junk_decisions", False, _prune_junk_decisions),
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
        kwargs: dict[str, Any] = {
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

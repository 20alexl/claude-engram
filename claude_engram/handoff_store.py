"""
Durable handoff storage with ring-buffer history.

Replaces the single-slot ``latest_handoff.json`` with:

- A capped ring buffer (``handoff_history.json``) so no handoff is ever lost
  (fixes the "single overwritable slot" bug).
- A promotion guard so a trivial auto-handoff (a session that edited nothing
  and made no decisions) never buries a substantive or manual handoff
  (fixes "auto-generated empty handoffs overwrite rich ones").
- A ``kind: manual|auto`` marker so retrieval can prefer substantive handoffs.
- ``latest_handoff.json`` kept in sync for backward compatibility with every
  existing reader.

This module is pure I/O + policy. Callers resolve *which* directories to
write/read (a per-project hash dir and the global checkpoints dir) and pass
them in. That keeps this module free of any dependency on manifest/path
resolution and avoids the import cycle with ``hooks.remind``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

HISTORY_FILENAME = "handoff_history.json"
LATEST_FILENAME = "latest_handoff.json"
DEFAULT_HISTORY_LIMIT = 20

# Default next_steps emitted by the auto writers — they carry no real signal,
# so they must not count toward a handoff being "substantive".
_TRIVIAL_NEXT_STEPS = {
    "review what was in progress",
    "continue work from before compaction",
    "review context_needed items",
}

# Manual handoffs are always substantive; this dwarfs any content-based score.
_MANUAL_BONUS = 100


def _created_ts(h: dict) -> float:
    """Timestamp of a handoff, tolerant of the legacy ``created_at`` key."""
    return h.get("created", h.get("created_at", 0)) or 0


def handoff_signal(h: dict) -> int:
    """
    Substantive-ness score for a handoff. ``0`` means a trivial auto-handoff
    with no real session signal; manual handoffs always score high.

    Used both to skip empty auto-handoffs and to guard the latest pointer.
    """
    if not h:
        return -1
    score = 0
    score += len(h.get("files_in_progress") or h.get("files_involved") or [])
    score += 2 * len(h.get("decisions") or [])
    score += len(h.get("context_needed") or [])
    score += len(h.get("warnings") or [])
    score += len(h.get("mistakes") or [])
    real_next = [
        s
        for s in (h.get("next_steps") or [])
        if s and s.strip().lower() not in _TRIVIAL_NEXT_STEPS
    ]
    score += 2 * len(real_next)
    if h.get("kind") == "manual":
        score += _MANUAL_BONUS
    return score


def is_trivial_auto(h: dict) -> bool:
    """An auto-handoff that carries no signal worth persisting."""
    return h.get("kind") != "manual" and handoff_signal(h) <= 0


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _load_history(dir_path: Path) -> list:
    data = _read_json(dir_path / HISTORY_FILENAME)
    if isinstance(data, dict):
        return data.get("handoffs", []) or []
    if isinstance(data, list):  # tolerate a bare-list format
        return data
    return []


def _should_promote(
    new: dict, existing: Optional[dict], stale_hours: float = 24.0
) -> bool:
    """
    Decide whether ``new`` should replace the current ``latest`` pointer.

    Rules:
    - No existing latest -> promote.
    - Manual handoff -> always promote.
    - Otherwise promote only if ``new`` is at least as substantive as the
      existing one, or the existing one is stale (older than ``stale_hours``).
    """
    if not existing:
        return True
    if new.get("kind") == "manual":
        return True
    if handoff_signal(new) >= handoff_signal(existing):
        return True
    age_h = (time.time() - _created_ts(existing)) / 3600
    return age_h > stale_hours


def write_handoff(
    handoff: dict,
    target_dirs: list[Optional[Path]],
    *,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    stale_hours: float = 24.0,
) -> dict:
    """
    Persist ``handoff`` to each target dir. MANUAL handoffs append to the
    history ring AND contend for the ``latest`` pointer; AUTO handoffs only
    contend for the pointer (subject to the promotion guard).

    Why autos stay out of the ring: the Stop hook fires at the END OF EVERY
    TURN, so appending its per-turn "Session stopped" autos evicted real
    checkpoints from the 20-slot FIFO within a single working session. The
    newest auto stays visible anyway — read_history folds each dir's latest
    pointer back in. Nobody restores to "where I was three stops ago", but
    they do restore to last week's manual checkpoint.

    Trivial auto-handoffs (no files, no decisions, no real next steps) are
    skipped entirely — they are neither appended nor promoted, so they can
    never bury a substantive handoff.

    ``target_dirs`` is ordered (typically [project_hash_dir, global_dir]);
    ``None`` entries are ignored. Returns a small report.
    """
    handoff.setdefault("created", time.time())
    handoff.setdefault("kind", "auto")

    report = {"skipped": False, "appended": [], "promoted": []}

    if is_trivial_auto(handoff):
        report["skipped"] = True
        return report

    for d in target_dirs:
        if d is None:
            continue

        history = _load_history(d)
        history_changed = False
        # Migration: seed history from any pre-existing single-slot handoff so
        # we never silently drop what was there before this module existed.
        # Runs for auto writes too: an auto that out-promotes below would
        # otherwise overwrite the legacy latest before it ever reached the ring.
        if not history:
            seed = _read_json(d / LATEST_FILENAME)
            if seed:
                history = [seed]
                history_changed = True

        if handoff.get("kind") == "manual":
            history.append(handoff)
            history_changed = True
        if len(history) > history_limit:
            history = history[-history_limit:]
            history_changed = True
        if history_changed:
            _atomic_write(d / HISTORY_FILENAME, {"handoffs": history})
            report["appended"].append(str(d))

        existing_latest = _read_json(d / LATEST_FILENAME)
        if _should_promote(handoff, existing_latest, stale_hours=stale_hours):
            _atomic_write(d / LATEST_FILENAME, handoff)
            report["promoted"].append(str(d))

    return report


def read_latest(
    candidate_dirs: list[Optional[Path]], *, max_age_hours: Optional[float] = None
) -> Optional[dict]:
    """
    Return the most recent DELIBERATE handoff across all candidate dirs: the
    newest ``manual`` checkpoint, falling back to the newest handoff of any kind
    only when no manual one is in scope.

    This replaces "first candidate dir wins" (the old behavior), which returned
    a nearest ancestor ring's pointer regardless of age — so a sub-project query
    (e.g. ``monorepo/app`` -> ``monorepo``) could surface a weeks-old "ready for
    pretrain v3" as the latest while the genuine newest sat at a higher index. Two
    properties matter and pure recency only gets the first:
      1. a newer manual must outrank an older manual  -> kills the stale bug;
      2. a routine auto "Session stopped" must not bury a deliberate checkpoint.
    Newest-manual-first gives both. Per-ring manual promotion still happens at
    write time; this only chooses across the already-resolved scope. Callers
    that want a hard freshness bound pass ``max_age_hours`` (e.g. the
    SessionStart banner uses 48h) — the bound applies to AUTOS; a deliberate
    manual checkpoint gets 14 days (a weekend away must not silently expire
    the handoff you wrote for yourself while restore-by-index still finds it).
    """
    MANUAL_MAX_AGE_HOURS = 14 * 24.0

    hist = read_history(candidate_dirs)
    if max_age_hours is not None:
        manual_cut = max(float(max_age_hours), MANUAL_MAX_AGE_HOURS)

        def _fresh(h: dict) -> bool:
            age_h = (time.time() - _created_ts(h)) / 3600
            if h.get("kind") == "manual":
                return age_h <= manual_cut
            return age_h <= max_age_hours

        hist = [h for h in hist if _fresh(h)]
    if not hist:
        return None
    manual = [h for h in hist if h.get("kind") == "manual"]
    return manual[0] if manual else hist[0]


def read_history(
    candidate_dirs: list[Optional[Path]], *, limit: int = DEFAULT_HISTORY_LIMIT
) -> list:
    """
    Merged handoff history across candidate dirs, newest first, deduplicated
    by (timestamp, summary-prefix). Each dir's promoted ``latest`` pointer is
    folded in too, so a legacy single-slot handoff that predates the ring (no
    ``handoff_history.json``) is still seen by recency-based selection.
    """
    seen = set()
    out = []
    for d in candidate_dirs:
        if d is None:
            continue
        entries = list(_load_history(d))
        ptr = _read_json(d / LATEST_FILENAME)
        if ptr:
            entries.append(ptr)
        for h in entries:
            if not h:
                continue
            key = (round(_created_ts(h), 3), (h.get("summary") or "")[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
    out.sort(key=_created_ts, reverse=True)
    return out[:limit]


def read_ordered(
    candidate_dirs: list[Optional[Path]], *, limit: int = DEFAULT_HISTORY_LIMIT
) -> list:
    """History ordered for retrieval and listing: the deliberate ``latest``
    (see ``read_latest``) first, so index 0 == what ``checkpoint_restore``
    returns, then the remaining handoffs newest-first. ``read_latest`` now
    selects the newest *manual* checkpoint across the resolved scope, so index 0
    is the freshest deliberate checkpoint — not a stale ancestor pointer (the
    prior bug) and not a routine auto-stop that happens to be newest."""
    hist = read_history(candidate_dirs, limit=limit)
    latest = read_latest(candidate_dirs)
    if not latest:
        return hist

    def _key(h: dict):
        return (round(_created_ts(h), 3), (h.get("summary") or "")[:80])

    lk = _key(latest)
    ordered = [latest] + [h for h in hist if _key(h) != lk]
    return ordered[:limit]


def get_by_index(
    candidate_dirs: list[Optional[Path]],
    index: int,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> Optional[dict]:
    """Retrieve a single handoff by index (0 == the promoted latest, then older
    handoffs newest-first). See ``read_ordered``."""
    ordered = read_ordered(candidate_dirs, limit=limit)
    if 0 <= index < len(ordered):
        return ordered[index]
    return None

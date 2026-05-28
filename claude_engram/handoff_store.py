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
    Persist ``handoff`` to each target dir: append to the ring buffer and
    update the ``latest`` pointer subject to the promotion guard.

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
        # Migration: seed history from any pre-existing single-slot handoff so
        # we never silently drop what was there before this module existed.
        if not history:
            seed = _read_json(d / LATEST_FILENAME)
            if seed:
                history = [seed]

        history.append(handoff)
        if len(history) > history_limit:
            history = history[-history_limit:]
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
    Return the latest handoff from the first candidate dir that has one.

    Callers order ``candidate_dirs`` nearest-project-first with the global
    dir last, so a project's own handoff always wins over the shared global
    slot (fixes the "wrong handoff from the root project" bug).
    """
    for d in candidate_dirs:
        if d is None:
            continue
        h = _read_json(d / LATEST_FILENAME)
        if not h:
            hist = _load_history(d)
            h = hist[-1] if hist else None
        if not h:
            continue
        if max_age_hours is not None and (time.time() - _created_ts(h)) / 3600 > max_age_hours:
            continue
        return h
    return None


def read_history(
    candidate_dirs: list[Optional[Path]], *, limit: int = DEFAULT_HISTORY_LIMIT
) -> list:
    """
    Merged handoff history across candidate dirs, newest first, deduplicated
    by (timestamp, summary-prefix).
    """
    seen = set()
    out = []
    for d in candidate_dirs:
        if d is None:
            continue
        for h in _load_history(d):
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
    """History ordered for retrieval and listing: the promoted ``latest`` first
    (so index 0 == what a plain ``read_latest`` returns), then the remaining
    handoffs newest-first. This keeps ``handoff_get index=N`` and
    ``handoff_list`` consistent even when the promotion guard kept an older
    manual handoff as latest over a newer auto one.
    """
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

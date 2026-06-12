"""
Pattern Detection — find recurring patterns across sessions.

Analyzes session index + extractions to detect:
  - Struggle files (edited many times with errors)
  - Recurring errors (same error across 3+ sessions)
  - Edit correlations (files always edited together)
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Struggle:
    """A file/area where the user repeatedly struggles."""

    file_path: str
    sessions_affected: int
    total_edits: int
    errors_nearby: int
    description: str = ""


@dataclass
class RecurringError:
    """An error that appears across multiple sessions."""

    error_type: str
    message_pattern: str  # Normalized signature (grouping key only)
    session_count: int
    sessions: list[str] = field(default_factory=list)  # session IDs
    example: str = ""  # A concrete, un-templated instance — keeps it actionable
    fix: str = ""  # how_to_avoid, when one was recorded
    projects: list[str] = field(default_factory=list)  # sub-projects it hit
    last_seen: str = ""  # newest contributing session timestamp (ISO)


@dataclass
class EditCorrelation:
    """Files that are frequently edited together."""

    file_a: str
    file_b: str
    co_occurrence: int  # How many sessions both appear in
    total_sessions: int  # Total sessions where either appears
    strength: float = 0.0  # co_occurrence / total_sessions


@dataclass
class PatternReport:
    """All detected patterns for a project."""

    struggles: list[Struggle] = field(default_factory=list)
    recurring_errors: list[RecurringError] = field(default_factory=list)
    correlations: list[EditCorrelation] = field(default_factory=list)
    generated_at: float = 0.0


def detect_all_patterns(
    project_path: str,
    index,  # SessionIndex
    engram_storage_dir: str = "~/.claude_engram",
) -> Optional[PatternReport]:
    """
    Run all pattern detectors and save results.

    Returns PatternReport or None if insufficient data.
    """
    import time

    sessions = index.sessions
    if len(sessions) < 2:
        return None

    report = PatternReport(
        struggles=detect_struggles(
            sessions, project_root=project_path, engram_storage_dir=engram_storage_dir
        ),
        recurring_errors=detect_recurring_errors(
            sessions, project_path, engram_storage_dir
        ),
        correlations=detect_edit_correlations(sessions),
        generated_at=time.time(),
    )

    # Save report
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        norm_path = _normalize_path(project_path)
        proj_info = manifest.get("projects", {}).get(norm_path)
        if proj_info:
            hash_dir = storage / "projects" / proj_info["hash"]
            report_path = hash_dir / "patterns.json"
            tmp = report_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(asdict(report), indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(report_path)

    return report


def _error_sessions_by_file(
    project_root: str, engram_storage_dir: str
) -> "dict[str, set]":
    """basename(lower) -> sessions whose extraction MISTAKES reference it
    (via related_files or a traceback `File "x.py"` in the description).
    This is causal attribution; "the session had an error somewhere" is not."""
    out: dict[str, set] = {}
    try:
        storage = Path(engram_storage_dir).expanduser()
        manifest_path = storage / "manifest.json"
        if not (project_root and manifest_path.exists()):
            return out
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        proj_info = manifest.get("projects", {}).get(_normalize_path(project_root))
        if not proj_info:
            return out
        ext_dir = storage / "projects" / proj_info["hash"] / "extractions"
        if not ext_dir.exists():
            return out
        for ext_file in ext_dir.glob("*.json"):
            try:
                data = json.loads(ext_file.read_text(encoding="utf-8"))
                sid = data.get("session_id", ext_file.stem)
                for m in data.get("mistakes", []):
                    names = {
                        Path(f).name.lower()
                        for f in (m.get("related_files") or [])
                    }
                    for fm in re.finditer(
                        r'File ["\']([^"\']+\.py)["\']', m.get("description", "") or ""
                    ):
                        names.add(Path(fm.group(1)).name.lower())
                    for n in names:
                        out.setdefault(n, set()).add(sid)
            except Exception:
                continue
    except Exception:
        pass
    return out


def detect_struggles(
    sessions: dict[str, dict],
    project_root: str = "",
    engram_storage_dir: str = "",
) -> list[Struggle]:
    """
    Find files that are repeatedly edited WITH errors actually tied to them.

    Two deliberate properties (both were bugs before):
    - Keys are FULL paths — service-a/__init__.py and service-b/__init__.py
      no longer pool into one phantom "workspace/__init__.py".
    - errors_nearby counts sessions where the file was edited AND an
      extracted mistake references that file. The old session-level check
      ("the session had an error somewhere") made every often-edited file
      look like a struggle: "CLAUDE.md (4 sessions, 4 errors)".
    Files with zero attributable errors are not struggles, however often
    they're edited. If project_root is provided, only includes files that
    still exist (filters dead/archived code).
    """
    file_sessions: dict[str, set] = {}  # full path -> {session_ids}
    for sid, meta in sessions.items():
        files = (
            meta.get("files_edited", [])
            if isinstance(meta, dict)
            else getattr(meta, "files_edited", [])
        )
        for fp in files:
            file_sessions.setdefault(fp, set()).add(sid)

    error_by_name = _error_sessions_by_file(project_root, engram_storage_dir)
    if not error_by_name:
        return []  # no attributable errors anywhere -> no struggles to report

    # If project_root given, check file existence (skip archived/deleted code)
    _archive_dirs = {"archive", "old", "backup", "deprecated", "legacy", ".archive"}
    existing_files: "set[str] | None" = None
    if project_root:
        root = Path(project_root)
        if root.exists():
            existing_files = set()
            for p in root.rglob("*"):
                if any(part.lower() in _archive_dirs for part in p.parts):
                    continue
                if p.is_file():
                    existing_files.add(p.name)

    struggles = []
    for fpath, sids in file_sessions.items():
        if len(sids) < 2:
            continue
        name = Path(fpath).name
        if existing_files is not None and name not in existing_files:
            continue

        # Only sessions where this file was edited AND an extracted mistake
        # names it count as error sessions.
        real_errors = len(error_by_name.get(name.lower(), set()) & sids)
        if real_errors < 1:
            continue

        score = len(sids) * (1 + real_errors / len(sids))
        if score < 3:
            continue

        struggles.append(
            Struggle(
                file_path=fpath,
                sessions_affected=len(sids),
                total_edits=len(sids),
                errors_nearby=real_errors,
                description=(
                    f"Edited in {len(sids)} sessions, errors traced to it "
                    f"in {real_errors}"
                ),
            )
        )

    struggles.sort(key=lambda s: -(s.sessions_affected + s.errors_nearby))
    return struggles[:20]


_ERR_QUOTED = re.compile(r"""['"][^'"]{1,80}['"]""")
_ERR_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_ERR_DOTTED = re.compile(r"\b\w+(?:\.\w+)+\b")
_ERR_NUM = re.compile(r"\b\d+\b")


def _normalize_error_msg(msg: str) -> str:
    """Template out the variable parts of an error message — quoted names,
    dotted module paths, hex addresses, numbers — so the *same* error with
    different identifiers collapses into one signature. This turns coarse
    "AttributeError (3 sessions)" buckets into actionable, distinct patterns."""
    msg = _ERR_QUOTED.sub("<name>", msg)
    msg = _ERR_HEX.sub("<addr>", msg)
    msg = _ERR_DOTTED.sub("<path>", msg)
    msg = _ERR_NUM.sub("<n>", msg)
    return " ".join(msg.split())[:120]


def _clip(s: str, n: int) -> str:
    """Collapse whitespace and truncate at a word boundary, so an identifier is
    never cut mid-token (which made surfaced errors like '...checkpoint_ma'
    unreadable)."""
    s = " ".join((s or "").split())
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


def detect_recurring_errors(
    sessions: dict[str, dict],
    project_path: str,
    engram_storage_dir: str,
) -> list[RecurringError]:
    """
    Find errors that appear across multiple sessions.

    Reads extraction files to aggregate error types.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    norm_path = _normalize_path(project_path)
    proj_info = manifest.get("projects", {}).get(norm_path)
    if not proj_info:
        return []

    hash_dir = storage / "projects" / proj_info["hash"]
    extractions_dir = hash_dir / "extractions"
    if not extractions_dir.exists():
        return []

    # Collect errors from all extraction files
    error_occurrences: dict[str, list[str]] = {}  # error_key -> [session_ids]
    error_examples: dict[str, str] = {}  # error_key -> longest concrete description
    error_fixes: dict[str, str] = {}  # error_key -> first how_to_avoid seen

    for ext_file in extractions_dir.glob("*.json"):
        try:
            data = json.loads(ext_file.read_text(encoding="utf-8"))
            session_id = data.get("session_id", ext_file.stem)

            for mistake in data.get("mistakes", []):
                error_type = mistake.get("error_type", "")
                desc = mistake.get("description", "") or ""
                if not error_type:
                    continue
                # Group by a normalized signature (class + templated message),
                # not the bare exception class — the full message is already
                # stored in `description`, so this needs no schema change.
                prefix = error_type + ": "
                raw_msg = desc[len(prefix) :] if desc.startswith(prefix) else desc
                norm_msg = _normalize_error_msg(raw_msg)
                sig = f"{error_type}: {norm_msg}" if norm_msg else error_type
                error_occurrences.setdefault(sig, []).append(session_id)
                # Keep one concrete, un-templated instance (longest = most
                # context) plus a fix if recorded, so the surfaced pattern
                # stays actionable instead of "<name> has no attribute <name>".
                full = desc.strip()
                if len(full) > len(error_examples.get(sig, "")):
                    error_examples[sig] = full
                fix = (mistake.get("how_to_avoid") or mistake.get("fix") or "").strip()
                if fix and not error_fixes.get(sig):
                    error_fixes[sig] = fix
        except Exception:
            continue

    from datetime import datetime, timedelta, timezone

    from claude_engram.hooks.paths import resolve_project_for_file

    # Per-session project + recency lookups (sessions = the index metas).
    # Attribution: a session's errors belong to the sub-projects its edits
    # touched — so a vzip session stops seeing CORTEX errors at startup.
    def _session_projects(sid: str) -> set:
        meta = sessions.get(sid) or {}
        files = (
            meta.get("files_edited", [])
            if isinstance(meta, dict)
            else getattr(meta, "files_edited", [])
        )
        out = set()
        for f in files[:20]:
            try:
                out.add(_normalize_path(resolve_project_for_file(f, project_path)))
            except Exception:
                continue
        return out

    def _session_ts(sid: str) -> str:
        meta = sessions.get(sid) or {}
        if isinstance(meta, dict):
            return meta.get("last_timestamp", "")
        return getattr(meta, "last_timestamp", "")

    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).isoformat()

    recurring = []
    for sig, sids in error_occurrences.items():
        unique_sessions = list(set(sids))
        if len(unique_sessions) >= 2:
            last_seen = max((_session_ts(s) for s in unique_sessions), default="")
            # Recency: an error not seen in 30 days is history, not a
            # pattern — without this, high-count FIXED errors pin the
            # banner's top slots forever.
            if last_seen and last_seen < cutoff_iso:
                continue
            projects: set = set()
            for s in unique_sessions[:10]:
                projects |= _session_projects(s)
            error_type = sig.split(":", 1)[0]
            recurring.append(
                RecurringError(
                    error_type=error_type,
                    message_pattern=sig,
                    session_count=len(unique_sessions),
                    sessions=unique_sessions[:10],
                    example=_clip(error_examples.get(sig, ""), 200),
                    fix=_clip(error_fixes.get(sig, ""), 160),
                    projects=sorted(projects)[:5],
                    last_seen=last_seen,
                )
            )

    # Most sessions first; ties broken by freshest sighting.
    recurring.sort(key=lambda e: (e.session_count, e.last_seen), reverse=True)
    return recurring[:15]


def detect_edit_correlations(
    sessions: dict[str, dict],
    min_co_occurrence: int = 2,
    min_strength: float = 0.3,
) -> list[EditCorrelation]:
    """
    Find files that are frequently edited together.

    Uses co-occurrence analysis across sessions.
    """
    # Build file -> sessions mapping (use filenames, not full paths)
    file_sessions: dict[str, set[str]] = {}
    for sid, meta in sessions.items():
        for fp in meta.get("files_edited", []):
            name = Path(fp).name
            file_sessions.setdefault(name, set()).add(sid)

    # Filter to files that appear in 2+ sessions
    active_files = {f: sids for f, sids in file_sessions.items() if len(sids) >= 2}

    correlations = []
    files = sorted(active_files.keys())

    for i, file_a in enumerate(files):
        for file_b in files[i + 1 :]:
            co = len(active_files[file_a] & active_files[file_b])
            if co < min_co_occurrence:
                continue

            total = len(active_files[file_a] | active_files[file_b])
            strength = co / total if total > 0 else 0

            if strength >= min_strength:
                correlations.append(
                    EditCorrelation(
                        file_a=file_a,
                        file_b=file_b,
                        co_occurrence=co,
                        total_sessions=total,
                        strength=round(strength, 3),
                    )
                )

    correlations.sort(key=lambda c: -c.strength)
    return correlations[:30]


def _normalize_path(project_path: str) -> str:
    """Normalize project path for manifest lookup."""
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm

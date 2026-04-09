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
    message_pattern: str  # Common substring
    session_count: int
    sessions: list[str] = field(default_factory=list)  # session IDs


@dataclass
class EditCorrelation:
    """Files that are frequently edited together."""
    file_a: str
    file_b: str
    co_occurrence: int     # How many sessions both appear in
    total_sessions: int    # Total sessions where either appears
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
        struggles=detect_struggles(sessions, project_root=project_path),
        recurring_errors=detect_recurring_errors(sessions, project_path, engram_storage_dir),
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


def detect_struggles(
    sessions: dict[str, dict],
    project_root: str = "",
) -> list[Struggle]:
    """
    Find files that are repeatedly edited with errors nearby.

    A "struggle" is a file that appears in 3+ sessions with high edit counts
    or errors in those sessions. If project_root is provided, only includes
    files that still exist in the project (filters out dead/archived code).
    """
    # Count per-file: how many sessions, total edits estimated, error sessions
    file_sessions: dict[str, list[str]] = {}  # filename -> [session_ids]
    file_error_sessions: dict[str, int] = {}  # filename -> count of error sessions

    for sid, meta in sessions.items():
        files = meta.get("files_edited", [])
        has_errors = meta.get("has_errors", False) or meta.get("error_count", 0) > 0

        for fp in files:
            name = Path(fp).name
            file_sessions.setdefault(name, []).append(sid)
            if has_errors:
                file_error_sessions[name] = file_error_sessions.get(name, 0) + 1

    # If project_root given, check file existence (skip archived/deleted code)
    # Exclude common archive/backup directories
    _archive_dirs = {"archive", "old", "backup", "deprecated", "legacy", ".archive"}
    existing_files: set[str] | None = None
    if project_root:
        root = Path(project_root)
        if root.exists():
            existing_files = set()
            for p in root.rglob("*"):
                # Skip archive directories
                if any(part.lower() in _archive_dirs for part in p.parts):
                    continue
                if p.is_file():
                    existing_files.add(p.name)

    struggles = []
    for name, sids in file_sessions.items():
        if len(sids) < 2:
            continue

        # Skip files that no longer exist in the project
        if existing_files is not None and name not in existing_files:
            continue

        error_count = file_error_sessions.get(name, 0)

        # Score: sessions * error_ratio
        score = len(sids) * (1 + error_count / len(sids))
        if score < 3:
            continue

        struggles.append(Struggle(
            file_path=name,
            sessions_affected=len(sids),
            total_edits=len(sids),
            errors_nearby=error_count,
            description=f"Edited in {len(sids)} sessions, {error_count} had errors",
        ))

    struggles.sort(key=lambda s: -(s.sessions_affected + s.errors_nearby))
    return struggles[:20]


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

    for ext_file in extractions_dir.glob("*.json"):
        try:
            data = json.loads(ext_file.read_text(encoding="utf-8"))
            session_id = data.get("session_id", ext_file.stem)

            for mistake in data.get("mistakes", []):
                error_type = mistake.get("error_type", "")
                desc = mistake.get("description", "")
                if error_type:
                    # Group by error type (e.g., "AttributeError")
                    error_occurrences.setdefault(error_type, []).append(session_id)
        except Exception:
            continue

    recurring = []
    for error_type, sids in error_occurrences.items():
        unique_sessions = list(set(sids))
        if len(unique_sessions) >= 2:
            recurring.append(RecurringError(
                error_type=error_type,
                message_pattern=error_type,
                session_count=len(unique_sessions),
                sessions=unique_sessions[:10],
            ))

    recurring.sort(key=lambda e: -e.session_count)
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
        for file_b in files[i + 1:]:
            co = len(active_files[file_a] & active_files[file_b])
            if co < min_co_occurrence:
                continue

            total = len(active_files[file_a] | active_files[file_b])
            strength = co / total if total > 0 else 0

            if strength >= min_strength:
                correlations.append(EditCorrelation(
                    file_a=file_a,
                    file_b=file_b,
                    co_occurrence=co,
                    total_sessions=total,
                    strength=round(strength, 3),
                ))

    correlations.sort(key=lambda c: -c.strength)
    return correlations[:30]


def _normalize_path(project_path: str) -> str:
    """Normalize project path for manifest lookup."""
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm

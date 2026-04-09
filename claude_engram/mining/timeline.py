"""
Timeline — project development timeline and auto session summaries.

Builds an ordered timeline of what was built, when, by analyzing
session index + extractions. Generates session summaries from JSONL data.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TimelineEvent:
    """A single event in the project timeline."""
    timestamp: str
    event_type: str       # "feature" | "fix" | "refactor" | "decision" | "error"
    description: str
    session_id: str = ""
    related_files: list[str] = field(default_factory=list)


@dataclass
class SessionSummary:
    """Auto-generated summary for a session."""
    session_id: str
    date: str             # YYYY-MM-DD
    duration_str: str     # "2.5h"
    files_edited: list[str] = field(default_factory=list)
    key_activities: list[str] = field(default_factory=list)
    errors_fixed: int = 0
    decisions_made: int = 0


@dataclass
class ProjectOverview:
    """High-level project stats."""
    total_sessions: int = 0
    total_messages: int = 0
    active_days: int = 0
    first_session: str = ""
    last_session: str = ""
    top_files: list[tuple[str, int]] = field(default_factory=list)
    total_errors: int = 0
    total_decisions: int = 0


def build_timeline(
    index,  # SessionIndex
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[TimelineEvent]:
    """
    Build project development timeline from session data + extractions.
    """
    events = []

    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    extractions_dir = None

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        norm_path = _normalize_path(project_path)
        proj_info = manifest.get("projects", {}).get(norm_path)
        if proj_info:
            hash_dir = storage / "projects" / proj_info["hash"]
            extractions_dir = hash_dir / "extractions"

    for sid, meta in index.sessions.items():
        ts = meta.get("first_timestamp", "")
        files = meta.get("files_edited", [])
        short_files = [Path(f).name for f in files[:5]]

        if files:
            events.append(TimelineEvent(
                timestamp=ts,
                event_type="feature",
                description=f"Edited {len(files)} files: {', '.join(short_files)}",
                session_id=sid,
                related_files=short_files,
            ))

        error_count = meta.get("error_count", 0)
        if error_count > 0:
            events.append(TimelineEvent(
                timestamp=ts,
                event_type="error",
                description=f"{error_count} errors encountered",
                session_id=sid,
            ))

        # Add decisions from extractions
        if extractions_dir:
            ext_file = extractions_dir / f"{sid}.json"
            if ext_file.exists():
                try:
                    ext = json.loads(ext_file.read_text(encoding="utf-8"))
                    for d in ext.get("decisions", []):
                        events.append(TimelineEvent(
                            timestamp=d.get("timestamp", ts),
                            event_type="decision",
                            description=d.get("content", "")[:200],
                            session_id=sid,
                            related_files=d.get("related_files", []),
                        ))
                except Exception:
                    pass

    events.sort(key=lambda e: e.timestamp)
    return events


def generate_session_summaries(
    index,  # SessionIndex
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> list[SessionSummary]:
    """Generate concise summaries for all sessions."""
    summaries = []

    storage = Path(engram_storage_dir).expanduser()
    extractions_dir = None

    if (storage / "manifest.json").exists():
        manifest = json.loads((storage / "manifest.json").read_text(encoding="utf-8"))
        norm_path = _normalize_path(project_path)
        proj_info = manifest.get("projects", {}).get(norm_path)
        if proj_info:
            extractions_dir = storage / "projects" / proj_info["hash"] / "extractions"

    for sid, meta in index.sessions.items():
        first_ts = meta.get("first_timestamp", "")
        last_ts = meta.get("last_timestamp", "")

        # Calculate duration
        duration_str = ""
        date_str = first_ts[:10] if first_ts else ""
        if first_ts and last_ts:
            try:
                from datetime import datetime, timezone
                start = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                end = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                hours = (end - start).total_seconds() / 3600
                if hours < 1:
                    duration_str = f"{int(hours * 60)}m"
                else:
                    duration_str = f"{hours:.1f}h"
            except Exception:
                pass

        files = [Path(f).name for f in meta.get("files_edited", [])[:10]]

        # Build activities list
        activities = []
        tools = meta.get("tools_used", {})
        if tools.get("Edit", 0) + tools.get("Write", 0) > 0:
            edit_count = tools.get("Edit", 0) + tools.get("Write", 0)
            activities.append(f"{edit_count} file edits")
        if tools.get("Bash", 0) > 0:
            activities.append(f"{tools['Bash']} commands")
        if meta.get("compaction_count", 0) > 0:
            activities.append(f"{meta['compaction_count']} compactions")

        errors_fixed = 0
        decisions_made = 0

        if extractions_dir:
            ext_file = extractions_dir / f"{sid}.json"
            if ext_file.exists():
                try:
                    ext = json.loads(ext_file.read_text(encoding="utf-8"))
                    errors_fixed = len(ext.get("mistakes", []))
                    decisions_made = len(ext.get("decisions", []))
                    if errors_fixed:
                        activities.append(f"{errors_fixed} errors")
                    if decisions_made:
                        activities.append(f"{decisions_made} decisions")
                except Exception:
                    pass

        summaries.append(SessionSummary(
            session_id=sid,
            date=date_str,
            duration_str=duration_str,
            files_edited=files,
            key_activities=activities,
            errors_fixed=errors_fixed,
            decisions_made=decisions_made,
        ))

    summaries.sort(key=lambda s: s.date, reverse=True)
    return summaries


def get_project_overview(
    index,  # SessionIndex
    project_path: str = "",
) -> ProjectOverview:
    """High-level project statistics."""
    sessions = index.sessions
    if not sessions:
        return ProjectOverview()

    dates = set()
    total_errors = 0
    file_counts: dict[str, int] = {}

    for meta in sessions.values():
        ts = meta.get("first_timestamp", "")
        if ts:
            dates.add(ts[:10])

        total_errors += meta.get("error_count", 0)

        for f in meta.get("files_edited", []):
            name = Path(f).name
            file_counts[name] = file_counts.get(name, 0) + 1

    timestamps = [m.get("first_timestamp", "") for m in sessions.values() if m.get("first_timestamp")]

    top_files = sorted(file_counts.items(), key=lambda x: -x[1])[:10]

    return ProjectOverview(
        total_sessions=len(sessions),
        total_messages=index.get_total_messages(),
        active_days=len(dates),
        first_session=min(timestamps) if timestamps else "",
        last_session=max(timestamps) if timestamps else "",
        top_files=top_files,
        total_errors=total_errors,
    )


def _normalize_path(project_path: str) -> str:
    """Normalize project path for manifest lookup."""
    norm = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm) >= 2 and norm[1] == ":":
        norm = norm[0].lower() + norm[1:]
    return norm

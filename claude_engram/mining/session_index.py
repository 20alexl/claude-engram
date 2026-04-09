"""
Session Index — incremental index of Claude Code session logs.

Tracks per-session metadata (files edited, tools used, timestamps, summary)
with byte-offset cursors for incremental processing. Never re-processes
already-indexed data.

Storage: ~/.claude_engram/projects/<hash>/session_index.json
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from claude_engram.mining.jsonl_reader import (
    get_session_files,
    iter_messages,
    read_tail,
    extract_user_text,
    extract_assistant_text,
    extract_tool_uses,
    extract_file_edits,
    extract_bash_commands,
    get_session_id,
    get_timestamp,
    get_git_branch,
    is_compaction_event,
)


@dataclass
class SessionMeta:
    """Metadata for a single session."""
    session_id: str = ""
    jsonl_file: str = ""
    file_size_bytes: int = 0
    processed_offset: int = 0
    message_count: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    first_timestamp: str = ""
    last_timestamp: str = ""
    git_branch: str = ""
    files_edited: list[str] = field(default_factory=list)
    tools_used: dict[str, int] = field(default_factory=dict)
    has_errors: bool = False
    error_count: int = 0
    compaction_count: int = 0
    token_usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})
    summary: str = ""
    last_user_message: str = ""


def build_index_for_session(
    jsonl_path: Path,
    start_offset: int = 0,
) -> SessionMeta:
    """
    Scan a session JSONL and extract metadata.

    Args:
        jsonl_path: Path to the JSONL file
        start_offset: Byte offset to resume from (0 for full scan)

    Returns:
        SessionMeta with all extracted metadata
    """
    meta = SessionMeta(
        jsonl_file=jsonl_path.name,
        file_size_bytes=jsonl_path.stat().st_size,
    )

    files_edited = set()
    tools_used: dict[str, int] = {}
    last_offset = start_offset

    for offset, msg in iter_messages(jsonl_path, start_offset=start_offset):
        last_offset = offset
        msg_type = msg.get("type", "")
        meta.message_count += 1

        # Capture session ID and timestamps
        ts = get_timestamp(msg)
        if ts:
            if not meta.first_timestamp:
                meta.first_timestamp = ts
            meta.last_timestamp = ts

        if not meta.session_id:
            sid = get_session_id(msg)
            if sid:
                meta.session_id = sid

        if not meta.git_branch:
            branch = get_git_branch(msg)
            if branch:
                meta.git_branch = branch

        # User messages
        if msg_type == "user":
            meta.user_message_count += 1
            text = extract_user_text(msg)
            if text:
                meta.last_user_message = text[:500]

            # Check for tool results with errors
            tool_result = msg.get("toolUseResult", {})
            if isinstance(tool_result, dict) and tool_result.get("stderr"):
                meta.has_errors = True
                meta.error_count += 1

            # Check list content for error tool results
            content = msg.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        if block.get("is_error"):
                            meta.has_errors = True
                            meta.error_count += 1

        # Assistant messages
        elif msg_type == "assistant":
            meta.assistant_message_count += 1

            # Track tool usage
            for tool in extract_tool_uses(msg):
                name = tool["name"]
                tools_used[name] = tools_used.get(name, 0) + 1

            # Track file edits
            for fp in extract_file_edits(msg):
                files_edited.add(fp)

            # Track token usage
            usage = msg.get("message", {}).get("usage", {})
            if usage:
                meta.token_usage["input"] += usage.get("input_tokens", 0)
                meta.token_usage["output"] += usage.get("output_tokens", 0)

        # System messages
        elif msg_type == "system":
            if is_compaction_event(msg):
                meta.compaction_count += 1

    meta.files_edited = sorted(files_edited)
    meta.tools_used = tools_used
    # Store file size as processed offset to indicate "fully processed"
    meta.processed_offset = jsonl_path.stat().st_size

    return meta


class SessionIndex:
    """
    Manages the per-project session index.

    Tracks which sessions have been processed and their metadata.
    Supports incremental updates — only processes new data.
    """

    VERSION = 1

    def __init__(self, index_path: Path):
        self._path = index_path
        self._data: dict = {"version": self.VERSION, "sessions": {}}
        self._dirty = False
        self._load()

    def _load(self):
        """Load index from disk."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        """Save index to disk (atomic write)."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
        self._dirty = False

    @property
    def sessions(self) -> dict[str, dict]:
        """All session metadata, keyed by session ID."""
        return self._data.get("sessions", {})

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get metadata for a specific session."""
        return self.sessions.get(session_id)

    def needs_processing(self, jsonl_path: Path) -> tuple[bool, int]:
        """
        Check if a JSONL file needs (re-)processing.

        Returns:
            (needs_work, start_offset) — whether processing is needed and
            the byte offset to start from.
        """
        current_size = jsonl_path.stat().st_size

        # Find session entry by filename
        for sid, meta in self.sessions.items():
            if meta.get("jsonl_file") == jsonl_path.name:
                stored_size = meta.get("file_size_bytes", 0)
                stored_offset = meta.get("processed_offset", 0)

                if current_size <= stored_offset:
                    return False, 0  # Fully processed
                if current_size > stored_offset:
                    return True, stored_offset  # New data appended

        return True, 0  # Never processed

    def update_session(self, meta: SessionMeta):
        """Add or update a session in the index."""
        if not meta.session_id:
            # Use filename as fallback key
            meta.session_id = Path(meta.jsonl_file).stem

        self._data.setdefault("sessions", {})[meta.session_id] = asdict(meta)
        self._dirty = True

    def get_latest_session(self) -> Optional[dict]:
        """Get the most recent session by timestamp."""
        sessions = self.sessions
        if not sessions:
            return None

        latest = None
        latest_ts = ""
        for sid, meta in sessions.items():
            ts = meta.get("last_timestamp", "")
            if ts > latest_ts:
                latest_ts = ts
                latest = meta

        return latest

    def get_latest_session_summary(self) -> Optional[dict]:
        """
        Get a formatted summary of the most recent session.

        Returns dict with: session_id, age_str, branch, files_edited,
        error_count, last_message, tools_summary
        """
        latest = self.get_latest_session()
        if not latest:
            return None

        # Calculate age
        last_ts = latest.get("last_timestamp", "")
        age_str = ""
        if last_ts:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                age_secs = (datetime.now(timezone.utc) - dt).total_seconds()
                if age_secs < 3600:
                    age_str = f"{int(age_secs / 60)}m ago"
                elif age_secs < 86400:
                    age_str = f"{age_secs / 3600:.1f}h ago"
                else:
                    age_str = f"{age_secs / 86400:.0f}d ago"
            except Exception:
                pass

        files = latest.get("files_edited", [])
        # Just show filenames, not full paths
        short_files = [Path(f).name for f in files[:10]]

        return {
            "session_id": latest.get("session_id", "?"),
            "age_str": age_str,
            "branch": latest.get("git_branch", "?"),
            "files_edited": short_files,
            "file_count": len(files),
            "error_count": latest.get("error_count", 0),
            "compaction_count": latest.get("compaction_count", 0),
            "last_message": latest.get("last_user_message", "")[:200],
            "message_count": latest.get("message_count", 0),
            "user_message_count": latest.get("user_message_count", 0),
            "tools_summary": _summarize_tools(latest.get("tools_used", {})),
            "summary": latest.get("summary", ""),
        }

    def get_all_files_edited(self) -> dict[str, int]:
        """Get aggregate file edit counts across all sessions."""
        counts: dict[str, int] = {}
        for meta in self.sessions.values():
            for f in meta.get("files_edited", []):
                counts[f] = counts.get(f, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def get_session_count(self) -> int:
        """Total number of indexed sessions."""
        return len(self.sessions)

    def get_total_messages(self) -> int:
        """Total messages across all sessions."""
        return sum(m.get("message_count", 0) for m in self.sessions.values())


def _summarize_tools(tools: dict[str, int]) -> str:
    """Summarize tool usage into a short string."""
    if not tools:
        return ""
    top = sorted(tools.items(), key=lambda x: -x[1])[:5]
    parts = [f"{name}:{count}" for name, count in top]
    return ", ".join(parts)


def get_or_create_index(project_hash_dir: Path) -> SessionIndex:
    """Get or create a session index for a project."""
    index_path = project_hash_dir / "session_index.json"
    return SessionIndex(index_path)


def build_project_index(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> Optional[SessionIndex]:
    """
    Build/update the session index for a project.

    Scans all JSONL files, processes only new/changed ones.
    Returns the updated index, or None if no sessions found.
    """
    from claude_engram.mining.jsonl_reader import resolve_jsonl_dir

    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return None

    # Get engram project dir from manifest
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Normalize project path to match manifest keys
    norm_path = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm_path) >= 2 and norm_path[1] == ":":
        norm_path = norm_path[0].lower() + norm_path[1:]

    projects = manifest.get("projects", {})
    if norm_path not in projects:
        return None

    hash_id = projects[norm_path]["hash"]
    project_dir = storage / "projects" / hash_id
    project_dir.mkdir(parents=True, exist_ok=True)

    index = get_or_create_index(project_dir)

    # Process each session file
    session_files = list(jsonl_dir.glob("*.jsonl"))
    for jsonl_path in session_files:
        needs_work, start_offset = index.needs_processing(jsonl_path)
        if not needs_work:
            continue

        meta = build_index_for_session(jsonl_path, start_offset=start_offset)
        index.update_session(meta)

    index.save()
    return index


def resolve_project_index(
    project_path: str,
    engram_storage_dir: str = "~/.claude_engram",
) -> Optional[SessionIndex]:
    """
    Find the best session index for a project, with workspace inheritance.

    Tries the project itself first. If no index found (sub-project with no
    own sessions), walks up to parent directories looking for a workspace
    that has an index. This handles the common case where Claude Code runs
    from workspace root but edits are in sub-projects.

    Returns the index, or None if nothing found.
    """
    storage = Path(engram_storage_dir).expanduser()
    manifest_path = storage / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    projects = manifest.get("projects", {})

    # Normalize
    norm_path = str(Path(project_path).resolve()).replace("\\", "/")
    if len(norm_path) >= 2 and norm_path[1] == ":":
        norm_path = norm_path[0].lower() + norm_path[1:]

    # Try this project first
    idx = _try_load_index(norm_path, projects, storage)
    if idx and idx.get_session_count() > 0:
        return idx

    # Walk up to parent directories (workspace inheritance)
    current = norm_path
    while True:
        parent = str(Path(current).parent).replace("\\", "/")
        if parent == current:
            break
        current = parent

        idx = _try_load_index(current, projects, storage)
        if idx and idx.get_session_count() > 0:
            return idx

    # Last resort: try build_project_index (scans JSONL files)
    return build_project_index(project_path, engram_storage_dir)


def _try_load_index(
    norm_path: str,
    projects: dict,
    storage: Path,
) -> Optional[SessionIndex]:
    """Try to load an existing session index for a normalized path."""
    if norm_path not in projects:
        return None
    hash_id = projects[norm_path]["hash"]
    idx_path = storage / "projects" / hash_id / "session_index.json"
    if idx_path.exists():
        return SessionIndex(idx_path)
    return None

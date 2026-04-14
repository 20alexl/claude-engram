"""
JSONL Reader — streaming parser for Claude Code session logs.

Claude Code stores conversation logs at:
  ~/.claude/projects/<dir-hash>/*.jsonl

Directory naming convention:
  E:\\workspace\\project  →  E--workspace-project
  (drive letter + '--' + path segments joined by '-')

Each line in a JSONL file is a JSON object with a 'type' field:
  user, assistant, system, file-history-snapshot, attachment,
  queue-operation, permission-mode, last-prompt
"""

import json
import os
import re
from pathlib import Path
from typing import Iterator, Optional


def _get_claude_projects_dir() -> Path:
    """Get the Claude Code projects directory."""
    return Path.home() / ".claude" / "projects"


def path_to_dir_name(project_path: str) -> str:
    """
    Convert a filesystem path to Claude Code's directory naming convention.

    Examples:
        E:\\workspace           → E--workspace
        E:\\workspace\\project  → E--workspace-project
        /home/user/project     → -home-user-project
    """
    # Normalize
    p = project_path.replace("/", "\\")

    # Windows drive path: E:\\workspace → E--workspace
    match = re.match(r"^([a-zA-Z]):\\(.*)$", p)
    if match:
        drive = match.group(1)
        rest = match.group(2).rstrip("\\")
        segments = rest.replace("\\", "-")
        return f"{drive}--{segments}"

    # Unix path: /home/user/project → -home-user-project
    p = p.strip("\\").replace("\\", "-")
    return f"-{p}" if project_path.startswith("/") else p


def dir_name_to_path(dir_name: str) -> str:
    """
    Convert Claude Code's directory name back to a filesystem path.

    Examples:
        E--workspace         → E:\\workspace
        e--workspace-project → e:\\workspace\\project  (ambiguous — best effort)
    """
    # Windows drive: X--rest
    match = re.match(r"^([a-zA-Z])--(.+)$", dir_name)
    if match:
        drive = match.group(1)
        rest = match.group(2)
        # Ambiguity: dashes could be literal or path separators.
        # We can't fully resolve this without checking the filesystem.
        # Return with backslash separators as best guess.
        segments = rest.replace("-", "\\")
        return f"{drive}:\\{segments}"

    # Unix-style
    if dir_name.startswith("-"):
        return "/" + dir_name[1:].replace("-", "/")

    return dir_name


def resolve_jsonl_dir(project_path: str) -> Optional[Path]:
    """
    Find the ~/.claude/projects/<hash>/ directory for a given project path.

    Tries exact match first, then case-insensitive, then substring match.
    Returns None if no matching directory found.
    """
    projects_dir = _get_claude_projects_dir()
    if not projects_dir.exists():
        return None

    # Generate expected dir name
    expected = path_to_dir_name(project_path)

    # Exact match
    candidate = projects_dir / expected
    if candidate.is_dir():
        return candidate

    # Case-insensitive match (Windows drive letters vary in case)
    expected_lower = expected.lower()
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.lower() == expected_lower:
            return d

    # Fallback: check if any directory's cwd matches (read first session file)
    norm_path = project_path.lower().replace("\\", "/").rstrip("/")
    for d in projects_dir.iterdir():
        if not d.is_dir():
            continue
        # Quick check: does the dir name contain key parts of our path?
        if norm_path.split("/")[-1] not in d.name.lower():
            continue
        # Read first JSONL to check cwd
        jsonls = sorted(d.glob("*.jsonl"))
        if not jsonls:
            continue
        try:
            with open(jsonls[0], encoding="utf-8") as f:
                for line in f:
                    msg = json.loads(line)
                    if msg.get("type") == "user" and msg.get("cwd"):
                        cwd = msg["cwd"].lower().replace("\\", "/").rstrip("/")
                        if cwd == norm_path:
                            return d
                        break
        except Exception:
            continue

    return None


def get_session_files(project_path: str) -> list[Path]:
    """
    Get all JSONL session files for a project, sorted by modification time (newest first).
    """
    jsonl_dir = resolve_jsonl_dir(project_path)
    if not jsonl_dir:
        return []

    files = list(jsonl_dir.glob("*.jsonl"))
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def iter_messages(
    jsonl_path: Path,
    start_offset: int = 0,
    types: Optional[set[str]] = None,
) -> Iterator[tuple[int, dict]]:
    """
    Stream messages from a JSONL file.

    Args:
        jsonl_path: Path to the JSONL file
        start_offset: Byte offset to start reading from (for incremental processing)
        types: If set, only yield messages with these types (e.g., {"user", "assistant"})

    Yields:
        (byte_offset, parsed_message) tuples
    """
    with open(jsonl_path, "rb") as f:
        if start_offset > 0:
            f.seek(start_offset)

        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break

            try:
                msg = json.loads(line.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if types and msg.get("type") not in types:
                continue

            yield offset, msg


def read_tail(jsonl_path: Path, n_messages: int = 50) -> list[dict]:
    """
    Read the last N messages from a JSONL file efficiently.

    Seeks from the end of the file to avoid reading the entire file.
    """
    file_size = jsonl_path.stat().st_size
    if file_size == 0:
        return []

    # Start with a reasonable buffer, grow if needed
    buffer_size = min(file_size, max(4096, n_messages * 2000))
    messages = []

    with open(jsonl_path, "rb") as f:
        while len(messages) < n_messages and buffer_size <= file_size:
            seek_pos = max(0, file_size - buffer_size)
            f.seek(seek_pos)

            if seek_pos > 0:
                # Skip partial first line
                f.readline()

            messages = []
            for line in f:
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                    messages.append(msg)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

            if len(messages) >= n_messages or seek_pos == 0:
                break
            buffer_size *= 2

    return messages[-n_messages:]


def extract_user_text(msg: dict) -> Optional[str]:
    """Extract plain text from a user message (skip tool results)."""
    if msg.get("type") != "user":
        return None
    content = msg.get("message", {}).get("content", "")
    if isinstance(content, str) and len(content) > 0:
        return content
    return None


def extract_assistant_text(msg: dict) -> list[str]:
    """Extract text blocks from an assistant message."""
    if msg.get("type") != "assistant":
        return []
    content = msg.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return []
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                texts.append(text)
    return texts


def extract_thinking(msg: dict) -> list[str]:
    """Extract thinking blocks from an assistant message."""
    if msg.get("type") != "assistant":
        return []
    content = msg.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return []
    thoughts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking", "")
            if text:
                thoughts.append(text)
    return thoughts


def extract_tool_uses(msg: dict) -> list[dict]:
    """Extract tool_use blocks from an assistant message."""
    if msg.get("type") != "assistant":
        return []
    content = msg.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return []
    tools = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tools.append(
                {
                    "name": block.get("name", ""),
                    "id": block.get("id", ""),
                    "input": block.get("input", {}),
                }
            )
    return tools


def extract_tool_results(msg: dict) -> list[dict]:
    """
    Extract tool results from a user message.

    Tool results come back as user messages with list content containing
    tool_result blocks.
    """
    if msg.get("type") != "user":
        return []

    # Check toolUseResult field (bash results)
    tool_result = msg.get("toolUseResult")
    if tool_result:
        return [tool_result]

    # Check list content (other tool results)
    content = msg.get("message", {}).get("content", "")
    if not isinstance(content, list):
        return []

    results = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            results.append(block)
    return results


def extract_file_edits(msg: dict) -> list[str]:
    """Extract file paths from Edit/Write tool_use blocks."""
    tools = extract_tool_uses(msg)
    paths = []
    for tool in tools:
        if tool["name"] in ("Edit", "Write"):
            fp = tool["input"].get("file_path", "")
            if fp:
                paths.append(fp)
    return paths


def extract_bash_commands(msg: dict) -> list[str]:
    """Extract bash commands from Bash tool_use blocks."""
    tools = extract_tool_uses(msg)
    commands = []
    for tool in tools:
        if tool["name"] == "Bash":
            cmd = tool["input"].get("command", "")
            if cmd:
                commands.append(cmd)
    return commands


def get_session_id(msg: dict) -> str:
    """Get the session ID from any message."""
    return msg.get("sessionId", "")


def get_timestamp(msg: dict) -> str:
    """Get the ISO timestamp from any message."""
    return msg.get("timestamp", "")


def get_git_branch(msg: dict) -> str:
    """Get the git branch from any message."""
    return msg.get("gitBranch", "")


def is_compaction_event(msg: dict) -> bool:
    """Check if a system message is a compaction boundary."""
    return msg.get("type") == "system" and msg.get("subtype") == "compact_boundary"

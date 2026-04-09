#!/usr/bin/env python3
"""
Claude Engram Enforcement Hook - AUTOMATIC TOOL INJECTION

NEW APPROACH (Round 3):
Instead of REMINDING Claude to use tools, we AUTOMATICALLY use them.

Auto-injection:
1. Before edit → Auto-run pre_edit_check, show results
2. After edit → Auto-record loop(operation='record_edit')
3. On error → Auto-log work(operation='log_mistake')
4. Results show IMMEDIATE value (not just future benefit)

The goal: Remove friction, add immediate value, make tools invisible but always-on.
"""

import sys
import os
import json
import time
import re
import threading
from pathlib import Path


def _read_stdin_with_timeout(timeout_secs: float = 0.5) -> str:
    """
    Cross-platform stdin reader with timeout.
    Works on both Windows and Unix.
    """
    result = {"data": ""}

    def read_stdin():
        try:
            result["data"] = sys.stdin.read()
        except Exception:
            pass

    thread = threading.Thread(target=read_stdin)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout_secs)

    return result["data"]



# NOTE: habit tracker imports REMOVED - habit tools removed as noisy


# ============================================================================
# State Tracking - Track EVERYTHING Claude does and doesn't do
# ============================================================================

def get_state_file() -> Path:
    """Get the hook state file path."""
    return Path.home() / ".claude_engram" / "hook_state.json"


def load_state() -> dict:
    """Load hook state."""
    state_file = get_state_file()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {
        "prompts_without_session": 0,
        "prompts_this_session": 0,  # Track prompts within active session
        "edits_without_session": 0,
        "edits_without_pre_check": 0,
        "edits_without_loop_record": 0,
        "tests_without_record": 0,
        "errors_without_log": 0,
        "checkpoint_reminded": False,  # Track if we've shown checkpoint reminder
        "last_session_start": None,
        "last_pre_edit_check": None,
        "last_loop_record": None,
        "last_scope_declare": None,
        "last_test_record": None,
        "last_mistake_log": None,
        "files_edited_this_session": [],
        "last_session_files": [],  # Files from previous session (for curated context)
        "ignored_warnings": 0,
        "active_project": "",
        # Search spiral tracking - detect when Claude is flailing on searches
        "consecutive_search_failures": 0,
        "last_search_query": "",
        "search_spiral_warned": False,
        # Test state tracking - only remind on meaningful test runs
        "last_test_passed": None,  # None = unknown, True = passed, False = failed
        "test_runs_this_session": 0,
        # Tool usage tracking - helps identify underused tools
        "tool_usage": {
            "session_start": 0,
            "memory_remember": 0,
            "memory_recall": 0,
            "work_log_mistake": 0,
            "work_log_decision": 0,
            "work_pre_edit_check": 0,
            "loop_record_edit": 0,
            "loop_record_test": 0,
            "scope_declare": 0,
            "impact_analyze": 0,
            "context_checkpoint_save": 0,
            "code_quality_check": 0,
        },
    }


def save_state(state: dict):
    """Save hook state."""
    state_file = get_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        state_file.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _increment_tool_usage(state: dict, tool_name: str):
    """Increment usage count for a tool."""
    if "tool_usage" not in state:
        state["tool_usage"] = {}
    state["tool_usage"][tool_name] = state["tool_usage"].get(tool_name, 0) + 1


def mark_session_started(project_dir: str):
    """Mark that session_start was called - resets some counters."""
    state = load_state()
    state["prompts_without_session"] = 0
    state["prompts_this_session"] = 0  # Reset session prompt counter
    state["edits_without_session"] = 0
    state["checkpoint_reminded"] = False  # Reset checkpoint reminder flag
    state["last_session_start"] = time.time()
    state["active_project"] = project_dir
    state["files_edited_this_session"] = []
    _increment_tool_usage(state, "session_start")
    save_state(state)

    # Also create the marker file (in ~/.claude_engram/ for Windows compatibility)
    marker = Path.home() / ".claude_engram" / "session_active"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(project_dir)
    except Exception:
        pass


def mark_session_ended():
    """Mark that session_end was called - preserve files for next session's context."""
    state = load_state()

    # Save current session's files as last_session_files for curated context
    files_edited = state.get("files_edited_this_session", [])
    if files_edited:
        state["last_session_files"] = files_edited.copy()

    # Reset session-specific state
    state["files_edited_this_session"] = []
    state["test_runs_this_session"] = 0
    state["last_test_passed"] = None
    state["active_project"] = ""

    save_state(state)


def get_last_session_files() -> list[str]:
    """Get files edited in the last session for curated context."""
    state = load_state()
    return state.get("last_session_files", [])


def mark_pre_edit_check_done(file_path: str):
    """Mark that pre_edit_check was called."""
    state = load_state()
    state["last_pre_edit_check"] = time.time()
    state["last_pre_edit_file"] = file_path
    state["edits_without_pre_check"] = 0
    _increment_tool_usage(state, "work_pre_edit_check")
    save_state(state)


def mark_loop_record_done(file_path: str):
    """Mark that loop_record_edit was called."""
    state = load_state()
    state["last_loop_record"] = time.time()
    state["last_loop_file"] = file_path
    state["edits_without_loop_record"] = 0
    _increment_tool_usage(state, "loop_record_edit")
    save_state(state)


def mark_scope_declared():
    """Mark that scope_declare was called."""
    state = load_state()
    state["last_scope_declare"] = time.time()
    _increment_tool_usage(state, "scope_declare")
    save_state(state)


def mark_test_recorded():
    """Mark that loop_record_test was called."""
    state = load_state()
    state["last_test_record"] = time.time()
    state["tests_without_record"] = 0
    _increment_tool_usage(state, "loop_record_test")
    save_state(state)


def mark_mistake_logged():
    """Mark that work_log_mistake was called."""
    state = load_state()
    state["last_mistake_log"] = time.time()
    state["errors_without_log"] = 0
    _increment_tool_usage(state, "work_log_mistake")
    save_state(state)


def record_file_edit(file_path: str):
    """Record that a file was edited. Also saves to last_session_files continuously."""
    state = load_state()
    files = state.get("files_edited_this_session", [])
    if file_path not in files:
        files.append(file_path)
    state["files_edited_this_session"] = files[-50:]  # Keep last 50
    # Save continuously so session_end isn't required for curated context
    state["last_session_files"] = files[-50:]
    save_state(state)


# ============================================================================
# Search Spiral Detection - Detect when Claude is flailing on searches
# ============================================================================

def record_search_failure(query_hint: str = ""):
    """Record a failed search attempt (empty results or not found)."""
    state = load_state()
    state["consecutive_search_failures"] = state.get("consecutive_search_failures", 0) + 1
    if query_hint:
        state["last_search_query"] = query_hint
    save_state(state)


def record_search_success():
    """Record a successful search - resets the failure counter."""
    state = load_state()
    state["consecutive_search_failures"] = 0
    state["search_spiral_warned"] = False
    save_state(state)


def check_search_spiral() -> tuple[bool, int]:
    """
    Check if Claude is in a search spiral (3+ consecutive failed searches).

    Returns:
        (in_spiral, failure_count)
    """
    state = load_state()
    failures = state.get("consecutive_search_failures", 0)
    return (failures >= 3, failures)


def get_search_spiral_suggestion(project_dir: str) -> str:
    """
    Generate a suggestion for escaping search spiral.
    Only shows once per spiral (until a search succeeds).
    """
    state = load_state()

    # Don't repeat the warning
    if state.get("search_spiral_warned", False):
        return ""

    in_spiral, count = check_search_spiral()
    if not in_spiral:
        return ""

    # Mark as warned
    state["search_spiral_warned"] = True
    save_state(state)

    last_query = state.get("last_search_query", "what you're looking for")

    lines = [
        "---",
        f"SEARCH SPIRAL DETECTED - {count} failed search attempts",
        "",
        "You're struggling to find something. Try:",
        f'  scout_search(query="{last_query}", directory="{project_dir}")',
        "",
        "scout_search uses semantic matching - describe WHAT you want,",
        "not the exact filename. It reads actual code and finds relevant files.",
        "",
        "Or just ask the user where it is.",
        "---",
    ]
    return "\n".join(lines)


def detect_search_failure_in_output(command: str, output: str) -> bool:
    """
    Detect if a bash command was a failed search attempt.

    Returns True if this looks like a failed search (ls/dir/find that found nothing).
    """
    if not command or not output:
        return False

    command_lower = command.lower()
    output_lower = output.lower()

    # Check if this was a search-like command (must be the first word)
    import re as _re
    first_word = _re.split(r'\s+', command_lower.strip())[0] if command_lower.strip() else ""
    search_commands = ["ls", "dir", "find", "locate", "where", "which"]
    is_search = first_word in search_commands

    if not is_search:
        return False

    # Check for failure patterns
    failure_patterns = [
        "no such file",
        "cannot access",
        "not found",
        "does not exist",
        "cannot find",
        "no matches",
        "0 files",
        "nothing to show",
    ]

    return any(pattern in output_lower for pattern in failure_patterns)


def get_underused_tools() -> list[str]:
    """Get suggestions for underused tools based on usage patterns."""
    state = load_state()
    usage = state.get("tool_usage", {})
    suggestions = []

    # Key tools that should be used often (v2 combined tools)
    key_tools = {
        "work(operation='log_mistake')": "Log mistakes to avoid repeating them",
        "work(operation='log_decision')": "Log decisions so future sessions know why",
        "pre_edit_check": "Check for past mistakes before editing",
        "loop(operation='record_edit')": "Track edits to detect loops",
        "scope(operation='declare')": "Declare scope to prevent over-refactoring",
    }

    session_count = usage.get("session_start", 0)
    if session_count == 0:
        return []  # No sessions yet, skip analysis

    # Find tools that are used much less than session_start
    for tool, desc in key_tools.items():
        tool_count = usage.get(tool, 0)
        # If tool is used less than 20% as often as sessions, suggest it
        if tool_count < session_count * 0.2:
            suggestions.append(f"{tool}: {desc}")

    return suggestions[:3]  # Max 3 suggestions


# ============================================================================
# Project Context Loading
# ============================================================================

def _normalize_path(path: str) -> str:
    """Normalize a path for consistent storage (lowercase drive, forward slashes)."""
    # Resolve to absolute, then use forward slashes for consistency
    normalized = str(Path(path).resolve()).replace("\\", "/")
    # Lowercase drive letter on Windows (D:/Code -> d:/Code)
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0].lower() + normalized[1:]
    return normalized


# Project markers — files that indicate a project root
_PROJECT_MARKERS = {
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "go.sum",
    "pom.xml", "build.gradle", "CMakeLists.txt", "Makefile",
    "setup.py", "setup.cfg", ".git", "CLAUDE.md",
}

# Cache: file_path -> resolved project dir (avoids repeated filesystem walks)
_project_dir_cache: dict[str, str] = {}


def resolve_project_for_file(file_path: str, workspace_root: str = "") -> str:
    """
    Resolve which sub-project a file belongs to within a workspace.

    Walks up from the file toward workspace_root, looking for project markers
    (pyproject.toml, package.json, Cargo.toml, .git, etc.).

    Returns the project directory, or workspace_root if no marker found.
    """
    if not file_path:
        return workspace_root or _normalize_path(os.getcwd())

    # Check cache
    if file_path in _project_dir_cache:
        return _project_dir_cache[file_path]

    workspace = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    target = Path(file_path).resolve()

    # If the file IS the workspace (not inside a sub-project), just use workspace
    if target == workspace or not str(target).startswith(str(workspace)):
        return _normalize_path(str(workspace))

    # Walk up from file's directory toward workspace root
    current = target.parent if target.is_file() else target
    best_project = workspace  # Default fallback

    while current >= workspace:
        for marker in _PROJECT_MARKERS:
            if (current / marker).exists():
                best_project = current
                # Don't break — keep walking up. We want the CLOSEST marker
                # to the file, but if we're at workspace level that's just cwd.
                # So we actually want to stop at the first marker we find.
                result = _normalize_path(str(current))
                _project_dir_cache[file_path] = result
                return result
        if current == workspace:
            break
        current = current.parent

    result = _normalize_path(str(best_project))
    _project_dir_cache[file_path] = result
    return result


def get_project_dir(file_path: str = "") -> str:
    """
    Get the project directory, optionally scoped to a file's sub-project.

    Priority:
    1. CLAUDE_PROJECT_DIR env var (if set explicitly)
    2. Sub-project resolution from file_path (walks up looking for markers)
    3. Current working directory (fallback)
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if explicit:
        return _normalize_path(explicit)

    workspace_root = _normalize_path(os.getcwd())

    if file_path:
        return resolve_project_for_file(file_path, workspace_root)

    return workspace_root


def get_memory_file() -> Path:
    """Get the Claude Engram memory file path (legacy compat)."""
    return Path.home() / ".claude_engram" / "memory.json"


def get_engram_storage_dir() -> Path:
    """Get the Claude Engram storage directory."""
    return Path.home() / ".claude_engram"


def _get_manifest() -> dict:
    """Load manifest.json if it exists."""
    manifest_file = get_engram_storage_dir() / "manifest.json"
    if manifest_file.exists():
        try:
            return json.loads(manifest_file.read_text())
        except Exception:
            pass
    return {}


def get_project_memory_dir(project_dir: str) -> Path:
    """Get the per-project memory directory for a project."""
    storage = get_engram_storage_dir()
    manifest = _get_manifest()
    normalized = _normalize_path(project_dir)
    projects = manifest.get("projects", {})
    if normalized in projects:
        hash_id = projects[normalized]["hash"]
        return storage / "projects" / hash_id
    # Not in manifest yet — compute hash
    import hashlib
    hash_id = hashlib.md5(normalized.encode()).hexdigest()[:8]
    return storage / "projects" / hash_id


def _load_project_entries_from_dir(project_hash_dir: Path) -> list[dict]:
    """Load entries from a per-project memory.json file."""
    mem_file = project_hash_dir / "memory.json"
    if mem_file.exists():
        try:
            data = json.loads(mem_file.read_text())
            return data.get("entries", [])
        except Exception:
            pass
    return []


def _load_project_data_from_dir(project_hash_dir: Path) -> dict:
    """Load full project data from a per-project memory.json file."""
    mem_file = project_hash_dir / "memory.json"
    if mem_file.exists():
        try:
            return json.loads(mem_file.read_text())
        except Exception:
            pass
    return {}


def load_project_memory(project_dir: str) -> dict:
    """
    Load memories for a project, including inherited workspace-level memories.

    v5: Uses per-project files via manifest. Falls back to legacy memory.json.
    """
    storage = get_engram_storage_dir()
    manifest = _get_manifest()
    normalized = _normalize_path(project_dir)

    # v5 path: manifest exists with per-project files
    if manifest.get("projects"):
        manifest_projects = manifest["projects"]

        # Load primary project
        primary = None
        if normalized in manifest_projects:
            hash_id = manifest_projects[normalized]["hash"]
            pdir = storage / "projects" / hash_id
            primary = _load_project_data_from_dir(pdir)

        # Collect entries from ancestor paths
        ancestor_entries = []
        check_path = str(Path(normalized).parent)
        while check_path:
            norm_check = check_path.replace("\\", "/")
            if len(norm_check) >= 2 and norm_check[1] == ":":
                norm_check = norm_check[0].lower() + norm_check[1:]
            if norm_check in manifest_projects:
                hash_id = manifest_projects[norm_check]["hash"]
                pdir = storage / "projects" / hash_id
                ancestor_entries.extend(_load_project_entries_from_dir(pdir))
            parent = str(Path(check_path).parent)
            if parent == check_path:
                break
            check_path = parent

        if primary:
            result = dict(primary)
            if ancestor_entries:
                existing_ids = {e.get("id") for e in result.get("entries", [])}
                for entry in ancestor_entries:
                    if entry.get("id") not in existing_ids:
                        result.setdefault("entries", []).append(entry)
            return result

        # Name-based fallback
        project_name = Path(project_dir).name
        for path, info in manifest_projects.items():
            if Path(path).name == project_name:
                hash_id = info["hash"]
                pdir = storage / "projects" / hash_id
                return _load_project_data_from_dir(pdir)

        if ancestor_entries:
            return {"entries": ancestor_entries, "project_name": Path(project_dir).name}

        return {}

    # Legacy fallback: single memory.json
    memory_file = get_memory_file()
    if not memory_file.exists():
        return {}

    try:
        data = json.loads(memory_file.read_text())
        projects = data.get("projects", {})

        primary = projects.get(normalized)
        if not primary:
            for path, proj in projects.items():
                if _normalize_path(path) == normalized:
                    primary = proj
                    break

        ancestor_entries = []
        check_path = str(Path(normalized).parent)
        while check_path:
            norm_check = check_path.replace("\\", "/")
            if len(norm_check) >= 2 and norm_check[1] == ":":
                norm_check = norm_check[0].lower() + norm_check[1:]
            if norm_check in projects:
                ancestor_entries.extend(projects[norm_check].get("entries", []))
            parent = str(Path(check_path).parent)
            if parent == check_path:
                break
            check_path = parent

        if primary:
            result = dict(primary)
            if ancestor_entries:
                existing_ids = {e.get("id") for e in result.get("entries", [])}
                for entry in ancestor_entries:
                    if entry.get("id") not in existing_ids:
                        result.setdefault("entries", []).append(entry)
            return result

        project_name = Path(project_dir).name
        for path, proj in projects.items():
            if Path(path).name == project_name:
                return proj

        if ancestor_entries:
            return {"entries": ancestor_entries, "project_name": Path(project_dir).name}

        return {}
    except Exception:
        return {}


def get_past_mistakes(project_memory: dict) -> list[dict]:
    """Extract past mistakes from project memory, newest first.
    Returns list of dicts with 'id' and 'content' keys."""
    mistakes = []
    entries = project_memory.get("entries", [])

    # Sort by created_at descending (newest first)
    sorted_entries = sorted(entries, key=lambda x: x.get("created_at", 0), reverse=True)

    for entry in sorted_entries:
        content = entry.get("content", "")
        category = entry.get("category", "")
        entry_id = entry.get("id", "")

        # Check both MISTAKE: prefix and category="mistake"
        if content.upper().startswith("MISTAKE:"):
            mistake_text = content[9:] if content.startswith("MISTAKE: ") else content[8:]
            mistakes.append({"id": entry_id, "content": mistake_text})
        elif category == "mistake":
            mistakes.append({"id": entry_id, "content": content})

    return mistakes


def get_project_rules(project_memory: dict) -> list[dict]:
    """Extract rules from project memory (always show these).
    Returns list of dicts with 'id' and 'content' keys."""
    rules = []
    entries = project_memory.get("entries", [])

    # Sort by relevance descending (most important first)
    sorted_entries = sorted(entries, key=lambda x: x.get("relevance", 5), reverse=True)

    for entry in sorted_entries:
        category = entry.get("category", "")
        if category == "rule":
            rules.append({"id": entry.get("id", ""), "content": entry.get("content", "")})

    return rules


def get_memory_counts(project_memory: dict) -> dict:
    """Get memory counts by category for summary display."""
    entries = project_memory.get("entries", [])
    counts = {}
    for entry in entries:
        cat = entry.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    counts["total"] = len(entries)
    return counts


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _pluralize(count: int, singular: str) -> str:
    """Pluralize a category name correctly."""
    if count == 1:
        return f"{count} {singular}"
    # Handle irregular plurals
    if singular == "discovery":
        return f"{count} discoveries"
    if singular == "memory":
        return f"{count} memories"
    return f"{count} {singular}s"


def _append_memory_summary(lines: list, project_memory: dict, project_dir: str):
    """Append memory summary and management hints to hook output."""
    counts = get_memory_counts(project_memory)
    total = counts.get("total", 0)

    if total == 0:
        return

    # Build compact summary line with correct plurals
    parts = [_pluralize(total, "memory")]
    for cat in ["rule", "mistake", "discovery", "decision", "context"]:
        n = counts.get(cat, 0)
        if n > 0:
            parts.append(_pluralize(n, cat))
    lines.append(f"Memory: {', '.join(parts)}")

    # Management hints when memory count is high
    if total > 20:
        lines.append(f"  Tip: memory(recent) to review | memory(delete, memory_id='...') to clean up")
    if total > 40:
        lines.append(f"  Consider: memory(cleanup, dry_run=true) to find stale/duplicate memories")
    lines.append("")


def check_session_active(project_dir: str) -> bool:
    """Check if a Claude Engram session is active."""
    state = load_state()

    # Check if session was started recently (within 4 hours)
    last_start = state.get("last_session_start")
    if last_start and (time.time() - last_start) < 14400:  # 4 hours
        active_project = state.get("active_project", "")
        if active_project == project_dir or Path(active_project).name == Path(project_dir).name:
            return True

    # Fallback to marker file (in ~/.claude_engram/ for Windows compatibility)
    marker = Path.home() / ".claude_engram" / "session_active"
    if marker.exists():
        try:
            active_project = marker.read_text().strip()
            return active_project == project_dir or Path(active_project).name == Path(project_dir).name
        except Exception:
            pass
    return False


def get_loop_status() -> dict:
    """Get loop detection status."""
    loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
    if not loop_file.exists():
        return {}
    try:
        return json.loads(loop_file.read_text())
    except Exception:
        return {}


def get_scope_status() -> dict:
    """Get scope guard status."""
    scope_file = Path.home() / ".claude_engram" / "scope_guard.json"
    if not scope_file.exists():
        return {}
    try:
        return json.loads(scope_file.read_text())
    except Exception:
        return {}


def get_checkpoint_data() -> dict:
    """Load the latest checkpoint data if it exists."""
    checkpoint_file = Path.home() / ".claude_engram" / "checkpoints" / "latest_checkpoint.json"
    if not checkpoint_file.exists():
        return {}
    try:
        data = json.loads(checkpoint_file.read_text())
        # Check age - only return if less than 48 hours old
        age_hours = (time.time() - data.get("timestamp", 0)) / 3600
        if age_hours < 48:
            return data
        return {}
    except Exception:
        return {}


def get_handoff_data() -> dict:
    """Load the latest handoff data if it exists."""
    handoff_file = Path.home() / ".claude_engram" / "checkpoints" / "latest_handoff.json"
    if not handoff_file.exists():
        return {}
    try:
        data = json.loads(handoff_file.read_text())
        # Check age - only return if less than 48 hours old
        age_hours = (time.time() - data.get("created", data.get("created_at", 0))) / 3600
        if age_hours < 48:
            return data
        return {}
    except Exception:
        return {}


# NOTE: detect_complex_task REMOVED - too many false positives
# Almost every prompt contains "add", "create", "modify" etc.


def check_loop_detected(file_path: str = "") -> tuple[bool, int]:
    """
    Check if we're in a loop (editing same file repeatedly).

    SMART DETECTION:
    - If tests are PASSING: 3+ edits = iterative improvement (not a loop)
    - If tests are FAILING: 3+ edits = death spiral (LOOP!)
    - No test data: 3+ edits = potential loop (warn)

    Returns:
        (in_loop, edit_count)
    """
    loop_status = get_loop_status()
    file_edits = loop_status.get("file_edit_counts", {})
    test_results = loop_status.get("recent_test_results", [])

    if file_path and file_path in file_edits:
        count = file_edits[file_path]
        if count >= 3:
            # SMART: Check test context
            # If last 2 tests passed, this is iterative improvement, not a loop
            if len(test_results) >= 2:
                last_two_passed = all(t.get("passed") for t in test_results[-2:])
                if last_two_passed:
                    # Tests passing = iterative improvement, not a loop
                    return (False, count)
                else:
                    # Tests failing = death spiral!
                    return (True, count)
            # No test data = assume potential loop
            return (True, count)

    # Check total edits across all files
    total_edits = loop_status.get("total_edits", 0)
    if total_edits >= 10:  # Lots of edits without resolution
        return (True, total_edits)

    return (False, 0)


# NOTE: check_risky_file and check_recent_thinker_usage REMOVED
# - Risky file blocking was too aggressive (blocked editing auth/config files)
# - Thinker usage tracking removed with habit tools


# ============================================================================
# AUTO-INJECTION - Automatically call Claude Engram tools
# ============================================================================

def _auto_run_pre_edit_check(project_dir: str, file_path: str) -> dict:
    """
    Automatically run pre_edit_check and return results.

    Returns dict with:
    - past_mistakes: list of relevant mistakes
    - loop_warnings: list of loop detector warnings
    - scope_warnings: list of scope violations
    - suggestions: immediately useful suggestions
    """
    results = {
        "past_mistakes": [],
        "loop_warnings": [],
        "scope_warnings": [],
        "suggestions": [],
    }

    # Check memory for past mistakes
    project_memory = load_project_memory(project_dir)
    all_mistakes = get_past_mistakes(project_memory)
    file_name = Path(file_path).name

    # Find mistakes related to this file (exact filename match, not substring)
    import re as _re3
    file_pattern = _re3.compile(r'(?:^|[\s/\\:])' + _re3.escape(file_name.lower()) + r'(?:[\s:,.]|$)')
    for mistake in all_mistakes:
        if file_pattern.search(mistake["content"].lower()):
            results["past_mistakes"].append(mistake["content"])

    # Check loop detector
    loop_status = get_loop_status()
    edits = loop_status.get("edit_counts", {})
    edit_count = edits.get(file_path, 0) or edits.get(file_name, 0)

    if edit_count >= 5:
        results["loop_warnings"].append(f"{edit_count} edits without passing tests")

    # Check scope guard
    scope_status = get_scope_status()
    task = scope_status.get("task_description", "")
    if task:
        in_scope = scope_status.get("in_scope_files", [])
        patterns = scope_status.get("in_scope_patterns", [])

        is_in_scope = file_path in in_scope or file_name in in_scope
        if not is_in_scope and patterns:
            import fnmatch
            is_in_scope = any(
                fnmatch.fnmatch(file_path, p) or fnmatch.fnmatch(file_name, p)
                for p in patterns
            )

        if not is_in_scope:
            results["scope_warnings"].append(f"{file_name} NOT in scope for: {task[:50]}")

    # Add RICH context - actually useful information
    try:
        file_obj = Path(file_path)

        # 1. Check for TODOs/FIXMEs in the file
        if file_obj.exists() and file_obj.is_file():
            try:
                content = file_obj.read_text()
                todos = []
                for line_num, line in enumerate(content.split('\n')[:500], 1):  # First 500 lines
                    if 'TODO' in line or 'FIXME' in line or 'XXX' in line or 'HACK' in line:
                        todos.append(f"L{line_num}: {line.strip()[:60]}")
                if todos:
                    results["suggestions"].append(f"{len(todos)} TODO/FIXME in file: {', '.join(todos[:2])}")
            except Exception:
                pass

        # Git commit history removed — not useful context before an edit.

        # Code style suggestions removed — they were generic linting noise
        # (bare except, print count, file size, "run tests", "restart server")
        # that wasted tokens without providing actionable context.

        # 5. NEW: Contextual memory injection
        contextual_memories = get_contextual_memories(project_dir, file_path)
        if contextual_memories:
            results["contextual_memories"] = contextual_memories

    except Exception:
        # Fallback to basic suggestions if rich context fails
        if "test" in file_name.lower():
            results["suggestions"].append("Run tests after editing")
        if edit_count >= 2:
            results["suggestions"].append("Edited multiple times - review approach")

    # Mark that we ran the check
    state = load_state()
    state["last_pre_edit_check"] = time.time()
    state["last_pre_edit_file"] = file_path
    _increment_tool_usage(state, "work_pre_edit_check")
    save_state(state)

    return results


def get_contextual_memories(project_dir: str, file_path: str) -> list[str]:
    """
    Get scored memories relevant to a file context using HotMemoryReader.

    Uses relevance scoring (file match, tags, recency, importance) instead
    of naive filename substring matching. Returns top 3 most relevant.
    """
    try:
        from claude_engram.tools.memory import HotMemoryReader

        reader = HotMemoryReader()
        context = {
            "file_path": file_path,
            "tool_name": "Edit",
            "tags": [],
        }
        scored = reader.get_scored_memories(project_dir, context, limit=3)
        return [
            f"{m['content'][:80]}..." if len(m['content']) > 80 else m['content']
            for m in scored
        ]
    except Exception:
        return []


def _auto_record_edit(file_path: str, description: str = "auto-tracked"):
    """
    Automatically record an edit in loop detector.
    Called post-edit to track changes invisibly.
    """
    loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
    loop_file.parent.mkdir(parents=True, exist_ok=True)

    # Load loop detector state
    if loop_file.exists():
        try:
            loop_data = json.loads(loop_file.read_text())
        except Exception:
            loop_data = {"edit_counts": {}, "test_results": []}
    else:
        loop_data = {"edit_counts": {}, "test_results": []}

    # Increment edit count for this file
    file_name = Path(file_path).name
    counts = loop_data.get("edit_counts", {})
    counts[file_path] = counts.get(file_path, 0) + 1
    counts[file_name] = counts.get(file_name, 0) + 1  # Track both full path and name
    loop_data["edit_counts"] = counts

    # Save
    try:
        loop_file.write_text(json.dumps(loop_data, indent=2))
    except Exception:
        pass  # Silently fail

    # Mark in state
    state = load_state()
    state["last_loop_record"] = time.time()
    state["last_loop_file"] = file_path
    _increment_tool_usage(state, "loop_record_edit")
    save_state(state)


def _auto_record_test(passed: bool, error_message: str = "") -> str:
    """
    Automatically record test result in loop detector.
    Called after test runs to track results invisibly.
    Returns confirmation message.
    """
    loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
    loop_file.parent.mkdir(parents=True, exist_ok=True)

    # Load loop detector state
    if loop_file.exists():
        try:
            loop_data = json.loads(loop_file.read_text())
        except Exception:
            loop_data = {"edit_counts": {}, "test_results": []}
    else:
        loop_data = {"edit_counts": {}, "test_results": []}

    # Add test result
    test_results = loop_data.get("test_results", [])
    test_results.append({
        "timestamp": time.time(),
        "passed": passed,
        "error_message": error_message[:200] if error_message else "",
    })
    # Keep last 20 results
    loop_data["test_results"] = test_results[-20:]

    # Save
    try:
        loop_file.write_text(json.dumps(loop_data, indent=2))
    except Exception:
        pass  # Silently fail

    # Mark in state
    state = load_state()
    state["last_test_record"] = time.time()
    state["last_test_passed"] = passed
    state["test_runs_this_session"] = state.get("test_runs_this_session", 0) + 1
    _increment_tool_usage(state, "loop_record_test")
    save_state(state)

    return "PASSED" if passed else "FAILED"


# ============================================================================
# ENFORCEMENT - Make Claude Engram usage mandatory
# ============================================================================

def should_show_full_reminder(project_dir: str, prompt: str = "") -> tuple[bool, str]:
    """
    Determine if we should show the full reminder block.

    Returns:
        (should_show, reason) - reason explains why we're showing/not showing

    CONTEXT-AWARE LOGIC:
    - Session not active: Auto-start and show welcome
    - First prompt of session: Show welcome
    - Checkpoint exists to restore: Remind once
    - Otherwise: SILENT (no injection)
    """
    state = load_state()
    session_active = check_session_active(project_dir)

    # CASE 1: Session not active - will auto-start, show welcome
    if not session_active:
        return (True, "auto_start_session")

    # Session IS active - track prompts within session
    state["prompts_this_session"] = state.get("prompts_this_session", 0) + 1
    prompts_this_session = state["prompts_this_session"]
    save_state(state)

    # CASE 2: First prompt of active session - show welcome
    if prompts_this_session == 1:
        return (True, "first_prompt_of_session")

    # CASE 3: Checkpoint exists and we haven't reminded yet
    checkpoint = get_checkpoint_data()
    if checkpoint and not state.get("checkpoint_reminded", False):
        state["checkpoint_reminded"] = True
        save_state(state)
        return (True, "checkpoint_exists")

    # CASE 4: Otherwise - SILENT
    return (False, "no_reminder_needed")


def reminder_for_prompt(project_dir: str, prompt: str = "") -> str:
    """
    Generate reminder for UserPromptSubmit hook.

    CONTEXT-AWARE: Only shows reminders when there's a good reason.
    - First prompt of session: Full welcome + past mistakes
    - Session not started: Escalating warnings
    - Tier 2 architectural task: Show thinking tool suggestions
    - Search spiral: Suggest scout_search after 3+ failed searches
    - Otherwise: SILENT (no spam)
    """
    # CHECK FOR SEARCH SPIRAL FIRST - always show if in spiral
    spiral_suggestion = get_search_spiral_suggestion(project_dir)
    if spiral_suggestion:
        return f"<engram-reminder>\n{spiral_suggestion}\n</engram-reminder>"

    # CHECK IF WE SHOULD SHOW ANYTHING AT ALL
    should_show, reason = should_show_full_reminder(project_dir, prompt)
    if not should_show:
        return ""  # SILENT - no injection

    state = load_state()
    session_active = check_session_active(project_dir)
    project_memory = load_project_memory(project_dir)

    lines = ["<engram-reminder>"]

    if not session_active:
        # AUTO-START SESSION - No more nagging!
        # This is Claude's tool, built by Claude, for Claude. Just start automatically.
        mark_session_started(project_dir)
        session_active = True  # Update local var

        lines.append("Claude Engram session auto-started")
        lines.append("")

        # AUTO-LOAD CHECKPOINT/HANDOFF
        checkpoint = get_checkpoint_data()
        handoff = get_handoff_data()

        if checkpoint or handoff:
            lines.append("---")
            lines.append("")
            lines.append("CONTEXT RESTORED FROM PREVIOUS SESSION")
            lines.append("")

            if checkpoint:
                age_hours = (time.time() - checkpoint.get("timestamp", 0)) / 3600
                lines.append(f"CHECKPOINT ({age_hours:.1f}h ago):")
                lines.append(f"  Task: {_truncate(checkpoint.get('task_description', 'Unknown'), 80)}")
                lines.append(f"  Current step: {_truncate(checkpoint.get('current_step', 'Unknown'), 60)}")
                if checkpoint.get("completed_steps"):
                    lines.append(f"  Done: {len(checkpoint['completed_steps'])} steps")
                    for step in checkpoint["completed_steps"][-3:]:
                        lines.append(f"    - {_truncate(step, 60)}")
                if checkpoint.get("pending_steps"):
                    lines.append(f"  Pending: {len(checkpoint['pending_steps'])} steps")
                    for step in checkpoint["pending_steps"][:3]:
                        lines.append(f"    - {_truncate(step, 60)}")
                if checkpoint.get("files_involved"):
                    lines.append(f"  Files: {', '.join(Path(f).name for f in checkpoint['files_involved'][:5])}")
                lines.append("")

            if handoff:
                lines.append("HANDOFF MESSAGE:")
                lines.append(f"  {_truncate(handoff.get('summary', 'No summary'), 100)}")
                if handoff.get("next_steps"):
                    lines.append("  Next steps:")
                    for step in handoff["next_steps"][:3]:
                        lines.append(f"    - {_truncate(step, 60)}")
                lines.append("")

            lines.append("CONTINUE FROM WHERE YOU LEFT OFF")
            lines.append("")
            lines.append("---")
            lines.append("")

        # Show RULES first (always follow these) - with IDs for management
        rules = get_project_rules(project_memory)
        if rules:
            lines.append(f"RULES ({len(rules)}) - always follow:")
            for r in rules[:5]:  # Show top 5 rules
                lines.append(f"  [{r['id']}] {_truncate(r['content'], 120)}")
            lines.append("")

        # Show past mistakes (newest first) - with IDs for management
        mistakes = get_past_mistakes(project_memory)
        if mistakes:
            lines.append(f"PAST MISTAKES ({len(mistakes)}) - avoid repeating:")
            for m in mistakes[:5]:  # Already sorted newest first
                lines.append(f"  [{m['id']}] {_truncate(m['content'], 100)}")
            lines.append("")

        # Show memory summary and management hints
        _append_memory_summary(lines, project_memory, project_dir)

    else:
        # Session is active — only show rules. Mistakes are file-specific
        # and handled by PreToolUse Edit injection (with relevance filtering).
        # Dumping generic mistakes on every prompt is noise, not signal.
        rules = get_project_rules(project_memory)
        if rules:
            lines.append(f"Rules ({len(rules)}):")
            for r in rules[:5]:
                lines.append(f"  [{r['id']}] {_truncate(r['content'], 100)}")
            lines.append("")
        else:
            return ""  # Nothing useful to inject — stay silent

    lines.append("</engram-reminder>")
    return "\n".join(lines)


def reminder_for_edit(project_dir: str, file_path: str = "") -> str:
    """
    Generate reminder for PreToolUse hook (Edit/Write).

    NOW WITH AUTO-INJECTION:
    - Automatically calls pre_edit_check and shows results
    - Automatically checks loops and scope
    - Makes tools useful NOW, not just future sessions

    Enforces:
    1. Session must be active
    2. Auto-runs pre_edit_check and shows results
    3. Loop detector warnings
    4. Scope guard warnings
    """
    state = load_state()
    session_active = check_session_active(project_dir)

    lines = ["<engram-edit-reminder>"]
    has_content = False

    # AUTO-INJECTION: Run pre_edit_check automatically
    auto_check_results = None
    if session_active and file_path:
        try:
            auto_check_results = _auto_run_pre_edit_check(project_dir, file_path)
        except Exception as e:
            # Silently fail if auto-check breaks
            pass

    # Show auto-check results FIRST (immediate value!)
    if auto_check_results:
        if auto_check_results["past_mistakes"]:
            lines.append("AUTO-CHECK: Past mistakes with this file:")
            for m in auto_check_results["past_mistakes"][:3]:
                lines.append(f"  - {_truncate(m, 80)}")
            lines.append("")
            has_content = True

        if auto_check_results["loop_warnings"]:
            lines.append("AUTO-CHECK: Loop detection:")
            for w in auto_check_results["loop_warnings"]:
                lines.append(f"  • {w}")
            lines.append("")
            has_content = True

        if auto_check_results["scope_warnings"]:
            lines.append("AUTO-CHECK: Scope warning:")
            for w in auto_check_results["scope_warnings"]:
                lines.append(f"  • {w}")
            lines.append("")
            has_content = True

        if auto_check_results["suggestions"]:
            lines.append("AUTO-CHECK: Suggestions:")
            for s in auto_check_results["suggestions"]:
                lines.append(f"  • {s}")
            lines.append("")
            has_content = True

        # NEW: Show contextual memories
        if auto_check_results.get("contextual_memories"):
            lines.append("Relevant memories for this file:")
            for m in auto_check_results["contextual_memories"]:
                lines.append(f"  • {m}")
            lines.append("")
            has_content = True

    # Loop detection - only warn if tests are failing (real spiral)
    is_loop, loop_count = check_loop_detected(file_path)
    if is_loop and loop_count >= 5:
        # check_loop_detected returns True only if tests are failing or no test data
        # and count >= 3. We raise to 5 to reduce false positives on iterative work.
        lines.append(f"LOOP WARNING: {loop_count} edits without passing tests")
        lines.append("")
        has_content = True

    # ENFORCE: Session must be active
    if not session_active:
        state["edits_without_session"] = state.get("edits_without_session", 0) + 1
        edits = state["edits_without_session"]
        save_state(state)

        lines.append(f"No session active (edit #{edits}). Run:")
        lines.append(f'  session_start(project_path="{project_dir}")')
        has_content = True
    else:
        # Track this edit
        record_file_edit(file_path)

    # Auto-recording happens silently post-edit - no need to announce it

    lines.append("</engram-edit-reminder>")

    if has_content:
        return "\n".join(lines)
    return ""


def reminder_for_write(project_dir: str, file_path: str = "", content: str = "") -> str:
    """
    Generate reminder for Write tool.

    Enforces:
    1. Code quality checks
    2. Same session/scope checks as edit
    """
    # First do all the edit checks
    edit_reminder = reminder_for_edit(project_dir, file_path)

    lines = []
    has_quality_issues = False

    # Code quality checks
    if content:
        issues = []

        # Check for long functions
        func_matches = re.findall(r'def\s+\w+\([^)]*\):[^\n]*\n((?:[ \t]+[^\n]*\n){50,})', content)
        if func_matches:
            issues.append("Function(s) >50 lines - break them down")

        # Check for vague names (only clearly bad ones, not x/y/z/data which are often legitimate)
        vague_names = ['temp', 'tmp', 'foo', 'bar', 'stuff', 'thing']
        for name in vague_names:
            if re.search(rf'\b{name}\b\s*=', content):
                issues.append(f"Vague variable name: '{name}'")
                break

        # Check for placeholders
        placeholders = ['TODO', 'FIXME', 'HACK', 'XXX', 'PLACEHOLDER']
        for p in placeholders:
            if p in content:
                issues.append(f"Found placeholder: '{p}'")
                break

        # Check for silent failure (CRITICAL) - only match at start of line (not in comments/strings)
        if re.search(r'^\s*except\s*:\s*pass', content, re.MULTILINE) or re.search(r'^\s*except\s+\w+:\s*pass', content, re.MULTILINE):
            issues.append("DANGER: Found 'except: pass' - silent failure pattern")

        # Check for hardcoded values
        if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', content, re.I):
            issues.append("DANGER: Possible hardcoded secret")

        if issues:
            lines.append("<engram-write-quality>")
            lines.append("Code Quality Warnings:")
            for issue in issues[:5]:
                lines.append(f"  {issue}")
            lines.append("")
            lines.append("Run: code_quality_check(code) for full analysis")
            lines.append("</engram-write-quality>")
            has_quality_issues = True

    if edit_reminder:
        return edit_reminder + ("\n" + "\n".join(lines) if has_quality_issues else "")
    elif has_quality_issues:
        return "\n".join(lines)
    return ""


def reminder_for_bash(project_dir: str, command: str = "", exit_code: str = "", output: str = "") -> str:
    """
    Generate reminder for PostToolUse hook on Bash.

    Enforces:
    1. If tests ran, demand loop(operation='record_test')
    2. If command failed, demand work(operation='log_mistake')
    3. NEW: Auto-log detected mistakes from common error patterns
    """
    lines = []
    has_content = False

    # Check if this was a test command - only track meaningful test runs
    # Must check the FIRST command in a chain, not substrings in commit messages/heredocs
    command_lower = command.lower().strip() if command else ""

    # Extract just the first command (before &&, ||, ;, or heredoc)
    import re
    first_cmd = re.split(r'&&|\|\||;|\$\(', command_lower)[0].strip()

    # Full suite patterns - must be the start of the first command
    full_suite_patterns = ['npm test', 'yarn test', 'make test', 'cargo test', 'go test ./...']
    is_full_suite = any(first_cmd.startswith(p) or first_cmd == p for p in full_suite_patterns)

    # Commands that might be full suite OR targeted - check first command only
    if not is_full_suite:
        test_commands = ['pytest', 'jest', 'mocha', 'python -m unittest', 'python -m pytest']
        for cmd in test_commands:
            if first_cmd.startswith(cmd):
                # If command is just "pytest" or "pytest -v" etc (no path), it's full suite
                # But "pytest tests/test_foo.py" is targeted
                parts = first_cmd.split()
                cmd_parts = cmd.split()
                remaining = parts[len(cmd_parts):]
                has_path = any('.py' in arg or '/' in arg or '\\' in arg or '::' in arg for arg in remaining if not arg.startswith('-'))
                if not has_path:
                    is_full_suite = True
                break

    if is_full_suite:
        passed = exit_code == "0"
        state = load_state()
        last_passed = state.get("last_test_passed")

        # Check if state changed (for informative message)
        state_changed = last_passed is not None and last_passed != passed
        first_run = last_passed is None

        # AUTO-RECORD the test result (no manual call needed)
        error_snippet = output[:200] if output and not passed else ""
        result = _auto_record_test(passed, error_snippet)

        # Show confirmation (not reminder)
        status_emoji = "PASS" if passed else "FAIL"
        lines.append("<engram-test-tracked>")
        if state_changed:
            if passed:
                lines.append(f"{status_emoji} Test tracked: NOW PASSING (were failing)")
            else:
                lines.append(f"{status_emoji} Test tracked: NOW FAILING (were passing)")
        elif first_run:
            lines.append(f"{status_emoji} Test tracked: {result} (baseline established)")
        else:
            lines.append(f"{status_emoji} Test tracked: {result}")
        lines.append("</engram-test-tracked>")
        has_content = True

    # Check if command failed
    if exit_code and exit_code != "0":
        state = load_state()
        state["errors_without_log"] = state.get("errors_without_log", 0) + 1
        errors = state["errors_without_log"]
        save_state(state)

        # NEW: Auto-detect and auto-log common mistakes
        auto_logged = _auto_log_detected_mistake(project_dir, command, output)

        lines.append("<engram-error-reminder>")
        if auto_logged:
            lines.append(f"Auto-logged: {auto_logged}")
        else:
            lines.append("Log with work(log_mistake) to get warned next time")
        lines.append("</engram-error-reminder>")
        has_content = True

    if has_content:
        return "\n".join(lines)
    return ""


# Trigger words that the decision regex looks for — used for typo correction
_DECISION_TRIGGER_WORDS = {
    "switch", "use", "using", "adopt", "prefer", "replace", "migrate", "swap",
    "change", "convert", "upgrade", "downgrade", "rewrite", "refactor",
    "remove", "drop", "import", "implement", "build", "choose", "pick",
    "stick", "keep", "stop", "avoid", "never", "always", "should",
    "please", "going", "forward", "instead", "rather", "lets", "let's",
    "don't", "dont", "doing", "importing",
}


def _fix_typo(word: str) -> str:
    """
    If a word is within edit distance 1-2 of a trigger word, return the trigger.
    Checks: adjacent swap, single char delete/insert/replace, and combos for short words.
    Returns the original word if no close match found.
    """
    if word in _DECISION_TRIGGER_WORDS:
        return word

    # Adjacent character swaps (most common typo: "swtich" -> "switch")
    for i in range(len(word) - 1):
        swapped = word[:i] + word[i + 1] + word[i] + word[i + 2:]
        if swapped in _DECISION_TRIGGER_WORDS:
            return swapped

    # Single character removed from word (word is shorter: "plase" -> check "please")
    # Try inserting each letter a-z at each position to see if it makes a trigger
    for trigger in _DECISION_TRIGGER_WORDS:
        if len(trigger) == len(word) + 1:
            # Check if word is trigger with one char removed
            for i in range(len(trigger)):
                if trigger[:i] + trigger[i + 1:] == word:
                    return trigger

    # Extra character in word (word is longer: "useing" -> check "using")
    for i in range(len(word)):
        shorter = word[:i] + word[i + 1:]
        if shorter in _DECISION_TRIGGER_WORDS:
            return shorter

    # Single character substitution ("avod" -> "avoid" won't work, but "replce" -> ?)
    for trigger in _DECISION_TRIGGER_WORDS:
        if len(trigger) == len(word):
            diffs = sum(1 for a, b in zip(word, trigger) if a != b)
            if diffs == 1:
                return trigger

    # Edit distance 2 — only for words that aren't common English words
    # (prevents "using"->"going", "the"->"use", "strict"->"stick")
    _COMMON_WORDS = {
        "the", "a", "an", "is", "was", "are", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "using", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "up", "about", "into", "through", "during", "before", "after",
        "above", "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so",
        "than", "too", "very", "just", "because", "but", "and", "or", "if",
        "while", "that", "this", "these", "those", "i", "you", "he", "she",
        "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
        "his", "its", "our", "their", "what", "which", "who", "whom",
        "going", "get", "got", "make", "take", "come", "go", "see", "know",
        "think", "say", "said", "like", "look", "find", "give", "tell",
        "work", "call", "try", "ask", "turn", "start", "show", "hear",
        "play", "run", "move", "live", "old", "new", "good", "bad", "big",
        "small", "long", "short", "high", "low", "right", "left", "sure",
        "still", "also", "back", "well", "way", "even", "want", "first",
        "last", "next", "now", "then", "end", "set", "put", "point", "help",
        "hand", "home", "any", "best", "open", "much", "real", "form",
        "part", "since", "until", "along", "never", "always", "stick",
        "strict", "script", "fast", "hard", "soft",
    }
    if word not in _COMMON_WORDS:
        for trigger in _DECISION_TRIGGER_WORDS:
            if abs(len(trigger) - len(word)) <= 2 and len(word) >= 3:
                if len(trigger) + len(word) <= 16:
                    d = _edit_distance(word, trigger)
                    if d <= 2:
                        return trigger

    return word


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance. Only called for short strings."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (0 if ca == cb else 1),
            ))
        prev = curr
    return prev[-1]


def _normalize_typos(text: str) -> str:
    """Correct trigger-word typos in text for better regex matching."""
    words = text.split()
    corrected = []
    for w in words:
        # Preserve punctuation
        prefix = ""
        suffix = ""
        core = w
        while core and not core[0].isalnum():
            prefix += core[0]
            core = core[1:]
        while core and not core[-1].isalnum():
            suffix = core[-1] + suffix
            core = core[:-1]
        if core:
            fixed = _fix_typo(core.lower())
            # Preserve original case if no fix
            if fixed != core.lower():
                core = fixed
            else:
                core = core.lower()
        corrected.append(prefix + core + suffix)
    return " ".join(corrected)


def _score_decision_intent(text: str) -> tuple[float, str]:
    """
    Score whether a sentence expresses a decision. No LLM needed.

    Uses weighted keyword + sentence structure analysis:
    - Decision verbs (use, switch, adopt, prefer, go with)
    - Directive markers (let's, we should, from now on, always, never)
    - Contrast signals (instead of, rather than, not X but Y, over)
    - Negation constraints (don't, stop, avoid, never)

    Applies lightweight typo correction on trigger words before matching.

    Returns (score 0.0-1.0, extracted_decision_text).
    Score >= 0.5 = capture as decision.
    """
    text_lower = _normalize_typos(text.lower().strip())
    score = 0.0
    best_match = ""

    # --- Decision verb presence (0.35 max) ---
    # Strong verbs that almost always indicate a decision
    strong_verbs = [
        "switch to", "go with", "adopt", "move to", "migrate to",
        "replace with", "swap to", "change to", "convert to", "upgrade to",
        "downgrade to", "rewrite in", "refactor to", "get rid of",
    ]
    # Moderate verbs that need additional context
    moderate_verbs = [
        "use", "prefer", "choose", "pick", "stick with", "keep using",
        "implement with", "build with", "import from", "import",
        "replace", "remove", "drop",
    ]
    verb_score = 0.0
    for verb in strong_verbs:
        if verb in text_lower:
            verb_score = 0.35
            break
    if verb_score == 0:
        for verb in moderate_verbs:
            if verb in text_lower:
                verb_score = 0.25
                break
    score += verb_score

    # --- Directive markers (0.25 max) ---
    directive_patterns = [
        (r"\blet'?s\s+", 0.25),
        (r"\bwe\s+should\b", 0.25),
        (r"\bfrom\s+now\s+on\b", 0.25),
        (r"\bgoing\s+forward\b", 0.2),
        (r"\balways\s+", 0.2),
        (r"\bnever\s+", 0.2),
        (r"\bmake\s+sure\s+(to|we)\b", 0.15),
        (r"\bi\s+want\s+(to|you\s+to)\b", 0.2),
        (r"\bplease\s+(use|switch|change|adopt|go|replace|remove|drop|stop|rewrite)\b", 0.25),
        (r"\bgo\s+ahead\s+and\b", 0.2),
        (r"\bjust\s+(use|do|go|switch|replace)\b", 0.2),
    ]
    for pattern, weight in directive_patterns:
        if re.search(pattern, text_lower):
            score += weight
            break

    # --- Contrast/comparison signals (0.2 max) ---
    contrast_patterns = [
        (r"\binstead\s+of\b", 0.2),
        (r"\brather\s+than\b", 0.2),
        (r"\bnot\s+\w+\s+but\b", 0.15),
        (r"\bover\s+\w+", 0.1),
        (r"\binstead\b", 0.1),
        (r"\brather\b", 0.1),
        (r"\breplace\b", 0.15),
    ]
    for pattern, weight in contrast_patterns:
        if re.search(pattern, text_lower):
            score += weight
            break

    # --- Negation constraints (0.2 max) ---
    negation_patterns = [
        (r"\bdon'?t\s+(use|do|add|include|import|ever)\b", 0.2),
        (r"\bstop\s+(using|doing|importing)\b", 0.2),
        (r"\bavoid\s+\w", 0.2),
        (r"\bnever\s+\w", 0.2),
        (r"\bremove\s+(the|all)\b", 0.15),
        (r"\bget\s+rid\s+of\b", 0.2),
        (r"\bdrop\s+(the|all|this)\b", 0.15),
    ]
    for pattern, weight in negation_patterns:
        if re.search(pattern, text_lower):
            score += weight
            break

    # --- Penalties ---
    # Questions are not decisions
    if "?" in text:
        score *= 0.3
    # Very short text is probably not a decision
    if len(text_lower) < 25:
        score *= 0.5
    # "can you" / "could you" / "would you" are requests, not decisions
    if re.search(r"\b(can|could|would|should)\s+you\b", text_lower):
        score *= 0.6
    # "what if" / "how about" are exploratory
    if re.search(r"\b(what\s+if|how\s+about|maybe|perhaps)\b", text_lower):
        score *= 0.5

    # --- Extract the decision text ---
    # Try to find the most decision-like sentence/clause
    extraction_patterns = [
        # "let's use X instead of Y"
        r"(let'?s\s+.{10,120}?)(?:\.|$|\n)",
        # "we should X"
        r"(we\s+should\s+.{10,120}?)(?:\.|$|\n)",
        # "from now on X" / "going forward X"
        r"((?:from\s+now\s+on|going\s+forward),?\s+.{10,120}?)(?:\.|$|\n)",
        # "please use/switch/change X"
        r"(please\s+(?:use|switch|change|adopt|go|replace|drop|remove|stop)\s+.{5,120}?)(?:\.|$|\n)",
        # "don't use X" / "avoid X" / "stop using X" / "never X"
        r"((?:don'?t|do\s+not|stop|avoid|never)\s+(?:use|using|do|doing|add|include)\s+.{5,100}?)(?:\.|$|\n)",
        # "use X instead of Y" / "switch to X"
        r"((?:use|switch\s+to|go\s+with|adopt|prefer|replace\s+\w+\s+with)\s+.{5,100}?)(?:\.|$|\n)",
        # "I want to/you to X"
        r"(i\s+want\s+(?:to|you\s+to)\s+.{10,120}?)(?:\.|$|\n)",
        # "always/never X"
        r"((?:always|never)\s+.{10,100}?)(?:\.|$|\n)",
    ]

    for pattern in extraction_patterns:
        match = re.search(pattern, text_lower)
        if match:
            best_match = match.group(1).strip()
            break

    # Fallback: if score is high but no extraction, take first 120 chars
    if score >= 0.5 and not best_match:
        # Take up to first period or newline
        first_sentence = re.split(r'[.\n]', text_lower)[0].strip()
        if len(first_sentence) > 15:
            best_match = first_sentence[:120]

    return (min(score, 1.0), best_match)


def _auto_capture_from_prompt(project_dir: str, prompt: str):
    """
    Auto-capture decisions from user prompts.

    Two-tier scoring:
    1. Semantic (AllMiniLM) — if sentence-transformers is installed, uses cosine
       similarity against pre-computed decision templates. Best accuracy.
    2. Regex fallback — weighted keyword + sentence structure analysis. Fast, no deps.

    If semantic scoring is available and confident, uses that result.
    Otherwise falls back to regex. Only captures when score >= 0.45.
    Does NOT log the full prompt (privacy).
    """
    prompt_lower = prompt.lower().strip()

    # Skip very short or command-like prompts
    if len(prompt_lower) < 25 or prompt_lower.startswith("/"):
        return

    try:
        import hashlib

        best_score = 0.0
        best_text = ""

        # Tier 1: Try semantic scoring (AllMiniLM)
        try:
            from claude_engram.hooks.intent import score_decision_semantic
            sem_score, sem_text = score_decision_semantic(prompt)
            if sem_score > best_score:
                best_score = sem_score
                best_text = sem_text
        except Exception:
            pass  # sentence-transformers not installed or other error

        # Tier 2: Regex fallback (always runs, may upgrade the score)
        sentences = re.split(r'(?<=[.!])\s+|\n+', prompt)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
        if len(sentences) <= 1:
            sentences = [prompt.strip()]

        for sentence in sentences:
            regex_score, regex_text = _score_decision_intent(sentence)
            if regex_score > best_score:
                best_score = regex_score
                best_text = regex_text

        # Only capture when confident (0.45 threshold — semantic scores are well-calibrated,
        # regex scores tend to cluster around 0.4-0.6 for borderline cases)
        if best_score < 0.45 or not best_text or len(best_text) < 15:
            return

        norm_dir = _normalize_path(project_dir)
        manifest = _get_manifest()

        content = f"DECISION: (from user) {best_text[:150]}"
        entry_id = hashlib.md5(content.encode()).hexdigest()[:12]

        # v5 path: per-project files
        if manifest.get("projects") and norm_dir in manifest["projects"]:
            pdir = get_project_memory_dir(project_dir)
            mem_file = pdir / "memory.json"
            proj_data = {}
            if mem_file.exists():
                proj_data = json.loads(mem_file.read_text())

            existing_entries = proj_data.get("entries", [])
            existing_contents = {e.get("content", "") for e in existing_entries}
            if content in existing_contents:
                return

            new_words = set(best_text.lower().split())
            for e in existing_entries:
                if e.get("category") != "decision":
                    continue
                existing_words = set(e.get("content", "").lower().split())
                if existing_words and new_words:
                    overlap = len(new_words & existing_words) / len(new_words | existing_words)
                    if overlap > 0.7:
                        return

            file_refs = re.findall(
                r'[\w/\\.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)',
                best_text
            )

            proj_data.setdefault("entries", []).append({
                "id": entry_id,
                "content": content,
                "category": "decision",
                "source": "auto-prompt",
                "relevance": 6,
                "created_at": time.time(),
                "last_accessed": time.time(),
                "access_count": 1,
                "tags": ["decision"],
                "related_files": file_refs[:5],
            })
            proj_data["last_updated"] = time.time()

            pdir.mkdir(parents=True, exist_ok=True)
            temp_file = mem_file.with_suffix(".json.tmp")
            temp_file.write_text(json.dumps(proj_data, indent=2))
            temp_file.replace(mem_file)

            # Embed to pending file (fast, no full load)
            try:
                from claude_engram.hooks.scorer_server import embed_via_server
                emb = embed_via_server(content)
                if emb:
                    pending_file = pdir / "embeddings_pending.json"
                    pending = {}
                    if pending_file.exists():
                        pending = json.loads(pending_file.read_text())
                    pending[entry_id] = emb
                    emb_tmp = pending_file.with_suffix(".json.tmp")
                    emb_tmp.write_text(json.dumps(pending))
                    emb_tmp.replace(pending_file)
            except Exception:
                pass
        else:
            # Legacy fallback: single memory.json
            memory_file = get_memory_file()
            data = {}
            if memory_file.exists():
                data = json.loads(memory_file.read_text())

            projects = data.get("projects", {})
            if norm_dir not in projects:
                return

            existing_entries = projects[norm_dir].get("entries", [])
            existing_contents = {e.get("content", "") for e in existing_entries}
            if content in existing_contents:
                return

            new_words = set(best_text.lower().split())
            for e in existing_entries:
                if e.get("category") != "decision":
                    continue
                existing_words = set(e.get("content", "").lower().split())
                if existing_words and new_words:
                    overlap = len(new_words & existing_words) / len(new_words | existing_words)
                    if overlap > 0.7:
                        return

            file_refs = re.findall(
                r'[\w/\\.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)',
                best_text
            )

            projects[norm_dir].setdefault("entries", []).append({
                "id": entry_id,
                "content": content,
                "category": "decision",
                "source": "auto-prompt",
                "relevance": 6,
                "created_at": time.time(),
                "last_accessed": time.time(),
                "access_count": 1,
                "tags": ["decision"],
                "related_files": file_refs[:5],
            })
            projects[norm_dir]["last_updated"] = time.time()

            data["projects"] = projects
            data["version"] = data.get("version", 2)
            if "global" not in data:
                data["global"] = []

            temp_file = memory_file.with_suffix(".json.tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(memory_file)

            # Embed to legacy global embeddings
            try:
                from claude_engram.hooks.scorer_server import embed_via_server
                emb = embed_via_server(content)
                if emb:
                    emb_file = memory_file.parent / "embeddings.json"
                    emb_data = {}
                    if emb_file.exists():
                        emb_data = json.loads(emb_file.read_text())
                    emb_data[entry_id] = emb
                    emb_tmp = emb_file.with_suffix(".json.tmp")
                    emb_tmp.write_text(json.dumps(emb_data))
                    emb_tmp.replace(emb_file)
            except Exception:
                pass
    except Exception:
        pass  # Silent failure — auto-capture must never break the hook


def _auto_log_detected_mistake(project_dir: str, command: str, output: str) -> str:
    """
    Auto-detect and log common mistake patterns from command output.
    Returns description of logged mistake, or empty string if nothing detected.

    Detects error patterns in command output.
    Called from PostToolUse (exit 0 commands) and PostToolUseFailure (exit != 0).
    PostToolUseFailure is now the primary path for catching errors.
    """
    if not output or len(output) > 5000:
        # Skip empty output and large outputs (build logs, test suites)
        # where error keywords appear in non-error contexts
        return ""

    mistake_type = None
    how_to_avoid = None

    # Pattern 1: Import/Module errors
    import re
    if "ModuleNotFoundError" in output or "ImportError" in output:
        # Try "No module named 'X'" first
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", output)
        if match:
            module = match.group(1)
            mistake_type = f"Import error: Module '{module}' not found"
            how_to_avoid = f"Install missing module: pip install {module}"
        else:
            # Try "cannot import name 'X' from 'Y'"
            match2 = re.search(r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]", output)
            if match2:
                name, module = match2.group(1), match2.group(2)
                mistake_type = f"Import error: cannot import '{name}' from '{module}'"
                how_to_avoid = f"Check that '{name}' exists in {module}, or update the package"
            # If neither regex matched, skip - don't log "unknown"

    # Pattern 2: Syntax errors
    elif "SyntaxError" in output:
        match = re.search(r"File ['\"]([^'\"]+)['\"], line (\d+)", output)
        if match:
            file_name = Path(match.group(1)).name
            line = match.group(2)
            mistake_type = f"Syntax error in {file_name}:{line}"
            how_to_avoid = "Check syntax before running - use linter or read the file"

    # Pattern 3: Type errors (only log if we can parse the actual message)
    elif "TypeError" in output:
        match = re.search(r"TypeError: (.+)", output)
        if match:
            error_msg = match.group(1)[:60]
            mistake_type = f"Type error: {error_msg}"
            how_to_avoid = "Check argument types and return values"

    # Pattern 4: Attribute errors (only log if we can parse the actual message)
    elif "AttributeError" in output:
        match = re.search(r"AttributeError: (.+)", output)
        if match:
            error_msg = match.group(1)[:60]
            mistake_type = f"Attribute error: {error_msg}"
            how_to_avoid = "Check object type and available attributes"

    # Pattern 5: Test failures (require pytest/unittest markers in output)
    elif "AssertionError" in output or re.search(r"\d+ failed,?\s*\d+\s*(passed|error)", output) or "FAILURES\n" in output:
        match = re.search(r"(\d+) failed", output)
        count = match.group(1) if match else "some"
        mistake_type = f"Test failure: {count} tests failed"
        how_to_avoid = "Review test output and fix the failing assertions"

    # Pattern 6: Permission errors
    elif "PermissionError" in output or "Permission denied" in output:
        mistake_type = "Permission error"
        how_to_avoid = "Check file permissions or run with appropriate privileges"

    # Pattern 7: Connection errors
    elif "ConnectionError" in output or "Connection refused" in output:
        mistake_type = "Connection error - service may not be running"
        how_to_avoid = "Ensure the required service is running"

    if mistake_type:
        try:
            # Write directly to per-project file (fast, no full MemoryStore load)
            import hashlib
            content = f"MISTAKE: {mistake_type}"
            if how_to_avoid:
                content += f" - Fix: {how_to_avoid}"

            norm_dir = _normalize_path(project_dir)
            entry_id = hashlib.md5(content.encode()).hexdigest()[:12]
            manifest = _get_manifest()

            new_entry = {
                "id": entry_id,
                "content": content,
                "category": "mistake",
                "source": "auto-detected",
                "relevance": 9,
                "created_at": time.time(),
                "last_accessed": time.time(),
                "access_count": 1,
                "tags": ["mistake", "bugfix"],
                "related_files": [],
            }

            # v5 path: per-project files
            if manifest.get("projects") and norm_dir in manifest["projects"]:
                pdir = get_project_memory_dir(project_dir)
                mem_file = pdir / "memory.json"
                proj_data = {}
                if mem_file.exists():
                    proj_data = json.loads(mem_file.read_text())

                existing_contents = {e.get("content", "") for e in proj_data.get("entries", [])}
                if content not in existing_contents:
                    proj_data.setdefault("entries", []).append(new_entry)
                    proj_data["last_updated"] = time.time()

                    pdir.mkdir(parents=True, exist_ok=True)
                    temp_file = mem_file.with_suffix(".json.tmp")
                    temp_file.write_text(json.dumps(proj_data, indent=2))
                    temp_file.replace(mem_file)

                    # Embed to pending file
                    try:
                        from claude_engram.hooks.scorer_server import embed_via_server
                        emb = embed_via_server(content)
                        if emb:
                            pending_file = pdir / "embeddings_pending.json"
                            pending = {}
                            if pending_file.exists():
                                pending = json.loads(pending_file.read_text())
                            pending[entry_id] = emb
                            emb_tmp = pending_file.with_suffix(".json.tmp")
                            emb_tmp.write_text(json.dumps(pending))
                            emb_tmp.replace(pending_file)
                    except Exception:
                        pass
            else:
                # Legacy fallback: single memory.json
                memory_file = get_memory_file()
                data = {}
                if memory_file.exists():
                    data = json.loads(memory_file.read_text())

                projects = data.get("projects", {})
                if norm_dir not in projects:
                    projects[norm_dir] = {
                        "project_path": norm_dir,
                        "project_name": Path(project_dir).name,
                        "entries": [],
                        "recent_searches": [],
                        "last_updated": time.time(),
                    }

                existing_contents = {e.get("content", "") for e in projects[norm_dir].get("entries", [])}
                if content not in existing_contents:
                    projects[norm_dir]["entries"].append(new_entry)
                    projects[norm_dir]["last_updated"] = time.time()

                    data["projects"] = projects
                    data["version"] = data.get("version", 2)
                    if "global" not in data:
                        data["global"] = []

                    temp_file = memory_file.with_suffix(".json.tmp")
                    temp_file.write_text(json.dumps(data, indent=2))
                    temp_file.replace(memory_file)

                    # Embed to legacy global embeddings
                    try:
                        from claude_engram.hooks.scorer_server import embed_via_server
                        emb = embed_via_server(content)
                        if emb:
                            emb_file = memory_file.parent / "embeddings.json"
                            emb_data = {}
                            if emb_file.exists():
                                emb_data = json.loads(emb_file.read_text())
                            emb_data[entry_id] = emb
                            emb_tmp = emb_file.with_suffix(".json.tmp")
                            emb_tmp.write_text(json.dumps(emb_data))
                            emb_tmp.replace(emb_file)
                    except Exception:
                        pass

            # Reset error counter since we logged it
            state = load_state()
            state["errors_without_log"] = 0
            save_state(state)

            return mistake_type
        except Exception:
            pass  # Silent failure

    return ""


def reminder_for_error(project_dir: str, error_message: str = "") -> str:
    """Generate reminder when something fails."""
    state = load_state()
    state["errors_without_log"] = state.get("errors_without_log", 0) + 1
    errors = state["errors_without_log"]
    save_state(state)

    lines = ["<engram-error-reminder>"]
    if errors >= 3:
        lines.append(f"{errors} errors without logging. Consider:")
        lines.append("  work(operation='log_mistake', description='...', how_to_avoid='...')")
    else:
        lines.append("Log recurring errors with work(log_mistake) to get warned next time")
    lines.append("</engram-error-reminder>")
    return "\n".join(lines)


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    hook_type = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    project_dir = get_project_dir()

    if hook_type == "prompt":
        prompt_text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(reminder_for_prompt(project_dir, prompt_text))

    elif hook_type == "edit":
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        result = reminder_for_edit(project_dir, file_path)
        if result:
            print(result)

    elif hook_type == "post_edit":
        # NEW: Auto-record edit after it completes
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        if file_path:
            _auto_record_edit(file_path, "auto-tracked")
        # Silent - no output

    elif hook_type == "write":
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        content = _read_stdin_with_timeout(0.5)  # Use timeout to avoid blocking
        result = reminder_for_write(project_dir, file_path, content)
        if result:
            print(result)

    elif hook_type == "post_write":
        # NEW: Auto-record write after it completes
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        if file_path:
            _auto_record_edit(file_path, "auto-tracked")
        # Silent - no output

    elif hook_type == "bash":
        command = sys.argv[2] if len(sys.argv) > 2 else ""
        exit_code = sys.argv[3] if len(sys.argv) > 3 else ""
        result = reminder_for_bash(project_dir, command, exit_code)
        if result:
            print(result)

    elif hook_type == "bash_json":
        # PostToolUse hooks need to output JSON with additionalContext to show in conversation
        # NOTE: This only fires for SUCCESSFUL commands. Failed commands (exit != 0) don't trigger
        # PostToolUse hooks. See: https://github.com/anthropics/claude-code/issues/6371
        import json as json_module
        try:
            # Cross-platform stdin reading with timeout
            stdin_data = _read_stdin_with_timeout(0.5)
            if stdin_data:
                data = json_module.loads(stdin_data)
                command = data.get("tool_input", {}).get("command", "")
                # tool_response is an object with stdout/stderr fields
                tool_response = data.get("tool_response", {})
                if isinstance(tool_response, dict):
                    stdout = tool_response.get("stdout", "")
                    stderr = tool_response.get("stderr", "")
                    response = f"{stdout}\n{stderr}".strip()
                else:
                    response = str(tool_response)

                # SEARCH SPIRAL DETECTION: Track failed search commands
                if detect_search_failure_in_output(command, response):
                    record_search_failure(command[:50])
                else:
                    # Check if first word is a search command (success resets spiral)
                    import re as _re2
                    first_word = _re2.split(r'\s+', command.lower().strip())[0] if command else ""
                    if first_word in ["ls", "dir", "find", "locate", "where", "which"]:
                        record_search_success()

                # Reset loop detector on git commit (edit cycle completed)
                if command and "git commit" in command:
                    try:
                        loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
                        if loop_file.exists():
                            ld = json.loads(loop_file.read_text())
                            ld["file_edit_counts"] = {}
                            ld["edit_counts"] = {}
                            ld["total_edits"] = 0
                            loop_file.write_text(json.dumps(ld, indent=2))
                    except Exception:
                        pass

                # This handler only fires for successful commands (exit 0).
                # Don't manufacture fake errors from output content.
                result = reminder_for_bash(project_dir, command, "0", output=response)

                # Add search spiral suggestion if in spiral
                spiral_suggestion = get_search_spiral_suggestion(project_dir)
                if spiral_suggestion:
                    result = (result + "\n" + spiral_suggestion) if result else spiral_suggestion

                if result:
                    # Output JSON format for PostToolUse to add context to Claude
                    hook_output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": result
                        }
                    }
                    print(json_module.dumps(hook_output))
        except Exception:
            pass  # Silent failure

    elif hook_type == "post_edit_json":
        # PostToolUse hook for Edit/Write - auto-record edit and show confirmation
        import json as json_module
        try:
            # Cross-platform stdin reading with timeout
            stdin_data = _read_stdin_with_timeout(0.5)
            if stdin_data:
                data = json_module.loads(stdin_data)
                file_path = data.get("tool_input", {}).get("file_path", "")
                # Resolve sub-project from the file
                if file_path:
                    project_dir = get_project_dir(file_path)

                if file_path:
                    # AUTO-RECORD the edit
                    _auto_record_edit(file_path, "auto-tracked")

                    # Track in files_edited_this_session AND last_session_files
                    # Saving last_session_files continuously means session_end is optional
                    state = load_state()
                    files_edited = state.get("files_edited_this_session", [])
                    if file_path not in files_edited:
                        files_edited.append(file_path)
                        # Keep last 50 files
                        state["files_edited_this_session"] = files_edited[-50:]
                        # Also save as last_session_files so it persists without session_end
                        state["last_session_files"] = files_edited[-50:]
                        save_state(state)

                    # Get edit count for this file
                    loop_file = Path.home() / ".claude_engram" / "loop_detector.json"
                    edit_count = 1
                    if loop_file.exists():
                        try:
                            loop_data = json_module.loads(loop_file.read_text())
                            edit_count = loop_data.get("edit_counts", {}).get(file_path, 1)
                        except Exception:
                            pass

                    # Show confirmation
                    file_name = Path(file_path).name
                    result = f"<engram-edit-tracked>Edit tracked: {file_name} (edit #{edit_count})</engram-edit-tracked>"

                    # Output JSON format for PostToolUse
                    hook_output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": result
                        }
                    }
                    print(json_module.dumps(hook_output))
        except Exception:
            pass  # Silent failure

    # ==================================================================
    # PostToolUseFailure for ALL tools - catches any failed tool call
    # Gets: {tool_name, tool_input, error, is_interrupt, tool_use_id}
    # ==================================================================
    elif hook_type in ("tool_failure_json", "bash_failure_json"):
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            if stdin_data:
                data = json_module.loads(stdin_data)
                tool_name = data.get("tool_name", "")
                tool_input = data.get("tool_input", {})
                error_msg = data.get("error", "")
                is_interrupt = data.get("is_interrupt", False)

                # Resolve sub-project from file_path if available
                if isinstance(tool_input, dict):
                    fp = tool_input.get("file_path", "")
                    if fp:
                        project_dir = get_project_dir(fp)

                # Don't log user interrupts as mistakes
                if is_interrupt:
                    pass  # Silent
                else:
                    lines = []

                    if tool_name == "Bash":
                        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

                        # Auto-log mistake from error output
                        if error_msg:
                            logged = _auto_log_detected_mistake(project_dir, command, error_msg)
                            if logged:
                                lines.append(f"Auto-logged: {logged}")

                        # Auto-record failed test
                        if command:
                            first_cmd = re.split(r'&&|\|\||;', command.lower().strip())[0].strip()
                            test_commands = ['pytest', 'jest', 'mocha', 'npm test', 'yarn test',
                                             'make test', 'cargo test', 'go test', 'python -m pytest',
                                             'python -m unittest']
                            if any(first_cmd.startswith(c) for c in test_commands):
                                _auto_record_test(False, error_msg[:200])
                                lines.append("FAIL Test tracked")

                    elif tool_name in ("Edit", "Write"):
                        file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
                        if file_path and error_msg:
                            file_name = Path(file_path).name
                            # Auto-log edit failure with file context
                            _auto_log_detected_mistake(
                                project_dir, f"edit {file_name}",
                                f"Edit failed on {file_name}: {error_msg[:200]}"
                            )
                            lines.append(f"Edit failure on {file_name} tracked")

                    elif tool_name == "Read" and error_msg:
                        # Track file-not-found patterns
                        file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
                        if "not found" in error_msg.lower() or "no such file" in error_msg.lower():
                            record_search_failure(file_path[:50])

                    # Track error counter
                    state = load_state()
                    state["errors_without_log"] = state.get("errors_without_log", 0) + 1
                    save_state(state)

                    if not lines:
                        lines.append(f"{tool_name} failed. Log with work(log_mistake) to track.")

                    result = "\n".join(lines)
                    hook_output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUseFailure",
                            "additionalContext": f"<engram-error>{result}</engram-error>"
                        }
                    }
                    print(json_module.dumps(hook_output))
        except Exception:
            pass

    # ==================================================================
    # NEW: PreCompact - auto-save checkpoint before context compaction
    # ==================================================================
    elif hook_type == "pre_compact_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            trigger = "auto"
            if stdin_data:
                data = json_module.loads(stdin_data)
                trigger = data.get("trigger", "auto")

            # Auto-save checkpoint with current session state
            state = load_state()
            files_edited = state.get("files_edited_this_session", [])

            checkpoint_dir = Path.home() / ".claude_engram" / "checkpoints"
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            checkpoint = {
                "task_id": f"auto_compact_{int(time.time())}",
                "task_description": f"Auto-saved before {trigger} compaction",
                "current_step": "Context was compacted",
                "completed_steps": [],
                "pending_steps": ["Restore context with session_start"],
                "files_involved": files_edited[:10],
                "key_decisions": [],
                "blockers": [],
                "timestamp": time.time(),
                "metadata": {"project_path": project_dir, "trigger": trigger},
                "handoff_summary": f"Context compacted ({trigger}). {len(files_edited)} files were being edited.",
                "handoff_context_needed": [],
                "handoff_warnings": ["Context was compacted - call session_start to restore memories"],
            }

            # Save as latest checkpoint
            latest = checkpoint_dir / "latest_checkpoint.json"
            temp = latest.with_suffix(".json.tmp")
            temp.write_text(json_module.dumps(checkpoint, indent=2))
            temp.replace(latest)
            # PreCompact has no hookSpecificOutput in Claude Code's schema
            # The value is the checkpoint file saved above
        except Exception:
            pass

    # ==================================================================
    # NEW: PostCompact - inject restore reminder into compacted context
    # ==================================================================
    elif hook_type == "post_compact_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            summary = ""
            if stdin_data:
                data = json_module.loads(stdin_data)
                summary = data.get("compact_summary", "")

            # Load rules and mistakes to re-inject after compaction
            project_memory = load_project_memory(project_dir)
            rules = get_project_rules(project_memory)
            mistakes = get_past_mistakes(project_memory)

            lines = []
            lines.append("MINI CLAUDE: Context was compacted. Call session_start to restore full context.")
            if rules:
                lines.append(f"Rules ({len(rules)}):")
                for r in rules[:3]:
                    lines.append(f"  [{r['id']}] {_truncate(r['content'], 100)}")
            if mistakes:
                lines.append(f"Past mistakes ({len(mistakes)}):")
                for m in mistakes[:3]:
                    lines.append(f"  [{m['id']}] {_truncate(m['content'], 80)}")

            # PostCompact has no hookSpecificOutput in Claude Code's schema.
            # Print as plain stdout — Claude Code shows this as hook output.
            print("\n".join(lines))
        except Exception:
            pass

    # ==================================================================
    # NEW: SessionStart hook - native session tracking (replaces marker files)
    # ==================================================================
    elif hook_type == "session_start_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            source = "startup"
            if stdin_data:
                data = json_module.loads(stdin_data)
                source = data.get("source", "startup")

            # Auto-start claude_engram session
            mark_session_started(project_dir)

            # Start persistent scorer server in background (if sentence-transformers available)
            try:
                from claude_engram.hooks.scorer_server import start_server_background
                start_server_background()  # Non-blocking, returns immediately if already running
            except Exception:
                pass  # sentence-transformers not installed — regex fallback will be used

            lines = []
            lines.append(f"Claude Engram session started ({source})")

            # Load and show key context
            project_memory = load_project_memory(project_dir)
            rules = get_project_rules(project_memory)
            mistakes = get_past_mistakes(project_memory)

            if rules:
                lines.append(f"Rules ({len(rules)}):")
                for r in rules[:5]:
                    lines.append(f"  [{r['id']}] {_truncate(r['content'], 120)}")
            if mistakes:
                lines.append(f"Past mistakes ({len(mistakes)}):")
                for m in mistakes[:5]:
                    lines.append(f"  [{m['id']}] {_truncate(m['content'], 100)}")

            _append_memory_summary(lines, project_memory, project_dir)

            # Check for checkpoint/handoff to restore
            checkpoint = get_checkpoint_data()
            handoff = get_handoff_data()
            if checkpoint:
                age_hours = (time.time() - checkpoint.get("timestamp", 0)) / 3600
                lines.append(f"CHECKPOINT ({age_hours:.1f}h ago): {_truncate(checkpoint.get('task_description', '?'), 80)}")
            if handoff:
                lines.append(f"HANDOFF: {_truncate(handoff.get('summary', '?'), 100)}")

            # Session mining: show last session context (read-only, no building)
            try:
                from claude_engram.mining.session_index import get_or_create_index
                from pathlib import Path as _Path
                import hashlib as _hashlib

                # Resolve project hash dir (same logic as MemoryStore)
                _norm = str(_Path(project_dir).resolve()).replace("\\", "/")
                if len(_norm) >= 2 and _norm[1] == ":":
                    _norm = _norm[0].lower() + _norm[1:]
                _storage = _Path("~/.claude_engram").expanduser()
                _manifest_path = _storage / "manifest.json"
                _hash_dir = None
                if _manifest_path.exists():
                    _manifest = json_module.loads(_manifest_path.read_text())
                    _proj_info = _manifest.get("projects", {}).get(_norm)
                    if _proj_info:
                        _hash_dir = _storage / "projects" / _proj_info["hash"]

                if _hash_dir and (_hash_dir / "session_index.json").exists():
                    index = get_or_create_index(_hash_dir)
                else:
                    index = None

                    # Bootstrap: no index yet, but session JSONLs may exist
                    if _hash_dir:
                        try:
                            from claude_engram.mining.jsonl_reader import resolve_jsonl_dir
                            _jsonl_dir = resolve_jsonl_dir(project_dir)
                            if _jsonl_dir and any(_jsonl_dir.glob("*.jsonl")):
                                from claude_engram.mining.background import start_mining_background, is_mining_running
                                if not is_mining_running():
                                    start_mining_background(project_dir, mode="bootstrap")
                                    lines.append("Session mining: bootstrapping from history (background)...")
                        except Exception:
                            pass

                if index and index.get_session_count() > 0:
                    summary = index.get_latest_session_summary()
                    if summary and summary.get("file_count", 0) > 0:
                        age = summary.get("age_str", "")
                        branch = summary.get("branch", "")
                        header = f"Last session"
                        if age:
                            header += f" ({age}"
                            if branch:
                                header += f", branch: {branch}"
                            header += ")"
                        lines.append(header + ":")
                        files = summary.get("files_edited", [])
                        if files:
                            lines.append(f"  Worked on: {', '.join(files[:8])}")
                            if summary["file_count"] > 8:
                                lines.append(f"  ...and {summary['file_count'] - 8} more files")
                        errs = summary.get("error_count", 0)
                        msgs = summary.get("user_message_count", 0)
                        if errs or msgs:
                            parts = []
                            if msgs:
                                parts.append(f"{msgs} prompts")
                            if errs:
                                parts.append(f"{errs} errors")
                            lines.append(f"  Activity: {', '.join(parts)}")

                    # Auto-inject patterns if available
                    patterns_path = _hash_dir / "patterns.json"
                    if patterns_path.exists():
                        try:
                            pdata = json_module.loads(patterns_path.read_text())
                            struggles = pdata.get("struggles", [])[:3]
                            recurring = pdata.get("recurring_errors", [])[:3]
                            if struggles:
                                lines.append("Recurring struggles:")
                                for s in struggles:
                                    lines.append(f"  - {s['file_path']} ({s['sessions_affected']} sessions, {s['errors_nearby']} errors)")
                            if recurring:
                                lines.append("Recurring errors:")
                                for e in recurring:
                                    lines.append(f"  - {e['error_type']} ({e['session_count']} sessions)")
                        except Exception:
                            pass
            except Exception:
                pass  # Mining not available or no sessions — skip silently

            hook_output = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(lines)
                }
            }
            print(json_module.dumps(hook_output))
        except Exception:
            pass

    # ==================================================================
    # prompt_json - reads stdin JSON, auto-captures decisions from user
    # ==================================================================
    elif hook_type == "prompt_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            prompt_text = ""
            if stdin_data:
                data = json_module.loads(stdin_data)
                prompt_text = data.get("prompt", "")

            # Resolve project from recently edited files (not just cwd)
            state = load_state()
            recent_files = state.get("files_edited_this_session", []) or state.get("last_session_files", [])
            if recent_files:
                project_dir = get_project_dir(recent_files[-1])

            # Auto-capture decisions from user prompts
            if prompt_text and len(prompt_text) > 20:
                _auto_capture_from_prompt(project_dir, prompt_text)

            result = reminder_for_prompt(project_dir, prompt_text)
            if result:
                hook_output = {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": result
                    }
                }
                print(json_module.dumps(hook_output))
        except Exception:
            pass

    # ==================================================================
    # Stop hook - auto-save what Claude was doing when session stops
    # Gets: {last_assistant_message, stop_hook_active}
    # ==================================================================
    elif hook_type == "stop_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            if stdin_data:
                data = json_module.loads(stdin_data)
                last_message = data.get("last_assistant_message", "")

                # Auto-save session state
                state = load_state()
                files_edited = state.get("files_edited_this_session", [])

                if files_edited or last_message:
                    # Save a lightweight handoff for next session
                    checkpoint_dir = Path.home() / ".claude_engram" / "checkpoints"
                    checkpoint_dir.mkdir(parents=True, exist_ok=True)

                    handoff = {
                        "created": time.time(),
                        "summary": f"Session stopped. {len(files_edited)} files edited.",
                        "next_steps": ["Review what was in progress"],
                        "context_needed": [],
                        "warnings": [],
                        "project_path": project_dir,
                        "last_message_preview": last_message[:300] if last_message else "",
                        "files_in_progress": files_edited[:10],
                    }

                    handoff_file = checkpoint_dir / "latest_handoff.json"
                    temp = handoff_file.with_suffix(".json.tmp")
                    temp.write_text(json_module.dumps(handoff, indent=2))
                    temp.replace(handoff_file)

                # Also persist session files for next session context
                mark_session_ended()
        except Exception:
            pass

    # ==================================================================
    # SessionEnd hook - clean teardown, save state, output summary
    # Gets: {reason: 'clear'|'resume'|'logout'|'prompt_input_exit'|'other'}
    # ==================================================================
    elif hook_type == "session_end_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            reason = "other"
            if stdin_data:
                data = json_module.loads(stdin_data)
                reason = data.get("reason", "other")

            # Gather session summary before clearing state
            state = load_state()
            files_edited = state.get("files_edited_this_session", [])

            mark_session_ended()

            # Build summary
            lines = [f"Claude Engram session ended ({reason})."]
            if files_edited:
                lines.append(f"Files edited: {len(files_edited)}")
                for f in files_edited[:5]:
                    lines.append(f"  - {Path(f).name}")

            # Count memories created this session
            project_memory = load_project_memory(project_dir)
            counts = get_memory_counts(project_memory)
            if counts.get("total", 0) > 0:
                lines.append(f"Memories: {counts['total']} total ({counts.get('mistake', 0)} mistakes, {counts.get('rule', 0)} rules)")

            # Spawn background session miner (fire-and-forget, ~50ms)
            try:
                from claude_engram.mining.background import start_mining_background
                start_mining_background(project_dir, mode="post_session")
            except Exception:
                pass  # Mining not available — skip silently
        except Exception:
            # Even if summary fails, make sure session state is saved
            try:
                mark_session_ended()
            except Exception:
                pass

    # ==================================================================
    # pre_edit_json - reads stdin JSON for PreToolUse Edit/Write
    # ==================================================================
    elif hook_type == "pre_edit_json":
        import json as json_module
        try:
            stdin_data = _read_stdin_with_timeout(0.5)
            file_path = ""
            if stdin_data:
                data = json_module.loads(stdin_data)
                file_path = data.get("tool_input", {}).get("file_path", "")

            # Resolve sub-project from the file being edited
            if file_path:
                project_dir = get_project_dir(file_path)
                result = reminder_for_edit(project_dir, file_path)

                # Add predictive context from session mining (reads JSON, fast)
                try:
                    from claude_engram.mining.predictive import predict_for_file, format_prediction
                    pred = predict_for_file(file_path, project_dir)
                    pred_text = format_prediction(pred)
                    if pred_text:
                        result = (result or "") + "\n" + pred_text
                except Exception:
                    pass

                if result:
                    hook_output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "additionalContext": result
                        }
                    }
                    print(json_module.dumps(hook_output))
        except Exception:
            pass

    elif hook_type == "error":
        error_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        print(reminder_for_error(project_dir, error_msg))

    # Legacy tool callback hooks - called by handlers when Claude Engram tools are used
    elif hook_type == "session_started":
        mark_session_started(project_dir)

    elif hook_type == "pre_edit_checked":
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        mark_pre_edit_check_done(file_path)

    elif hook_type == "loop_recorded":
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        mark_loop_record_done(file_path)

    elif hook_type == "scope_declared":
        mark_scope_declared()

    elif hook_type == "test_recorded":
        mark_test_recorded()

    elif hook_type == "mistake_logged":
        mark_mistake_logged()

    # Legacy argv-based handlers (kept for backward compat)
    elif hook_type == "prompt":
        prompt_text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(reminder_for_prompt(project_dir, prompt_text))

    elif hook_type == "edit":
        file_path = sys.argv[2] if len(sys.argv) > 2 else ""
        result = reminder_for_edit(project_dir, file_path)
        if result:
            print(result)

    else:
        pass  # Unknown hook type - silent


if __name__ == "__main__":
    main()

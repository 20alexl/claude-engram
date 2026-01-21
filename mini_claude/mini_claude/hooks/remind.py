#!/usr/bin/env python3
"""
Mini Claude Enforcement Hook - AUTOMATIC TOOL INJECTION

NEW APPROACH (Round 3):
Instead of REMINDING Claude to use tools, we AUTOMATICALLY use them.

Auto-injection:
1. Before edit → Auto-run work_pre_edit_check, show results
2. After edit → Auto-record loop_record_edit
3. On error → Auto-log work_log_mistake
4. Results show IMMEDIATE value (not just future benefit)

The goal: Remove friction, add immediate value, make tools invisible but always-on.
"""

import sys
import os
import json
import time
import re
from pathlib import Path

# Import habit tracker for smart suggestions
try:
    from ..tools.habit_tracker import suggest_tool_for_context, get_habit_feedback, record_risky_edit_without_thinking
except ImportError:
    # Fallback if habit tracker not available
    def suggest_tool_for_context(context, risk_reason=""):
        return ("think_explore", "Explore solution space before coding")
    def get_habit_feedback():
        return ""
    def record_risky_edit_without_thinking(file_path, risk_reason):
        pass


# ============================================================================
# State Tracking - Track EVERYTHING Claude does and doesn't do
# ============================================================================

def get_state_file() -> Path:
    """Get the hook state file path."""
    return Path.home() / ".mini_claude" / "hook_state.json"


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
        "edits_without_session": 0,
        "edits_without_pre_check": 0,
        "edits_without_loop_record": 0,
        "tests_without_record": 0,
        "errors_without_log": 0,
        "last_session_start": None,
        "last_pre_edit_check": None,
        "last_loop_record": None,
        "last_scope_declare": None,
        "last_test_record": None,
        "last_mistake_log": None,
        "files_edited_this_session": [],
        "ignored_warnings": 0,
        "active_project": "",
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
    state["edits_without_session"] = 0
    state["last_session_start"] = time.time()
    state["active_project"] = project_dir
    state["files_edited_this_session"] = []
    _increment_tool_usage(state, "session_start")
    save_state(state)

    # Also create the marker file
    marker = Path("/tmp/mini_claude_session_active")
    try:
        marker.write_text(project_dir)
    except Exception:
        pass


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
    """Record that a file was edited."""
    state = load_state()
    files = state.get("files_edited_this_session", [])
    if file_path not in files:
        files.append(file_path)
    state["files_edited_this_session"] = files[-50:]  # Keep last 50
    save_state(state)


def get_underused_tools() -> list[str]:
    """Get suggestions for underused tools based on usage patterns."""
    state = load_state()
    usage = state.get("tool_usage", {})
    suggestions = []

    # Key tools that should be used often
    key_tools = {
        "work_log_mistake": "Log mistakes to avoid repeating them",
        "work_log_decision": "Log decisions so future sessions know why",
        "work_pre_edit_check": "Check for past mistakes before editing",
        "loop_record_edit": "Track edits to detect loops",
        "scope_declare": "Declare scope to prevent over-refactoring",
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

def get_project_dir() -> str:
    """Get the current project directory."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        return project_dir
    return os.getcwd()


def get_memory_file() -> Path:
    """Get the Mini Claude memory file path."""
    return Path.home() / ".mini_claude" / "memory.json"


def load_project_memory(project_dir: str) -> dict:
    """Load memories for a specific project."""
    memory_file = get_memory_file()
    if not memory_file.exists():
        return {}

    try:
        data = json.loads(memory_file.read_text())
        projects = data.get("projects", {})

        if project_dir in projects:
            return projects[project_dir]

        project_name = Path(project_dir).name
        for path, proj in projects.items():
            if Path(path).name == project_name:
                return proj

        return {}
    except Exception:
        return {}


def get_past_mistakes(project_memory: dict) -> list[str]:
    """Extract past mistakes from project memory."""
    mistakes = []
    entries = project_memory.get("entries", [])

    for entry in entries:
        content = entry.get("content", "")
        if content.upper().startswith("MISTAKE:"):
            mistake_text = content[9:] if content.startswith("MISTAKE: ") else content[8:]
            mistakes.append(mistake_text)

    return mistakes


def check_session_active(project_dir: str) -> bool:
    """Check if a Mini Claude session is active."""
    state = load_state()

    # Check if session was started recently (within 4 hours)
    last_start = state.get("last_session_start")
    if last_start and (time.time() - last_start) < 14400:  # 4 hours
        active_project = state.get("active_project", "")
        if active_project == project_dir or Path(active_project).name == Path(project_dir).name:
            return True

    # Fallback to marker file
    marker = Path("/tmp/mini_claude_session_active")
    if marker.exists():
        try:
            active_project = marker.read_text().strip()
            return active_project == project_dir or Path(active_project).name == Path(project_dir).name
        except Exception:
            pass
    return False


def get_loop_status() -> dict:
    """Get loop detection status."""
    loop_file = Path.home() / ".mini_claude" / "loop_detector.json"
    if not loop_file.exists():
        return {}
    try:
        return json.loads(loop_file.read_text())
    except Exception:
        return {}


def get_scope_status() -> dict:
    """Get scope guard status."""
    scope_file = Path.home() / ".mini_claude" / "scope_guard.json"
    if not scope_file.exists():
        return {}
    try:
        return json.loads(scope_file.read_text())
    except Exception:
        return {}


def get_checkpoint_data() -> dict:
    """Load the latest checkpoint data if it exists."""
    checkpoint_file = Path.home() / ".mini_claude" / "checkpoints" / "latest_checkpoint.json"
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
    handoff_file = Path.home() / ".mini_claude" / "checkpoints" / "latest_handoff.json"
    if not handoff_file.exists():
        return {}
    try:
        data = json.loads(handoff_file.read_text())
        # Check age - only return if less than 48 hours old
        age_hours = (time.time() - data.get("created_at", 0)) / 3600
        if age_hours < 48:
            return data
        return {}
    except Exception:
        return {}


# ============================================================================
# THINKING TOOL ENFORCEMENT - 3-Tier Progressive System
# ============================================================================

def detect_complex_task(prompt: str) -> tuple[bool, str, int]:
    """
    Detect if prompt indicates a complex task requiring Thinker tools.

    Returns:
        (is_complex, detected_pattern, tier_level)
        tier_level: 1 = suggestion, 2 = strong warning, 3 = blocking
    """
    prompt_lower = prompt.lower()

    # Tier 2: Strong warning keywords (architectural/design work)
    tier2_keywords = [
        "implement", "add feature", "refactor", "architecture",
        "design", "build new", "create system", "integrate",
        "authentication", "authorization", "payment", "security"
    ]

    for keyword in tier2_keywords:
        if keyword in prompt_lower:
            return (True, keyword, 2)

    # Tier 1: Gentle suggestion keywords (moderate complexity)
    tier1_keywords = [
        "add", "create", "modify", "update", "change",
        "improve", "optimize", "enhance"
    ]

    for keyword in tier1_keywords:
        if keyword in prompt_lower:
            # Check for complexity indicators
            if len(prompt.split()) > 15:  # Long prompt = complex
                return (True, keyword, 1)
            if "multiple" in prompt_lower or "several" in prompt_lower:
                return (True, keyword, 1)

    return (False, "", 0)


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


def check_risky_file(file_path: str) -> tuple[bool, str, int]:
    """
    Check if file is high-risk (core infrastructure).

    Returns:
        (is_risky, reason, tier_level)
        tier_level: 1 = warn, 2 = strong warn, 3 = BLOCK
    """
    if not file_path:
        return (False, "", 0)

    filename = Path(file_path).name.lower()
    parent = Path(file_path).parent.name.lower()

    # Tier 3: BLOCKING - Security-critical files (must use Thinker)
    tier3_patterns = {
        "auth": "authentication/authorization",
        "login": "authentication",
        "password": "security-sensitive",
        "security": "security-critical",
        "payment": "payment processing",
        "billing": "billing logic",
    }

    for pattern, reason in tier3_patterns.items():
        if pattern in filename or pattern in parent:
            return (True, reason, 3)

    # Tier 2: Strong warning - Important files (should use Thinker)
    tier2_patterns = {
        "config": "configuration",
        "settings": "configuration",
        "database": "data layer",
        "db": "data layer",
        "migration": "database schema",
        "schema": "database schema",
    }

    for pattern, reason in tier2_patterns.items():
        if pattern in filename or pattern in parent:
            return (True, reason, 2)

    return (False, "", 0)


def check_recent_thinker_usage(minutes: int = 5) -> tuple[bool, str]:
    """
    Check if any Thinker tool was used recently.

    Returns:
        (used_recently, last_tool_used)
    """
    try:
        from ..tools.habit_tracker import get_recent_thinker_usage

        # Check if any Thinker tool was used in last N minutes
        recent = get_recent_thinker_usage("", limit=10)
        if recent:
            import time
            from datetime import datetime

            for event in recent:
                timestamp = datetime.fromisoformat(event["timestamp"])
                age_seconds = time.time() - timestamp.timestamp()

                if age_seconds < (minutes * 60):
                    tool = event.get("tool_used", "unknown")
                    return (True, tool)

        return (False, "")
    except Exception:
        # If habit tracker not available, assume not used
        return (False, "")


# ============================================================================
# AUTO-INJECTION - Automatically call Mini Claude tools
# ============================================================================

def _auto_run_pre_edit_check(project_dir: str, file_path: str) -> dict:
    """
    Automatically run work_pre_edit_check and return results.

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

    # Find mistakes related to this file
    for mistake in all_mistakes:
        if file_name.lower() in mistake.lower():
            results["past_mistakes"].append(mistake)

    # Check loop detector
    loop_status = get_loop_status()
    edits = loop_status.get("edit_counts", {})
    edit_count = edits.get(file_path, 0) or edits.get(file_name, 0)

    if edit_count >= 3:
        results["loop_warnings"].append(f"⚠️ Edited {edit_count} times - try different approach")
    elif edit_count >= 2:
        results["loop_warnings"].append(f"Edited {edit_count} times - ensure this is different")

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
            results["scope_warnings"].append(f"⚠️ {file_name} NOT in scope for: {task[:50]}")

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
                    results["suggestions"].append(f"📝 {len(todos)} TODO/FIXME in file: {', '.join(todos[:2])}")
            except Exception:
                pass

        # 2. Check recent git commits for this file
        try:
            import subprocess
            git_result = subprocess.run(
                ['git', '-C', str(file_obj.parent), 'log', '--oneline', '-n', '3', '--', file_name],
                capture_output=True,
                text=True,
                timeout=2
            )
            if git_result.returncode == 0 and git_result.stdout:
                commits = git_result.stdout.strip().split('\n')[:2]
                if commits:
                    results["suggestions"].append(f"🔍 Recent commits: {'; '.join(c[:50] for c in commits)}")
        except Exception:
            pass

        # 3. Check for common patterns that need attention
        if file_obj.exists() and file_obj.is_file():
            try:
                content = file_obj.read_text()
                # Check for error handling patterns
                if 'except:' in content or 'except :' in content:
                    results["suggestions"].append("⚠️ Bare except clauses found - consider specific exceptions")
                # Check for print debugging
                if content.count('print(') > 5:
                    results["suggestions"].append("🐛 Multiple print() statements - consider using logging")
                # Check file size
                lines = content.count('\n')
                if lines > 500:
                    results["suggestions"].append(f"📏 Large file ({lines} lines) - consider refactoring")
            except Exception:
                pass

        # 4. Context-aware suggestions
        if "test" in file_name.lower():
            results["suggestions"].append("💡 Run tests after editing to verify changes")
        if "handler" in file_name.lower() or "server" in file_name.lower():
            results["suggestions"].append("💡 Restart server to apply changes")
        if edit_count >= 2:
            results["suggestions"].append("💡 Consider reviewing logs/errors before editing again")

    except Exception:
        # Fallback to basic suggestions if rich context fails
        if "test" in file_name.lower():
            results["suggestions"].append("💡 Run tests after editing")
        if edit_count >= 2:
            results["suggestions"].append("💡 Edited multiple times - review approach")

    # Mark that we ran the check
    state = load_state()
    state["last_pre_edit_check"] = time.time()
    state["last_pre_edit_file"] = file_path
    _increment_tool_usage(state, "work_pre_edit_check")
    save_state(state)

    return results


def _auto_record_edit(file_path: str, description: str = "auto-tracked"):
    """
    Automatically record an edit in loop detector.
    Called post-edit to track changes invisibly.
    """
    loop_file = Path.home() / ".mini_claude" / "loop_detector.json"
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


# ============================================================================
# ENFORCEMENT - Make Mini Claude usage mandatory
# ============================================================================

def reminder_for_prompt(project_dir: str, prompt: str = "") -> str:
    """
    Generate reminder for UserPromptSubmit hook.

    Enforces:
    1. session_start must be called
    2. Shows past mistakes to avoid
    3. Reminds about ALL tools to use
    4. Tier 2 warnings for complex/architectural tasks
    """
    state = load_state()
    session_active = check_session_active(project_dir)
    project_memory = load_project_memory(project_dir)

    lines = ["<mini-claude-reminder>"]

    # TIER 2 ENFORCEMENT: Strong warning for architectural/complex tasks with SMART SUGGESTIONS
    if prompt:
        is_complex, detected_pattern, tier = detect_complex_task(prompt)
        if tier == 2:
            # Get smart tool suggestion based on context
            suggested_tool, tool_reason = suggest_tool_for_context(prompt, detected_pattern)

            lines.append("⚠️" * 15)
            lines.append("")
            lines.append(f"ARCHITECTURAL TASK DETECTED: '{detected_pattern}'")
            lines.append("")
            lines.append("This appears to be high-impact work. Before coding:")
            lines.append("  - Multiple approaches exist")
            lines.append("  - Wrong choice = expensive refactor later")
            lines.append("  - Security/correctness critical")
            lines.append("")
            lines.append(f"⚠️ RECOMMENDED: Start with {suggested_tool}")
            lines.append(f"   WHY: {tool_reason}")
            lines.append("")
            lines.append("Other tools you might need:")
            # Show other tools but de-emphasize them
            other_tools = ["think_explore", "think_compare", "think_best_practice", "think_challenge"]
            if suggested_tool in other_tools:
                other_tools.remove(suggested_tool)
            for tool in other_tools[:2]:  # Show top 2 alternatives
                lines.append(f"  • {tool}")
            lines.append("")
            lines.append("Think first, code later. Mistakes cost 2-10x to fix:")
            lines.append("  • Wrong approach = wasted days of work")
            lines.append("  • Missing requirements = rebuild from scratch")
            lines.append("  • Bad architecture = months of refactoring")
            lines.append("")
            lines.append("⚠️" * 15)
            lines.append("")

    if not session_active:
        # Track ignored prompts
        state["prompts_without_session"] = state.get("prompts_without_session", 0) + 1
        prompts = state["prompts_without_session"]
        save_state(state)

        # AUTO-LOAD CHECKPOINT/HANDOFF - Show context even without session_start!
        # This is the key to surviving context compaction
        checkpoint = get_checkpoint_data()
        handoff = get_handoff_data()

        if checkpoint or handoff:
            lines.append("🔄" * 20)
            lines.append("")
            lines.append("📋 CONTEXT RESTORED FROM PREVIOUS SESSION")
            lines.append("   (You don't need to call session_start to see this)")
            lines.append("")

            if checkpoint:
                age_hours = (time.time() - checkpoint.get("timestamp", 0)) / 3600
                lines.append(f"CHECKPOINT ({age_hours:.1f}h ago):")
                lines.append(f"  Task: {checkpoint.get('task_description', 'Unknown')[:80]}")
                lines.append(f"  Current step: {checkpoint.get('current_step', 'Unknown')[:60]}")
                if checkpoint.get("completed_steps"):
                    lines.append(f"  ✓ Completed: {len(checkpoint['completed_steps'])} steps")
                    for step in checkpoint["completed_steps"][-3:]:
                        lines.append(f"    • {step[:60]}")
                if checkpoint.get("pending_steps"):
                    lines.append(f"  ⏳ Pending: {len(checkpoint['pending_steps'])} steps")
                    for step in checkpoint["pending_steps"][:3]:
                        lines.append(f"    • {step[:60]}")
                if checkpoint.get("files_involved"):
                    lines.append(f"  📁 Files: {', '.join(Path(f).name for f in checkpoint['files_involved'][:5])}")
                if checkpoint.get("key_decisions"):
                    lines.append("  🎯 Key decisions:")
                    for dec in checkpoint["key_decisions"][:2]:
                        lines.append(f"    • {dec[:60]}")
                lines.append("")

            if handoff:
                lines.append("HANDOFF MESSAGE:")
                lines.append(f"  {handoff.get('summary', 'No summary')[:100]}")
                if handoff.get("next_steps"):
                    lines.append("  Next steps:")
                    for step in handoff["next_steps"][:3]:
                        lines.append(f"    → {step[:60]}")
                if handoff.get("warnings"):
                    lines.append("  ⚠️ Warnings:")
                    for warn in handoff["warnings"][:2]:
                        lines.append(f"    • {warn[:60]}")
                lines.append("")

            lines.append("⚡ CONTINUE FROM WHERE YOU LEFT OFF!")
            lines.append("")
            lines.append("🔄" * 20)
            lines.append("")

        # ALWAYS show past mistakes first - this is the compelling reason to use Mini Claude
        mistakes = get_past_mistakes(project_memory)
        if mistakes:
            lines.append("🔴 PAST MISTAKES YOU WILL REPEAT WITHOUT SESSION:")
            for m in mistakes[-5:]:  # Show up to 5 most recent
                lines.append(f"  • {m[:100]}")
            lines.append("")

        # ESCALATE based on how many times ignored
        if prompts == 1:
            lines.append("⚠️ Mini Claude session not started!")
            lines.append(f'Run: mcp__mini-claude__session_start(project_path="{project_dir}")')
            lines.append("")
        elif prompts <= 3:
            lines.append(f"⚠️ Mini Claude session not started (prompt #{prompts})")
            lines.append(f'Run: mcp__mini-claude__session_start(project_path="{project_dir}")')
            lines.append("")
        elif prompts <= 5:
            lines.append("=" * 50)
            lines.append(f"🔴 SESSION NOT STARTED - PROMPT #{prompts}")
            lines.append("=" * 50)
            lines.append(f'RUN: mcp__mini-claude__session_start(project_path="{project_dir}")')
            lines.append("=" * 50)
            lines.append("")
        else:
            lines.append("🚨" * 15)
            lines.append(f"SESSION NOT STARTED - {prompts} PROMPTS IGNORED")
            lines.append(f'RUN: mcp__mini-claude__session_start(project_path="{project_dir}")')
            lines.append("🚨" * 15)
            lines.append("")
    else:
        # Session is active - show useful context + HABIT FEEDBACK
        mistakes = get_past_mistakes(project_memory)

        if mistakes:
            lines.append(f"⚠️ Past mistakes to avoid ({len(mistakes)}):")
            for m in mistakes[-3:]:
                lines.append(f"  - {m[:80]}")
            lines.append("")

        # Show habit feedback (gamification!)
        habit_feedback = get_habit_feedback()
        if habit_feedback:
            lines.append(habit_feedback)
            lines.append("")

        # Check if scope is declared - only suggest for 3+ files (avoid ceremony for small tasks)
        scope = get_scope_status()
        if not scope.get("has_scope"):
            files_edited = state.get("files_edited_this_session", [])
            if len(files_edited) >= 3:  # Changed from 2 to 3 - less ceremony for small tasks
                lines.append(f"💡 You've edited {len(files_edited)} files - consider declaring scope to prevent creep")
                lines.append("  Run: scope_declare(task_description='...', in_scope_files=[...])")
                lines.append("")

    # ALWAYS show the checklist
    lines.append("Mini Claude reminders:")
    lines.append("- BEFORE editing shared files: work_pre_edit_check(file_path)")
    lines.append("- AFTER editing: loop_record_edit(file_path, description)")
    lines.append("- WHEN something breaks: work_log_mistake(description, file_path)")
    lines.append("- WHEN making decisions: work_log_decision(decision, reason)")
    lines.append("- FOR multi-file tasks: scope_declare(task_description, in_scope_files)")
    lines.append("")

    # THINKING TOOLS - Tier 1 gentle reminder for complex tasks
    lines.append("💡 For complex tasks, consider THINKING FIRST:")
    lines.append("- think_compare: Compare multiple approaches with pros/cons")
    lines.append("- think_explore: Explore solution space before picking first idea")
    lines.append("- think_challenge: Challenge your assumptions")
    lines.append("- think_research: Deep research with web + codebase + LLM")
    lines.append("Remember: Mistakes cost 2x to fix later!")

    lines.append("</mini-claude-reminder>")
    return "\n".join(lines)


def reminder_for_edit(project_dir: str, file_path: str = "") -> str:
    """
    Generate reminder for PreToolUse hook (Edit/Write).

    NOW WITH AUTO-INJECTION:
    - Automatically calls work_pre_edit_check and shows results
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

    lines = ["<mini-claude-edit-reminder>"]
    has_content = False

    # AUTO-INJECTION: Run work_pre_edit_check automatically
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
            lines.append("🔴 AUTO-CHECK: Past mistakes with this file:")
            for m in auto_check_results["past_mistakes"][:3]:
                lines.append(f"  • {m[:80]}")
            lines.append("")
            has_content = True

        if auto_check_results["loop_warnings"]:
            lines.append("⚠️ AUTO-CHECK: Loop detection:")
            for w in auto_check_results["loop_warnings"]:
                lines.append(f"  • {w}")
            lines.append("")
            has_content = True

        if auto_check_results["scope_warnings"]:
            lines.append("⚠️ AUTO-CHECK: Scope warning:")
            for w in auto_check_results["scope_warnings"]:
                lines.append(f"  • {w}")
            lines.append("")
            has_content = True

        if auto_check_results["suggestions"]:
            lines.append("💡 AUTO-CHECK: Suggestions:")
            for s in auto_check_results["suggestions"]:
                lines.append(f"  • {s}")
            lines.append("")
            has_content = True

    # TIER 3 ENFORCEMENT: BLOCKING on loop detection
    is_loop, loop_count = check_loop_detected(file_path)
    if is_loop:
        lines.append("🛑" * 15)
        lines.append("")
        lines.append(f"LOOP DETECTED - SAME FILE EDITED {loop_count} TIMES")
        lines.append("")
        lines.append("You are stuck in a loop. Editing the same file repeatedly suggests:")
        lines.append("  - Your approach isn't working")
        lines.append("  - You're missing root cause")
        lines.append("  - You need to THINK, not code more")
        lines.append("")
        lines.append("🛑 REQUIRED: Use these tools BEFORE editing again:")
        lines.append("  1. think_challenge: Challenge your current approach")
        lines.append("  2. think_explore: Explore alternative solutions")
        lines.append("  3. think_research: Research the problem deeper")
        lines.append("")
        lines.append("Death spirals waste hours. Step back, think, then code.")
        lines.append("")
        lines.append("🛑" * 15)
        has_content = True

    # TIER 2/3 ENFORCEMENT: Warnings or BLOCKING for risky files
    if file_path:
        is_risky, risk_reason, tier = check_risky_file(file_path)
        if is_risky:
            # Get smart tool suggestion
            suggested_tool, tool_reason = suggest_tool_for_context(file_path, risk_reason)

            # Check if Thinker was used recently
            used_thinker, last_tool = check_recent_thinker_usage(minutes=5)

            # TIER 3: BLOCK security files without Thinker
            if tier == 3 and not used_thinker:
                # Record that risky edit is happening without thinking
                record_risky_edit_without_thinking(file_path, risk_reason)

                lines.append("🛑" * 20)
                lines.append("")
                lines.append(f"🛑 BLOCKED: SECURITY-CRITICAL FILE - {risk_reason}")
                lines.append("")
                lines.append(f"You are about to edit {Path(file_path).name} without using Thinker tools.")
                lines.append("")
                lines.append("This file is security-critical. Bugs here can:")
                lines.append("  • Expose sensitive data")
                lines.append("  • Create authentication bypasses")
                lines.append("  • Enable privilege escalation")
                lines.append("  • Compromise user accounts")
                lines.append("")
                lines.append("🛑 REQUIRED: Use a Thinker tool FIRST")
                lines.append("")
                lines.append(f"RECOMMENDED: {suggested_tool}")
                lines.append(f"WHY: {tool_reason}")
                lines.append("")
                lines.append("Other options:")
                lines.append("  • think_best_practice: Check 2026 security standards")
                lines.append("  • think_research: Research secure implementation patterns")
                lines.append("  • think_compare: Compare security approaches")
                lines.append("")
                lines.append("Mistakes here are expensive:")
                lines.append("  • Security bugs = data breaches")
                lines.append("  • Wrong architecture = complete rewrite")
                lines.append("  • Bad patterns = technical debt forever")
                lines.append("Think before coding. Fixes cost 2-10x later.")
                lines.append("")
                lines.append("🛑" * 20)
                has_content = True

            # TIER 2: Strong warning for important files
            elif tier >= 2:
                # Record that risky edit is happening (maybe without thinking)
                if not used_thinker:
                    record_risky_edit_without_thinking(file_path, risk_reason)

                lines.append("⚠️" * 15)
                lines.append("")
                if used_thinker:
                    lines.append(f"HIGH-RISK FILE: {risk_reason} (Thinker used: {last_tool} ✓)")
                else:
                    lines.append(f"HIGH-RISK FILE: {risk_reason}")
                lines.append("")
                lines.append(f"Editing {Path(file_path).name} requires careful thought:")
                lines.append("  - Changes here affect critical functionality")
                lines.append("  - Bugs here have high impact")
                lines.append("  - Security/data integrity at stake")
                lines.append("")
                if not used_thinker:
                    lines.append(f"⚠️ RECOMMENDED: Start with {suggested_tool}")
                    lines.append(f"   WHY: {tool_reason}")
                    lines.append("")
                    lines.append("Also consider:")
                    lines.append("  • impact_analyze: What breaks if this fails?")
                    lines.append("")
                lines.append("Critical files need thought. Bugs here cost days to fix.")
                lines.append("")
                lines.append("⚠️" * 15)
                has_content = True

    # ENFORCE: Session must be active
    if not session_active:
        state["edits_without_session"] = state.get("edits_without_session", 0) + 1
        edits = state["edits_without_session"]
        save_state(state)

        lines.append("🚫" * 15)
        lines.append("")
        lines.append(f"EDITING WITHOUT MINI CLAUDE SESSION (edit #{edits})")
        lines.append("")
        lines.append("You are about to edit files without loading your memories.")
        lines.append("This means:")
        lines.append("  - Past mistakes won't warn you")
        lines.append("  - Loop detection won't work")
        lines.append("  - Scope guard won't protect you")
        lines.append("")
        lines.append("STOP. Run this first:")
        lines.append(f'  mcp__mini-claude__session_start(project_path="{project_dir}")')
        lines.append("")
        lines.append("🚫" * 15)
        has_content = True
    else:
        # Track this edit
        record_file_edit(file_path)

    # Note: Auto-recording will happen post-edit now
    if file_path and has_content:
        lines.append("ℹ️ Edit will be auto-tracked after completion")
        lines.append("")

    lines.append("</mini-claude-edit-reminder>")

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
            issues.append("⚠️ Function(s) >50 lines - break them down")

        # Check for vague names
        vague_names = ['data', 'temp', 'tmp', 'foo', 'bar', 'stuff', 'thing', 'x', 'y', 'z']
        for name in vague_names:
            if re.search(rf'\b{name}\b\s*=', content):
                issues.append(f"⚠️ Vague variable name: '{name}'")
                break

        # Check for placeholders
        placeholders = ['TODO', 'FIXME', 'HACK', 'XXX', 'PLACEHOLDER']
        for p in placeholders:
            if p in content:
                issues.append(f"⚠️ Found placeholder: '{p}'")
                break

        # Check for silent failure (CRITICAL)
        if re.search(r'except\s*:\s*pass', content) or re.search(r'except\s+\w+:\s*pass', content):
            issues.append("🔴 DANGER: Found 'except: pass' - silent failure pattern!")

        # Check for hardcoded values
        if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', content, re.I):
            issues.append("🔴 DANGER: Possible hardcoded secret!")

        if issues:
            lines.append("<mini-claude-write-quality>")
            lines.append("Code Quality Warnings:")
            for issue in issues[:5]:
                lines.append(f"  {issue}")
            lines.append("")
            lines.append("Run: code_quality_check(code) for full analysis")
            lines.append("</mini-claude-write-quality>")
            has_quality_issues = True

    if edit_reminder:
        return edit_reminder + ("\n" + "\n".join(lines) if has_quality_issues else "")
    elif has_quality_issues:
        return "\n".join(lines)
    return ""


def reminder_for_bash(project_dir: str, command: str = "", exit_code: str = "") -> str:
    """
    Generate reminder for PostToolUse hook on Bash.

    Enforces:
    1. If tests ran, demand loop_record_test
    2. If command failed, demand work_log_mistake
    """
    lines = []
    has_content = False

    # Check if this was a test command
    test_patterns = ['pytest', 'npm test', 'yarn test', 'jest', 'mocha', 'unittest', 'cargo test', 'go test', 'make test']
    is_test = any(p in command.lower() for p in test_patterns) if command else False

    if is_test:
        passed = exit_code == "0"
        lines.append("<mini-claude-test-reminder>")
        lines.append("You just ran tests. Record the result:")
        lines.append(f'  loop_record_test(passed={passed}, error_message="...")')
        lines.append("")
        lines.append("This helps detect when you're stuck in a loop.")
        lines.append("</mini-claude-test-reminder>")
        has_content = True

    # Check if command failed
    if exit_code and exit_code != "0":
        state = load_state()
        state["errors_without_log"] = state.get("errors_without_log", 0) + 1
        errors = state["errors_without_log"]
        save_state(state)

        lines.append("<mini-claude-error-reminder>")
        if errors >= 3:
            lines.append("🔴 MULTIPLE ERRORS WITHOUT LOGGING!")
            lines.append(f"You've had {errors} errors without logging any as mistakes.")
            lines.append("")
        lines.append("Something failed. Log this mistake:")
        lines.append("")
        lines.append("  mcp__mini-claude__work_log_mistake(")
        lines.append('    description="<what went wrong>",')
        lines.append('    how_to_avoid="<how to prevent this>"')
        lines.append("  )")
        lines.append("")
        lines.append("This will warn you if you're about to make the same mistake.")
        lines.append("</mini-claude-error-reminder>")
        has_content = True

    if has_content:
        return "\n".join(lines)
    return ""


def reminder_for_error(project_dir: str, error_message: str = "") -> str:
    """Generate reminder when something fails."""
    state = load_state()
    state["errors_without_log"] = state.get("errors_without_log", 0) + 1
    errors = state["errors_without_log"]
    save_state(state)

    lines = ["<mini-claude-error-reminder>"]

    if errors >= 3:
        lines.append("🔴" * 10)
        lines.append("")
        lines.append(f"YOU'VE HAD {errors} ERRORS WITHOUT LOGGING ANY!")
        lines.append("")
        lines.append("If you don't log mistakes, you WILL repeat them.")
        lines.append("")
        lines.append("🔴" * 10)
        lines.append("")

    lines.append("Something went wrong. Log this mistake so you don't repeat it:")
    lines.append("")
    lines.append("  mcp__mini-claude__work_log_mistake(")
    lines.append('    description="<what went wrong>",')
    lines.append('    how_to_avoid="<how to prevent this>"')
    lines.append("  )")
    lines.append("")
    lines.append("This will warn you if you're about to make the same mistake.")
    lines.append("</mini-claude-error-reminder>")
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
        content = ""
        if not sys.stdin.isatty():
            content = sys.stdin.read()
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

    elif hook_type == "error":
        error_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        print(reminder_for_error(project_dir, error_msg))

    # Tool callback hooks - called by handlers when Mini Claude tools are used
    elif hook_type == "session_started":
        mark_session_started(project_dir)
        print("<mini-claude-session-started>Session started! Mini Claude is now active.</mini-claude-session-started>")

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

    else:
        prompt_text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(reminder_for_prompt(project_dir, prompt_text))


if __name__ == "__main__":
    main()

"""
Change Scope Guard - Prevent over-refactoring and unintended changes

The problem: User asks me to fix ONE thing, and I end up rewriting 5 files.
This "scope creep" breaks working code and frustrates users.

The solution: Explicitly declare which files are "in scope" for the current task.
Warn (loudly) if I try to edit files outside the declared scope.
"""

import time
import json
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from ..schema import MiniClaudeResponse, WorkLog


@dataclass
class ScopeDeclaration:
    """A declared scope for a task."""
    task_description: str
    in_scope_files: list[str]  # Files explicitly allowed to edit
    in_scope_patterns: list[str]  # Glob patterns (e.g., "src/auth/*")
    out_of_scope_files: list[str]  # Files explicitly NOT to touch
    created_at: float = field(default_factory=time.time)
    reason: str = ""  # Why these files are in scope


class ScopeGuard:
    """
    Guards against unintended scope creep during a task.

    Use cases:
    1. User says "fix the login bug" -> scope is auth files only
    2. User says "add a button" -> scope is one component file
    3. User says "refactor X" -> scope is X and its direct dependencies

    If I try to edit outside scope, this raises a warning.
    """

    def __init__(self):
        self._current_scope: Optional[ScopeDeclaration] = None
        self._out_of_scope_attempts: list[tuple[str, float]] = []  # (file, timestamp)
        self._edits_made: list[tuple[str, float]] = []  # (file, timestamp)

        # Persistence for hooks to read
        self._state_file = Path.home() / ".claude_engram" / "scope_guard.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def _persist_state(self):
        """Save state to disk for hooks to read."""
        if not self._current_scope:
            state = {"has_scope": False}
        else:
            state = {
                "has_scope": True,
                "task_description": self._current_scope.task_description,
                "in_scope_files": self._current_scope.in_scope_files,
                "in_scope_patterns": self._current_scope.in_scope_patterns,
                "out_of_scope_files": self._current_scope.out_of_scope_files,
                "violations": len(self._out_of_scope_attempts),
                "updated": time.time(),
            }
        try:
            self._state_file.write_text(json.dumps(state, indent=2))
        except Exception:
            pass  # Non-critical

    def declare_scope(
        self,
        task_description: str,
        in_scope_files: list[str],
        in_scope_patterns: Optional[list[str]] = None,
        out_of_scope_files: Optional[list[str]] = None,
        reason: str = "",
    ) -> MiniClaudeResponse:
        """
        Declare the scope for the current task.

        Args:
            task_description: What the task is
            in_scope_files: List of files that CAN be edited
            in_scope_patterns: Glob patterns for files that can be edited
            out_of_scope_files: Files that should NOT be touched
            reason: Why this scope was chosen

        Returns:
            Confirmation of scope declaration
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("declaring scope")

        self._current_scope = ScopeDeclaration(
            task_description=task_description,
            in_scope_files=in_scope_files,
            in_scope_patterns=in_scope_patterns or [],
            out_of_scope_files=out_of_scope_files or [],
            reason=reason,
        )

        # Reset tracking
        self._out_of_scope_attempts = []
        self._edits_made = []
        self._persist_state()  # Save for hooks to read

        work_log.what_worked.append("scope declared")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Scope declared for: {task_description}",
            work_log=work_log,
            data={
                "task": task_description,
                "in_scope_files": in_scope_files,
                "in_scope_patterns": in_scope_patterns or [],
                "out_of_scope_files": out_of_scope_files or [],
            },
            suggestions=[
                "Edit only the files listed in scope",
                "If you need to edit other files, update the scope first",
            ],
        )

    def check_file(self, file_path: str) -> MiniClaudeResponse:
        """
        Check if editing a file is within scope.

        Call this BEFORE editing any file.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append(f"checking if {file_path} is in scope")

        if not self._current_scope:
            return MiniClaudeResponse(
                status="success",
                confidence="low",
                reasoning="No scope declared - consider declaring scope first",
                work_log=work_log,
                warnings=["No scope declared. Use scope_declare to set boundaries."],
                suggestions=["Call scope_declare with the files you plan to edit"],
            )

        # Check if file is in scope
        in_scope, reason = self._is_in_scope(file_path)

        if in_scope:
            work_log.what_worked.append("file is in scope")
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"'{Path(file_path).name}' is within scope: {reason}",
                work_log=work_log,
                data={"file": file_path, "in_scope": True, "reason": reason},
            )
        else:
            # Out of scope - this is a warning!
            self._out_of_scope_attempts.append((file_path, time.time()))

            work_log.what_worked.append("detected out of scope edit")

            return MiniClaudeResponse(
                status="warning",
                confidence="high",
                reasoning=f"'{Path(file_path).name}' is OUTSIDE declared scope!",
                work_log=work_log,
                data={
                    "file": file_path,
                    "in_scope": False,
                    "reason": reason,
                    "declared_scope": self._current_scope.in_scope_files,
                },
                warnings=[
                    f"SCOPE VIOLATION: '{Path(file_path).name}' is not in scope!",
                    f"   Task: {self._current_scope.task_description}",
                    f"   Allowed files: {', '.join(Path(f).name for f in self._current_scope.in_scope_files[:3])}...",
                    "   → Are you sure you need to edit this file?",
                ],
                suggestions=[
                    "Reconsider if this edit is necessary",
                    "If it IS necessary, call scope_expand to add it",
                    "Focus on the original task",
                ],
            )

    def record_edit(self, file_path: str):
        """Record that a file was edited (for tracking)."""
        self._edits_made.append((file_path, time.time()))

    def expand_scope(
        self,
        files_to_add: list[str],
        reason: str,
    ) -> MiniClaudeResponse:
        """
        Expand the current scope to include more files.

        This should be a deliberate decision, not automatic.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("expanding scope")

        if not self._current_scope:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No scope to expand - call scope_declare first",
                work_log=work_log,
            )

        # Add to scope
        self._current_scope.in_scope_files.extend(files_to_add)

        work_log.what_worked.append(f"added {len(files_to_add)} files to scope")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Scope expanded: added {len(files_to_add)} files",
            work_log=work_log,
            data={
                "added_files": files_to_add,
                "reason": reason,
                "total_in_scope": len(self._current_scope.in_scope_files),
            },
            warnings=[f"Scope expanded: {reason}"],
        )

    def get_status(self) -> MiniClaudeResponse:
        """Get current scope status and any violations."""
        work_log = WorkLog()
        work_log.what_i_tried.append("getting scope status")

        if not self._current_scope:
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No scope currently declared",
                work_log=work_log,
                data={"has_scope": False},
                suggestions=["Use scope_declare before starting a task"],
            )

        # Check for scope creep
        violations = len(self._out_of_scope_attempts)
        unique_out_of_scope = set(f for f, _ in self._out_of_scope_attempts)

        # Check what was edited
        files_edited = set(f for f, _ in self._edits_made)
        in_scope_edits = [f for f in files_edited if self._is_in_scope(f)[0]]
        out_scope_edits = [f for f in files_edited if not self._is_in_scope(f)[0]]

        warnings = []
        if out_scope_edits:
            warnings.append(f"Edited {len(out_scope_edits)} out-of-scope files!")
            for f in out_scope_edits[:3]:
                warnings.append(f"   - {Path(f).name}")

        if violations > 0:
            warnings.append(f"{violations} out-of-scope edit attempts this session")

        work_log.what_worked.append("status retrieved")

        return MiniClaudeResponse(
            status="warning" if out_scope_edits else "success",
            confidence="high",
            reasoning=f"Scope: {self._current_scope.task_description}",
            work_log=work_log,
            data={
                "has_scope": True,
                "task": self._current_scope.task_description,
                "in_scope_files": self._current_scope.in_scope_files,
                "in_scope_patterns": self._current_scope.in_scope_patterns,
                "out_of_scope_files": self._current_scope.out_of_scope_files,
                "files_edited": list(files_edited),
                "in_scope_edits": in_scope_edits,
                "out_scope_edits": out_scope_edits,
                "violation_attempts": violations,
            },
            warnings=warnings,
        )

    def clear_scope(self) -> MiniClaudeResponse:
        """Clear the current scope (task complete)."""
        work_log = WorkLog()
        work_log.what_i_tried.append("clearing scope")

        old_task = self._current_scope.task_description if self._current_scope else None

        self._current_scope = None
        self._out_of_scope_attempts = []
        self._edits_made = []
        self._persist_state()  # Clear persisted state

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Scope cleared{' for: ' + old_task if old_task else ''}",
            work_log=work_log,
        )

    def _is_in_scope(self, file_path: str) -> tuple[bool, str]:
        """
        Check if a file is in scope.

        Returns (is_in_scope, reason).
        """
        if not self._current_scope:
            return True, "no scope declared"

        path = Path(file_path)
        path_str = str(path)
        name = path.name

        # Check explicit out-of-scope first
        for excluded in self._current_scope.out_of_scope_files:
            if self._paths_match(path_str, excluded):
                return False, f"explicitly excluded: {excluded}"

        # Check explicit in-scope
        for allowed in self._current_scope.in_scope_files:
            if self._paths_match(path_str, allowed):
                return True, f"explicitly allowed: {allowed}"

        # Check patterns
        for pattern in self._current_scope.in_scope_patterns:
            if self._matches_pattern(path_str, pattern):
                return True, f"matches pattern: {pattern}"

        # Default: not in scope
        return False, "not in declared scope"

    def _paths_match(self, path1: str, path2: str) -> bool:
        """Check if two paths refer to the same file."""
        p1, p2 = Path(path1), Path(path2)

        # Exact match
        if p1 == p2:
            return True

        # Name match (for simple declarations)
        if p1.name == p2.name or p1.name == str(p2) or str(p1) == p2.name:
            return True

        # Ends with match (require path separator boundary)
        s1, s2 = str(p1).replace("\\", "/"), str(p2).replace("\\", "/")
        if s1.endswith("/" + s2) or s2.endswith("/" + s1):
            return True

        return False

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if a path matches a glob pattern."""
        from fnmatch import fnmatch

        # Try direct match
        if fnmatch(path, pattern):
            return True

        # Try matching just the relative part
        if fnmatch(Path(path).name, pattern):
            return True

        # Try with ** prefix for recursive patterns
        if fnmatch(path, f"**/{pattern}"):
            return True

        return False

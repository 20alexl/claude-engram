"""
Convention Tracker - Remember and Enforce Project Rules for Claude Engram

This tool addresses a key AI coding failure: ignoring project conventions.

Stores and retrieves:
- Naming conventions (files, functions, variables)
- Architecture patterns (where to put things)
- Coding style rules (formatting, imports)
- Do's and Don'ts specific to the project
"""

import json
import time
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from ..schema import MiniClaudeResponse, WorkLog


class Convention(BaseModel):
    """A single project convention/rule."""

    rule: str  # The actual rule text
    category: str  # "naming", "architecture", "style", "pattern", "avoid"
    examples: list[str] = Field(default_factory=list)  # Good/bad examples
    reason: Optional[str] = None  # Why this rule exists
    added_at: float = Field(default_factory=time.time)
    importance: int = 5  # 1-10, higher = more critical


class ProjectConventions(BaseModel):
    """All conventions for a project."""

    project_path: str
    project_name: str
    conventions: list[Convention] = Field(default_factory=list)
    last_updated: float = Field(default_factory=time.time)


class ConventionTracker:
    """
    Track and enforce project-specific coding conventions.

    Helps Claude remember:
    - "This project uses snake_case for files"
    - "Put all API routes in src/routes/"
    - "Never use var, always const/let"
    - "Auth tokens go in headers, not query params"
    """

    def __init__(self, storage_dir: str = "~/.claude_engram"):
        self.storage_dir = Path(storage_dir).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.conventions_file = self.storage_dir / "conventions.json"

        self._projects: dict[str, ProjectConventions] = {}
        self._load_error: str | None = None
        self._save_error: str | None = None
        self._load()

    def _load(self):
        """Load conventions from disk."""
        if self.conventions_file.exists():
            try:
                data = json.loads(self.conventions_file.read_text())
                for path, proj_data in data.items():
                    self._projects[path] = ProjectConventions(**proj_data)
            except Exception as e:
                # Track error and create backup of corrupted file
                self._load_error = f"Conventions file corrupted: {e}"
                try:
                    backup = self.conventions_file.with_suffix(".json.corrupted")
                    backup.write_text(self.conventions_file.read_text())
                except Exception:
                    pass  # Backup is best-effort
                # Start fresh
                self._projects = {}

    def _save(self) -> bool:
        """Save conventions to disk with atomic write."""
        data = {path: proj.model_dump() for path, proj in self._projects.items()}
        try:
            # Atomic write: write to temp file then rename
            temp_file = self.conventions_file.with_suffix(".json.tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(self.conventions_file)  # .replace() works on Windows
            self._save_error = None
            return True
        except Exception as e:
            self._save_error = f"Failed to save conventions: {e}"
            return False

    def add_convention(
        self,
        project_path: str,
        rule: str,
        category: str = "pattern",
        examples: Optional[list[str]] = None,
        reason: Optional[str] = None,
        importance: int = 5,
    ) -> MiniClaudeResponse:
        """Add a convention to a project."""
        work_log = WorkLog()
        work_log.what_i_tried.append(f"Adding {category} convention")

        if not rule:
            return MiniClaudeResponse(
                status="needs_clarification",
                confidence="high",
                reasoning="No rule provided",
                questions=["What convention should I remember?"],
                work_log=work_log,
            )

        # Ensure project exists
        if project_path not in self._projects:
            project_name = Path(project_path).name
            self._projects[project_path] = ProjectConventions(
                project_path=project_path,
                project_name=project_name,
            )

        proj = self._projects[project_path]

        # Check for duplicate/similar rules
        for existing in proj.conventions:
            if (
                rule.lower() in existing.rule.lower()
                or existing.rule.lower() in rule.lower()
            ):
                work_log.what_failed.append("Similar rule already exists")
                return MiniClaudeResponse(
                    status="partial",
                    confidence="medium",
                    reasoning=f"Similar convention already exists: '{existing.rule}'",
                    work_log=work_log,
                    suggestions=["Update the existing rule instead?"],
                )

        # Add the convention
        convention = Convention(
            rule=rule,
            category=category,
            examples=examples or [],
            reason=reason,
            importance=importance,
        )
        proj.conventions.append(convention)
        proj.last_updated = time.time()

        self._save()
        work_log.what_worked.append("Convention stored")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Remembered: {rule}",
            work_log=work_log,
            data={
                "category": category,
                "importance": importance,
                "total_conventions": len(proj.conventions),
            },
        )

    def get_conventions(
        self,
        project_path: str,
        category: Optional[str] = None,
    ) -> MiniClaudeResponse:
        """Get all conventions for a project."""
        work_log = WorkLog()
        work_log.what_i_tried.append("Retrieving conventions")

        if project_path not in self._projects:
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No conventions stored for this project yet",
                work_log=work_log,
                data={"conventions": []},
                suggestions=["Use convention_add to store project rules"],
            )

        proj = self._projects[project_path]
        conventions = proj.conventions

        if category:
            conventions = [c for c in conventions if c.category == category]

        # Sort by importance
        conventions = sorted(conventions, key=lambda x: x.importance, reverse=True)

        work_log.what_worked.append(f"Found {len(conventions)} conventions")

        # Format for easy reading
        formatted = []
        for conv in conventions:
            entry = {
                "rule": conv.rule,
                "category": conv.category,
                "importance": conv.importance,
            }
            if conv.examples:
                entry["examples"] = conv.examples
            if conv.reason:
                entry["reason"] = conv.reason
            formatted.append(entry)

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Found {len(formatted)} conventions for {proj.project_name}",
            work_log=work_log,
            data={
                "project": proj.project_name,
                "conventions": formatted,
            },
        )

    def check_conventions(
        self,
        project_path: str,
        code_or_filename: str,
    ) -> MiniClaudeResponse:
        """
        Check if code/filename follows project conventions.

        This is a simple heuristic check - not a full linter.
        Returns warnings about potential violations.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("Checking against conventions")

        if project_path not in self._projects:
            return MiniClaudeResponse(
                status="success",
                confidence="low",
                reasoning="No conventions stored - nothing to check against",
                work_log=work_log,
            )

        proj = self._projects[project_path]
        warnings = []

        for conv in proj.conventions:
            # Simple keyword-based checks
            rule_lower = conv.rule.lower()
            code_lower = code_or_filename.lower()

            # Check for "never use X" patterns
            if (
                "never use" in rule_lower
                or "don't use" in rule_lower
                or "avoid" in rule_lower
            ):
                # Extract what to avoid
                avoid_terms = []
                if "var " in rule_lower:
                    avoid_terms.append("var ")
                if "any" in rule_lower:
                    avoid_terms.append(": any")
                if "console.log" in rule_lower:
                    avoid_terms.append("console.log")

                for term in avoid_terms:
                    if term in code_lower:
                        warnings.append(
                            {
                                "rule": conv.rule,
                                "violation": f"Found '{term.strip()}'",
                                "importance": conv.importance,
                            }
                        )

            # Check naming conventions
            if (
                "snake_case" in rule_lower
                and "_" not in code_or_filename
                and code_or_filename.endswith((".py", ".js", ".ts"))
            ):
                if any(
                    c.isupper()
                    for c in code_or_filename.replace(".py", "")
                    .replace(".js", "")
                    .replace(".ts", "")
                ):
                    warnings.append(
                        {
                            "rule": conv.rule,
                            "violation": f"Filename may not follow snake_case",
                            "importance": conv.importance,
                        }
                    )

            if "camelCase" in rule_lower or "camel case" in rule_lower:
                # Check for snake_case in what looks like identifiers
                if "_" in code_or_filename and not code_or_filename.startswith("_"):
                    warnings.append(
                        {
                            "rule": conv.rule,
                            "violation": f"Found underscore in name (expecting camelCase)",
                            "importance": conv.importance,
                        }
                    )

        work_log.what_worked.append(f"Checked {len(proj.conventions)} conventions")

        if warnings:
            return MiniClaudeResponse(
                status="partial",
                confidence="medium",
                reasoning=f"Found {len(warnings)} potential convention violations",
                work_log=work_log,
                warnings=[
                    f"[{w['importance']}/10] {w['rule']}: {w['violation']}"
                    for w in warnings
                ],
                data={"violations": warnings},
            )
        else:
            return MiniClaudeResponse(
                status="success",
                confidence="medium",
                reasoning="No obvious convention violations detected",
                work_log=work_log,
            )

    def remove_convention(
        self,
        project_path: str,
        rule_substring: str,
    ) -> MiniClaudeResponse:
        """Remove a convention by matching rule text."""
        work_log = WorkLog()

        if project_path not in self._projects:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No conventions for this project",
                work_log=work_log,
            )

        proj = self._projects[project_path]
        original_count = len(proj.conventions)

        proj.conventions = [
            c for c in proj.conventions if rule_substring.lower() not in c.rule.lower()
        ]

        removed = original_count - len(proj.conventions)

        if removed > 0:
            self._save()
            work_log.what_worked.append(f"Removed {removed} conventions")
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Removed {removed} conventions matching '{rule_substring}'",
                work_log=work_log,
            )
        else:
            return MiniClaudeResponse(
                status="partial",
                confidence="high",
                reasoning=f"No conventions found matching '{rule_substring}'",
                work_log=work_log,
            )


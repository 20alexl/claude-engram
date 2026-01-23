"""
Convention Tracker - Remember and Enforce Project Rules for Mini Claude

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

    def __init__(self, storage_dir: str = "~/.mini_claude"):
        self.storage_dir = Path(storage_dir).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.conventions_file = self.storage_dir / "conventions.json"

        self._projects: dict[str, ProjectConventions] = {}
        self._load()

    def _load(self):
        """Load conventions from disk."""
        if self.conventions_file.exists():
            try:
                data = json.loads(self.conventions_file.read_text())
                for path, proj_data in data.items():
                    self._projects[path] = ProjectConventions(**proj_data)
            except Exception:
                pass  # Start fresh if corrupted

    def _save(self):
        """Save conventions to disk."""
        data = {
            path: proj.model_dump()
            for path, proj in self._projects.items()
        }
        self.conventions_file.write_text(json.dumps(data, indent=2))

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
            if rule.lower() in existing.rule.lower() or existing.rule.lower() in rule.lower():
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
            if "never use" in rule_lower or "don't use" in rule_lower or "avoid" in rule_lower:
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
                        warnings.append({
                            "rule": conv.rule,
                            "violation": f"Found '{term.strip()}'",
                            "importance": conv.importance,
                        })

            # Check naming conventions
            if "snake_case" in rule_lower and "_" not in code_or_filename and code_or_filename.endswith((".py", ".js", ".ts")):
                if any(c.isupper() for c in code_or_filename.replace(".py", "").replace(".js", "").replace(".ts", "")):
                    warnings.append({
                        "rule": conv.rule,
                        "violation": f"Filename may not follow snake_case",
                        "importance": conv.importance,
                    })

            if "camelCase" in rule_lower or "camel case" in rule_lower:
                # Check for snake_case in what looks like identifiers
                if "_" in code_or_filename and not code_or_filename.startswith("_"):
                    warnings.append({
                        "rule": conv.rule,
                        "violation": f"Found underscore in name (expecting camelCase)",
                        "importance": conv.importance,
                    })

        work_log.what_worked.append(f"Checked {len(proj.conventions)} conventions")

        if warnings:
            return MiniClaudeResponse(
                status="partial",
                confidence="medium",
                reasoning=f"Found {len(warnings)} potential convention violations",
                work_log=work_log,
                warnings=[f"[{w['importance']}/10] {w['rule']}: {w['violation']}" for w in warnings],
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
            c for c in proj.conventions
            if rule_substring.lower() not in c.rule.lower()
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

    def clear_project(self, project_path: str) -> MiniClaudeResponse:
        """Clear all conventions for a project."""
        work_log = WorkLog()

        if project_path in self._projects:
            del self._projects[project_path]
            self._save()
            work_log.what_worked.append("Cleared all conventions")
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Cleared all conventions for project",
                work_log=work_log,
            )
        else:
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No conventions to clear",
                work_log=work_log,
            )

    def get_stats(self) -> dict:
        """Get convention statistics."""
        total_conventions = sum(
            len(p.conventions) for p in self._projects.values()
        )
        return {
            "projects_with_conventions": len(self._projects),
            "total_conventions": total_conventions,
            "storage_path": str(self.conventions_file),
        }

    def check_code_with_llm(
        self,
        project_path: str,
        code: str,
        llm_client,
    ) -> MiniClaudeResponse:
        """
        Check code against stored conventions using LLM for deeper analysis.

        This is an enhanced version of check_conventions that uses
        the LLM to understand semantic violations, not just keyword matches.

        Args:
            project_path: Project directory
            code: Code snippet to check
            llm_client: LLM client for analysis
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("Checking code against conventions with LLM")

        if project_path not in self._projects:
            return MiniClaudeResponse(
                status="success",
                confidence="low",
                reasoning="No conventions stored - nothing to check against",
                work_log=work_log,
                suggestions=["Use convention_add to store project rules first"],
            )

        proj = self._projects[project_path]
        if not proj.conventions:
            return MiniClaudeResponse(
                status="success",
                confidence="low",
                reasoning="No conventions stored for this project",
                work_log=work_log,
            )

        # First do quick pattern-based check
        quick_result = self.check_conventions(project_path, code)
        quick_violations = quick_result.data.get("violations", []) if quick_result.data else []

        # Build prompt for LLM analysis
        conventions_text = "\n".join(
            f"- [{c.category}] {c.rule}" +
            (f" (importance: {c.importance}/10)" if c.importance >= 7 else "") +
            (f"\n  Examples: {', '.join(c.examples[:2])}" if c.examples else "")
            for c in sorted(proj.conventions, key=lambda x: x.importance, reverse=True)
        )

        prompt = f"""You are a code reviewer checking code against project conventions.

PROJECT CONVENTIONS (MUST be followed):
{conventions_text}

CODE TO CHECK:
```
{code[:3000]}
```

INSTRUCTIONS:
1. Check EACH convention against the code
2. For EACH convention that is violated, report it
3. Be STRICT - if the convention says "always" or "must", enforce it exactly
4. Look for SPECIFIC violations, not general style preferences

OUTPUT FORMAT (for each violation):
❌ VIOLATION: [convention that was violated]
   WHERE: [line number or code snippet]
   FIX: [how to fix it]

If ALL conventions are followed correctly, respond with ONLY:
✅ No violations found.

Be thorough. Don't miss violations. Don't make up violations that aren't there."""

        violations = []
        llm_analysis = None

        try:
            result = llm_client.generate(prompt, timeout=60)  # 60s timeout for convention check
            if result.get("success"):
                llm_analysis = result.get("response", "")
                work_log.what_worked.append("LLM analysis complete")

                # Check if LLM found violations
                # Look for explicit violation markers or absence of "no violations" confirmation
                has_violations = (
                    "❌" in llm_analysis or
                    "VIOLATION" in llm_analysis.upper() or
                    ("no violation" not in llm_analysis.lower() and
                     "✅" not in llm_analysis)
                )

                if has_violations:
                    violations.append({
                        "source": "llm",
                        "analysis": llm_analysis,
                    })
            else:
                work_log.what_failed.append(f"LLM check failed: {result.get('error')}")
        except Exception as e:
            work_log.what_failed.append(f"LLM analysis failed: {str(e)}")

        # Combine quick violations with LLM analysis
        all_violations = quick_violations + violations
        total_violations = len(quick_violations) + (1 if violations else 0)

        if all_violations:
            status = "partial"
            reasoning = f"Found {total_violations} potential violation(s)"
            warnings = [f"[{v.get('importance', '?')}/10] {v.get('rule', 'LLM Analysis')}: {v.get('violation', v.get('analysis', '')[:100])}"
                       for v in all_violations[:5]]
        else:
            status = "success"
            reasoning = "Code follows all stored conventions"
            warnings = []

        return MiniClaudeResponse(
            status=status,
            confidence="medium",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "conventions_checked": len(proj.conventions),
                "quick_violations": quick_violations,
                "llm_analysis": llm_analysis,
            },
            warnings=warnings,
            suggestions=["Fix violations before committing"] if all_violations else [],
        )

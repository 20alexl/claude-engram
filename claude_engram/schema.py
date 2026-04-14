"""
Claude Engram Response Schema

Every tool response follows this structure to ensure rich communication
back to Claude Code. No silent failures, always context.
"""

import json
from typing import Optional, Any
from pydantic import BaseModel, Field


class WorkLog(BaseModel):
    """What claude_engram did during this operation."""

    what_i_tried: list[str] = Field(default_factory=list)
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    files_examined: int = 0
    time_taken_ms: int = 0


class SearchResult(BaseModel):
    """A single search finding."""

    file: str
    line: Optional[int] = None
    relevance: str = "medium"  # high, medium, low
    summary: str
    snippet: Optional[str] = None


class MiniClaudeResponse(BaseModel):
    """
    The structured response every claude_engram tool returns.

    This is the core of the "junior agent" pattern - rich communication
    that tells Claude not just WHAT was found, but HOW and WHY.
    """

    # Core result
    status: str = "success"  # success, partial, failed, needs_clarification

    # What happened (always provided)
    work_log: WorkLog = Field(default_factory=WorkLog)

    # Communication back to Claude
    confidence: str = "medium"  # high, medium, low
    reasoning: str = ""  # "I chose approach X because..."

    # The actual findings (for search operations)
    findings: list[SearchResult] = Field(default_factory=list)
    connections: Optional[str] = None  # How findings relate to each other

    # Generic data payload for other tools
    data: Optional[Any] = None

    # Proactive collaboration
    questions: list[str] = Field(default_factory=list)  # "Should I also check...?"
    suggestions: list[str] = Field(
        default_factory=list
    )  # "I noticed X might be related..."
    warnings: list[str] = Field(
        default_factory=list
    )  # "This code has a potential issue..."

    # For Claude to decide next steps
    follow_up_options: list[dict] = Field(default_factory=list)

    def to_formatted_string(self) -> str:
        """Convert response to a readable format for Claude."""
        lines = []

        # SPECIAL CASE: Test failures need prominent display
        is_test_failure = (
            self.status == "failed"
            and isinstance(self.data, dict)
            and self.data.get("passed") is False
        )

        if is_test_failure:
            lines.append("=" * 60)
            lines.append("TEST FAILURES DETECTED")
            lines.append("=" * 60)
            lines.append("")

            # Show failure count
            failures = self.data.get("failures", [])
            if failures:
                lines.append(f"**Failed tests ({len(failures)}):**")
                for failure in failures[:10]:  # Show first 10
                    lines.append(f"  • {failure}")
                lines.append("")

            # Show full output prominently
            full_output = self.data.get("full_output", "")
            if full_output:
                lines.append("**Test Output:**")
                lines.append("```")
                lines.append(full_output[:3000])  # Show more for test failures
                if len(full_output) > 3000:
                    lines.append("...")
                    lines.append(f"(truncated - {len(full_output)} chars total)")
                lines.append("```")
                lines.append("")

            # Show exit code
            exit_code = self.data.get("exit_code", "unknown")
            lines.append(f"**Exit code:** {exit_code}")
            lines.append("")

            # Warnings are CRITICAL for test failures
            if self.warnings:
                lines.append("🛑 **CRITICAL WARNINGS:**")
                for w in self.warnings:
                    lines.append(f"  • {w}")
                lines.append("")

            # Suggestions for fixing
            if self.suggestions:
                lines.append("**What to do next:**")
                for s in self.suggestions:
                    lines.append(f"  • {s}")
                lines.append("")

            lines.append("=" * 60)
            lines.append("")

            # Skip normal data display - we already showed it
            # Continue with work log below
            lines.append("### Work Log")
            lines.append(f"- Files examined: {self.work_log.files_examined}")
            lines.append(f"- Time taken: {self.work_log.time_taken_ms}ms")
            if self.work_log.what_i_tried:
                lines.append(f"- Tried: {', '.join(self.work_log.what_i_tried)}")
            if self.work_log.what_failed:
                lines.append(f"- Failed: {', '.join(self.work_log.what_failed)}")

            return "\n".join(lines)

        # NORMAL CASE: Token-efficient output
        # Only include what Claude actually needs to act on.
        # Drop: confidence, work_log, verbose JSON, generic suggestions.

        # Status + reasoning (one line)
        if self.status == "failed" or self.status == "needs_clarification":
            lines.append(f"{self.status}: {self.reasoning}")
        elif self.reasoning:
            lines.append(self.reasoning)

        # Warnings (critical — always show)
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  ! {w}")

        # Findings (search results — compact format)
        if self.findings:
            for f in self.findings:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                lines.append(f"[{f.relevance}] {loc} — {f.summary}")

        # Data — compact rendering
        if self.data:
            if isinstance(self.data, dict):
                for key, value in self.data.items():
                    if isinstance(value, list):
                        if value:
                            # Compact list: one line per item, no header bloat
                            for item in value[:10]:
                                if isinstance(item, dict):
                                    # Memory entries: [id] (relevance) content #tags
                                    mid = item.get("id", "")
                                    content = item.get("content", str(item))
                                    rel = item.get("relevance", "")
                                    tags = " ".join(
                                        f"#{t}" for t in item.get("tags", [])[:3]
                                    )
                                    lines.append(
                                        f"[{mid}] ({rel}) {content[:100]} {tags}".rstrip()
                                    )
                                else:
                                    lines.append(f"  {item}")
                    elif isinstance(value, dict):
                        # Inline small dicts, skip large ones
                        flat = ", ".join(
                            f"{k}={v}"
                            for k, v in value.items()
                            if v is not None and v != "" and v != []
                        )
                        if flat:
                            lines.append(f"{key}: {flat}")
                    elif value is not None and value != "" and value != []:
                        lines.append(f"{key}: {value}")
            else:
                lines.append(str(self.data))

        # Connections
        if self.connections:
            lines.append(self.connections)

        # Questions (only when clarification needed)
        if self.questions:
            for q in self.questions:
                lines.append(f"? {q}")

        # Suggestions (only first 2, only if not generic)
        if self.suggestions:
            for s in self.suggestions[:2]:
                lines.append(f"  > {s}")

        # Failures from work log
        if self.work_log.what_failed:
            lines.append(f"FAILED: {', '.join(self.work_log.what_failed)}")

        return "\n".join(lines)

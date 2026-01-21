"""
Mini Claude Response Schema

Every tool response follows this structure to ensure rich communication
back to Claude Code. No silent failures, always context.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class WorkLog(BaseModel):
    """What mini_claude did during this operation."""
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
    The structured response every mini_claude tool returns.

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
    suggestions: list[str] = Field(default_factory=list)  # "I noticed X might be related..."
    warnings: list[str] = Field(default_factory=list)  # "This code has a potential issue..."

    # For Claude to decide next steps
    follow_up_options: list[dict] = Field(default_factory=list)

    def to_formatted_string(self) -> str:
        """Convert response to a readable format for Claude."""
        lines = []

        # SPECIAL CASE: Test failures need prominent display
        is_test_failure = (
            self.status == "failed" and
            isinstance(self.data, dict) and
            self.data.get("passed") is False
        )

        if is_test_failure:
            lines.append("=" * 60)
            lines.append("❌ TEST FAILURES DETECTED")
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

        # NORMAL CASE: Streamlined formatting (less verbose)
        # Compact status line
        lines.append(f"**{self.status}** | confidence: {self.confidence}")

        # Reasoning (the most important part)
        if self.reasoning:
            lines.append(f"{self.reasoning}")
        lines.append("")

        # Warnings FIRST - they're important
        if self.warnings:
            for w in self.warnings:
                lines.append(f"⚠️ {w}")
            lines.append("")

        # Findings
        if self.findings:
            for i, f in enumerate(self.findings, 1):
                loc = f"{f.file}:{f.line}" if f.line else f.file
                lines.append(f"{i}. [{f.relevance}] `{loc}` - {f.summary}")
                if f.snippet:
                    lines.append(f"   ```")
                    lines.append(f"   {f.snippet}")
                    lines.append(f"   ```")
            lines.append("")

        # Data (for non-search tools) - more compact
        if self.data:
            if isinstance(self.data, dict):
                for key, value in self.data.items():
                    if isinstance(value, list):
                        if value:  # Only show non-empty lists
                            lines.append(f"**{key}:**")
                            for item in value[:10]:
                                lines.append(f"  - {item}")
                    elif isinstance(value, dict):
                        lines.append(f"**{key}:** {json.dumps(value, indent=2)}")
                    elif value is not None and value != "":  # Only show non-empty values
                        lines.append(f"**{key}:** {value}")
            else:
                lines.append(str(self.data))
            lines.append("")

        # Connections
        if self.connections:
            lines.append(self.connections)
            lines.append("")

        # Suggestions
        if self.suggestions:
            for s in self.suggestions:
                lines.append(f"💡 {s}")
            lines.append("")

        # Questions
        if self.questions:
            lines.append("**Questions:**")
            for q in self.questions:
                lines.append(f"- {q}")
            lines.append("")

        # Work log - only show if there's something notable (failures)
        if self.work_log.what_failed:
            lines.append(f"❌ Failed: {', '.join(self.work_log.what_failed)}")

        return "\n".join(lines)


# Need to import json for the data formatting
import json

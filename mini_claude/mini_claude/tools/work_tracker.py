"""
Work Tracker - Automatic session journaling for Mini Claude

The problem: I (Claude) do work and immediately forget what I did.
Next session, I start from scratch with no context.

The solution: Track what files I edit, what searches I run, what mistakes
I make - and surface this context at the start of each session.

This is the "junior dev taking notes" feature.
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from ..schema import MiniClaudeResponse, WorkLog
from .memory import MemoryStore


@dataclass
class WorkEvent:
    """A single work event in the current session."""
    event_type: str  # "edit", "search", "error", "decision"
    description: str
    file_path: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class WorkTracker:
    """
    Tracks what Claude is doing during a session.

    Use cases:
    1. Log when files are edited -> can summarize what changed
    2. Log when searches happen -> can avoid redundant searches
    3. Log when errors occur -> can warn about repeating mistakes
    4. Log decisions made -> can explain why things were done

    At session end (or periodically), this can auto-generate memories.
    """

    def __init__(self, memory: MemoryStore):
        self.memory = memory
        self._events: list[WorkEvent] = []
        self._session_start_time: float = 0
        self._current_project: Optional[str] = None
        self._mistakes: list[dict] = []  # Track mistakes for learning

    def start_session(self, project_path: str):
        """Begin tracking work for a session."""
        self._events = []
        self._session_start_time = time.time()
        self._current_project = project_path
        self._mistakes = []

    def log_edit(
        self,
        file_path: str,
        description: str,
        lines_changed: int = 0,
    ):
        """Log when a file is edited."""
        self._events.append(WorkEvent(
            event_type="edit",
            description=description,
            file_path=file_path,
            metadata={"lines_changed": lines_changed},
        ))

    def log_search(
        self,
        query: str,
        results_count: int,
        directory: str,
    ):
        """Log when a search is performed."""
        self._events.append(WorkEvent(
            event_type="search",
            description=f"Searched for '{query}' - found {results_count} results",
            file_path=directory,
            metadata={"query": query, "results_count": results_count},
        ))

    def log_mistake(
        self,
        description: str,
        file_path: Optional[str] = None,
        how_to_avoid: Optional[str] = None,
    ):
        """
        Log when something goes wrong.

        This is the KEY feature - remembering mistakes so we don't repeat them.
        """
        mistake = {
            "description": description,
            "file_path": file_path,
            "how_to_avoid": how_to_avoid,
            "timestamp": time.time(),
        }
        self._mistakes.append(mistake)

        self._events.append(WorkEvent(
            event_type="error",
            description=description,
            file_path=file_path,
            metadata={"how_to_avoid": how_to_avoid},
        ))

        # Immediately persist mistakes - they're valuable
        if self._current_project:
            self.memory.remember_discovery(
                self._current_project,
                f"MISTAKE: {description}" + (f" - Fix: {how_to_avoid}" if how_to_avoid else ""),
                source="work_tracker",
                relevance=9,  # Mistakes are high relevance
                category="mistake",  # Use proper category for filtering
            )

    def log_decision(
        self,
        decision: str,
        reason: str,
        alternatives_considered: Optional[list[str]] = None,
    ):
        """Log an important decision and why it was made."""
        self._events.append(WorkEvent(
            event_type="decision",
            description=f"{decision} - Reason: {reason}",
            metadata={
                "decision": decision,
                "reason": reason,
                "alternatives": alternatives_considered or [],
            },
        ))

    def get_session_summary(self) -> MiniClaudeResponse:
        """
        Summarize what happened in this session.

        This creates memories that will help next session.
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("summarizing session")

        if not self._events:
            return MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="No work tracked in this session yet",
                work_log=work_log,
            )

        # Count by type
        edits = [e for e in self._events if e.event_type == "edit"]
        searches = [e for e in self._events if e.event_type == "search"]
        errors = [e for e in self._events if e.event_type == "error"]
        decisions = [e for e in self._events if e.event_type == "decision"]

        # Build summary
        summary_parts = []

        if edits:
            files_edited = list(set(e.file_path for e in edits if e.file_path))
            summary_parts.append(f"Edited {len(files_edited)} files: {', '.join(Path(f).name for f in files_edited[:5])}")

        if searches:
            queries = list(set(e.metadata.get("query", "") for e in searches))
            summary_parts.append(f"Searched for: {', '.join(queries[:5])}")

        if errors:
            summary_parts.append(f"Encountered {len(errors)} issues")

        if decisions:
            summary_parts.append(f"Made {len(decisions)} decisions")

        work_log.what_worked.append("session summarized")

        # Duration
        duration_mins = (time.time() - self._session_start_time) / 60 if self._session_start_time else 0

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=". ".join(summary_parts) if summary_parts else "Session in progress",
            work_log=work_log,
            data={
                "duration_minutes": round(duration_mins, 1),
                "edits": len(edits),
                "searches": len(searches),
                "errors": len(errors),
                "decisions": len(decisions),
                "files_touched": list(set(e.file_path for e in self._events if e.file_path)),
                "mistakes": self._mistakes,
            },
            suggestions=[
                "Use memory_remember to save important learnings",
                "Use convention_add if you discovered coding rules",
            ],
        )

    def get_relevant_context(self, file_path: str) -> MiniClaudeResponse:
        """
        Get context relevant to a specific file.

        Called before editing a file to surface:
        - Previous edits to this file in this session
        - Mistakes made with this file
        - Related searches
        """
        work_log = WorkLog()
        work_log.what_i_tried.append(f"finding context for {Path(file_path).name}")

        # Find relevant events
        relevant = []

        for event in self._events:
            if event.file_path and self._paths_related(event.file_path, file_path):
                relevant.append({
                    "type": event.event_type,
                    "description": event.description,
                    "when": event.timestamp,
                })

        # Check memory for past mistakes with this file
        past_context = []
        if self._current_project:
            memories = self.memory.recall(project_path=self._current_project)
            project = memories.get("project", {})
            discoveries = project.get("discoveries", [])

            for disc in discoveries:
                content = disc.get("content", "")
                if "MISTAKE" in content and Path(file_path).name in content:
                    past_context.append(content)

        warnings = []
        suggestions = []

        if past_context:
            warnings.append(f"Found {len(past_context)} past issues with this file!")
            for ctx in past_context[:3]:
                warnings.append(f"  - {ctx}")

        # Helpful message when no history exists
        if not relevant and not past_context:
            suggestions.append(f"No history yet for {Path(file_path).name}.")
            suggestions.append("After editing, use loop_record_edit(file_path, description) to build history.")
            suggestions.append("If something breaks, use work_log_mistake() so you'll be warned next time.")

        work_log.what_worked.append(f"found {len(relevant)} relevant events")

        # Build a more useful reasoning message
        if relevant or past_context:
            reasoning = f"Found {len(relevant)} session events and {len(past_context)} past mistakes for {Path(file_path).name}"
        else:
            reasoning = f"No history for {Path(file_path).name} yet - this is a fresh file in your workflow"

        return MiniClaudeResponse(
            status="success",
            confidence="medium" if (relevant or past_context) else "low",
            reasoning=reasoning,
            work_log=work_log,
            data={
                "current_session_events": relevant,
                "past_mistakes": past_context,
            },
            warnings=warnings,
            suggestions=suggestions,
        )

    def check_for_repeated_mistake(self, action: str) -> Optional[str]:
        """
        Check if an action might repeat a previous mistake.

        Returns a warning if we're about to repeat history.
        """
        if not self._current_project:
            return None

        memories = self.memory.recall(project_path=self._current_project)
        project = memories.get("project", {})
        discoveries = project.get("discoveries", [])

        # Look for mistakes that might be relevant
        action_lower = action.lower()

        for disc in discoveries:
            content = disc.get("content", "").lower()
            if "mistake" in content:
                # Simple keyword matching - could be smarter with LLM
                keywords = action_lower.split()
                if any(kw in content for kw in keywords if len(kw) > 3):
                    return f"Warning: You may be repeating a past mistake. Previous issue: {disc.get('content')}"

        return None

    def persist_session_to_memory(self) -> MiniClaudeResponse:
        """
        Save session work as memories for future sessions.

        Called at session end or manually to persist what was learned.
        """
        if not self._current_project:
            return MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning="No active project to save session for",
            )

        work_log = WorkLog()
        work_log.what_i_tried.append("persisting session to memory")

        memories_created = 0

        # Save decisions as memories (they explain WHY)
        decisions = [e for e in self._events if e.event_type == "decision"]
        for decision in decisions:
            self.memory.remember_discovery(
                self._current_project,
                f"DECISION: {decision.description}",
                source="work_tracker",
                relevance=7,
            )
            memories_created += 1

        # Save significant edits
        edits = [e for e in self._events if e.event_type == "edit"]
        if edits:
            files = list(set(e.file_path for e in edits if e.file_path))
            if files:
                self.memory.remember_discovery(
                    self._current_project,
                    f"SESSION WORK: Edited {len(files)} files: {', '.join(Path(f).name for f in files[:5])}",
                    source="work_tracker",
                    relevance=5,
                )
                memories_created += 1

        work_log.what_worked.append(f"created {memories_created} memories")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Saved {memories_created} session memories for next time",
            work_log=work_log,
            data={"memories_created": memories_created},
        )

    def _paths_related(self, path1: str, path2: str) -> bool:
        """Check if two paths are related (same file or same directory)."""
        p1, p2 = Path(path1), Path(path2)
        return p1 == p2 or p1.name == p2.name or p1.parent == p2.parent

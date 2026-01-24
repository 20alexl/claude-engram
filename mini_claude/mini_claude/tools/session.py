"""
Session Manager - Context loading and session lifecycle for Mini Claude

The problem: I forget to check what I know at the start of sessions.
The solution: One tool that loads everything I need to remember.

session_start: Load memories + conventions for a project
session_end: Summarize what was done (future)
"""

from typing import Optional
from pathlib import Path
from ..schema import MiniClaudeResponse, WorkLog
from .memory import MemoryStore
from .conventions import ConventionTracker


class SessionManager:
    """
    Manages session lifecycle for Mini Claude.

    Primary use: Call session_start at the beginning of work on a project
    to load all relevant context in one call.

    Enhanced with proactive context:
    - Surfaces past mistakes FIRST so I don't repeat them
    - Shows what files were touched last session
    - Highlights urgent conventions
    """

    def __init__(self, memory: MemoryStore, conventions: ConventionTracker):
        self.memory = memory
        self.conventions = conventions

    def start_session(self, project_path: str) -> MiniClaudeResponse:
        """
        Load all context for starting work on a project.

        Returns:
        - Project memories (discoveries, priorities)
        - Project conventions (rules to follow)
        - Recent searches (to avoid redundant work)
        - Suggestions for what to check first
        """
        work_log = WorkLog()
        work_log.what_i_tried.append("loading session context")

        if not project_path:
            return MiniClaudeResponse(
                status="needs_clarification",
                confidence="high",
                reasoning="No project path provided",
                questions=["Which project are you starting work on?"],
            )

        # Load memories
        work_log.what_i_tried.append("recalling memories")
        memories = self.memory.recall(project_path=project_path)

        has_memories = bool(
            memories.get("project") or
            memories.get("global_priorities")
        )

        if has_memories:
            work_log.what_worked.append("memories loaded")
        else:
            work_log.what_worked.append("no existing memories for this project")

        # Load conventions
        work_log.what_i_tried.append("loading conventions")
        conv_response = self.conventions.get_conventions(project_path)
        conventions_data = conv_response.data.get("conventions", []) if conv_response.data else []

        if conventions_data:
            work_log.what_worked.append(f"loaded {len(conventions_data)} conventions")
        else:
            work_log.what_worked.append("no conventions stored yet")

        # Build combined context - COMPACT version
        # Only return counts - protected items (mistakes, rules) are in warnings
        project = memories.get("project", {})
        discoveries = project.get("discoveries", [])

        # Count by type for summary
        mistake_count = sum(1 for d in discoveries if d.get("content", "").upper().startswith("MISTAKE:"))
        rule_count = len([c for c in conventions_data if c.get("category") == "avoid" or c.get("importance", 5) >= 9])

        # Get top 3 non-mistake discoveries by relevance for discoverability
        non_mistakes = [d for d in discoveries if not d.get("content", "").upper().startswith("MISTAKE:")]
        top_discoveries = sorted(non_mistakes, key=lambda d: d.get("relevance", 5), reverse=True)[:3]
        hints = [d.get("content", "")[:60] for d in top_discoveries]

        # Get memory health summary
        memory_summary = self.memory.get_memory_summary(project_path)

        context = {
            "project_path": project_path,
            "counts": {
                "total_memories": len(discoveries),
                "mistakes": mistake_count,
                "rules": rule_count,
                "conventions": len(conventions_data),
                "decisions": memory_summary.get("decision_count", 0),
                "stale": memory_summary.get("stale_count", 0),
            },
            "recent_hints": hints,  # One-line summaries for discoverability
            "tip": "memory(search/modify/delete, ...) for details",
        }

        # Get last session files for curated context
        try:
            from ..hooks.remind import get_last_session_files
            last_session_files = get_last_session_files()
        except ImportError:
            last_session_files = []

        # Add last session context to data
        if last_session_files:
            context["last_session_files"] = [
                str(Path(f).name) for f in last_session_files[:5]  # Show file names only
            ]
            # Get memories relevant to these files
            curated = self.memory.get_memories_for_files(project_path, last_session_files)
            context["curated_context"] = {
                "file_memories": len(curated.get("file_memories", [])),
                "other": len(curated.get("other", [])),
            }

        # Generate suggestions
        suggestions = self._generate_suggestions(memories, conventions_data, project_path)

        # Extract warnings - past mistakes are CRITICAL to surface
        warnings = self._extract_warnings(memories, conventions_data)

        # Check for recent activity (auto-captured from last session_end)
        recent_activity = self._find_recent_activity(memories)
        if recent_activity:
            # Insert at the beginning of warnings so it's seen first
            warnings = [recent_activity] + warnings

        # Add last session files context to warnings if present
        if last_session_files:
            file_names = [str(Path(f).name) for f in last_session_files[:3]]
            warnings.insert(0, f"Last session files: {', '.join(file_names)}")

        return MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=self._build_reasoning(memories, conventions_data),
            work_log=work_log,
            data=context,
            suggestions=suggestions,
            warnings=warnings,
        )

    def _build_summary(self, memories: dict, conventions: list) -> dict:
        """Build a quick summary of what was loaded."""
        project = memories.get("project", {})

        return {
            "has_project_memory": bool(project),
            "project_name": project.get("name") if project else None,
            "discovery_count": len(project.get("discoveries", [])) if project else 0,
            "convention_count": len(conventions),
            "global_priority_count": len(memories.get("global_priorities", [])),
            "recent_search_count": len(project.get("recent_searches", [])) if project else 0,
        }

    def _build_reasoning(self, memories: dict, conventions: list) -> str:
        """Build human-readable reasoning about the loaded context."""
        parts = []

        project = memories.get("project")
        if project:
            parts.append(f"Found memories for '{project.get('name', 'this project')}'")

            discoveries = project.get("discoveries", [])
            if discoveries:
                parts.append(f"with {len(discoveries)} discoveries")
        else:
            parts.append("No existing project memories")

        if conventions:
            parts.append(f"and {len(conventions)} conventions to follow")
        else:
            parts.append("and no stored conventions")

        global_priorities = memories.get("global_priorities", [])
        if global_priorities:
            parts.append(f"Plus {len(global_priorities)} global priorities")

        return ". ".join(parts) + "."

    def _generate_suggestions(
        self,
        memories: dict,
        conventions: list,
        project_path: str,
    ) -> list[str]:
        """Generate suggestions based on loaded context."""
        suggestions = []

        project = memories.get("project")

        # If no memories, suggest exploring
        if not project or not project.get("discoveries"):
            suggestions.append("Use scout_search to explore this codebase")
            suggestions.append("Use memory_remember to store what you learn")

        # If no conventions, suggest adding some
        if not conventions:
            suggestions.append("Use convention_add to store project coding rules")

        # If there are recent searches, mention them
        if project and project.get("recent_searches"):
            recent = project["recent_searches"][-1]
            suggestions.append(f"Last search was for '{recent.get('query', '?')}' - avoid repeating")

        # Add memory management suggestions from memory summary
        memory_summary = self.memory.get_memory_summary(project_path)
        if memory_summary.get("suggestions"):
            suggestions.extend(memory_summary["suggestions"])

        return suggestions[:5]  # Limit to 5 suggestions

    def _extract_warnings(self, memories: dict, conventions: list) -> list[str]:
        """
        Extract warnings from memories - especially past mistakes.

        This is the KEY to not repeating mistakes: surface them prominently
        at session start.
        """
        warnings = []

        project = memories.get("project")
        if not project:
            return warnings

        discoveries = project.get("discoveries", [])

        # Find past mistakes - they're marked with "MISTAKE:" prefix at the START
        mistakes = [
            d for d in discoveries
            if d.get("content", "").upper().startswith("MISTAKE:")
        ]

        if mistakes:
            warnings.append(f"Found {len(mistakes)} past mistake(s) to remember:")
            for mistake in mistakes[:5]:  # Show top 5
                content = mistake.get("content", "")
                # Clean up the display
                if content.startswith("MISTAKE: "):
                    content = content[9:]
                warnings.append(f"  - {content[:100]}")

        # Find "avoid" conventions - things NOT to do
        avoid_rules = [c for c in conventions if c.get("category") == "avoid"]
        if avoid_rules:
            warnings.append("Things to AVOID in this project:")
            for rule in avoid_rules[:3]:
                warnings.append(f"  - {rule.get('rule', '')[:80]}")

        # Check for high-importance conventions
        critical_rules = [c for c in conventions if c.get("importance", 5) >= 9]
        if critical_rules and not avoid_rules:
            warnings.append("Critical conventions to follow:")
            for rule in critical_rules[:3]:
                warnings.append(f"  - {rule.get('rule', '')[:80]}")

        # Find recent decisions - surface them so they're remembered
        decisions = self._extract_decisions(memories)
        if decisions:
            warnings.append(f"Recent decisions ({len(decisions)}):")
            for d in decisions[:3]:  # Show top 3
                warnings.append(f"  - {d}")

        return warnings

    def _extract_decisions(self, memories: dict) -> list[str]:
        """
        Extract recent decisions to show prominently at session start.

        Decisions have DECISION: prefix or decision category.
        Only shows decisions from last 48 hours to keep it relevant.
        """
        import time

        decisions = []
        project = memories.get("project")
        if not project:
            return decisions

        discoveries = project.get("discoveries", [])
        now = time.time()

        for d in discoveries:
            content = d.get("content", "")
            category = d.get("category", "")
            created_at = d.get("created_at", 0)

            # Check if it's a decision
            is_decision = (
                content.upper().startswith("DECISION:") or
                category == "decision"
            )
            if not is_decision:
                continue

            # Only show recent decisions (48 hours)
            age_hours = (now - created_at) / 3600 if created_at else 999
            if age_hours > 48:
                continue

            # Clean up display
            if content.upper().startswith("DECISION:"):
                content = content[9:].strip()

            decisions.append(content[:100])

        return decisions

    def _find_recent_activity(self, memories: dict) -> str | None:
        """
        Find recent session activity to show 'what was I doing?'

        Looks for SESSION: entries auto-saved by session_end.
        Returns a summary if recent activity found (within ~2 hours).
        """
        import time

        project = memories.get("project")
        if not project:
            return None

        discoveries = project.get("discoveries", [])

        # Find SESSION: entries (auto-saved by session_end)
        session_entries = [
            d for d in discoveries
            if d.get("content", "").startswith("SESSION:")
        ]

        if not session_entries:
            return None

        # Check if any are recent (within 2 hours)
        two_hours_ago = time.time() - (2 * 60 * 60)
        recent = [
            s for s in session_entries
            if s.get("created_at", 0) > two_hours_ago
        ]

        if recent:
            # Show the most recent one
            latest = max(recent, key=lambda x: x.get("created_at", 0))
            content = latest.get("content", "")
            return f"📋 Recent: {content}"

        return None

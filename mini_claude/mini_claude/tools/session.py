"""
Session Manager - Context loading and session lifecycle for Mini Claude

The problem: I forget to check what I know at the start of sessions.
The solution: One tool that loads everything I need to remember.

session_start: Load memories + conventions for a project
session_end: Summarize what was done (future)
"""

from typing import Optional
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
        # Don't include all discoveries - just summary and highlights
        project = memories.get("project", {})

        # Get only the most relevant discoveries (top 5 by relevance)
        discoveries = project.get("discoveries", [])
        top_discoveries = sorted(
            discoveries,
            key=lambda d: d.get("relevance", 5),
            reverse=True
        )[:5]

        context = {
            "project_path": project_path,
            "memories": {
                "global_priorities": memories.get("global_priorities", []),
                "project": {
                    "name": project.get("name"),
                    "discoveries": [
                        {"content": d.get("content", "")[:100], "relevance": d.get("relevance", 5)}
                        for d in top_discoveries
                    ],
                },
            },
            "summary": self._build_summary(memories, conventions_data),
        }

        # Generate suggestions
        suggestions = self._generate_suggestions(memories, conventions_data, project_path)

        # Extract warnings - past mistakes are CRITICAL to surface
        warnings = self._extract_warnings(memories, conventions_data)

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

        # Always remind about impact analysis for edits
        suggestions.append("Use impact_analyze before editing shared files")

        return suggestions[:4]  # Limit to 4 suggestions

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

        return warnings

"""
Claude Engram Handlers - Request processing logic

This module contains all the handler functions that process tool calls.
Each handler:
1. Validates inputs
2. Delegates work to the appropriate tool class
3. Returns a MiniClaudeResponse

Keeping handlers separate from server.py keeps the routing layer thin
and makes it easier to add new tools.
"""

import asyncio
import time
from mcp.types import TextContent

from .llm import LLMClient
from .schema import MiniClaudeResponse, WorkLog
from .tools import (
    SearchEngine,
    MemoryStore,
    FileSummarizer,
    DependencyMapper,
    ConventionTracker,
    ImpactAnalyzer,
    SessionManager,
    WorkTracker,
    Thinker,
)
from .tools.code_quality import CodeQualityChecker
from .tools.loop_detector import LoopDetector
from .tools.scope_guard import ScopeGuard
from .tools.context_guard import ContextGuard
from .tools.output_validator import OutputValidator
from .tools.habit_tracker import (
    get_habit_tracker,
    start_session as start_habit_session,
    record_session_tool_use,
    record_session_file_edit,
    record_session_decision,
    record_session_mistake,
)


class Handlers:
    """
    Central handler class for all Claude Engram tool calls.

    Initialized once with all tool instances, then handles
    requests by delegating to the appropriate tool.
    """

    def __init__(self):
        """Initialize all tool instances."""
        self.llm = LLMClient()
        self.search_engine = SearchEngine(self.llm)
        self.memory = MemoryStore()
        self.summarizer = FileSummarizer(self.llm)
        self.dependency_mapper = DependencyMapper(self.llm)
        self.conventions = ConventionTracker()
        self.impact_analyzer = ImpactAnalyzer(self.llm)
        self.session_manager = SessionManager(self.memory, self.conventions)
        self.work_tracker = WorkTracker(self.memory)
        self.code_quality = CodeQualityChecker()
        self.loop_detector = LoopDetector()
        self.scope_guard = ScopeGuard()
        self.context_guard = ContextGuard()
        self.output_validator = OutputValidator()
        self.thinker = Thinker(self.memory, self.search_engine, self.llm)
        self.habit_tracker = get_habit_tracker()

        # Track session state to remind Claude to use tools properly
        self._active_sessions: set[str] = set()  # project paths with active sessions
        self._tool_call_count = 0  # how many tool calls since session_start
        self._last_project_path: str | None = None  # for session_end() with no args

    def close(self):
        """Close all resources to prevent leaks."""
        if hasattr(self, "llm") and self.llm:
            self.llm.close()
        if hasattr(self, "thinker") and self.thinker:
            self.thinker.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check_session(self, project_path: str | None) -> str | None:
        """
        Check if session_start was called for this project.
        Returns a warning message if not, None if OK.
        """
        self._tool_call_count += 1

        if not project_path:
            return None

        # Normalize path for comparison
        normalized = project_path.rstrip("/")

        # Sessions auto-start via hooks — no need to nag about manual session_start

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    async def status(self) -> list[TextContent]:
        """Check Claude Engram's health status."""
        health = self.llm.health_check()
        stats = self.memory.get_stats()
        queue_stats = self.llm.get_queue_stats()

        if health["healthy"]:
            suggestions = []

            # Add queue info if there's been queueing
            queue_info = []
            if queue_stats["total_requests"] > 0:
                queue_info.append(f"LLM requests: {queue_stats['total_requests']}")
                if queue_stats["queued_requests"] > 0:
                    queue_info.append(
                        f"Queued (parallel): {queue_stats['queued_requests']} (avg wait: {queue_stats['avg_queue_wait_ms']}ms)"
                    )

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="Claude Engram is ready. Did you call session_start yet?",
                work_log=WorkLog(
                    what_worked=[
                        "LLM connection verified",
                        f"Model '{self.llm.model}' is available",
                        f"Memory tracking {stats['projects_tracked']} projects",
                    ]
                    + queue_info
                ),
                data={
                    "model": self.llm.model,
                    "memory_stats": stats,
                    "queue_stats": queue_stats,
                },
                suggestions=suggestions,
                warnings=[
                    "Remember: session_start loads memories + conventions in one call"
                ],
            )
        else:
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=health.get("error", "Unknown error"),
                work_log=WorkLog(
                    what_failed=[health.get("error", "Health check failed")]
                ),
                suggestions=[health.get("suggestion", "Check Ollama installation")],
                warnings=[
                    "Claude Engram cannot function without a working Ollama connection"
                ],
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Scout - Search
    # -------------------------------------------------------------------------

    async def search(
        self, query: str, directory: str, max_results: int
    ) -> list[TextContent]:
        """Handle search requests."""
        # Validate inputs
        if not query:
            return self._needs_clarification(
                "No query provided", "What would you like me to search for?"
            )

        if not directory:
            return self._needs_clarification(
                "No directory provided", "Which directory should I search in?"
            )

        # Check if session was started
        session_warning = self._check_session(directory)

        # Run search in thread pool to not block
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self.search_engine.search(query, directory, max_results)
        )

        # Log to memory
        if response.findings:
            self.memory.log_search(
                directory,
                query,
                len(response.findings),
                [f.file for f in response.findings],
            )

        # Add session warning to output if needed
        output = response.to_formatted_string()
        if session_warning:
            output = f"{session_warning}\n\n---\n\n{output}"

        return [TextContent(type="text", text=output)]

    # -------------------------------------------------------------------------
    # Scout - Analyze
    # -------------------------------------------------------------------------

    async def analyze(self, code: str, question: str) -> list[TextContent]:
        """Handle code analysis requests."""
        if not code:
            return self._needs_clarification(
                "No code provided", "What code would you like me to analyze?"
            )

        if not question:
            return self._needs_clarification(
                "No question provided", "What would you like to know about this code?"
            )

        # Analyze using LLM
        result = self.llm.analyze_code(code, question)

        work_log = WorkLog(
            what_i_tried=["LLM analysis"],
            time_taken_ms=result.get("time_taken_ms", 0),
        )

        if result.get("success"):
            work_log.what_worked.append("Analysis complete")
            response = MiniClaudeResponse(
                status="success",
                confidence="medium",
                reasoning=result["response"],
                work_log=work_log,
            )
        else:
            work_log.what_failed.append(result.get("error", "Unknown error"))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Analysis failed: {result.get('error')}",
                work_log=work_log,
                suggestions=[
                    "Check if Ollama is running",
                    "Try simplifying the question",
                ],
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Memory - Remember
    # -------------------------------------------------------------------------

    async def remember(
        self,
        content: str,
        category: str,
        project_path: str | None,
        relevance: int,
    ) -> list[TextContent]:
        """Handle remember requests."""
        if not content:
            return self._needs_clarification(
                "No content provided", "What would you like me to remember?"
            )

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Storing {category} memory")

        try:
            self._store_memory(content, category, project_path, relevance)
            work_log.what_worked.append("Memory stored")

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Remembered: {content[:100]}{'...' if len(content) > 100 else ''}",
                work_log=work_log,
                data={"category": category, "relevance": relevance},
            )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to store memory: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    def _store_memory(
        self, content: str, category: str, project_path: str | None, relevance: int
    ):
        """Store memory based on category. Extracted for clarity."""
        if category == "priority":
            self.memory.add_priority(content, project_path, relevance)
        elif category == "discovery":
            if project_path:
                self.memory.remember_discovery(
                    project_path, content, relevance=relevance
                )
            else:
                self.memory.add_priority(content, relevance=relevance)
        else:  # note
            if project_path:
                self.memory.remember_discovery(
                    project_path, content, relevance=relevance
                )
            else:
                self.memory.add_priority(content, relevance=relevance)

    # -------------------------------------------------------------------------
    # Memory - Recall
    # -------------------------------------------------------------------------

    async def recall(self, project_path: str | None) -> list[TextContent]:
        """Handle recall requests."""
        work_log = WorkLog()
        work_log.what_i_tried.append("Retrieving memories")

        try:
            memories = self.memory.recall(project_path=project_path)
            work_log.what_worked.append("Memories retrieved")

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="Here's what I remember",
                work_log=work_log,
                data=memories,
            )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to recall memories: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Memory - Forget
    # -------------------------------------------------------------------------

    async def forget(self, project_path: str) -> list[TextContent]:
        """Handle forget requests."""
        if not project_path:
            return self._needs_clarification(
                "No project path provided", "Which project should I forget?"
            )

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Forgetting project: {project_path}")

        try:
            self.memory.forget_project(project_path)
            work_log.what_worked.append("Project memories cleared")

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Forgot all memories for: {project_path}",
                work_log=work_log,
            )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to forget: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Memory - Cleanup (v2)
    # -------------------------------------------------------------------------

    async def memory_cleanup(
        self,
        project_path: str,
        dry_run: bool = True,
        min_relevance: int = 3,
        max_age_days: int = 30,
    ) -> list[TextContent]:
        """Handle memory cleanup requests."""
        if not project_path:
            return self._needs_clarification(
                "No project path provided", "Which project should I clean up?"
            )

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Cleaning up memories for: {project_path}")

        try:
            report = self.memory.cleanup_memories(
                project_path=project_path,
                dry_run=dry_run,
                min_relevance=min_relevance,
                max_age_days=max_age_days,
            )

            # Use the summary from the report
            summary = report.get("summary", "Cleanup completed")
            work_log.what_worked.append(summary)

            # Build detailed reasoning
            mode = "preview" if dry_run else "completed"
            reasoning = f"Memory cleanup {mode}: {summary}"

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=reasoning,
                work_log=work_log,
                data=report,
            )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to clean up memories: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Memory - Search (v2)
    # -------------------------------------------------------------------------

    async def memory_search(
        self,
        project_path: str,
        file_path: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> list[TextContent]:
        """Handle contextual memory search requests."""
        if not project_path:
            return self._needs_clarification(
                "No project path provided", "Which project should I search?"
            )

        if not file_path and not tags and not query:
            return self._needs_clarification(
                "No search criteria provided",
                "Provide file_path, tags, or query to search",
            )

        work_log = WorkLog()
        criteria = []
        if file_path:
            criteria.append(f"file={file_path}")
        if tags:
            criteria.append(f"tags={tags}")
        if query:
            criteria.append(f"query={query}")
        work_log.what_i_tried.append(f"Searching memories: {', '.join(criteria)}")

        try:
            results = self.memory.search_memories(
                project_path=project_path,
                file_path=file_path,
                tags=tags,
                query=query,
                limit=limit,
            )

            work_log.what_worked.append(f"Found {len(results)} relevant memories")

            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Found {len(results)} memories matching criteria",
                work_log=work_log,
                data={
                    "count": len(results),
                    "memories": [
                        {
                            "id": m.id,
                            "content": m.content,
                            "relevance": m.relevance,
                            "tags": m.tags,
                            "related_files": m.related_files,
                            "access_count": m.access_count,
                        }
                        for m in results
                    ],
                },
            )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to search memories: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Memory - Cluster View (v2)
    # -------------------------------------------------------------------------

    async def memory_cluster_view(
        self,
        project_path: str,
        cluster_id: str | None = None,
    ) -> list[TextContent]:
        """Handle memory cluster view requests."""
        if not project_path:
            return self._needs_clarification(
                "No project path provided", "Which project's clusters should I show?"
            )

        work_log = WorkLog()
        work_log.what_i_tried.append(
            f"Getting memory clusters for: {project_path}"
            + (f" (cluster: {cluster_id})" if cluster_id else "")
        )

        try:
            result = self.memory.get_clusters(
                project_path=project_path,
                cluster_id=cluster_id,
            )

            if "error" in result and result["error"]:
                work_log.what_failed.append(result["error"])
                response = MiniClaudeResponse(
                    status="failed",
                    confidence="high",
                    reasoning=result["error"],
                    work_log=work_log,
                )
            else:
                if cluster_id:
                    work_log.what_worked.append(
                        f"Retrieved cluster: {result.get('cluster', {}).get('name', cluster_id)}"
                    )
                else:
                    work_log.what_worked.append(
                        f"Found {len(result.get('clusters', []))} clusters"
                    )

                response = MiniClaudeResponse(
                    status="success",
                    confidence="high",
                    reasoning=(
                        "Memory clusters retrieved"
                        if not cluster_id
                        else f"Cluster {cluster_id} details"
                    ),
                    work_log=work_log,
                    data=result,
                )
        except Exception as e:
            work_log.what_failed.append(str(e))
            response = MiniClaudeResponse(
                status="failed",
                confidence="high",
                reasoning=f"Failed to get clusters: {e}",
                work_log=work_log,
            )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # File Summarizer
    # -------------------------------------------------------------------------

    async def summarize(self, file_path: str, mode: str) -> list[TextContent]:
        """Handle file summarize requests."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file should I summarize?"
            )

        # Run summarizer in thread pool
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self.summarizer.summarize(file_path, mode)
        )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Dependency Mapper
    # -------------------------------------------------------------------------

    async def deps_map(
        self,
        file_path: str,
        project_root: str | None,
        include_reverse: bool,
    ) -> list[TextContent]:
        """Handle dependency mapping requests."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file should I analyze dependencies for?"
            )

        # Run mapper in thread pool
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.dependency_mapper.map_file(
                file_path, project_root, include_reverse
            ),
        )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Session Manager
    # -------------------------------------------------------------------------

    async def session_start(self, project_path: str) -> list[TextContent]:
        """Handle session start requests."""
        response = self.session_manager.start_session(project_path)

        # Register this session as active
        if project_path:
            self._active_sessions.add(project_path.rstrip("/"))
            self._tool_call_count = 0  # Reset counter
            self._last_project_path = project_path  # For session_end() with no args
            # Start work tracking for this project
            self.work_tracker.start_session(project_path)
            # Start habit tracking session
            start_habit_session()
            record_session_tool_use("session_start", f"project: {project_path}")
            # Create session marker for hooks to detect (in ~/.claude_engram/ for Windows)
            try:
                from pathlib import Path

                marker = Path.home() / ".claude_engram" / "session_active"
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(project_path)
            except Exception:
                pass  # Non-critical

            # Notify remind hook that session was started - resets warning counters
            try:
                from .hooks.remind import mark_session_started

                mark_session_started(project_path)
            except Exception:
                pass  # Non-critical if hooks aren't available

        # Check for and auto-restore any existing checkpoints or handoffs
        checkpoint_info = ""
        try:
            # Try to restore checkpoint
            checkpoint_result = self.context_guard.restore_checkpoint(project_path=project_path)
            if checkpoint_result.status == "success" and checkpoint_result.data:
                cpd = checkpoint_result.data
                checkpoint_info = "\n\n" + "=" * 50 + "\n"
                checkpoint_info += "RESTORED CHECKPOINT FROM PREVIOUS SESSION:\n"
                checkpoint_info += "=" * 50 + "\n"
                checkpoint_info += f"Task: {cpd.get('task_description', 'Unknown')}\n"
                checkpoint_info += f"Step: {cpd.get('current_step', 'Unknown')}\n"
                if cpd.get("pending_steps"):
                    checkpoint_info += f"Pending: {', '.join(cpd['pending_steps'][:3])}\n"
                checkpoint_info += "\nCONTINUE FROM WHERE YOU LEFT OFF"

            # Also check for handoff
            handoff_result = self.context_guard.get_handoff(project_path=project_path)
            if handoff_result.status == "success" and handoff_result.data:
                handoff = handoff_result.data
                if handoff.get("summary"):
                    checkpoint_info += "\n\n" + "=" * 50 + "\n"
                    checkpoint_info += "HANDOFF FROM PREVIOUS SESSION:\n"
                    checkpoint_info += "=" * 50 + "\n"
                    checkpoint_info += f"Summary: {handoff.get('summary', 'N/A')}\n"
                    if handoff.get("next_steps"):
                        checkpoint_info += "Next steps:\n"
                        for step in handoff["next_steps"]:
                            checkpoint_info += f"  • {step}\n"
                    if handoff.get("warnings"):
                        checkpoint_info += "Warnings:\n"
                        for warn in handoff["warnings"]:
                            checkpoint_info += f"  • {warn}\n"
        except Exception as e:
            checkpoint_info = f"\n\nCould not restore checkpoint: {e}"

        # Auto-cleanup memories (non-destructive: dedup + cluster only)
        cleanup_info = ""
        try:
            if project_path:
                cleanup_result = self.memory.cleanup_memories(
                    project_path=project_path,
                    dry_run=False,
                    apply_decay=False,  # Don't auto-decay - requires manual control
                    min_relevance=1,  # Don't auto-remove any memories
                )
                # Only show summary if something was cleaned up
                dups = len(cleanup_result.get("duplicates_merged", []))
                clusters = len(cleanup_result.get("clusters_created", []))
                broken = len(cleanup_result.get("broken_found", []))
                if dups > 0 or clusters > 0 or broken > 0:
                    cleanup_info = "\n\nAuto-cleanup: "
                    parts = []
                    if broken > 0:
                        parts.append(f"removed {broken} broken")
                    if dups > 0:
                        parts.append(f"merged {dups} duplicates")
                    if clusters > 0:
                        parts.append(f"created {clusters} clusters")
                    cleanup_info += ", ".join(parts)
        except Exception as e:
            cleanup_info = f"\n\nAuto-cleanup failed: {e}"

        # Check memory health and report any errors
        memory_health_info = ""
        try:
            health = self.memory.get_health()
            if not health.get("healthy"):
                memory_health_info = "\n\nMEMORY SYSTEM WARNING:\n"
                if health.get("load_error"):
                    memory_health_info += f"  Load error: {health['load_error']}\n"
                    if health.get("backup_created"):
                        memory_health_info += "  (Backup of corrupted file created)\n"
                if health.get("save_error"):
                    memory_health_info += f"  Save error: {health['save_error']}\n"
                memory_health_info += "  Memory operations may be degraded."
        except Exception:
            pass  # Non-critical

        output = response.to_formatted_string()
        if checkpoint_info:
            output += checkpoint_info
        if cleanup_info:
            output += cleanup_info
        if memory_health_info:
            output += memory_health_info

        return [TextContent(type="text", text=output)]

    # -------------------------------------------------------------------------
    # Session End (combines summary + save)
    # -------------------------------------------------------------------------

    async def session_end(self, project_path: str | None = None) -> list[TextContent]:
        """
        End a session - AUTO-CAPTURES work and saves to memory.

        No manual input needed. Automatically grabs:
        - Tools used (from habit_tracker)
        - Files edited
        - Decisions logged
        - Mistakes logged

        Just call session_end() - it does the rest.
        """
        from pathlib import Path

        # Use last session's project_path if not provided (true zero friction)
        if not project_path:
            project_path = self._last_project_path

        work_log = WorkLog()
        work_log.what_i_tried.append("Ending session")

        lines = []
        lines.append("=" * 50)
        lines.append("SESSION END SUMMARY")
        lines.append("=" * 50)

        # Session stats from hook state (reliable — hooks always fire)
        from claude_engram.hooks.remind import load_state

        hook_state = load_state()

        duration_mins = 0
        last_start = hook_state.get("last_session_start")
        if last_start:
            duration_mins = (time.time() - last_start) / 60

        files_edited = hook_state.get("files_edited_this_session", [])

        lines.append("")
        lines.append("Session Stats:")
        if duration_mins > 0:
            lines.append(f"  Duration: {duration_mins:.0f} minutes")
        lines.append(f"  Files edited: {len(files_edited)}")

        if files_edited:
            lines.append("")
            lines.append("Files edited:")
            for f in files_edited[:10]:
                lines.append(f"  - {Path(f).name}")

        # Tool usage from hook state
        tool_usage = hook_state.get("tool_usage", {})
        if tool_usage:
            top_tools = sorted(
                ((k, v) for k, v in tool_usage.items() if v > 0),
                key=lambda x: -x[1],
            )[:5]
            if top_tools:
                lines.append("")
                lines.append("Tool usage:")
                for name, count in top_tools:
                    lines.append(f"  - {name}: {count}")

        work_log.what_worked.append("Auto-captured session activity")

        # 2. Auto-save session summary to memory (zero effort persistence)
        memories_saved = 0
        try:
            # First, persist any work tracker events
            save_response = self.work_tracker.persist_session_to_memory()
            if save_response.data:
                memories_saved = save_response.data.get("memories_created", 0)

            # Auto-generate compact session summary
            if project_path and files_edited:
                summary_parts = []
                if duration_mins > 0:
                    summary_parts.append(f"{duration_mins:.0f}min session")
                if files_edited:
                    file_names = [Path(f).name for f in files_edited[:3]]
                    summary_parts.append(f"edited {', '.join(file_names)}")

                if summary_parts:
                    auto_summary = "SESSION: " + " | ".join(summary_parts)
                    self.memory.remember_discovery(
                        project_path,
                        auto_summary,
                        source="session_end_auto",
                        relevance=5,  # Medium relevance - will decay naturally
                        category="context",
                    )
                    memories_saved += 1

            lines.append("")
            lines.append(f"Auto-saved {memories_saved} memories")
            work_log.what_worked.append(f"Auto-saved {memories_saved} memories")
        except Exception as e:
            work_log.what_failed.append(f"Save failed: {str(e)}")

        # 3. Clear scope if active
        try:
            if self.scope_guard._current_scope:
                self.scope_guard.clear_scope()
                lines.append("Cleared task scope")
        except Exception:
            pass

        # 4. Save last_session_files for curated context at next session_start
        try:
            from .hooks.remind import mark_session_ended

            mark_session_ended()
            lines.append("Saved session files for next session context")
        except Exception:
            pass

        # 5. Remove from active sessions
        if project_path:
            self._active_sessions.discard(project_path.rstrip("/"))

        lines.append("")
        lines.append("=" * 50)
        lines.append(
            "All memories auto-saved. session_end is optional - just a nice summary."
        )
        lines.append("Next session: Run session_start to restore context.")
        lines.append("=" * 50)

        response = MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning="Session ended and saved",
            work_log=work_log,
            data={
                "memories_saved": memories_saved,
            },
        )

        # Combine formatted response with summary
        output = "\n".join(lines) + "\n\n" + response.to_formatted_string()
        return [TextContent(type="text", text=output)]

    # -------------------------------------------------------------------------
    # Impact Analyzer
    # -------------------------------------------------------------------------

    async def impact_analyze(
        self,
        file_path: str,
        project_root: str,
        proposed_changes: str | None,
    ) -> list[TextContent]:
        """Handle impact analysis requests."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided",
                "Which file do you want to analyze for change impact?",
            )

        if not project_root:
            return self._needs_clarification(
                "No project root provided", "What is the project root directory?"
            )

        # Check if session was started
        session_warning = self._check_session(project_root)

        # Run analyzer in thread pool
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.impact_analyzer.analyze(
                file_path, project_root, proposed_changes
            ),
        )

        output = response.to_formatted_string()
        if session_warning:
            output = f"{session_warning}\n\n---\n\n{output}"

        return [TextContent(type="text", text=output)]

    # -------------------------------------------------------------------------
    # Convention Tracker
    # -------------------------------------------------------------------------

    async def convention_add(
        self,
        project_path: str,
        rule: str,
        category: str,
        examples: list[str] | None,
        reason: str | None,
        importance: int,
    ) -> list[TextContent]:
        """Handle convention add requests."""
        # Check session - but don't block convention adds
        session_warning = self._check_session(project_path)

        response = self.conventions.add_convention(
            project_path=project_path,
            rule=rule,
            category=category,
            examples=examples,
            reason=reason,
            importance=importance,
        )

        output = response.to_formatted_string()
        if session_warning:
            output = f"{session_warning}\n\n---\n\n{output}"

        return [TextContent(type="text", text=output)]

    async def convention_get(
        self,
        project_path: str,
        category: str | None,
    ) -> list[TextContent]:
        """Handle convention get requests."""
        # Check session
        session_warning = self._check_session(project_path)

        response = self.conventions.get_conventions(
            project_path=project_path,
            category=category,
        )

        output = response.to_formatted_string()
        if session_warning:
            output = f"{session_warning}\n\n---\n\n{output}"

        return [TextContent(type="text", text=output)]

    async def convention_check(
        self,
        project_path: str,
        code_or_filename: str,
    ) -> list[TextContent]:
        """Handle convention check requests.

        Uses LLM-based checking by default for accurate violation detection.
        Falls back to simple pattern matching if LLM is unavailable.
        """
        # Check session
        session_warning = self._check_session(project_path)

        # Use LLM-based checking for accurate results
        # The simple keyword-based check misses most violations
        response = self.conventions.check_code_with_llm(
            project_path=project_path,
            code=code_or_filename,
            llm_client=self.llm,
        )

        output = response.to_formatted_string()
        if session_warning:
            output = f"{session_warning}\n\n---\n\n{output}"

        return [TextContent(type="text", text=output)]

    # -------------------------------------------------------------------------
    # Work Tracker
    # -------------------------------------------------------------------------

    async def work_log_mistake(
        self,
        description: str,
        file_path: str | None,
        how_to_avoid: str | None,
    ) -> list[TextContent]:
        """Log a mistake for future reference."""
        if not description:
            return self._needs_clarification(
                "No description provided", "What went wrong?"
            )

        self.work_tracker.log_mistake(description, file_path, how_to_avoid)

        # Track in session
        record_session_mistake()
        record_session_tool_use("work_log_mistake", description[:30])

        # Notify hook that mistake was logged
        try:
            from .hooks.remind import mark_mistake_logged

            mark_mistake_logged()
        except Exception:
            pass

        response = MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Logged mistake: {description[:100]}",
            work_log=WorkLog(what_worked=["Mistake saved to memory"]),
            suggestions=["This will warn you if you're about to repeat this mistake"],
        )

        return [TextContent(type="text", text=response.to_formatted_string())]

    async def work_log_decision(
        self,
        decision: str,
        reason: str,
        alternatives: list[str] | None,
    ) -> list[TextContent]:
        """Log an important decision."""
        if not decision or not reason:
            return self._needs_clarification(
                "Need both decision and reason", "What was decided and why?"
            )

        self.work_tracker.log_decision(decision, reason, alternatives)

        # Track in session
        record_session_decision()
        record_session_tool_use("work_log_decision", decision[:30])

        response = MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Logged decision: {decision[:100]}",
            work_log=WorkLog(what_worked=["Decision recorded"]),
        )

        return [TextContent(type="text", text=response.to_formatted_string())]

    async def work_session_summary(self) -> list[TextContent]:
        """Get summary of current session work."""
        response = self.work_tracker.get_session_summary()
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def work_pre_edit_check(self, file_path: str) -> list[TextContent]:
        """Check for relevant context before editing a file."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file are you about to edit?"
            )

        # Notify hook that pre-edit check was done
        try:
            from .hooks.remind import mark_pre_edit_check_done

            mark_pre_edit_check_done(file_path)
        except Exception:
            pass

        response = self.work_tracker.get_relevant_context(file_path)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def work_save_session(self) -> list[TextContent]:
        """Save current session work as memories."""
        response = self.work_tracker.persist_session_to_memory()
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Unified Pre-Edit Check (combines work_pre_edit_check + loop + scope)
    # -------------------------------------------------------------------------

    async def pre_edit_check(self, file_path: str) -> list[TextContent]:
        """
        Unified pre-edit check - combines all safety checks before editing.

        Checks:
        1. Past mistakes with this file (work tracker)
        2. Loop detection (are you editing this file too many times?)
        3. Scope check (is this file in scope for your task?)

        Call this ONCE before editing instead of 3 separate tools.
        """
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file are you about to edit?"
            )

        from pathlib import Path

        work_log = WorkLog()
        work_log.what_i_tried.append(f"Pre-edit check for {Path(file_path).name}")

        all_warnings = []
        all_suggestions = []
        combined_data = {"file": file_path}
        overall_status = "success"

        # 1. Work tracker - past mistakes and context
        try:
            work_response = self.work_tracker.get_relevant_context(file_path)
            if work_response.warnings:
                all_warnings.extend(work_response.warnings)
            if work_response.suggestions:
                all_suggestions.extend(work_response.suggestions)
            if work_response.data:
                combined_data["work_context"] = work_response.data
            if work_response.status == "warning":
                overall_status = "warning"
            work_log.what_worked.append("Checked work history")
        except Exception as e:
            work_log.what_failed.append(f"Work check failed: {str(e)}")

        # 2. Loop detector - are we stuck?
        try:
            loop_response = self.loop_detector.check_before_edit(file_path)
            if loop_response.warnings:
                all_warnings.extend(loop_response.warnings)
            if loop_response.suggestions:
                all_suggestions.extend(loop_response.suggestions)
            if loop_response.data:
                combined_data["loop_risk"] = loop_response.data.get("risk_level", "low")
                combined_data["edit_count"] = loop_response.data.get("edit_count", 0)
            if loop_response.status == "warning":
                overall_status = "warning"
            work_log.what_worked.append("Checked loop risk")
        except Exception as e:
            work_log.what_failed.append(f"Loop check failed: {str(e)}")

        # 3. Scope guard - is this file in scope?
        try:
            scope_response = self.scope_guard.check_file(file_path)
            if scope_response.warnings:
                all_warnings.extend(scope_response.warnings)
            if scope_response.suggestions:
                all_suggestions.extend(scope_response.suggestions)
            if scope_response.data:
                combined_data["in_scope"] = scope_response.data.get("in_scope", True)
            if scope_response.status == "warning":
                overall_status = "warning"
            work_log.what_worked.append("Checked scope")
        except Exception as e:
            work_log.what_failed.append(f"Scope check failed: {str(e)}")

        # Notify hooks
        try:
            from .hooks.remind import mark_pre_edit_check_done

            mark_pre_edit_check_done(file_path)
        except Exception:
            pass

        # Track in habit tracker
        record_session_tool_use("pre_edit_check", file_path[:30])

        # Build summary
        issues = []
        if combined_data.get("loop_risk") == "high":
            issues.append("high loop risk")
        if combined_data.get("in_scope") is False:
            issues.append("out of scope")
        if combined_data.get("work_context", {}).get("past_mistakes"):
            issues.append("past mistakes found")

        if issues:
            reasoning = f"Issues found: {', '.join(issues)}"
        else:
            reasoning = f"Safe to edit {Path(file_path).name}"

        response = MiniClaudeResponse(
            status=overall_status,
            confidence="high",
            reasoning=reasoning,
            work_log=work_log,
            data=combined_data,
            warnings=all_warnings[:10],  # Limit warnings
            suggestions=list(dict.fromkeys(all_suggestions))[:5],  # Dedupe and limit
        )

        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Code Quality Checker
    # -------------------------------------------------------------------------

    async def code_quality_check(
        self,
        code: str,
        language: str,
    ) -> list[TextContent]:
        """Check code for structural quality issues."""
        if not code:
            return self._needs_clarification(
                "No code provided", "What code would you like me to check?"
            )

        response = self.code_quality.check(code, language)
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Loop Detector
    # -------------------------------------------------------------------------

    async def loop_record_edit(
        self,
        file_path: str,
        description: str,
    ) -> list[TextContent]:
        """Record that a file was edited."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file was edited?"
            )

        # Notify hook that edit was recorded
        try:
            from .hooks.remind import mark_loop_record_done

            mark_loop_record_done(file_path)
        except Exception:
            pass

        response = self.loop_detector.record_edit(file_path, description or "")
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def loop_check_before_edit(self, file_path: str) -> list[TextContent]:
        """Check if editing a file might create a loop."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file are you about to edit?"
            )

        response = self.loop_detector.check_before_edit(file_path)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def loop_record_test(
        self,
        passed: bool,
        error_message: str,
    ) -> list[TextContent]:
        """Record test results."""
        self.loop_detector.record_test_result(passed, error_message or "")

        # Notify hook that test was recorded
        try:
            from .hooks.remind import mark_test_recorded

            mark_test_recorded()
        except Exception:
            pass

        response = MiniClaudeResponse(
            status="success",
            confidence="high",
            reasoning=f"Test result recorded: {'PASSED' if passed else 'FAILED'}",
            work_log=WorkLog(what_worked=["Test result logged"]),
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def loop_status(self) -> list[TextContent]:
        """Get loop detection status."""
        response = self.loop_detector.get_status()
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Scope Guard
    # -------------------------------------------------------------------------

    async def scope_declare(
        self,
        task_description: str,
        in_scope_files: list[str],
        in_scope_patterns: list[str] | None,
        out_of_scope_files: list[str] | None,
        reason: str,
    ) -> list[TextContent]:
        """Declare the scope for the current task."""
        if not task_description:
            return self._needs_clarification(
                "No task description provided", "What task are you working on?"
            )

        if not in_scope_files:
            return self._needs_clarification(
                "No files specified", "Which files are you allowed to edit?"
            )

        # Notify hook that scope was declared
        try:
            from .hooks.remind import mark_scope_declared

            mark_scope_declared()
        except Exception:
            pass

        response = self.scope_guard.declare_scope(
            task_description=task_description,
            in_scope_files=in_scope_files,
            in_scope_patterns=in_scope_patterns,
            out_of_scope_files=out_of_scope_files,
            reason=reason or "",
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def scope_check(self, file_path: str) -> list[TextContent]:
        """Check if editing a file is within scope."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file do you want to check?"
            )

        response = self.scope_guard.check_file(file_path)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def scope_expand(
        self,
        files_to_add: list[str],
        reason: str,
    ) -> list[TextContent]:
        """Expand the current scope."""
        if not files_to_add:
            return self._needs_clarification(
                "No files provided", "Which files do you want to add to scope?"
            )

        if not reason:
            return self._needs_clarification(
                "No reason provided", "Why do you need to expand the scope?"
            )

        response = self.scope_guard.expand_scope(files_to_add, reason)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def scope_status(self) -> list[TextContent]:
        """Get scope status."""
        response = self.scope_guard.get_status()
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def scope_clear(self) -> list[TextContent]:
        """Clear the current scope."""
        response = self.scope_guard.clear_scope()
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Context Guard - Checkpoints & Task Continuity
    # -------------------------------------------------------------------------

    async def context_checkpoint_save(
        self,
        task_description: str,
        current_step: str,
        completed_steps: list[str],
        pending_steps: list[str],
        files_involved: list[str],
        key_decisions: list[str] | None,
        blockers: list[str] | None,
        project_path: str | None,
        # Optional handoff fields (merged from create_handoff)
        handoff_summary: str | None = None,
        handoff_context_needed: list[str] | None = None,
        handoff_warnings: list[str] | None = None,
    ) -> list[TextContent]:
        """Save a checkpoint of current task state with optional handoff info."""
        if not task_description:
            return self._needs_clarification(
                "No task description", "What task are you working on?"
            )

        response = self.context_guard.save_checkpoint(
            task_description=task_description,
            current_step=current_step or "",
            completed_steps=completed_steps or [],
            pending_steps=pending_steps or [],
            files_involved=files_involved or [],
            key_decisions=key_decisions,
            blockers=blockers,
            project_path=project_path,
            handoff_summary=handoff_summary,
            handoff_context_needed=handoff_context_needed,
            handoff_warnings=handoff_warnings,
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_checkpoint_restore(
        self,
        task_id: str | None,
        project_path: str | None = None,
    ) -> list[TextContent]:
        """Restore task state from a checkpoint."""
        response = self.context_guard.restore_checkpoint(task_id, project_path=project_path)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_checkpoint_list(self) -> list[TextContent]:
        """List all saved checkpoints."""
        response = self.context_guard.list_checkpoints()
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_instruction_add(
        self,
        instruction: str,
        reason: str,
        importance: int,
    ) -> list[TextContent]:
        """Register a critical instruction that must not be forgotten."""
        if not instruction:
            return self._needs_clarification(
                "No instruction provided", "What instruction should never be forgotten?"
            )

        response = self.context_guard.add_critical_instruction(
            instruction=instruction,
            reason=reason or "Important rule",
            importance=importance,
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_instruction_reinforce(self) -> list[TextContent]:
        """Get critical instructions that need reinforcement."""
        response = self.context_guard.get_reinforcement()
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_claim_completion(
        self,
        task: str,
        evidence: list[str] | None,
    ) -> list[TextContent]:
        """Record a claim that a task is complete."""
        if not task:
            return self._needs_clarification(
                "No task specified", "What task are you claiming is complete?"
            )

        response = self.context_guard.claim_completion(task, evidence)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_self_check(
        self,
        task: str,
        verification_steps: list[str],
    ) -> list[TextContent]:
        """Verify that claimed work was actually done."""
        if not task:
            return self._needs_clarification(
                "No task specified", "What task do you want to verify?"
            )

        if not verification_steps:
            return self._needs_clarification(
                "No verification steps", "How should the task be verified?"
            )

        response = self.context_guard.self_check(task, verification_steps)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def verify_completion(
        self,
        task: str,
        verification_steps: list[str],
        evidence: list[str] | None = None,
    ) -> list[TextContent]:
        """Unified completion verification: claim + verify in one step."""
        if not task:
            return self._needs_clarification(
                "No task specified", "What task are you claiming is complete?"
            )

        if not verification_steps:
            return self._needs_clarification(
                "No verification steps", "How should the task be verified?"
            )

        response = self.context_guard.verify_completion(
            task=task,
            verification_steps=verification_steps,
            evidence=evidence,
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_handoff_create(
        self,
        summary: str,
        next_steps: list[str],
        context_needed: list[str],
        warnings: list[str] | None,
        project_path: str | None,
    ) -> list[TextContent]:
        """Create a structured handoff for the next session."""
        if not summary:
            return self._needs_clarification(
                "No summary provided", "What's the summary of what was done?"
            )

        if not next_steps:
            return self._needs_clarification(
                "No next steps provided", "What should the next session work on?"
            )

        response = self.context_guard.create_handoff(
            summary=summary,
            next_steps=next_steps,
            context_needed=context_needed or [],
            warnings=warnings,
            project_path=project_path,
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def context_handoff_get(self, project_path: str = "") -> list[TextContent]:
        """Retrieve the latest handoff document."""
        response = self.context_guard.get_handoff(project_path=project_path)
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Output Validator - Detect Silent Failures
    # -------------------------------------------------------------------------

    async def output_validate_code(
        self,
        code: str,
        context: str | None,
    ) -> list[TextContent]:
        """Validate code for signs of fake output or silent failure."""
        if not code:
            return self._needs_clarification(
                "No code provided", "What code should I validate?"
            )

        response = self.output_validator.validate_code(code, context)
        return [TextContent(type="text", text=response.to_formatted_string())]

    async def output_validate_result(
        self,
        output: str,
        expected_format: str | None,
        should_contain: list[str] | None,
        should_not_contain: list[str] | None,
    ) -> list[TextContent]:
        """Validate command/function output for signs of fake results."""
        if not output:
            return self._needs_clarification(
                "No output provided", "What output should I validate?"
            )

        response = self.output_validator.validate_output(
            output=output,
            expected_format=expected_format,
            should_contain=should_contain,
            should_not_contain=should_not_contain,
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    # NOTE: TestRunner, GitHelper, MomentumTracker handlers REMOVED
    # - Tests: Use Claude Code's native Bash tool
    # - Git: Claude excels at commit messages natively
    # - Momentum: Use Claude Code's native TodoWrite

    # -------------------------------------------------------------------------
    # NOTE: Think tools REMOVED - generic LLM responses weren't useful enough
    # Scout tools (semantic search/analysis) still available
    # Thinker instance kept for audit_batch which provides practical value
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Think Audit - Used internally by audit_batch
    # -------------------------------------------------------------------------

    async def think_audit(
        self,
        file_path: str,
        focus_areas: list[str] | None,
        min_severity: str | None = None,
    ) -> list[TextContent]:
        """Audit a file for common issues and anti-patterns."""
        if not file_path:
            return self._needs_clarification(
                "No file path provided", "Which file should I audit?"
            )

        record_session_tool_use("think_audit", file_path[:50])
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self.thinker.audit(file_path, focus_areas, min_severity)
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Audit Batch - Audit multiple files at once
    # -------------------------------------------------------------------------

    async def audit_batch(
        self,
        file_paths: list[str],
        min_severity: str | None = None,
    ) -> list[TextContent]:
        """Audit multiple files at once."""
        if not file_paths:
            return self._needs_clarification(
                "No file paths provided",
                "Which files should I audit? (supports glob patterns like 'src/**/*.py')",
            )

        record_session_tool_use("audit_batch", f"{len(file_paths)} files")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self.thinker.audit_batch(file_paths, min_severity)
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Find Similar Issues - Search codebase for similar patterns
    # -------------------------------------------------------------------------

    async def find_similar_issues(
        self,
        issue_pattern: str,
        project_path: str,
        file_extensions: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        exclude_strings: bool = True,
    ) -> list[TextContent]:
        """Search codebase for code similar to a found issue pattern."""
        if not issue_pattern:
            return self._needs_clarification(
                "No pattern provided",
                "What pattern should I search for? (e.g., 'except: pass', 'eval(')",
            )

        if not project_path:
            return self._needs_clarification(
                "No project path provided", "Which directory should I search in?"
            )

        record_session_tool_use("find_similar_issues", issue_pattern[:30])
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.thinker.find_similar_issues(
                issue_pattern,
                project_path,
                file_extensions,
                exclude_paths,
                exclude_strings,
            ),
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    # -------------------------------------------------------------------------
    # Code Pattern Check - Check code against conventions with LLM
    # -------------------------------------------------------------------------

    async def code_pattern_check(
        self,
        project_path: str,
        code: str,
    ) -> list[TextContent]:
        """Check code against stored conventions using LLM."""
        if not project_path:
            return self._needs_clarification(
                "No project path provided",
                "Which project's conventions should I check against?",
            )

        if not code:
            return self._needs_clarification(
                "No code provided", "What code should I check?"
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.conventions.check_code_with_llm(project_path, code, self.llm),
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

    # =========================================================================
    # COMBINED TOOL ROUTERS (v2 - token-efficient tools)
    # =========================================================================

    async def handle_memory(self, operation: str, args: dict) -> list[TextContent]:
        """Route memory operations to existing handlers."""
        project_path = args.get("project_path", "")

        if operation == "remember":
            return await self.remember(
                content=args.get("content", ""),
                category=args.get("category", "note"),
                project_path=project_path,
                relevance=args.get("relevance", 5),
            )
        elif operation == "recall":
            return await self.recall(project_path)
        elif operation == "forget":
            return await self.forget(project_path)
        elif operation == "search":
            return await self.memory_search(
                project_path=project_path,
                file_path=args.get("file_path"),
                tags=args.get("tags"),
                query=args.get("query"),
                limit=args.get("limit", 5),
            )
        elif operation == "clusters":
            return await self.memory_cluster_view(
                project_path=project_path,
                cluster_id=args.get("cluster_id"),
            )
        elif operation == "cleanup":
            return await self.memory_cleanup(
                project_path=project_path,
                dry_run=args.get("dry_run", True),
                min_relevance=args.get("min_relevance", 3),
                max_age_days=args.get("max_age_days", 30),
            )
        elif operation == "consolidate":
            tag = args.get("tag")
            dry_run = args.get("dry_run", True)
            result = self.memory.consolidate_memories(
                project_path=project_path,
                llm_client=self.llm,
                tag=tag,
                dry_run=dry_run,
            )
            if "error" in result:
                response = MiniClaudeResponse(
                    status="needs_clarification",
                    confidence="high",
                    reasoning=result["error"],
                )
            else:
                lines = [result.get("summary", "Consolidation complete")]
                lines.append(f"Before: {result.get('original_count', '?')} memories")
                if result.get("new_count"):
                    lines.append(f"After: {result['new_count']} memories")
                for group in result.get("groups_found", []):
                    tag_name = group.get("tag", "?")
                    count = group.get("count", 0)
                    action = "would merge" if dry_run else "merged"
                    lines.append(f"\n  [{tag_name}] {count} entries {action}:")
                    for e in group.get("entries", []):
                        lines.append(f"    [{e['id']}] {e['preview']}")
                    if group.get("consolidated_to"):
                        c = group["consolidated_to"]
                        lines.append(f"    -> kept top 5, removed {c.get('removed_count', '?')}, summary: {c.get('content', '')[:80]}")
                response = MiniClaudeResponse(
                    status="success",
                    confidence="high",
                    reasoning="\n".join(lines),
                    data=result,
                )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "add_rule":
            added, msg = self.memory.add_rule(
                project_path=project_path,
                content=args.get("content", ""),
                reason=args.get("reason"),
                relevance=args.get("relevance", 9),
            )
            response = MiniClaudeResponse(
                status="success" if added else "needs_clarification",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "list_rules":
            rules = self.memory.get_rules(project_path)
            if not rules:
                return [
                    TextContent(type="text", text="No rules defined for this project")
                ]
            lines = [f"Rules for {project_path}:", ""]
            for r in rules:
                lines.append(f"  [{r.id}] {r.content}")
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="\n".join(lines),
                data={"rules": [r.model_dump() for r in rules]},
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "modify":
            success, msg = self.memory.modify_memory(
                project_path=project_path,
                memory_id=args.get("memory_id", ""),
                content=args.get("content"),
                relevance=args.get("relevance"),
                category=args.get("category"),
            )
            response = MiniClaudeResponse(
                status="success" if success else "needs_clarification",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "delete":
            success, msg = self.memory.delete_memory(
                project_path=project_path,
                memory_id=args.get("memory_id", ""),
            )
            response = MiniClaudeResponse(
                status="success" if success else "needs_clarification",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "batch_delete":
            memory_ids = args.get("memory_ids", [])
            category = args.get("category")
            count, msg = self.memory.batch_delete(
                project_path=project_path,
                memory_ids=memory_ids if memory_ids else None,
                category=category,
            )
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "promote":
            success, msg = self.memory.promote_to_rule(
                project_path=project_path,
                memory_id=args.get("memory_id", ""),
                reason=args.get("reason"),
            )
            response = MiniClaudeResponse(
                status="success" if success else "needs_clarification",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "recent":
            entries = self.memory.get_recent_memories(
                project_path=project_path,
                category=args.get("category"),
                limit=args.get("limit", 10),
            )
            if not entries:
                return [TextContent(type="text", text="No recent memories")]
            lines = ["Recent memories (newest first):", ""]
            for e in entries:
                age_mins = int((time.time() - e.created_at) / 60)
                if age_mins < 60:
                    age_str = f"{age_mins}m ago"
                elif age_mins < 1440:
                    age_str = f"{age_mins // 60}h ago"
                else:
                    age_str = f"{age_mins // 1440}d ago"
                content_display = (
                    e.content[:57] + "..." if len(e.content) > 60 else e.content
                )
                lines.append(f"  [{e.id}] ({age_str}) [{e.category}] {content_display}")
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="\n".join(lines),
                data={"memories": [e.model_dump() for e in entries]},
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "archive":
            result = self.memory.archive_old_memories(
                project_path=project_path,
                dry_run=args.get("dry_run", True),
            )
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"{'Would archive' if result.get('dry_run') else 'Archived'} {result['archived_count']} memories",
                data=result,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "restore":
            success, msg = self.memory.restore_from_archive(
                project_path=project_path,
                memory_id=args.get("memory_id", ""),
            )
            response = MiniClaudeResponse(
                status="success" if success else "needs_clarification",
                confidence="high",
                reasoning=msg,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "archive_search":
            entries = self.memory.search_archive(
                project_path=project_path,
                query=args.get("query"),
                tags=args.get("tags"),
                limit=args.get("limit", 5),
            )
            if not entries:
                return [TextContent(type="text", text="No archived memories found")]
            lines = ["Archived memories:", ""]
            for e in entries:
                age_days = int((time.time() - (e.archived_at or e.created_at)) / 86400)
                content_display = (
                    e.content[:57] + "..." if len(e.content) > 60 else e.content
                )
                lines.append(
                    f"  [{e.id}] ({age_days}d archived) [{e.category}] {content_display}"
                )
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="\n".join(lines),
                data={"memories": [e.model_dump() for e in entries]},
                suggestions=[
                    "Use memory(restore, memory_id='...') to bring one back to active"
                ],
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "archive_status":
            stats = self.memory.get_archive_stats(project_path)
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Hot: {stats['hot_total']} memories | Archive: {stats['archive_total']} memories",
                data=stats,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "hybrid_search":
            results = self.memory.hybrid_search(
                project_path=project_path,
                query=args.get("query", ""),
                file_path=args.get("file_path", ""),
                tags=args.get("tags"),
                limit=args.get("limit", 5),
            )
            if not results:
                return [TextContent(type="text", text="No results")]
            lines = [
                f"Found {len(results)} results (hybrid: keyword + scored + vector):"
            ]
            for entry, score in results:
                lines.append(f"[{entry.id}] ({score:.3f}) {entry.content[:80]}")
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="\n".join(lines),
                data={"memories": [e.model_dump() for e, _ in results]},
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "embed_all":
            force = arguments.get("force", False)
            count = self.memory.embed_all_memories(project_path, force=force)
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=(
                    f"{'Rebuilt' if force else 'Embedded'} {count} memories"
                    if count
                    else "All memories already embedded (or scorer server not running)"
                ),
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "list_mistakes":
            entries = self.memory.get_recent_memories(
                project_path=project_path,
                category="mistake",
                limit=args.get("limit", 20),
            )
            if not entries:
                return [TextContent(type="text", text="No mistakes tracked")]
            lines = [f"Tracked mistakes ({len(entries)}):"]
            for e in entries:
                age_days = int((time.time() - e.created_at) / 86400)
                files = ", ".join(e.related_files[:3]) if e.related_files else "no file"
                lines.append(f"  [{e.id}] ({age_days}d) [{files}] {e.content[:100]}")
            lines.append("")
            lines.append("Use memory(acknowledge_mistake, memory_id='...') to archive a learned mistake")
            response = MiniClaudeResponse(
                status="success", confidence="high", reasoning="\n".join(lines),
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "acknowledge_mistake":
            mid = args.get("memory_id", "")
            if not mid:
                return self._needs_clarification("No memory_id", "Which mistake to acknowledge? Use list_mistakes to see IDs.")
            proj = self.memory.get_project(project_path)
            if proj:
                entry = next((e for e in proj.entries if e.id == mid and e.category == "mistake"), None)
                if entry:
                    entry.archived_at = time.time()
                    self.memory._save_project(self.memory._normalize_path(project_path))
                    response = MiniClaudeResponse(
                        status="success", confidence="high",
                        reasoning=f"Mistake [{mid}] acknowledged and archived. It won't appear in pre-edit warnings.",
                    )
                    return [TextContent(type="text", text=response.to_formatted_string())]
            return self._needs_clarification(f"Mistake [{mid}] not found", "Check the ID with list_mistakes")
        else:
            return self._needs_clarification(
                f"Unknown memory operation: {operation}",
                "Use: remember, recall, forget, search, clusters, cleanup, consolidate, add_rule, list_rules, modify, delete, batch_delete, promote, recent, archive, restore, archive_search, archive_status, list_mistakes, acknowledge_mistake",
            )

    async def handle_work(self, operation: str, args: dict) -> list[TextContent]:
        """Route work operations to existing handlers."""
        if operation == "log_mistake":
            return await self.work_log_mistake(
                description=args.get("description", ""),
                file_path=args.get("file_path"),
                how_to_avoid=args.get("how_to_avoid"),
            )
        elif operation == "log_decision":
            return await self.work_log_decision(
                decision=args.get("decision", ""),
                reason=args.get("reason", ""),
                alternatives=args.get("alternatives"),
            )
        else:
            return self._needs_clarification(
                f"Unknown work operation: {operation}",
                "Use: log_mistake or log_decision",
            )

    async def handle_scope(self, operation: str, args: dict) -> list[TextContent]:
        """Route scope operations to existing handlers."""
        if operation == "declare":
            return await self.scope_declare(
                task_description=args.get("task_description", ""),
                in_scope_files=args.get("in_scope_files", []),
                in_scope_patterns=args.get("in_scope_patterns"),
                out_of_scope_files=args.get("out_of_scope_files"),
                reason=args.get("reason", ""),
            )
        elif operation == "check":
            return await self.scope_check(args.get("file_path", ""))
        elif operation == "expand":
            return await self.scope_expand(
                files_to_add=args.get("files_to_add", []),
                reason=args.get("reason", ""),
            )
        elif operation == "status":
            return await self.scope_status()
        elif operation == "clear":
            return await self.scope_clear()
        else:
            return self._needs_clarification(
                f"Unknown scope operation: {operation}",
                "Use: declare, check, expand, status, or clear",
            )

    async def handle_loop(self, operation: str, args: dict) -> list[TextContent]:
        """Route loop operations to existing handlers."""
        if operation == "record_edit":
            return await self.loop_record_edit(
                file_path=args.get("file_path", ""),
                description=args.get("description", ""),
            )
        elif operation == "record_test":
            return await self.loop_record_test(
                passed=args.get("passed", False),
                error_message=args.get("error_message", ""),
            )
        elif operation == "check":
            return await self.loop_check_before_edit(args.get("file_path", ""))
        elif operation == "status":
            return await self.loop_status()
        elif operation == "reset":
            self.loop_detector.reset()
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning="Loop tracking reset. All edit counts and test history cleared.",
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        else:
            return self._needs_clarification(
                f"Unknown loop operation: {operation}",
                "Use: record_edit, record_test, check, status, or reset",
            )

    @staticmethod
    def _coerce_list(val) -> list:
        """Coerce a value to a list — handles stringified JSON arrays from Claude."""
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            val = val.strip()
            if val.startswith("["):
                try:
                    import json
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass
            if val:
                return [val]
        return []

    _instructions_migrated = False

    def _migrate_legacy_instructions(self, project_path: str):
        """Migrate critical_instructions.json entries to rules (one-time)."""
        if self._instructions_migrated:
            return
        self._instructions_migrated = True
        try:
            from pathlib import Path
            import json as json_mod

            inst_file = Path.home() / ".claude_engram" / "checkpoints" / "critical_instructions.json"
            if not inst_file.exists():
                return
            instructions = json_mod.loads(inst_file.read_text())
            if not instructions:
                return
            migrated = 0
            for inst in instructions:
                content = inst.get("instruction", "")
                reason = inst.get("reason", "")
                importance = inst.get("importance", 9)
                self.memory.add_rule(project_path, content, reason=reason, relevance=importance)
                migrated += 1
            # Remove legacy file after migration
            inst_file.unlink()
        except Exception:
            pass

    async def handle_context(self, operation: str, args: dict) -> list[TextContent]:
        """Route context operations to existing handlers."""
        if operation == "checkpoint_save":
            return await self.context_checkpoint_save(
                task_description=args.get("task_description", ""),
                current_step=args.get("current_step", ""),
                completed_steps=self._coerce_list(args.get("completed_steps", [])),
                pending_steps=self._coerce_list(args.get("pending_steps", [])),
                files_involved=self._coerce_list(args.get("files_involved", [])),
                key_decisions=args.get("key_decisions"),
                blockers=args.get("blockers"),
                project_path=args.get("project_path"),
                handoff_summary=args.get("handoff_summary"),
                handoff_context_needed=self._coerce_list(args.get("handoff_context_needed")),
                handoff_warnings=self._coerce_list(args.get("handoff_warnings")),
            )
        elif operation == "checkpoint_restore":
            return await self.context_checkpoint_restore(args.get("task_id"), project_path=args.get("project_path"))
        elif operation == "checkpoint_list":
            return await self.context_checkpoint_list()
        elif operation == "verify_completion":
            return await self.verify_completion(
                task=args.get("task", ""),
                verification_steps=self._coerce_list(args.get("verification_steps", [])),
                evidence=self._coerce_list(args.get("evidence")),
            )
        elif operation == "instruction_add":
            # Route through rules system — instructions ARE rules
            project_path = args.get("project_path", "")
            instruction = args.get("instruction", "")
            reason = args.get("reason", "")
            importance = args.get("importance", 10)
            if not instruction:
                return self._needs_clarification("No instruction provided", "What rule should be enforced?")
            self.memory.add_rule(project_path, instruction, reason=reason, relevance=importance)
            # Also migrate any legacy instructions
            self._migrate_legacy_instructions(project_path)
            response = MiniClaudeResponse(
                status="success",
                confidence="high",
                reasoning=f"Rule registered (importance: {importance}/10). Use memory(list_rules) to see all rules.",
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        elif operation == "instruction_reinforce":
            # Return rules (instructions are now rules)
            project_path = args.get("project_path", "")
            self._migrate_legacy_instructions(project_path)
            return await self.handle_memory("list_rules", {"project_path": project_path})
        elif operation == "instruction_list":
            project_path = args.get("project_path", "")
            self._migrate_legacy_instructions(project_path)
            return await self.handle_memory("list_rules", {"project_path": project_path})
        elif operation == "instruction_delete":
            return await self.handle_memory("delete", {
                "memory_id": args.get("memory_id", args.get("instruction_id", "")),
                "project_path": args.get("project_path", ""),
            })
        elif operation == "handoff_create":
            return await self.context_handoff_create(
                summary=args.get("handoff_summary", ""),
                next_steps=self._coerce_list(args.get("next_steps") or args.get("pending_steps", [])),
                context_needed=self._coerce_list(args.get("handoff_context_needed", [])),
                warnings=self._coerce_list(args.get("handoff_warnings")),
                project_path=args.get("project_path"),
            )
        elif operation == "handoff_get":
            return await self.context_handoff_get(project_path=args.get("project_path"))
        else:
            return self._needs_clarification(
                f"Unknown context operation: {operation}",
                "Use: checkpoint_save, checkpoint_restore, checkpoint_list, verify_completion, instruction_add, instruction_reinforce, handoff_create, or handoff_get",
            )

    # NOTE: handle_momentum REMOVED - use Claude Code's native TodoWrite instead

    # NOTE: handle_think REMOVED - think tools removed (generic LLM responses weren't useful)

    # NOTE: handle_habit REMOVED - meta-tracking of tool usage adds noise without value
    # The habit_tracker is still used internally for session statistics

    async def handle_convention(self, operation: str, args: dict) -> list[TextContent]:
        """Route convention operations to existing handlers."""
        project_path = args.get("project_path", "")

        if operation == "add":
            return await self.convention_add(
                project_path=project_path,
                rule=args.get("rule", ""),
                category=args.get("category", "pattern"),
                examples=args.get("examples"),
                reason=args.get("reason"),
                importance=args.get("importance", 5),
            )
        elif operation == "get":
            return await self.convention_get(
                project_path=project_path,
                category=args.get("category"),
            )
        elif operation == "check":
            return await self.convention_check(
                project_path=project_path,
                code_or_filename=args.get("code_or_filename", ""),
            )
        elif operation == "remove":
            rule_text = args.get("rule", "")
            if not rule_text:
                return self._needs_clarification(
                    "No rule text provided",
                    "Provide the rule text (or substring) to match for removal",
                )
            response = self.conventions.remove_convention(
                project_path=project_path,
                rule_substring=rule_text,
            )
            return [TextContent(type="text", text=response.to_formatted_string())]
        else:
            return self._needs_clarification(
                f"Unknown convention operation: {operation}",
                "Use: add, get, check, or remove",
            )

    async def handle_output(self, operation: str, args: dict) -> list[TextContent]:
        """Route output operations to existing handlers."""
        if operation == "validate_code":
            return await self.output_validate_code(
                code=args.get("code", ""),
                context=args.get("context"),
            )
        elif operation == "validate_result":
            return await self.output_validate_result(
                output=args.get("output", ""),
                expected_format=args.get("expected_format"),
                should_contain=args.get("should_contain"),
                should_not_contain=args.get("should_not_contain"),
            )
        else:
            return self._needs_clarification(
                f"Unknown output operation: {operation}",
                "Use: validate_code or validate_result",
            )

    # NOTE: handle_test REMOVED - use Claude Code's native Bash tool instead

    # NOTE: handle_git REMOVED - Claude excels at commit messages natively
    # Use memory(search) to get work context if needed for commits

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def handle_session_mine(
        self, operation: str, args: dict
    ) -> list[TextContent]:
        """Route session mining operations."""
        import json as json_mod
        from dataclasses import asdict

        project_path = args.get("project_path", "")

        if operation == "search":
            from claude_engram.mining.search import search_sessions

            results = search_sessions(
                project_path,
                query=args.get("query", ""),
                limit=args.get("limit", 10),
                method=args.get("method", "hybrid"),
                since=args.get("since", ""),
                until=args.get("until", ""),
            )
            if not results:
                return [
                    TextContent(
                        type="text",
                        text="No results found. Run reindex(mode=bootstrap) to build search index.",
                    )
                ]
            lines = [f"Found {len(results)} results:"]
            for r in results:
                lines.append(f"  [{r.score:.2f}] {r.chunk_text[:150]}")
                lines.append(
                    f"    Session: {r.session_id[:12]} | {r.timestamp[:19]} | {r.msg_type}"
                )
                if r.related_files:
                    lines.append(f"    Files: {', '.join(r.related_files[:5])}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "decisions":
            from claude_engram.mining.search import find_decision

            results = find_decision(
                project_path,
                query=args.get("query", ""),
            )
            if not results:
                return [TextContent(type="text", text="No matching decisions found.")]
            lines = [f"Found {len(results)} decision(s):"]
            for r in results:
                lines.append(f"\n[{r.score:.2f}] {r.chunk_text[:200]}")
                lines.append(f"  Session: {r.session_id[:12]} | {r.timestamp[:19]}")
                if r.surrounding:
                    lines.append("  Context:")
                    for ctx in r.surrounding:
                        lines.append(f"    {ctx}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "replay":
            from claude_engram.mining.search import find_file_discussions

            results = find_file_discussions(
                project_path,
                file_path=args.get("file_path", ""),
                limit=args.get("limit", 10),
            )
            if not results:
                return [
                    TextContent(type="text", text="No discussions found for this file.")
                ]
            lines = [f"Found {len(results)} discussion(s):"]
            for r in results:
                lines.append(f"  [{r.score:.2f}] {r.chunk_text[:150]}")
                lines.append(f"    {r.timestamp[:19]} | {r.msg_type}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "struggles":
            from claude_engram.mining.patterns import detect_struggles
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            struggles = detect_struggles(index.sessions, project_root=project_path)
            if not struggles:
                return [TextContent(type="text", text="No struggle patterns detected.")]
            lines = ["Struggle areas:"]
            for s in struggles[:10]:
                lines.append(f"  {s.file_path}: {s.description}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "errors":
            from claude_engram.mining.patterns import detect_recurring_errors
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            errors = detect_recurring_errors(
                index.sessions, project_path, str(self.memory.storage_dir)
            )
            if not errors:
                return [TextContent(type="text", text="No recurring error patterns.")]
            lines = ["Recurring errors:"]
            for e in errors:
                lines.append(f"  {e.error_type}: {e.session_count} sessions")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "correlations":
            from claude_engram.mining.patterns import detect_edit_correlations
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            corrs = detect_edit_correlations(index.sessions)
            if not corrs:
                return [
                    TextContent(
                        type="text",
                        text="No edit correlations found (need 2+ sessions).",
                    )
                ]
            lines = ["Files often edited together:"]
            for c in corrs[:15]:
                lines.append(
                    f"  {c.file_a} ↔ {c.file_b} ({c.strength:.0%} correlation, {c.co_occurrence} sessions)"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "timeline":
            from claude_engram.mining.timeline import build_timeline
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            events = build_timeline(index, project_path, str(self.memory.storage_dir))
            if not events:
                return [TextContent(type="text", text="No timeline events.")]
            lines = ["Project timeline:"]
            for e in events[-20:]:  # Most recent 20
                lines.append(
                    f"  [{e.timestamp[:10]}] {e.event_type}: {e.description[:120]}"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "summaries":
            from claude_engram.mining.timeline import generate_session_summaries
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            summaries = generate_session_summaries(
                index, project_path, str(self.memory.storage_dir)
            )
            lines = [f"{len(summaries)} sessions:"]
            for s in summaries[:10]:
                files_str = ", ".join(s.files_edited[:5])
                acts = " | ".join(s.key_activities) if s.key_activities else ""
                lines.append(f"  [{s.date}] {s.duration_str} — {files_str}")
                if acts:
                    lines.append(f"    {acts}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "overview":
            from claude_engram.mining.timeline import get_project_overview
            from claude_engram.mining.session_index import resolve_project_index

            index = resolve_project_index(project_path)
            if not index:
                return [TextContent(type="text", text="No session data found.")]
            ov = get_project_overview(index, project_path)
            lines = [
                f"Sessions: {ov.total_sessions} | Messages: {ov.total_messages}",
                f"Active days: {ov.active_days} | Errors: {ov.total_errors}",
                f"Period: {ov.first_session[:10]} → {ov.last_session[:10]}",
            ]
            if ov.top_files:
                lines.append("Top files:")
                for name, count in ov.top_files[:10]:
                    lines.append(f"  {name}: {count} sessions")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "status":
            from claude_engram.mining.session_index import resolve_project_index
            from claude_engram.mining.background import get_mining_status

            index = resolve_project_index(project_path)
            status = get_mining_status()
            lines = []
            if index:
                lines.append(
                    f"Indexed: {index.get_session_count()} sessions, {index.get_total_messages()} messages"
                )
            else:
                lines.append("No index built yet.")
            lines.append(f"Miner: {status.get('status', 'unknown')}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "reindex":
            from claude_engram.mining.background import start_mining_background, get_mining_status
            import asyncio

            mode = args.get("mode", "full")
            started = start_mining_background(project_path, mode=mode)
            if not started:
                return [
                    TextContent(
                        type="text",
                        text="Mining already running. Check status with session_mine(operation='status').",
                    )
                ]

            # Poll for completion (up to 10s) instead of fire-and-forget
            for _ in range(20):
                await asyncio.sleep(0.5)
                status = get_mining_status()
                if status.get("status") == "completed":
                    result = status.get("result", {})
                    if not isinstance(result, dict):
                        result = {}
                    lines = [f"Mining completed (mode={mode}):"]
                    if result.get("sessions"):
                        lines.append(f"  Sessions indexed: {result['sessions']}")
                    if result.get("messages"):
                        lines.append(f"  Messages: {result['messages']}")
                    if result.get("extractions"):
                        lines.append(f"  Extractions: {result['extractions']} findings")
                    if result.get("embeddings"):
                        lines.append(f"  Search chunks: {result['embeddings']}")
                    return [TextContent(type="text", text="\n".join(lines))]

            # Still running after 10s — return status hint
            status = get_mining_status()
            phase = status.get("phase", "unknown")
            return [
                TextContent(
                    type="text",
                    text=f"Mining started (mode={mode}), currently in '{phase}' phase. Check session_mine(operation='status') for results.",
                )
            ]

        elif operation == "predict":
            from claude_engram.mining.predictive import (
                predict_for_file,
                format_prediction,
            )

            pred = predict_for_file(
                file_path=args.get("file_path", ""),
                project_path=project_path,
            )
            formatted = format_prediction(pred)
            if not formatted:
                return [
                    TextContent(
                        type="text",
                        text=f"No predictions for {pred.target_file} yet (patterns build up over sessions).",
                    )
                ]
            lines = [f"Predictions for {pred.target_file}:"]
            lines.append(formatted)
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "reflect":
            from claude_engram.mining.reflect import reflect_all

            insights = reflect_all(project_path, str(self.memory.storage_dir))
            if not insights:
                return [
                    TextContent(
                        type="text",
                        text="No insights generated. Needs Ollama running + 3+ recurring mistakes or patterns.",
                    )
                ]
            lines = [f"Reflected on {len(insights)} patterns:"]
            for ins in insights:
                lines.append(
                    f"\n[{ins.insight_type}] (confidence: {ins.confidence:.0%})"
                )
                lines.append(f"  {ins.content}")
                if ins.related_files:
                    lines.append(f"  Files: {', '.join(ins.related_files[:5])}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif operation == "cross_project":
            from claude_engram.mining.cross_project import analyze_cross_project

            report = analyze_cross_project(str(self.memory.storage_dir))
            lines = [
                f"Cross-project analysis: {report.total_projects} projects, {report.total_sessions} sessions",
            ]
            if report.insights:
                lines.append("\nInsights:")
                for ins in report.insights[:10]:
                    lines.append(f"  [{ins.insight_type}] {ins.description}")
                    if ins.projects_affected:
                        lines.append(
                            f"    Projects: {', '.join(ins.projects_affected)}"
                        )
            if report.tool_usage:
                top_tools = list(report.tool_usage.items())[:5]
                lines.append(
                    f"\nTop tools: {', '.join(f'{t}:{c}' for t, c in top_tools)}"
                )
            if not report.insights:
                lines.append(
                    "\nNo cross-project patterns yet (need 2+ projects with session indexes)."
                )
            return [TextContent(type="text", text="\n".join(lines))]

        else:
            return self._needs_clarification(
                f"Unknown session_mine operation: {operation}",
                "Use: search, decisions, replay, struggles, errors, correlations, timeline, summaries, overview, status, reindex, predict, cross_project",
            )

    # -------------------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------------------

    def _needs_clarification(self, reasoning: str, question: str) -> list[TextContent]:
        """Return a standard clarification response."""
        response = MiniClaudeResponse(
            status="needs_clarification",
            confidence="high",
            reasoning=reasoning,
            questions=[question],
        )
        return [TextContent(type="text", text=response.to_formatted_string())]

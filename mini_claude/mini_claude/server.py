"""
Mini Claude MCP Server

The main entry point that exposes mini_claude's capabilities to Claude Code
via the Model Context Protocol.

This file is intentionally kept as a thin routing layer.
All handler logic is in handlers.py.
"""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .handlers import Handlers
from .tool_definitions import TOOL_DEFINITIONS


# Initialize handlers (contains all tool instances)
handlers = Handlers()

# Create MCP server
server = Server("mini-claude")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Mini Claude tools."""
    return TOOL_DEFINITIONS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Route tool calls to the appropriate handler.

    This is a thin routing layer - all logic is in handlers.py.
    """
    # Route to handler based on tool name
    match name:
        case "mini_claude_status":
            return await handlers.status()

        case "scout_search":
            return await handlers.search(
                query=arguments.get("query", ""),
                directory=arguments.get("directory", ""),
                max_results=arguments.get("max_results", 10),
            )

        case "scout_analyze":
            return await handlers.analyze(
                code=arguments.get("code", ""),
                question=arguments.get("question", ""),
            )

        case "memory_remember":
            return await handlers.remember(
                content=arguments.get("content", ""),
                category=arguments.get("category", "note"),
                project_path=arguments.get("project_path"),
                relevance=arguments.get("relevance", 5),
            )

        case "memory_recall":
            return await handlers.recall(
                project_path=arguments.get("project_path"),
            )

        case "memory_forget":
            return await handlers.forget(
                project_path=arguments.get("project_path", ""),
            )

        case "file_summarize":
            return await handlers.summarize(
                file_path=arguments.get("file_path", ""),
                mode=arguments.get("mode", "quick"),
            )

        case "deps_map":
            return await handlers.deps_map(
                file_path=arguments.get("file_path", ""),
                project_root=arguments.get("project_root"),
                include_reverse=arguments.get("include_reverse", False),
            )

        case "session_start":
            return await handlers.session_start(
                project_path=arguments.get("project_path", ""),
            )

        case "impact_analyze":
            return await handlers.impact_analyze(
                file_path=arguments.get("file_path", ""),
                project_root=arguments.get("project_root", ""),
                proposed_changes=arguments.get("proposed_changes"),
            )

        case "convention_add":
            return await handlers.convention_add(
                project_path=arguments.get("project_path", ""),
                rule=arguments.get("rule", ""),
                category=arguments.get("category", "pattern"),
                examples=arguments.get("examples"),
                reason=arguments.get("reason"),
                importance=arguments.get("importance", 5),
            )

        case "convention_get":
            return await handlers.convention_get(
                project_path=arguments.get("project_path", ""),
                category=arguments.get("category"),
            )

        case "convention_check":
            return await handlers.convention_check(
                project_path=arguments.get("project_path", ""),
                code_or_filename=arguments.get("code_or_filename", ""),
            )

        case "work_log_mistake":
            return await handlers.work_log_mistake(
                description=arguments.get("description", ""),
                file_path=arguments.get("file_path"),
                how_to_avoid=arguments.get("how_to_avoid"),
            )

        case "work_log_decision":
            return await handlers.work_log_decision(
                decision=arguments.get("decision", ""),
                reason=arguments.get("reason", ""),
                alternatives=arguments.get("alternatives"),
            )

        case "work_session_summary":
            return await handlers.work_session_summary()

        case "work_pre_edit_check":
            return await handlers.work_pre_edit_check(
                file_path=arguments.get("file_path", ""),
            )

        case "work_save_session":
            return await handlers.work_save_session()

        # Code Quality Checker
        case "code_quality_check":
            return await handlers.code_quality_check(
                code=arguments.get("code", ""),
                language=arguments.get("language", "python"),
            )

        # Loop Detector
        case "loop_record_edit":
            return await handlers.loop_record_edit(
                file_path=arguments.get("file_path", ""),
                description=arguments.get("description", ""),
            )

        case "loop_check_before_edit":
            return await handlers.loop_check_before_edit(
                file_path=arguments.get("file_path", ""),
            )

        case "loop_record_test":
            return await handlers.loop_record_test(
                passed=arguments.get("passed", False),
                error_message=arguments.get("error_message", ""),
            )

        case "loop_status":
            return await handlers.loop_status()

        # Scope Guard
        case "scope_declare":
            return await handlers.scope_declare(
                task_description=arguments.get("task_description", ""),
                in_scope_files=arguments.get("in_scope_files", []),
                in_scope_patterns=arguments.get("in_scope_patterns"),
                out_of_scope_files=arguments.get("out_of_scope_files"),
                reason=arguments.get("reason", ""),
            )

        case "scope_check":
            return await handlers.scope_check(
                file_path=arguments.get("file_path", ""),
            )

        case "scope_expand":
            return await handlers.scope_expand(
                files_to_add=arguments.get("files_to_add", []),
                reason=arguments.get("reason", ""),
            )

        case "scope_status":
            return await handlers.scope_status()

        case "scope_clear":
            return await handlers.scope_clear()

        # Context Guard - Checkpoints & Task Continuity
        case "context_checkpoint_save":
            return await handlers.context_checkpoint_save(
                task_description=arguments.get("task_description", ""),
                current_step=arguments.get("current_step", ""),
                completed_steps=arguments.get("completed_steps", []),
                pending_steps=arguments.get("pending_steps", []),
                files_involved=arguments.get("files_involved", []),
                key_decisions=arguments.get("key_decisions"),
                blockers=arguments.get("blockers"),
                project_path=arguments.get("project_path"),
            )

        case "context_checkpoint_restore":
            return await handlers.context_checkpoint_restore(
                task_id=arguments.get("task_id"),
            )

        case "context_checkpoint_list":
            return await handlers.context_checkpoint_list()

        case "context_instruction_add":
            return await handlers.context_instruction_add(
                instruction=arguments.get("instruction", ""),
                reason=arguments.get("reason", ""),
                importance=arguments.get("importance", 10),
            )

        case "context_instruction_reinforce":
            return await handlers.context_instruction_reinforce()

        case "context_claim_completion":
            return await handlers.context_claim_completion(
                task=arguments.get("task", ""),
                evidence=arguments.get("evidence"),
            )

        case "context_self_check":
            return await handlers.context_self_check(
                task=arguments.get("task", ""),
                verification_steps=arguments.get("verification_steps", []),
            )

        case "context_handoff_create":
            return await handlers.context_handoff_create(
                summary=arguments.get("summary", ""),
                next_steps=arguments.get("next_steps", []),
                context_needed=arguments.get("context_needed", []),
                warnings=arguments.get("warnings"),
                project_path=arguments.get("project_path"),
            )

        case "context_handoff_get":
            return await handlers.context_handoff_get()

        # Output Validator
        case "output_validate_code":
            return await handlers.output_validate_code(
                code=arguments.get("code", ""),
                context=arguments.get("context"),
            )

        case "output_validate_result":
            return await handlers.output_validate_result(
                output=arguments.get("output", ""),
                expected_format=arguments.get("expected_format"),
                should_contain=arguments.get("should_contain"),
                should_not_contain=arguments.get("should_not_contain"),
            )

        case "test_run":
            return await handlers.test_run(
                project_dir=arguments.get("project_dir", ""),
                test_command=arguments.get("test_command"),
                timeout=arguments.get("timeout", 300),
            )

        case "test_can_claim_completion":
            return await handlers.test_can_claim_completion()

        case "git_generate_commit_message":
            return await handlers.git_generate_commit_message(
                project_dir=arguments.get("project_dir", ""),
            )

        case "git_auto_commit":
            return await handlers.git_auto_commit(
                project_dir=arguments.get("project_dir", ""),
                message=arguments.get("message"),
                files=arguments.get("files"),
            )

        case "momentum_start_task":
            return await handlers.momentum_start_task(
                task_description=arguments.get("task_description", ""),
                expected_steps=arguments.get("expected_steps", []),
            )

        case "momentum_complete_step":
            return await handlers.momentum_complete_step(
                step=arguments.get("step", ""),
            )

        case "momentum_check":
            return await handlers.momentum_check()

        case "momentum_finish_task":
            return await handlers.momentum_finish_task()

        case "momentum_status":
            return await handlers.momentum_status()

        case "think_research":
            return await handlers.think_research(
                question=arguments.get("question", ""),
                context=arguments.get("context"),
                depth=arguments.get("depth", "medium"),
                project_path=arguments.get("project_path"),
            )

        case "think_compare":
            return await handlers.think_compare(
                options=arguments.get("options", []),
                context=arguments.get("context", ""),
                criteria=arguments.get("criteria"),
            )

        case "think_challenge":
            return await handlers.think_challenge(
                assumption=arguments.get("assumption", ""),
                context=arguments.get("context"),
            )

        case "think_explore":
            return await handlers.think_explore(
                problem=arguments.get("problem", ""),
                constraints=arguments.get("constraints"),
                project_path=arguments.get("project_path"),
            )

        case "think_best_practice":
            return await handlers.think_best_practice(
                topic=arguments.get("topic", ""),
                language_or_framework=arguments.get("language_or_framework"),
                year=arguments.get("year", 2026),
            )

        # Habit Tracker Tools
        case "habit_get_stats":
            return await handlers.habit_get_stats(
                days=arguments.get("days", 7),
            )

        case "habit_get_feedback":
            return await handlers.habit_get_feedback()

        case "habit_session_summary":
            return await handlers.habit_session_summary(
                project_path=arguments.get("project_path"),
            )

        # -------------------------------------------------------------------------
        # New Tools: diff_review, think_audit, code_pattern_check
        # -------------------------------------------------------------------------

        case "diff_review":
            return await handlers.diff_review(
                project_dir=arguments.get("project_dir", ""),
                staged_only=arguments.get("staged_only", False),
            )

        case "think_audit":
            return await handlers.think_audit(
                file_path=arguments.get("file_path", ""),
                focus_areas=arguments.get("focus_areas"),
                min_severity=arguments.get("min_severity"),
            )

        case "audit_batch":
            return await handlers.audit_batch(
                file_paths=arguments.get("file_paths", []),
                min_severity=arguments.get("min_severity"),
            )

        case "find_similar_issues":
            return await handlers.find_similar_issues(
                issue_pattern=arguments.get("issue_pattern", ""),
                project_path=arguments.get("project_path", ""),
                file_extensions=arguments.get("file_extensions"),
            )

        case "code_pattern_check":
            return await handlers.code_pattern_check(
                project_path=arguments.get("project_path", ""),
                code=arguments.get("code", ""),
            )

        case _:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


def main():
    """Main entry point."""
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()

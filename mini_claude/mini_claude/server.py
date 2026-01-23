"""
Mini Claude MCP Server

The main entry point that exposes mini_claude's capabilities to Claude Code
via the Model Context Protocol.

This file is intentionally kept as a thin routing layer.
All handler logic is in handlers.py.

v2: Uses combined tools for 75% token reduction (66 tools -> 25 tools)
"""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .handlers import Handlers
from .tool_definitions_v2 import TOOL_DEFINITIONS


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
        # =====================================================================
        # ESSENTIAL TOOLS (always needed)
        # =====================================================================

        case "mini_claude_status":
            return await handlers.status()

        case "session_start":
            return await handlers.session_start(
                project_path=arguments.get("project_path", ""),
            )

        case "session_end":
            return await handlers.session_end(
                project_path=arguments.get("project_path"),
            )

        case "pre_edit_check":
            return await handlers.pre_edit_check(
                file_path=arguments.get("file_path", ""),
            )

        # =====================================================================
        # COMBINED TOOLS (grouped by domain)
        # =====================================================================

        case "memory":
            return await handlers.handle_memory(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "work":
            return await handlers.handle_work(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "scope":
            return await handlers.handle_scope(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "loop":
            return await handlers.handle_loop(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "context":
            return await handlers.handle_context(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        # NOTE: "momentum" case REMOVED - use TodoWrite instead

        case "think":
            return await handlers.handle_think(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "habit":
            return await handlers.handle_habit(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "convention":
            return await handlers.handle_convention(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        case "output":
            return await handlers.handle_output(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        # NOTE: "test" case REMOVED - use Bash instead

        case "git":
            return await handlers.handle_git(
                operation=arguments.get("operation", ""),
                args=arguments,
            )

        # =====================================================================
        # STANDALONE TOOLS (unique functionality)
        # =====================================================================

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

        case "impact_analyze":
            return await handlers.impact_analyze(
                file_path=arguments.get("file_path", ""),
                project_root=arguments.get("project_root", ""),
                proposed_changes=arguments.get("proposed_changes"),
            )

        case "code_quality_check":
            return await handlers.code_quality_check(
                code=arguments.get("code", ""),
                language=arguments.get("language", "python"),
            )

        case "code_pattern_check":
            return await handlers.code_pattern_check(
                project_path=arguments.get("project_path", ""),
                code=arguments.get("code", ""),
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
                exclude_paths=arguments.get("exclude_paths"),
                exclude_strings=arguments.get("exclude_strings", True),
            )

        case _:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


def main():
    """Main entry point."""
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    try:
        asyncio.run(run())
    finally:
        # Clean up resources on shutdown
        handlers.close()


if __name__ == "__main__":
    main()

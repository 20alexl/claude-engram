"""
Mini Claude Tool Definitions v2 - Optimized for token efficiency

Combines 66 tools into ~20 tools using operation parameters.
Reduces token overhead from ~20K to ~5K per message.
"""

from mcp.types import Tool


TOOL_DEFINITIONS = [
    # =========================================================================
    # ESSENTIAL TOOLS (always needed)
    # =========================================================================

    Tool(
        name="mini_claude_status",
        description="Check Mini Claude health. Returns: status, model, memory stats.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),

    Tool(
        name="session_start",
        description="START EVERY SESSION. Loads memories, past mistakes, checkpoints. Auto-cleans duplicates.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Project directory path"}
            },
            "required": ["project_path"],
        },
    ),

    Tool(
        name="session_end",
        description="END EVERY SESSION. Saves work summary, decisions, mistakes to memory.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Project directory (optional)"}
            },
            "required": [],
        },
    ),

    Tool(
        name="pre_edit_check",
        description="Run BEFORE editing important files. Checks: past mistakes, loop risk, scope violations.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "File about to edit"}
            },
            "required": ["file_path"],
        },
    ),

    # =========================================================================
    # COMBINED TOOLS (grouped by domain)
    # =========================================================================

    Tool(
        name="memory",
        description="""Memory operations. Operations:
- remember: Store discovery/note (content, category, relevance)
- recall: Get all memories for project
- forget: Clear project memories
- search: Find by file/tags/query (file_path, tags, query, limit)
- clusters: View grouped memories (cluster_id to expand)
- cleanup: Dedupe/cluster/decay (dry_run, min_relevance, max_age_days)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["remember", "recall", "forget", "search", "clusters", "cleanup"],
                    "description": "Operation to perform"
                },
                "project_path": {"type": "string", "description": "Project directory"},
                "content": {"type": "string", "description": "For remember: what to store"},
                "category": {"type": "string", "enum": ["discovery", "priority", "note"], "description": "For remember: type"},
                "relevance": {"type": "integer", "description": "For remember: importance 1-10"},
                "file_path": {"type": "string", "description": "For search: filter by file"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "For search: filter by tags"},
                "query": {"type": "string", "description": "For search: keyword search"},
                "limit": {"type": "integer", "description": "For search: max results"},
                "cluster_id": {"type": "string", "description": "For clusters: expand specific cluster"},
                "dry_run": {"type": "boolean", "description": "For cleanup: preview only"},
                "min_relevance": {"type": "integer", "description": "For cleanup: min to keep"},
                "max_age_days": {"type": "integer", "description": "For cleanup: decay threshold"},
            },
            "required": ["operation", "project_path"],
        },
    ),

    Tool(
        name="work",
        description="""Work tracking. Operations:
- log_mistake: Record error (description, file_path, how_to_avoid)
- log_decision: Record choice (decision, reason, alternatives)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["log_mistake", "log_decision"],
                    "description": "Operation"
                },
                "description": {"type": "string", "description": "For log_mistake: what went wrong"},
                "file_path": {"type": "string", "description": "For log_mistake: affected file"},
                "how_to_avoid": {"type": "string", "description": "For log_mistake: prevention"},
                "decision": {"type": "string", "description": "For log_decision: what was decided"},
                "reason": {"type": "string", "description": "For log_decision: why"},
                "alternatives": {"type": "array", "items": {"type": "string"}, "description": "For log_decision: other options"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="scope",
        description="""Scope guard for multi-file tasks. Operations:
- declare: Set task scope (task_description, in_scope_files, in_scope_patterns)
- check: Verify file is in scope (file_path)
- expand: Add files to scope (files_to_add, reason)
- status: Get violations
- clear: Reset scope""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["declare", "check", "expand", "status", "clear"],
                    "description": "Operation"
                },
                "task_description": {"type": "string", "description": "For declare: task being done"},
                "in_scope_files": {"type": "array", "items": {"type": "string"}, "description": "For declare: allowed files"},
                "in_scope_patterns": {"type": "array", "items": {"type": "string"}, "description": "For declare: glob patterns"},
                "file_path": {"type": "string", "description": "For check: file to verify"},
                "files_to_add": {"type": "array", "items": {"type": "string"}, "description": "For expand: files to add"},
                "reason": {"type": "string", "description": "For expand: why adding"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="loop",
        description="""Loop detection to prevent death spirals. Operations:
- record_edit: Log file edit (file_path, description)
- record_test: Log test result (passed, error_message)
- check: Check if safe to edit (file_path)
- status: Get edit counts and warnings""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["record_edit", "record_test", "check", "status"],
                    "description": "Operation"
                },
                "file_path": {"type": "string", "description": "File being edited"},
                "description": {"type": "string", "description": "For record_edit: what changed"},
                "passed": {"type": "boolean", "description": "For record_test: did tests pass"},
                "error_message": {"type": "string", "description": "For record_test: error if failed"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="context",
        description="""Context protection for long tasks. Operations:
- checkpoint_save: Save task state (task_description, current_step, completed_steps, pending_steps, files_involved)
- checkpoint_restore: Restore last checkpoint (task_id optional)
- checkpoint_list: List saved checkpoints
- verify_completion: Claim task done + verify (task, evidence, verification_steps)
- instruction_add: Register critical instruction (instruction, reason, importance)
- instruction_reinforce: Get instructions to remember""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["checkpoint_save", "checkpoint_restore", "checkpoint_list", "verify_completion", "instruction_add", "instruction_reinforce"],
                    "description": "Operation"
                },
                "task_description": {"type": "string"},
                "current_step": {"type": "string"},
                "completed_steps": {"type": "array", "items": {"type": "string"}},
                "pending_steps": {"type": "array", "items": {"type": "string"}},
                "files_involved": {"type": "array", "items": {"type": "string"}},
                "task_id": {"type": "string", "description": "For restore: specific checkpoint"},
                "task": {"type": "string", "description": "For verify: task to verify"},
                "evidence": {"type": "array", "items": {"type": "string"}, "description": "For verify: proof"},
                "verification_steps": {"type": "array", "items": {"type": "string"}, "description": "For verify: checks"},
                "instruction": {"type": "string", "description": "For instruction_add"},
                "reason": {"type": "string"},
                "importance": {"type": "integer"},
                "project_path": {"type": "string"},
                "handoff_summary": {"type": "string"},
                "handoff_context_needed": {"type": "array", "items": {"type": "string"}},
                "handoff_warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="momentum",
        description="""Track multi-step tasks. Operations:
- start: Begin tracking (task_description, expected_steps)
- complete: Mark step done (step)
- check: Check if momentum maintained
- finish: Mark task complete
- status: Get current progress""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["start", "complete", "check", "finish", "status"],
                    "description": "Operation"
                },
                "task_description": {"type": "string"},
                "expected_steps": {"type": "array", "items": {"type": "string"}},
                "step": {"type": "string", "description": "For complete: step finished"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="think",
        description="""Local LLM thinking tools. Operations:
- research: Search codebase + reason (question, project_path, depth)
- compare: Evaluate options (options, context, criteria)
- challenge: Devil's advocate (assumption, context)
- explore: Solution space (problem, constraints, project_path)
- best_practice: Find patterns (topic, language_or_framework)
- audit: Check file for issues (file_path, focus_areas, min_severity)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["research", "compare", "challenge", "explore", "best_practice", "audit"],
                    "description": "Operation"
                },
                "question": {"type": "string"},
                "project_path": {"type": "string"},
                "depth": {"type": "string", "enum": ["quick", "medium", "deep"]},
                "options": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
                "criteria": {"type": "array", "items": {"type": "string"}},
                "assumption": {"type": "string"},
                "problem": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "topic": {"type": "string"},
                "language_or_framework": {"type": "string"},
                "file_path": {"type": "string"},
                "focus_areas": {"type": "array", "items": {"type": "string"}},
                "min_severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="habit",
        description="""Habit tracking. Operations:
- stats: Get habit statistics (days)
- feedback: Get gamified feedback
- summary: Session summary for handoff (project_path)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["stats", "feedback", "summary"],
                    "description": "Operation"
                },
                "days": {"type": "integer", "description": "For stats: days to analyze"},
                "project_path": {"type": "string"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="convention",
        description="""Project conventions. Operations:
- add: Store rule (project_path, rule, category, reason, examples, importance)
- get: Get rules (project_path, category)
- check: Check code/filename (project_path, code_or_filename)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "get", "check"],
                    "description": "Operation"
                },
                "project_path": {"type": "string"},
                "rule": {"type": "string"},
                "category": {"type": "string", "enum": ["naming", "architecture", "style", "pattern", "avoid"]},
                "reason": {"type": "string"},
                "examples": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "integer"},
                "code_or_filename": {"type": "string"},
            },
            "required": ["operation", "project_path"],
        },
    ),

    Tool(
        name="output",
        description="""Output validation. Operations:
- validate_code: Check for fake/silent failures (code, context)
- validate_result: Check output for fakes (output, expected_format, should_contain, should_not_contain)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["validate_code", "validate_result"],
                    "description": "Operation"
                },
                "code": {"type": "string"},
                "context": {"type": "string"},
                "output": {"type": "string"},
                "expected_format": {"type": "string"},
                "should_contain": {"type": "array", "items": {"type": "string"}},
                "should_not_contain": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="test",
        description="""Test running. Operations:
- run: Auto-detect and run tests (project_dir, test_command, timeout)
- can_claim: Check if tests allow completion claim""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["run", "can_claim"],
                    "description": "Operation"
                },
                "project_dir": {"type": "string"},
                "test_command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["operation"],
        },
    ),

    Tool(
        name="git",
        description="""Git helpers. Operations:
- commit_message: Generate from work logs (project_dir)
- commit: Auto-commit with context (project_dir, message, files)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["commit_message", "commit"],
                    "description": "Operation"
                },
                "project_dir": {"type": "string"},
                "message": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["operation", "project_dir"],
        },
    ),

    # =========================================================================
    # STANDALONE TOOLS (unique functionality, keep separate)
    # =========================================================================

    Tool(
        name="scout_search",
        description="Search codebase semantically. Returns findings with files, lines, connections.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "directory": {"type": "string", "description": "Directory to search"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query", "directory"],
        },
    ),

    Tool(
        name="scout_analyze",
        description="Analyze code with local LLM. Provide code and question.",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["code", "question"],
        },
    ),

    Tool(
        name="file_summarize",
        description="Summarize file purpose. Modes: quick (pattern-based) or detailed (LLM).",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "mode": {"type": "string", "enum": ["quick", "detailed"], "default": "quick"},
            },
            "required": ["file_path"],
        },
    ),

    Tool(
        name="deps_map",
        description="Map file dependencies. Shows imports and optionally reverse deps.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "include_reverse": {"type": "boolean", "default": False},
                "project_root": {"type": "string"},
            },
            "required": ["file_path"],
        },
    ),

    Tool(
        name="impact_analyze",
        description="Analyze change impact. Shows dependents, exports, risk level.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "project_root": {"type": "string"},
                "proposed_changes": {"type": "string"},
            },
            "required": ["file_path", "project_root"],
        },
    ),

    Tool(
        name="code_quality_check",
        description="Check code for AI slop: long functions, vague names, deep nesting.",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "default": "python"},
            },
            "required": ["code"],
        },
    ),

    Tool(
        name="code_pattern_check",
        description="Check code against stored conventions using LLM.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["project_path", "code"],
        },
    ),

    Tool(
        name="audit_batch",
        description="Audit multiple files for issues. Supports glob patterns.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"}},
                "min_severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            },
            "required": ["file_paths"],
        },
    ),

    Tool(
        name="find_similar_issues",
        description="Search codebase for bug pattern (e.g., 'except:\\s*pass').",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_pattern": {"type": "string", "description": "Regex pattern"},
                "project_path": {"type": "string"},
                "file_extensions": {"type": "array", "items": {"type": "string"}},
                "exclude_paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["issue_pattern", "project_path"],
        },
    ),
]

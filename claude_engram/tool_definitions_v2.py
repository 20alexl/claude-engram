"""
Claude Engram Tool Definitions v2 - Optimized for token efficiency

Combines 66 tools into ~20 tools using operation parameters.
Reduces token overhead from ~20K to ~5K per message.
"""

from mcp.types import Tool, ToolAnnotations


TOOL_DEFINITIONS = [
    # =========================================================================
    # ESSENTIAL TOOLS (always needed)
    # =========================================================================
    Tool(
        name="claude_engram_status",
        description="Check Claude Engram health. Returns: status, model, memory stats.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="session_start",
        description="RARELY NEEDED — the SessionStart hook auto-loads context every session. Call only for an explicit deep re-load (full memories + checkpoints + decisions + health).",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory path",
                }
            },
            "required": ["project_path"],
        },
    ),
    Tool(
        name="session_end",
        description="RARELY NEEDED — Stop/SessionEnd hooks handle teardown automatically. Just a summary recap; memories save without it.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory (optional)",
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="pre_edit_check",
        description="RARELY NEEDED — the PreToolUse hook auto-runs this before every edit. Call manually only for an explicit impact check (past mistakes, loop risk, scope violations).",
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
- remember: Store a note (just content - category/relevance optional)
- recall: Get all memories for project
- forget: Clear project memories
- search: Find by file/tags/query (file_path, tags, query, limit)
- cleanup: Dedupe/cluster/decay (dry_run, min_relevance, max_age_days)
- add_rule: Add permanent rule (content, reason) - never decays
- list_rules: Get all rules for project
- modify: Edit memory (memory_id, content, relevance, category)
- delete: Remove single memory (memory_id)
- batch_delete: Bulk delete by IDs (memory_ids) or by category. Rules/mistakes protected from category delete.
- promote: Promote memory to rule (memory_id, reason)
- recent: Get recent memories newest first (category, limit)
- archive: Move old inactive memories to cold storage (dry_run to preview)
- restore: Bring archived memory back to active (memory_id)
- archive_search: Search archived memories (query, tags, limit)
- archive_status: Show hot vs archived memory counts
- hybrid_search: Semantic + keyword + scored search (query, file_path, tags, limit). Best retrieval.
- embed_all: Generate AllMiniLM embeddings for all memories (enables hybrid_search)
- list_mistakes: View tracked mistakes with IDs, file associations, and age
- acknowledge_mistake: Archive a learned mistake so it stops appearing in pre-edit warnings (memory_id)""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "remember",
                        "recall",
                        "forget",
                        "search",
                        "cleanup",
                        "add_rule",
                        "list_rules",
                        "modify",
                        "delete",
                        "batch_delete",
                        "promote",
                        "recent",
                        "archive",
                        "restore",
                        "archive_search",
                        "archive_status",
                        "hybrid_search",
                        "embed_all",
                        "list_mistakes",
                        "acknowledge_mistake",
                    ],
                    "description": "Operation to perform",
                },
                "project_path": {"type": "string", "description": "Project directory"},
                "content": {
                    "type": "string",
                    "description": "For remember/add_rule/modify: content",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "discovery",
                        "priority",
                        "note",
                        "rule",
                        "mistake",
                        "context",
                    ],
                    "description": "For remember/modify/batch_delete/recent: memory category",
                },
                "relevance": {
                    "type": "integer",
                    "description": "For remember/modify: importance 1-10",
                },
                "file_path": {
                    "type": "string",
                    "description": "For search: filter by file",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For search: filter by tags",
                },
                "query": {
                    "type": "string",
                    "description": "For search: keyword search",
                },
                "limit": {
                    "type": "integer",
                    "description": "For search/recent: max results",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "For cleanup/archive: preview only",
                },
                "min_relevance": {
                    "type": "integer",
                    "description": "For cleanup: min to keep",
                },
                "max_age_days": {
                    "type": "integer",
                    "description": "For cleanup: decay threshold",
                },
                "memory_id": {
                    "type": "string",
                    "description": "For modify/delete/promote: memory ID",
                },
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For batch_delete: list of memory IDs to delete",
                },
                "reason": {
                    "type": "string",
                    "description": "For add_rule/promote: why this rule",
                },
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
                    "description": "Operation",
                },
                "description": {
                    "type": "string",
                    "description": "For log_mistake: what went wrong",
                },
                "file_path": {
                    "type": "string",
                    "description": "For log_mistake: affected file",
                },
                "how_to_avoid": {
                    "type": "string",
                    "description": "For log_mistake: prevention",
                },
                "decision": {
                    "type": "string",
                    "description": "For log_decision: what was decided",
                },
                "reason": {"type": "string", "description": "For log_decision: why"},
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For log_decision: other options",
                },
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
                    "description": "Operation",
                },
                "task_description": {
                    "type": "string",
                    "description": "For declare: task being done",
                },
                "in_scope_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For declare: allowed files",
                },
                "in_scope_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For declare: glob patterns",
                },
                "file_path": {
                    "type": "string",
                    "description": "For check: file to verify",
                },
                "files_to_add": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For expand: files to add",
                },
                "reason": {"type": "string", "description": "For expand: why adding"},
            },
            "required": ["operation"],
        },
    ),
    # NOTE: "loop" tool REMOVED - loop detection is hook-automatic: edits and
    # test results are tracked per-session by the PreToolUse/PostToolUse hooks,
    # which warn on real spirals (repeat edits with failing tests).
    Tool(
        name="context",
        description="""Context protection for long tasks. Checkpoint and handoff are ONE construct (a durable ring) — checkpoint_* are the primary names; handoff_* are deprecated aliases kept for back-compat. Operations:
- checkpoint_save: Save task/session state (task_description, current_step, completed_steps, pending_steps [= next steps], files_involved; optional handoff_summary/handoff_context_needed/handoff_warnings for the next session). Emits HANDOFF.md when handoff content is present.
- checkpoint_restore: Restore a checkpoint (index=0 latest, index=N older from history; task_id optional)
- checkpoint_list: List the unified checkpoint/handoff history newest-first (index, age, kind, summary), retrievable via checkpoint_restore index=N
- verify_completion: Claim task done + verify (task, evidence, verification_steps)
- handoff_create: [deprecated alias of checkpoint_save] handoff_summary, next_steps, handoff_context_needed, handoff_warnings
- handoff_get: [deprecated alias of checkpoint_restore] retrieve by index (0 latest, N older)
- handoff_list: [deprecated alias of checkpoint_list] list history newest-first""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "checkpoint_save",
                        "checkpoint_restore",
                        "checkpoint_list",
                        "verify_completion",
                        "handoff_create",
                        "handoff_get",
                        "handoff_list",
                    ],
                    "description": "Which context operation to perform",
                },
                "task_description": {
                    "type": "string",
                    "description": "For checkpoint_save: what task is in progress",
                },
                "current_step": {
                    "type": "string",
                    "description": "For checkpoint_save: which step you're currently on",
                },
                "completed_steps": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For checkpoint_save: list of completed steps",
                },
                "pending_steps": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For checkpoint_save: list of remaining steps",
                },
                "files_involved": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For checkpoint_save: files being worked on",
                },
                "task_id": {
                    "type": "string",
                    "description": "For restore: specific checkpoint",
                },
                "index": {
                    "type": "integer",
                    "description": "For checkpoint_restore/handoff_get: 0 = latest, N>0 = older entry from history (see checkpoint_list)",
                },
                "task": {"type": "string", "description": "For verify: task to verify"},
                "evidence": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For verify: proof",
                },
                "verification_steps": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For verify: checks",
                },
                "project_path": {
                    "type": "string",
                    "description": "Project directory path",
                },
                "handoff_summary": {
                    "type": "string",
                    "description": "For handoff_create: summary for next session",
                },
                "next_steps": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For handoff_create: what to do next",
                },
                "handoff_context_needed": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For handoff_create: context the next session needs",
                },
                "handoff_warnings": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "For handoff_create: warnings for next session",
                },
            },
            "required": ["operation"],
        },
    ),
    # NOTE: momentum tool REMOVED - redundant with Claude Code's native TodoWrite
    # Use TodoWrite for task tracking instead
    # NOTE: think tool REMOVED - generic LLM responses weren't useful enough
    # Scout tools (semantic search/analysis) are still available
    # NOTE: habit tool REMOVED - meta-tracking of tool usage adds noise without value
    Tool(
        name="convention",
        description="""Manage project coding conventions and style rules. Stores rules per-project with categories, checks code against them with deterministic pattern matching, and enforces consistency across the codebase. Operations:
- add: Store a new convention rule with category and reasoning
- get: Retrieve all conventions, optionally filtered by category
- check: Validate code or a filename against stored conventions (deterministic pattern check)
- remove: Delete a convention rule by matching its text""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "get", "check", "remove"],
                    "description": "Which convention operation to perform",
                },
                "project_path": {
                    "type": "string",
                    "description": "Absolute path to the project directory",
                },
                "rule": {
                    "type": "string",
                    "description": "For add/remove: the convention rule text (e.g., 'Always use snake_case for function names')",
                },
                "category": {
                    "type": "string",
                    "enum": ["naming", "architecture", "style", "pattern", "avoid"],
                    "description": "For add/get: convention category to organize rules",
                },
                "reason": {
                    "type": "string",
                    "description": "For add: why this convention exists (e.g., 'Consistency with stdlib')",
                },
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For add: code examples showing correct usage",
                },
                "importance": {
                    "type": "integer",
                    "description": "For add: priority 1-10, higher = more important to enforce",
                },
                "code_or_filename": {
                    "type": "string",
                    "description": "For check: code snippet or filename to validate against conventions",
                },
            },
            "required": ["operation", "project_path"],
        },
    ),
    # NOTE: output tool REMOVED - regex stub duplicating audit_batch's inline
    # mode; zero recorded use
    # NOTE: test tool REMOVED - redundant with Claude Code's native Bash
    # Use Bash to run tests directly: pytest, npm test, etc.
    # NOTE: git tool REMOVED - Claude excels at commit messages natively
    # Use memory(search) to get work context if needed for commits
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
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of results to return",
                },
            },
            "required": ["query", "directory"],
        },
    ),
    # NOTE: scout_analyze REMOVED - "paste code, ask the local LLM" had zero
    # recorded use; the agent reads code better than a 12B commentary pass
    Tool(
        name="file_summarize",
        description="Summarize a file's purpose, exports, and role in the project using structural analysis (imports, classes, functions). Returns: purpose, key exports, dependencies, and complexity estimate.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to summarize",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="deps_map",
        description="Map a file's dependency graph. Parses imports to find what a file depends on (forward deps) and optionally what depends on it (reverse deps). Useful before refactoring to understand blast radius. Returns: imports list, dependency tree, and optionally reverse dependents.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to analyze",
                },
                "include_reverse": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, also find all files that import this file (reverse dependencies)",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root directory for resolving relative imports",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="impact_analyze",
        description="Analyze the impact of changing a file before making edits. Scans dependents, exported symbols, and usage patterns to estimate risk level (low/medium/high/critical). Returns: affected files, exported symbols at risk, suggested test targets, and overall risk assessment.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file being changed",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root directory for scanning dependents",
                },
                "proposed_changes": {
                    "type": "string",
                    "description": "Description of planned changes (helps assess which exports are affected)",
                },
            },
            "required": ["file_path", "project_root"],
        },
    ),
    Tool(
        name="audit_batch",
        description="Audit code for quality issues. Two modes: pass file_paths (paths or globs like 'src/**/*.py') to audit files on disk for bugs, missing error handling, security issues, TODOs, and anti-patterns; OR pass code (+language) for a fast, no-I/O structural/naming lint of an inline snippet (long functions, vague names, deep nesting, too many params). Returns issues with severity, line numbers, and fix suggestions.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files mode: file paths or glob patterns to audit (e.g., ['src/auth.py', 'src/models/*.py'])",
                },
                "min_severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Files mode: minimum severity to report: 'critical' (bugs only), 'warning' (bugs + smells), 'info' (everything)",
                },
                "code": {
                    "type": "string",
                    "description": "Inline mode: code snippet to lint for structural/naming quality (instead of file_paths)",
                },
                "language": {
                    "type": "string",
                    "default": "python",
                    "description": "Inline mode: language for the snippet (python, javascript, typescript, go, rust)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="find_similar_issues",
        description="Search an entire codebase for a regex bug pattern. Finds all occurrences of anti-patterns like bare excepts, hardcoded secrets, or missing null checks. Returns: matching files with line numbers, context snippets, and match count.",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for (e.g., 'except:\\s*pass', 'TODO|FIXME|HACK', 'password\\s*=\\s*[\"\\']')",
                },
                "project_path": {
                    "type": "string",
                    "description": "Absolute path to the project root to search",
                },
                "file_extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to include (e.g., ['.py', '.js']). Empty means all files",
                },
                "exclude_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directory patterns to skip (e.g., ['node_modules', 'venv', '__pycache__'])",
                },
            },
            "required": ["issue_pattern", "project_path"],
        },
    ),
    # =========================================================================
    # SESSION MINING (search history, find decisions, detect patterns)
    # =========================================================================
    Tool(
        name="session_mine",
        description="""Mine session history. Operations:
- search: Search across past conversations (query, project_path, limit, method=hybrid|semantic|keyword, kind=decision|next-step|error|narration to filter hits by type)
- decisions: Find when/why a decision was made (query, project_path)
- replay: Find discussions about a file (file_path, project_path)
- struggles: Files/areas with repeated difficulty (project_path)
- errors: Recurring error patterns across sessions (project_path)
- correlations: Files always edited together (project_path)
- timeline: Project development timeline (project_path)
- summaries: Auto-generated session summaries (project_path)
- overview: High-level project stats (project_path)
- status: Mining index coverage (project_path)
- reindex: Trigger background re-indexing (project_path, mode=post_session|bootstrap|full)
- predict: Predict context needed for a file edit (file_path, project_path)
- cross_project: Patterns across all projects (no project_path needed)
- reflect: how engram is doing — injection precision (which context kinds precede passing tests) + LLM-synthesized insights from recurring mistakes/patterns
- commitments: what you said you'd do THIS session and whether it's done — scans the LIVE transcript (the one the post-session index can't see) for deferred open-loops + recent in-flight actions. Run before asking the user "what next?" or on resume.""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "search",
                        "decisions",
                        "replay",
                        "struggles",
                        "errors",
                        "correlations",
                        "timeline",
                        "summaries",
                        "overview",
                        "status",
                        "reindex",
                        "predict",
                        "cross_project",
                        "reflect",
                        "commitments",
                    ],
                    "description": "Operation to perform",
                },
                "project_path": {"type": "string", "description": "Project directory"},
                "query": {
                    "type": "string",
                    "description": "For search/decisions: search query",
                },
                "file_path": {
                    "type": "string",
                    "description": "For replay: file to find discussions about",
                },
                "limit": {"type": "integer", "description": "Max results (default 10)"},
                "method": {
                    "type": "string",
                    "enum": ["hybrid", "semantic", "keyword"],
                    "description": "For search: search method",
                },
                "kind": {
                    "type": "string",
                    "enum": ["decision", "next-step", "error", "narration"],
                    "description": "For search: filter hits to one kind",
                },
                "mode": {
                    "type": "string",
                    "enum": ["post_session", "bootstrap", "full"],
                    "description": "For reindex: mining mode",
                },
                "since": {
                    "type": "string",
                    "description": "For search: filter after date (YYYY-MM-DD)",
                },
                "until": {
                    "type": "string",
                    "description": "For search: filter before date (YYYY-MM-DD)",
                },
            },
            "required": ["operation"],
        },
    ),
]


# ─────────────────────────────────────────────────────────────────────────
# MCP tool annotations ("agent-native signals")
# ─────────────────────────────────────────────────────────────────────────
# Tell MCP clients (and Claude Code's permission system) which tools are safe
# to call without prompting, plus a human-friendly display title. Applied here
# in one place so the read-only set is auditable at a glance.
#
# - readOnlyHint=True  -> pure read/analyze tools: no state mutation, no side
#   effects (also marked idempotent). Clients can call these freely.
# - readOnlyHint=False -> the operation-enum tools bundle reads AND writes
#   under one name, so they may mutate; claiming read-only would be dishonest.
#   (destructive/idempotent are left unset because they vary per operation.)
# - openWorldHint=False everywhere -> all tools are local (project files,
#   local storage, a local Ollama); none reach the open internet.
_TOOL_TITLES = {
    "claude_engram_status": "Engram Status",
    "session_start": "Load Session Context",
    "session_end": "Session Summary",
    "pre_edit_check": "Pre-Edit Check",
    "memory": "Memory",
    "work": "Work Log",
    "scope": "Task Scope Guard",
    "context": "Checkpoint & Handoff",
    "convention": "Coding Conventions",
    "scout_search": "Scout Search",
    "file_summarize": "Summarize File",
    "deps_map": "Map Dependencies",
    "impact_analyze": "Analyze Impact",
    "find_similar_issues": "Find Similar Issues",
    "audit_batch": "Audit Code",
    "session_mine": "Mine Sessions",
}

# Tools that only read/analyze — no state mutation, no side effects.
_READ_ONLY_TOOLS = {
    "claude_engram_status",
    "pre_edit_check",
    "scout_search",
    "file_summarize",
    "deps_map",
    "impact_analyze",
    "find_similar_issues",
    "audit_batch",
}

for _tool in TOOL_DEFINITIONS:
    _read_only = _tool.name in _READ_ONLY_TOOLS
    _tool.annotations = ToolAnnotations(
        title=_TOOL_TITLES.get(_tool.name),
        readOnlyHint=_read_only,
        idempotentHint=True if _read_only else None,
        openWorldHint=False,
    )

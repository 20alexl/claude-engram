"""
Claude Engram Tool Definitions v2 - Optimized for token efficiency

Combines 66 tools into ~20 tools using operation parameters.
Reduces token overhead from ~20K to ~5K per message.
"""

from mcp.types import Tool


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
        description="Load full context: memories, checkpoints, decisions, memory health. Auto-cleans duplicates. Hook auto-starts basic session, but this gives deep context.",
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
        description="Optional. Shows session summary. All memories auto-save without this - just a nice recap.",
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
- remember: Store a note (just content - category/relevance optional)
- recall: Get all memories for project
- forget: Clear project memories
- search: Find by file/tags/query (file_path, tags, query, limit)
- clusters: View grouped memories (cluster_id to expand)
- cleanup: Dedupe/cluster/decay (dry_run, min_relevance, max_age_days)
- consolidate: LLM-powered merge of related memories (tag, dry_run)
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
                        "clusters",
                        "cleanup",
                        "consolidate",
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
                "cluster_id": {
                    "type": "string",
                    "description": "For clusters: expand specific cluster",
                },
                "tag": {
                    "type": "string",
                    "description": "For consolidate: only consolidate memories with this tag",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "For cleanup/consolidate: preview only",
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
    Tool(
        name="loop",
        description="""Loop detection to prevent death spirals. Operations:
- record_edit: Log file edit (file_path, description)
- record_test: Log test result (passed, error_message)
- check: Check if safe to edit (file_path)
- status: Get edit counts and warnings
- reset: Clear all loop tracking for a fresh start""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["record_edit", "record_test", "check", "status", "reset"],
                    "description": "Operation",
                },
                "file_path": {"type": "string", "description": "File being edited"},
                "description": {
                    "type": "string",
                    "description": "For record_edit: what changed",
                },
                "passed": {
                    "type": "boolean",
                    "description": "For record_test: did tests pass",
                },
                "error_message": {
                    "type": "string",
                    "description": "For record_test: error if failed",
                },
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
- instruction_add: Register a rule (routes to memory system — instructions ARE rules)
- instruction_list: List all rules (alias for list_rules)
- instruction_delete: Delete a rule by ID (memory_id)
- instruction_reinforce: Get all rules for reinforcement
- handoff_create: Create session handoff (handoff_summary, pending_steps, handoff_context_needed, handoff_warnings)
- handoff_get: Retrieve latest handoff document (project_path for per-project handoff)""",
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
                        "instruction_add",
                        "instruction_list",
                        "instruction_delete",
                        "instruction_reinforce",
                        "handoff_create",
                        "handoff_get",
                    ],
                    "description": "Which context operation to perform",
                },
                "task_description": {"type": "string", "description": "For checkpoint_save: what task is in progress"},
                "current_step": {"type": "string", "description": "For checkpoint_save: which step you're currently on"},
                "completed_steps": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "For checkpoint_save: list of completed steps"},
                "pending_steps": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "For checkpoint_save: list of remaining steps"},
                "files_involved": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "For checkpoint_save: files being worked on"},
                "task_id": {
                    "type": "string",
                    "description": "For restore: specific checkpoint",
                },
                "memory_id": {
                    "type": "string",
                    "description": "For instruction_delete: ID of the rule to delete (shown in list_rules output)",
                },
                "task": {"type": "string", "description": "For verify: task to verify"},
                "evidence": {
                    "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                    "description": "For verify: proof",
                },
                "verification_steps": {
                    "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                    "description": "For verify: checks",
                },
                "instruction": {"type": "string", "description": "For instruction_add"},
                "reason": {"type": "string", "description": "For instruction_add: why this instruction matters"},
                "importance": {"type": "integer", "description": "For instruction_add: priority 1-10"},
                "project_path": {"type": "string", "description": "Project directory path"},
                "handoff_summary": {
                    "type": "string",
                    "description": "For handoff_create: summary for next session",
                },
                "next_steps": {
                    "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                    "description": "For handoff_create: what to do next",
                },
                "handoff_context_needed": {
                    "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                    "description": "For handoff_create: context the next session needs",
                },
                "handoff_warnings": {
                    "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
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
        description="""Manage project coding conventions and style rules. Stores rules per-project with categories, checks code against them using LLM, and enforces consistency across the codebase. Operations:
- add: Store a new convention rule with category and reasoning
- get: Retrieve all conventions, optionally filtered by category
- check: Validate code or a filename against stored conventions using LLM analysis
- remove: Delete a convention rule by matching its text""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "get", "check", "remove"],
                    "description": "Which convention operation to perform",
                },
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "rule": {"type": "string", "description": "For add/remove: the convention rule text (e.g., 'Always use snake_case for function names')"},
                "category": {
                    "type": "string",
                    "enum": ["naming", "architecture", "style", "pattern", "avoid"],
                    "description": "For add/get: convention category to organize rules",
                },
                "reason": {"type": "string", "description": "For add: why this convention exists (e.g., 'Consistency with stdlib')"},
                "examples": {"type": "array", "items": {"type": "string"}, "description": "For add: code examples showing correct usage"},
                "importance": {"type": "integer", "description": "For add: priority 1-10, higher = more important to enforce"},
                "code_or_filename": {"type": "string", "description": "For check: code snippet or filename to validate against conventions"},
            },
            "required": ["operation", "project_path"],
        },
    ),
    Tool(
        name="output",
        description="""Validate code and command output for correctness. Detects fake results, silent failures, and missing expected content. Operations:
- validate_code: Analyze code for patterns that silently fail (empty except blocks, unused return values, missing error handling)
- validate_result: Check command output against expected format and required/forbidden content""",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["validate_code", "validate_result"],
                    "description": "Which validation operation to perform",
                },
                "code": {"type": "string", "description": "For validate_code: the code snippet to analyze for silent failure patterns"},
                "context": {"type": "string", "description": "For validate_code: what this code is supposed to do (helps detect semantic failures)"},
                "output": {"type": "string", "description": "For validate_result: the actual command/tool output to validate"},
                "expected_format": {"type": "string", "description": "For validate_result: expected output format (e.g., 'JSON array', 'CSV with headers')"},
                "should_contain": {"type": "array", "items": {"type": "string"}, "description": "For validate_result: strings that must appear in valid output"},
                "should_not_contain": {"type": "array", "items": {"type": "string"}, "description": "For validate_result: strings that indicate failure (e.g., 'Error', 'undefined')"},
            },
            "required": ["operation"],
        },
    ),
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
                "max_results": {"type": "integer", "default": 10, "description": "Maximum number of results to return"},
            },
            "required": ["query", "directory"],
        },
    ),
    Tool(
        name="scout_analyze",
        description="Analyze code using local LLM (Ollama). Send a code snippet with a specific question and get back architectural insights, bug analysis, or refactoring suggestions. Requires Ollama running with configured model.",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The code snippet to analyze"},
                "question": {"type": "string", "description": "Specific question about the code (e.g., 'What are the edge cases?', 'Is this thread-safe?')"},
            },
            "required": ["code", "question"],
        },
    ),
    Tool(
        name="file_summarize",
        description="Summarize a file's purpose, exports, and role in the project. Quick mode uses structural analysis (imports, classes, functions). Detailed mode uses local LLM for deeper understanding. Returns: purpose, key exports, dependencies, and complexity estimate.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file to summarize"},
                "mode": {
                    "type": "string",
                    "enum": ["quick", "detailed"],
                    "default": "quick",
                    "description": "Analysis depth: 'quick' for pattern-based (fast, no LLM), 'detailed' for LLM-powered (slower, richer insights)",
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
                "file_path": {"type": "string", "description": "Absolute path to the file to analyze"},
                "include_reverse": {"type": "boolean", "default": False, "description": "If true, also find all files that import this file (reverse dependencies)"},
                "project_root": {"type": "string", "description": "Project root directory for resolving relative imports"},
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
                "file_path": {"type": "string", "description": "Absolute path to the file being changed"},
                "project_root": {"type": "string", "description": "Project root directory for scanning dependents"},
                "proposed_changes": {"type": "string", "description": "Description of planned changes (helps assess which exports are affected)"},
            },
            "required": ["file_path", "project_root"],
        },
    ),
    Tool(
        name="code_quality_check",
        description="Check code quality against common anti-patterns: overly long functions (>50 lines), deep nesting (>4 levels), vague variable names, missing error handling, and AI-generated boilerplate. Returns: list of issues with severity, line numbers, and fix suggestions.",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code snippet to analyze for quality issues"},
                "language": {"type": "string", "default": "python", "description": "Programming language for language-specific checks (python, javascript, typescript, go, rust)"},
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="code_pattern_check",
        description="Check code against project-specific conventions stored via the convention tool. Uses local LLM to analyze whether code follows naming, architecture, style, and pattern rules. Returns: violations found, matching convention rules, and suggested fixes.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project whose conventions to check against"},
                "code": {"type": "string", "description": "Code snippet to validate against stored project conventions"},
            },
            "required": ["project_path", "code"],
        },
    ),
    Tool(
        name="audit_batch",
        description="Audit multiple files for code quality issues in a single pass. Accepts file paths or glob patterns (e.g., 'src/**/*.py'). Checks each file for long functions, deep nesting, missing error handling, and anti-patterns. Returns: per-file issue lists with severity and line numbers, plus aggregate summary.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths or glob patterns to audit (e.g., ['src/auth.py', 'src/models/*.py'])"},
                "min_severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Minimum severity to report: 'critical' (bugs only), 'warning' (bugs + smells), 'info' (everything)",
                },
            },
            "required": ["file_paths"],
        },
    ),
    Tool(
        name="find_similar_issues",
        description="Search an entire codebase for a regex bug pattern. Finds all occurrences of anti-patterns like bare excepts, hardcoded secrets, or missing null checks. Returns: matching files with line numbers, context snippets, and match count.",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_pattern": {"type": "string", "description": "Regex pattern to search for (e.g., 'except:\\s*pass', 'TODO|FIXME|HACK', 'password\\s*=\\s*[\"\\']')"},
                "project_path": {"type": "string", "description": "Absolute path to the project root to search"},
                "file_extensions": {"type": "array", "items": {"type": "string"}, "description": "File extensions to include (e.g., ['.py', '.js']). Empty means all files"},
                "exclude_paths": {"type": "array", "items": {"type": "string"}, "description": "Directory patterns to skip (e.g., ['node_modules', 'venv', '__pycache__'])"},
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
- search: Search across past conversations (query, project_path, limit, method=hybrid|semantic|keyword)
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
- reflect: LLM-powered analysis of mistakes, patterns, and decisions (project_path)""",
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

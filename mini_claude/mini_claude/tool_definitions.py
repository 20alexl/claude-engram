"""
Mini Claude Tool Definitions

Static Tool schema definitions for the MCP server.
Separated from server.py to keep the routing layer clean.
"""

from mcp.types import Tool


TOOL_DEFINITIONS = [
    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------
    Tool(
        name="mini_claude_status",
        description="""Check if Mini Claude (your junior agent) is ready and healthy.
Call this before using other tools to verify the connection.
Returns: health status, available model, memory stats.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Scout - Search
    # -------------------------------------------------------------------------
    Tool(
        name="scout_search",
        description="""Ask Scout to search a codebase for something.

Scout will:
1. Search for literal matches (function names, variables, etc.)
2. Use semantic understanding to find related code
3. Analyze connections between findings
4. Suggest follow-up areas to explore

Returns a structured report with:
- Findings (files, line numbers, summaries)
- Connections between findings
- Confidence level
- Suggestions for next steps
- Work log of what was tried

Use this when you need to find code but aren't sure exactly where it is.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for. Can be a literal term, function name, or natural language query like 'where is authentication handled?'"
                },
                "directory": {
                    "type": "string",
                    "description": "The directory to search in (absolute path)"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 10)",
                    "default": 10
                },
            },
            "required": ["query", "directory"],
        },
    ),

    # -------------------------------------------------------------------------
    # Scout - Analyze
    # -------------------------------------------------------------------------
    Tool(
        name="scout_analyze",
        description="""Ask Mini Claude to analyze a specific piece of code.

Provide code content and a question about it.
Mini Claude will use the local LLM to analyze and answer.

Returns:
- Analysis results
- Confidence level
- Follow-up questions if needed""",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to analyze"
                },
                "question": {
                    "type": "string",
                    "description": "What do you want to know about this code?"
                },
            },
            "required": ["code", "question"],
        },
    ),

    # -------------------------------------------------------------------------
    # Memory - Remember
    # -------------------------------------------------------------------------
    Tool(
        name="memory_remember",
        description="""Tell Mini Claude to remember something important.

Use this to store:
- Project understanding (what this codebase does)
- Key discoveries (important files, patterns found)
- Priorities (things to focus on or watch out for)

Mini Claude will persist this across sessions.""",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What to remember"
                },
                "category": {
                    "type": "string",
                    "enum": ["discovery", "priority", "note"],
                    "description": "Type of memory: discovery (found something), priority (important), note (general)"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional: Associate with a specific project directory"
                },
                "relevance": {
                    "type": "integer",
                    "description": "Importance 1-10 (default: 5, higher = more important)",
                    "default": 5
                },
            },
            "required": ["content", "category"],
        },
    ),

    # -------------------------------------------------------------------------
    # Memory - Recall
    # -------------------------------------------------------------------------
    Tool(
        name="memory_recall",
        description="""Ask Mini Claude what it remembers.

Returns accumulated knowledge about:
- Global priorities
- Project-specific discoveries
- Key files and their purposes
- Recent searches (to avoid redundant work)

Use this when starting work on a project or when you need context.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Optional: Recall memories for a specific project"
                },
            },
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Memory - Forget
    # -------------------------------------------------------------------------
    Tool(
        name="memory_forget",
        description="""Tell Mini Claude to forget memories for a project.

Use this when:
- A project has changed significantly
- Memories are outdated or wrong
- Starting fresh analysis""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "The project directory to forget"
                },
            },
            "required": ["project_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # File Summarizer
    # -------------------------------------------------------------------------
    Tool(
        name="file_summarize",
        description="""Get a quick summary of what a file does.

Two modes:
- quick: Fast pattern-based summary (no LLM, instant)
- detailed: LLM-powered analysis (slower, more context)

Returns:
- Summary of file purpose
- Key facts (functions, classes, imports)
- File statistics""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to summarize"
                },
                "mode": {
                    "type": "string",
                    "enum": ["quick", "detailed"],
                    "description": "Summary mode: 'quick' (fast) or 'detailed' (LLM)",
                    "default": "quick"
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Dependency Mapper
    # -------------------------------------------------------------------------
    Tool(
        name="deps_map",
        description="""Map dependencies for a file.

Shows:
- What the file imports (stdlib, external, internal)
- Optionally: what files import this file (reverse deps)

Use this to understand:
- What a file depends on
- Impact of changing a file""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to analyze"
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for finding reverse dependencies"
                },
                "include_reverse": {
                    "type": "boolean",
                    "description": "Whether to find files that import this file",
                    "default": False
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Convention Tracker - Add
    # -------------------------------------------------------------------------
    Tool(
        name="convention_add",
        description="""Store a project convention or coding rule.

Categories:
- naming: File/function/variable naming rules
- architecture: Where to put files, folder structure
- style: Code formatting, import ordering
- pattern: Preferred patterns to use
- avoid: Things NOT to do

Use this to help me remember project-specific rules so I don't violate them later.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory this convention applies to"
                },
                "rule": {
                    "type": "string",
                    "description": "The convention/rule to remember (e.g., 'Use snake_case for file names')"
                },
                "category": {
                    "type": "string",
                    "enum": ["naming", "architecture", "style", "pattern", "avoid"],
                    "description": "Category of convention",
                    "default": "pattern"
                },
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional examples (good or bad)"
                },
                "reason": {
                    "type": "string",
                    "description": "Optional: why this rule exists"
                },
                "importance": {
                    "type": "integer",
                    "description": "1-10, how critical (default: 5)",
                    "default": 5
                },
            },
            "required": ["project_path", "rule"],
        },
    ),

    # -------------------------------------------------------------------------
    # Convention Tracker - Get
    # -------------------------------------------------------------------------
    Tool(
        name="convention_get",
        description="""Get all conventions for a project.

Returns all stored rules and patterns.
Use this before starting work to remind yourself of project conventions.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory to get conventions for"
                },
                "category": {
                    "type": "string",
                    "enum": ["naming", "architecture", "style", "pattern", "avoid"],
                    "description": "Optional: filter by category"
                },
            },
            "required": ["project_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Convention Tracker - Check
    # -------------------------------------------------------------------------
    Tool(
        name="convention_check",
        description="""Check code/filename against project conventions.

Simple heuristic check for potential violations.
Use this before committing changes to catch convention issues.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory"
                },
                "code_or_filename": {
                    "type": "string",
                    "description": "Code snippet or filename to check"
                },
            },
            "required": ["project_path", "code_or_filename"],
        },
    ),

    # -------------------------------------------------------------------------
    # Session Manager
    # -------------------------------------------------------------------------
    Tool(
        name="session_start",
        description="""Start a work session by loading all context for a project.

Call this FIRST when beginning work on any project. It loads:
- Project memories (what you discovered before)
- Conventions (rules to follow)
- Recent searches (to avoid redundant work)
- Global priorities

Returns everything you need to remember in one call.
This replaces manually calling memory_recall + convention_get.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "The project directory you're starting work on"
                },
            },
            "required": ["project_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Impact Analyzer
    # -------------------------------------------------------------------------
    Tool(
        name="impact_analyze",
        description="""Analyze potential impact before changing a file.

Before editing a file, use this to understand:
- How many files depend on it
- What functions/classes it exports
- Where those exports are used
- Overall risk level (low/medium/high/critical)

Returns:
- List of dependent files
- Exported symbols and their usage locations
- Risk assessment with reasons
- Suggestions for safe changes

Use this BEFORE making significant changes to shared code.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The file you plan to change (absolute path)"
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root directory to search for dependents"
                },
                "proposed_changes": {
                    "type": "string",
                    "description": "Optional: describe what you plan to change (helps assess risk)"
                },
            },
            "required": ["file_path", "project_root"],
        },
    ),

    # -------------------------------------------------------------------------
    # Work Tracker - Log Mistake
    # -------------------------------------------------------------------------
    Tool(
        name="work_log_mistake",
        description="""Log a mistake so Mini Claude remembers it.

Use this when:
- Something breaks unexpectedly
- You realize you did something wrong
- A test fails because of your change
- You had to undo work

This creates a high-priority memory that will warn you
if you're about to make the same mistake again.""",
        inputSchema={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What went wrong"
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional: which file was involved"
                },
                "how_to_avoid": {
                    "type": "string",
                    "description": "Optional: how to avoid this next time"
                },
            },
            "required": ["description"],
        },
    ),

    # -------------------------------------------------------------------------
    # Work Tracker - Log Decision
    # -------------------------------------------------------------------------
    Tool(
        name="work_log_decision",
        description="""Log an important decision and why it was made.

Use this when:
- Choosing between approaches
- Deciding on architecture
- Making trade-offs

This helps future sessions understand WHY things are the way they are.""",
        inputSchema={
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "description": "What was decided"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this choice was made"
                },
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: other options that were considered"
                },
            },
            "required": ["decision", "reason"],
        },
    ),

    # -------------------------------------------------------------------------
    # Work Tracker - Get Session Summary
    # -------------------------------------------------------------------------
    Tool(
        name="work_session_summary",
        description="""Get a summary of what happened in the current session.

Returns:
- Files edited
- Searches performed
- Mistakes logged
- Decisions made
- Time spent

Use this before ending a session to review work done.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Work Tracker - Pre-Edit Check
    # -------------------------------------------------------------------------
    Tool(
        name="work_pre_edit_check",
        description="""Check for relevant context before editing a file.

Returns:
- Previous edits to this file in this session
- Past mistakes involving this file
- Related searches

Use this BEFORE editing a file to avoid repeating mistakes.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The file you're about to edit"
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Work Tracker - Save Session
    # -------------------------------------------------------------------------
    Tool(
        name="work_save_session",
        description="""Save the current session's work as memories.

Persists:
- Important decisions made
- Files touched
- Lessons learned

Call this at the end of a session or periodically to save progress.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Code Quality Checker
    # -------------------------------------------------------------------------
    Tool(
        name="code_quality_check",
        description="""Check code for structural quality issues BEFORE writing it.

Detects common Claude Code problems:
- Functions that are too long (>50 lines)
- Vague names like 'data', 'handle', 'process'
- Too many parameters (>5)
- Deep nesting (>3 levels)
- High cyclomatic complexity

Returns issues with severity levels and suggestions.
Use this to catch "AI slop" before it gets written.""",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to check"
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (python, javascript, typescript)",
                    "default": "python"
                },
            },
            "required": ["code"],
        },
    ),

    # -------------------------------------------------------------------------
    # Loop Detector - Record Edit
    # -------------------------------------------------------------------------
    Tool(
        name="loop_record_edit",
        description="""Record that a file was edited (for loop detection).

The loop detector tracks edits and warns when you're stuck:
- Same file edited 3+ times
- Tests keep failing after edits
- Same error repeating

Call this after each edit to enable loop detection.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The file that was edited"
                },
                "description": {
                    "type": "string",
                    "description": "What was changed"
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Loop Detector - Check Before Edit
    # -------------------------------------------------------------------------
    Tool(
        name="loop_check_before_edit",
        description="""Check if editing a file might put you in a loop.

Returns warning if:
- File has been edited too many times
- Previous edits to this file failed tests
- You're oscillating between files

Call this BEFORE editing to catch death spirals early.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The file you're about to edit"
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Loop Detector - Record Test Result
    # -------------------------------------------------------------------------
    Tool(
        name="loop_record_test",
        description="""Record the result of running tests.

This helps the loop detector know if your edits are working.
Call this after running tests.""",
        inputSchema={
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "Whether tests passed"
                },
                "error_message": {
                    "type": "string",
                    "description": "Error message if tests failed"
                },
            },
            "required": ["passed"],
        },
    ),

    # -------------------------------------------------------------------------
    # Loop Detector - Get Status
    # -------------------------------------------------------------------------
    Tool(
        name="loop_status",
        description="""Get current loop detection status.

Shows:
- Files edited and how many times
- Test pass rate
- Any detected loop patterns

Use this to see if you're making progress.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Scope Guard - Declare
    # -------------------------------------------------------------------------
    Tool(
        name="scope_declare",
        description="""Declare the scope of files for the current task.

CRITICAL for preventing over-refactoring. Before starting a task:
1. List which files you're allowed to edit
2. If you try to edit other files, you'll get a warning

Example: "Fix login bug" -> scope is only auth files.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "What the task is"
                },
                "in_scope_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files that CAN be edited"
                },
                "in_scope_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns for files that can be edited (e.g., 'src/auth/*')"
                },
                "out_of_scope_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files that should NOT be touched"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this scope was chosen"
                },
            },
            "required": ["task_description", "in_scope_files"],
        },
    ),

    # -------------------------------------------------------------------------
    # Scope Guard - Check File
    # -------------------------------------------------------------------------
    Tool(
        name="scope_check",
        description="""Check if editing a file is within the declared scope.

Call this BEFORE editing any file to catch scope creep.
Returns warning if the file is outside scope.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The file you want to edit"
                },
            },
            "required": ["file_path"],
        },
    ),

    # -------------------------------------------------------------------------
    # Scope Guard - Expand
    # -------------------------------------------------------------------------
    Tool(
        name="scope_expand",
        description="""Expand the current scope to include more files.

Use this when you discover you legitimately need to edit more files.
This should be a deliberate decision, not automatic.""",
        inputSchema={
            "type": "object",
            "properties": {
                "files_to_add": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to add to scope"
                },
                "reason": {
                    "type": "string",
                    "description": "Why these files need to be in scope"
                },
            },
            "required": ["files_to_add", "reason"],
        },
    ),

    # -------------------------------------------------------------------------
    # Scope Guard - Status
    # -------------------------------------------------------------------------
    Tool(
        name="scope_status",
        description="""Get current scope status and any violations.

Shows:
- What task you're working on
- Which files are in scope
- Any out-of-scope edits attempted

Use this to review your scope discipline.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Scope Guard - Clear
    # -------------------------------------------------------------------------
    Tool(
        name="scope_clear",
        description="""Clear the current scope (task complete).

Call this when you're done with a task and ready to start a new one.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Save Checkpoint
    # -------------------------------------------------------------------------
    Tool(
        name="context_checkpoint_save",
        description="""Save a checkpoint of current task state.

Use this to preserve task progress that survives:
- Context compaction
- Session ends
- Crashes or interruptions

Call this:
- Before long operations that might fail
- When context is getting long (approaching compaction)
- At natural breakpoints in multi-step tasks
- Before ending a session""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "What task you're working on"
                },
                "current_step": {
                    "type": "string",
                    "description": "What step you're currently on"
                },
                "completed_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Steps already completed"
                },
                "pending_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Steps still to do"
                },
                "files_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files being worked on"
                },
                "key_decisions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Important decisions made so far"
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things blocking progress"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional: project directory"
                },
            },
            "required": ["task_description", "current_step", "completed_steps", "pending_steps", "files_involved"],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Restore Checkpoint
    # -------------------------------------------------------------------------
    Tool(
        name="context_checkpoint_restore",
        description="""Restore task state from a checkpoint.

Call this at session start to continue previous work.
If no task_id provided, restores the latest checkpoint.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Optional: specific checkpoint to restore"
                },
            },
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - List Checkpoints
    # -------------------------------------------------------------------------
    Tool(
        name="context_checkpoint_list",
        description="""List all saved checkpoints.

Shows available checkpoints with their age and progress.
Use this to find a checkpoint to restore.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Add Critical Instruction
    # -------------------------------------------------------------------------
    Tool(
        name="context_instruction_add",
        description="""Register an instruction that must not be forgotten.

These get re-injected into context periodically to combat
the tendency to ignore CLAUDE.md instructions as context grows.

Use for rules that MUST be followed no matter what.""",
        inputSchema={
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "The instruction that must be remembered"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this instruction is critical"
                },
                "importance": {
                    "type": "integer",
                    "description": "1-10, how critical (default: 10)",
                    "default": 10
                },
            },
            "required": ["instruction", "reason"],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Get Reinforcement
    # -------------------------------------------------------------------------
    Tool(
        name="context_instruction_reinforce",
        description="""Get critical instructions that need reinforcement.

Call this periodically (every few messages) to re-inject
important instructions that might have faded from attention.

Returns the most important instructions to keep in mind.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Claim Completion
    # -------------------------------------------------------------------------
    Tool(
        name="context_claim_completion",
        description="""Record a claim that a task is complete.

This creates an audit trail for self_check to verify later.
Forces explicit recording of what was supposedly done.

Include evidence (file paths, test results) for verification.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task being claimed as complete"
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence supporting the claim (file paths, test output, etc.)"
                },
            },
            "required": ["task"],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Self Check
    # -------------------------------------------------------------------------
    Tool(
        name="context_self_check",
        description="""Verify that claimed work was actually completed.

This combats the tendency to claim 100% completion when
work is actually incomplete. Forces explicit verification.

Provide concrete verification steps like:
- "File X exists and contains Y"
- "Test Z passes"
- "Function W is called in file V" """,
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task to verify"
                },
                "verification_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete steps to verify the task is done"
                },
            },
            "required": ["task", "verification_steps"],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Create Handoff
    # -------------------------------------------------------------------------
    Tool(
        name="context_handoff_create",
        description="""Create a structured handoff document for the next session.

This ensures nothing is lost when:
- Session ends
- Context gets compacted
- A different Claude instance takes over

Include everything the next session needs to continue.""",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of what was accomplished"
                },
                "next_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What to do next"
                },
                "context_needed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key context the next session needs"
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things to watch out for"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional: project directory"
                },
            },
            "required": ["summary", "next_steps", "context_needed"],
        },
    ),

    # -------------------------------------------------------------------------
    # Context Guard - Get Handoff
    # -------------------------------------------------------------------------
    Tool(
        name="context_handoff_get",
        description="""Retrieve the latest handoff document.

Call this at session start to see what the previous session left.
Contains summary, next steps, and important context.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Output Validator - Validate Code
    # -------------------------------------------------------------------------
    Tool(
        name="output_validate_code",
        description="""Validate code for signs of fake output or silent failure.

Detects dangerous patterns that pass tests but fail silently:
- Removed safety checks (except: pass)
- Fake/placeholder outputs
- Hardcoded test values
- Missing error handling for I/O
- Suspiciously simple implementations

Use this BEFORE writing code to catch "AI slop" patterns.""",
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The code to validate"
                },
                "context": {
                    "type": "string",
                    "description": "Optional: what the code should do"
                },
            },
            "required": ["code"],
        },
    ),

    # -------------------------------------------------------------------------
    # Output Validator - Validate Result
    # -------------------------------------------------------------------------
    Tool(
        name="output_validate_result",
        description="""Validate command/function output for signs of fake results.

Checks for:
- Placeholder keywords (example, test, TODO)
- Suspiciously short output
- Error messages disguised as success
- Missing expected patterns

Use this to verify that outputs are real, not generated fakes.""",
        inputSchema={
            "type": "object",
            "properties": {
                "output": {
                    "type": "string",
                    "description": "The output to validate"
                },
                "expected_format": {
                    "type": "string",
                    "description": "Optional: expected format (JSON, list, etc.)"
                },
                "should_contain": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns that should be in the output"
                },
                "should_not_contain": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns that should NOT be in the output"
                },
            },
            "required": ["output"],
        },
    ),

    # -------------------------------------------------------------------------
    # Test Runner - Run Tests
    # -------------------------------------------------------------------------
    Tool(
        name="test_run",
        description="""Run tests and return results.

Auto-detects test commands for:
- Python: pytest, unittest
- Node.js: npm test
- Go: go test
- Rust: cargo test
- Makefile: make test

Prevents false completion claims by tracking test results.
Use this to verify changes before claiming work is done.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "Project directory to run tests in"
                },
                "test_command": {
                    "type": "string",
                    "description": "Optional: explicit test command (auto-detect if omitted)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max time in seconds (default: 300)",
                    "default": 300
                },
            },
            "required": ["project_dir"],
        },
    ),

    # -------------------------------------------------------------------------
    # Test Runner - Can Claim Completion
    # -------------------------------------------------------------------------
    Tool(
        name="test_can_claim_completion",
        description="""Check if completion can be claimed based on test history.

Returns whether tests are passing consistently.
Detects flaky tests (passed now but failed recently).

Use this before claiming a task is complete.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Git Helper - Generate Commit Message
    # -------------------------------------------------------------------------
    Tool(
        name="git_generate_commit_message",
        description="""Generate intelligent commit message from work context.

Combines:
1. Work logs (what was done)
2. Decisions (why choices were made)
3. Files changed (what was touched)
4. Git diff (actual changes)

Returns a structured commit message with:
- Summary line (72 char limit)
- Detailed changes from decisions
- Fixes from mistakes logged
- File change statistics
- Co-authored-by tag for Claude

Use this to create meaningful commit messages instead of generic ones.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "Project directory"
                },
            },
            "required": ["project_dir"],
        },
    ),

    # -------------------------------------------------------------------------
    # Git Helper - Auto Commit
    # -------------------------------------------------------------------------
    Tool(
        name="git_auto_commit",
        description="""Automatically commit changes with generated or explicit message.

If no message provided, generates one from work logs and changes.
Handles git add and git commit automatically.

Returns the commit hash and message.

Use this to quickly commit work with context-aware messages.""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "Project directory"
                },
                "message": {
                    "type": "string",
                    "description": "Optional: explicit commit message (generate if omitted)"
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: specific files to commit (all if omitted)"
                },
            },
            "required": ["project_dir"],
        },
    ),

    # -------------------------------------------------------------------------
    # Momentum Tracker - Prevent stopping mid-task
    # -------------------------------------------------------------------------
    Tool(
        name="momentum_start_task",
        description="""Start tracking a multi-step task to prevent stopping mid-task.

Use this when beginning work that has multiple clear steps.
Helps detect when you stop after step 1 instead of continuing to step 2.

Example:
  momentum_start_task(
    task_description="Wire new tools into MCP server",
    expected_steps=["Add to __init__.py", "Add handlers", "Add routing", "Add tool definitions"]
  )

The tracker will warn if you stop before completing all steps.""",
        inputSchema={
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Description of the task"
                },
                "expected_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of steps that should be completed"
                },
            },
            "required": ["task_description", "expected_steps"],
        },
    ),

    Tool(
        name="momentum_complete_step",
        description="""Mark a step as completed in the current task.

Call this as you finish each step to track progress.""",
        inputSchema={
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "The step that was completed"
                },
            },
            "required": ["step"],
        },
    ),

    Tool(
        name="momentum_check",
        description="""Check if momentum is being maintained.

Returns warnings if:
- Current task has pending steps
- Too many reads without corresponding edits
- Inactive for >30s with pending work

Use this periodically to catch yourself stopping mid-task.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    Tool(
        name="momentum_finish_task",
        description="""Mark the current task as finished.

Call this when all steps are complete.""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    Tool(
        name="momentum_status",
        description="""Get current momentum tracking status.

Shows:
- Active task (if any)
- Expected vs completed steps
- Pending steps
- Time since start and last action""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    # -------------------------------------------------------------------------
    # Thinker - Research and reasoning partner
    # -------------------------------------------------------------------------
    Tool(
        name="think_research",
        description="""Deep research on a question using web + codebase + reasoning.

Helps overcome tunnel vision by:
- Searching current best practices (2026 docs)
- Finding existing patterns in codebase
- Using LLM to reason about findings
- Suggesting next steps

Use this BEFORE writing code to understand the problem space.

Example:
  think_research(
    question="What's the best way to handle async file I/O in Python?",
    context="Building an MCP server with high concurrency",
    depth="medium"
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to research"
                },
                "context": {
                    "type": "string",
                    "description": "Optional context about why you're asking"
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "medium", "deep"],
                    "description": "How thorough to be (default: medium)",
                    "default": "medium"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional project to search for existing patterns"
                },
            },
            "required": ["question"],
        },
    ),

    Tool(
        name="think_compare",
        description="""Compare multiple approaches with pros/cons analysis.

Prevents hasty decisions by evaluating trade-offs.

Use this when you have multiple options and aren't sure which is best.

Example:
  think_compare(
    options=["SQLite", "PostgreSQL", "DuckDB"],
    context="Local-first MCP server with <100MB data",
    criteria=["complexity", "performance", "features"]
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of options to compare"
                },
                "context": {
                    "type": "string",
                    "description": "Context for the decision"
                },
                "criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional criteria to evaluate (default: complexity, performance, maintainability, ecosystem)"
                },
            },
            "required": ["options", "context"],
        },
    ),

    Tool(
        name="think_challenge",
        description="""Challenge an assumption with devil's advocate reasoning.

Prevents over-engineering and premature optimization.

Use this when you're about to make a strong assumption (e.g., "we need sub-1ms latency").

Example:
  think_challenge(
    assumption="We need to cache everything in memory for speed",
    context="Processing user queries in MCP server"
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "assumption": {
                    "type": "string",
                    "description": "The assumption to challenge"
                },
                "context": {
                    "type": "string",
                    "description": "Optional context about the assumption"
                },
            },
            "required": ["assumption"],
        },
    ),

    Tool(
        name="think_explore",
        description="""Broad exploration of solution space for a problem.

Prevents tunnel vision by showing multiple approaches:
- Simple/naive (quick to implement)
- Standard (what most people do)
- Creative (unusual but potentially better)
- Ideal (if resources unlimited)

Use this when starting a new feature to see all options.

Example:
  think_explore(
    problem="Store conversation history across sessions",
    constraints=["local-first", "under 10MB", "fast reads"]
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "problem": {
                    "type": "string",
                    "description": "The problem to solve"
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional constraints"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional project to check for existing patterns"
                },
            },
            "required": ["problem"],
        },
    ),

    Tool(
        name="think_best_practice",
        description="""Find current best practices for a topic.

Ensures you're using 2026 best practices, not outdated patterns.

Use this before implementing something you're not sure about.

Example:
  think_best_practice(
    topic="error handling",
    language_or_framework="Python asyncio",
    year=2026
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What to find best practices for"
                },
                "language_or_framework": {
                    "type": "string",
                    "description": "Optional language/framework context"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for recency (default: 2026)",
                    "default": 2026
                },
            },
            "required": ["topic"],
        },
    ),

    # =========================================================================
    # Habit Tracker Tools - Build good coding habits through feedback
    # =========================================================================

    Tool(
        name="habit_get_stats",
        description="""Get habit formation statistics for the last N days.

Shows:
- How often you use Thinker tools before risky work
- Loop avoidance rate
- Overall habit trends

Use this to see if you're building good habits or need to improve.

Example:
  habit_get_stats(days=7)""",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)",
                    "default": 7
                },
            },
            "required": [],
        },
    ),

    Tool(
        name="habit_get_feedback",
        description="""Get encouraging or warning feedback based on your habits.

Provides:
- Gamified feedback on habit performance
- Specific suggestions for improvement
- Encouragement for good habits

Use this to stay motivated and build better habits.

Example:
  habit_get_feedback()""",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),

    Tool(
        name="habit_session_summary",
        description="""Get a comprehensive session summary for handoff to next session.

CALL THIS BEFORE ENDING A SESSION!

Combines:
- Files edited and why
- Decisions made and reasoning
- Mistakes logged
- Habit performance stats
- Tips for next session

This creates a perfect handoff document for the next Claude instance.

Example:
  habit_session_summary(project_path="/path/to/project")""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Optional project directory"
                },
            },
            "required": [],
        },
    ),

    # =========================================================================
    # New Tools: diff_review, think_audit, code_pattern_check
    # =========================================================================

    Tool(
        name="diff_review",
        description="""Review git diff for issues BEFORE committing.

Catches problems before they reach your repo:
- Silent failures (except: pass, empty catch blocks)
- Debug code left in (print, console.log, debugger)
- Hardcoded secrets/credentials
- TODO/FIXME comments
- Security issues (eval, innerHTML, shell=True)
- Convention violations

Use this before every commit to catch "AI slop" patterns.

Example:
  diff_review(project_dir="/path/to/project")
  diff_review(project_dir="/path/to/project", staged_only=True)""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "Project directory to review diff in"
                },
                "staged_only": {
                    "type": "boolean",
                    "description": "If true, only review staged changes (git diff --staged)",
                    "default": False
                },
            },
            "required": ["project_dir"],
        },
    ),

    Tool(
        name="think_audit",
        description="""Audit a file for common issues and anti-patterns.

Combines pattern matching + LLM analysis to find:
- Silent failures (except: pass, empty catch)
- Missing error handling for I/O
- Hardcoded values that should be configurable
- TODO/FIXME items
- Security vulnerabilities
- Type safety issues (any, type:ignore)

Returns issues with severity, line numbers, and suggested fixes (quick_fix).

Example:
  think_audit(file_path="/path/to/file.py")
  think_audit(file_path="/path/to/file.py", focus_areas=["security", "error_handling"])
  think_audit(file_path="/path/to/file.py", min_severity="warning")  # Skip info-level""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to audit"
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional areas to focus on (e.g., ['error_handling', 'security'])"
                },
                "min_severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Minimum severity level to report. 'critical' shows only critical, 'warning' shows critical+warning, 'info' shows all."
                },
            },
            "required": ["file_path"],
        },
    ),

    Tool(
        name="code_pattern_check",
        description="""Check code against stored conventions using LLM for deep analysis.

Enhanced version of convention_check that uses LLM to understand semantic violations,
not just keyword matches.

Use this to verify code follows project patterns before committing.

Example:
  code_pattern_check(
    project_path="/path/to/project",
    code="def myFunction(): ..."
  )""",
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Project directory with stored conventions"
                },
                "code": {
                    "type": "string",
                    "description": "Code snippet to check against conventions"
                },
            },
            "required": ["project_path", "code"],
        },
    ),

    Tool(
        name="audit_batch",
        description="""Audit multiple files at once for common issues.

Fast pattern-based auditing across many files. Supports glob patterns.

Use this to scan a directory or set of files before committing.

Example:
  audit_batch(file_paths=["src/**/*.py"])
  audit_batch(file_paths=["file1.py", "file2.py"], min_severity="warning")""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths or glob patterns (e.g., ['src/**/*.py'])"
                },
                "min_severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Minimum severity level to report"
                },
            },
            "required": ["file_paths"],
        },
    ),

    Tool(
        name="find_similar_issues",
        description="""Search codebase for code matching an issue pattern.

When you find a bug pattern (e.g., 'except: pass'), use this to find
all similar occurrences across the codebase.

By default, excludes vendor directories (node_modules, site-packages, venv, etc.)
and skips matches inside string literals to reduce false positives.

Example:
  find_similar_issues(issue_pattern="except:\\s*pass", project_path="/path/to/project")
  find_similar_issues(issue_pattern="eval\\(", project_path="/path", file_extensions=[".py"])
  find_similar_issues(issue_pattern="TODO", project_path="/path", exclude_paths=["tests/"])""",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for (e.g., 'except:\\s*pass', 'eval\\(')"
                },
                "project_path": {
                    "type": "string",
                    "description": "Root directory to search in"
                },
                "file_extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File extensions to search (default: .py, .js, .ts, etc.)"
                },
                "exclude_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to exclude (default: node_modules, site-packages, venv, etc.)"
                },
                "exclude_strings": {
                    "type": "boolean",
                    "description": "Skip matches inside string literals (default: true)"
                },
            },
            "required": ["issue_pattern", "project_path"],
        },
    ),
]

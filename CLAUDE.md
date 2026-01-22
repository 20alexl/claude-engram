# Mini Claude - Project Instructions

**NOTE:** This file is for Claude Code (the AI). Copy it to your project root so Claude knows how to use Mini Claude tools effectively.

## STOP. READ THIS FIRST.

You have a junior dev (Mini Claude) who remembers things across sessions. **USE HIM.**

If you skip these steps, you WILL:
- Repeat mistakes you already made
- Forget why things are structured the way they are
- Break things you broke before

---

## MANDATORY: First Thing Every Session

```
mcp__mini-claude__session_start(project_path="<PROJECT_PATH>")
```

Replace `<PROJECT_PATH>` with the actual project directory.

**DO NOT SKIP THIS.** It loads your memories AND warns you about past mistakes.

---

## MANDATORY: Before Editing Shared/Important Files

Before editing files that are shared, config files, or core modules:

```
mcp__mini-claude__pre_edit_check(file_path="<the file>")
```

This unified check combines:
- Past mistakes with that file
- Loop detection (are you editing too many times?)
- Scope check (is this file in scope?)

**If you skip this, you will repeat mistakes.**

---

## MANDATORY: When Something Breaks

When tests fail, something errors, or you have to undo work:

```
mcp__mini-claude__work_log_mistake(
  description="What went wrong",
  file_path="which file",
  how_to_avoid="How to prevent this"
)
```

**If you don't log mistakes, you WILL repeat them next session.**

---

## RECOMMENDED: For Multi-File Tasks

When working on a task that spans multiple files:

```
mcp__mini-claude__scope_declare(
  task_description="What you're doing",
  in_scope_files=["file1.py", "file2.py"]
)
```

This prevents scope creep and over-refactoring.

---

## RECOMMENDED: Log Important Decisions

When you choose between approaches or make architectural decisions:

```
mcp__mini-claude__work_log_decision(
  decision="What you decided",
  reason="Why"
)
```

Next session, you'll know WHY things are the way they are.

---

## Quick Reference

| When | Tool | Why |
|------|------|-----|
| Start of session | `session_start` | Load context + past mistakes + **auto-restore checkpoints + auto-cleanup** |
| Before editing important files | `pre_edit_check` | **Unified check**: past mistakes + loop risk + scope (use this!) |
| Something breaks | `work_log_mistake` | Remember for next time |
| Make a decision | `work_log_decision` | Explain WHY for future |
| Multi-file task | `scope_declare` | Prevent over-refactoring |
| Before big changes | `impact_analyze` | See what depends on file |
| Audit a file | `think_audit` | Find anti-patterns + get quick fixes |
| Audit many files | `audit_batch` | Scan directory for issues |
| Find similar bugs | `find_similar_issues` | Search codebase for pattern |
| End of session | `session_end` | **Summary + save** in one call (use this!) |
| Find related memories | `memory_search` | Contextual search by file, tags, or query (NEW!) |
| View memory clusters | `memory_cluster_view` | See grouped memories instead of flat list (NEW!) |
| Cleanup memories | `memory_cleanup` | Deduplicate, cluster, decay old memories (NEW!) |
| Before long tasks | `context_checkpoint_save` | **Survive compaction + handoff** (now includes handoff!) |
| When claiming done | `verify_completion` | **Claim + verify** in one call (NEW!) |

---

## CRITICAL: Surviving Context Compaction

When context gets long, it will be compacted (summarized). **You WILL lose context.**

To survive compaction:

1. **Before long tasks**: `context_checkpoint_save(task_description, current_step, ...)`
   - Now includes optional handoff fields: `handoff_summary`, `handoff_context_needed`, `handoff_warnings`
2. **Periodically**: Save checkpoints at natural breakpoints
3. **After compaction**: `session_start` auto-restores your checkpoint!

If you notice you've lost context mid-task:

```python
mcp__mini-claude__context_checkpoint_restore()
```

This restores your last saved state including:

- What task you were working on
- Which steps are done/pending
- Key decisions made
- Files involved

### IMPORTANT: When Writing Continuation Summaries

If context is being compacted and you're writing a continuation summary, **ALWAYS INCLUDE**:

```text
CRITICAL: This project uses Mini Claude MCP for persistent memory.
FIRST ACTION after resuming: Call mcp__mini-claude__session_start(project_path="<path>")
This will restore your checkpoint and show what you were working on.
```

This ensures the next Claude instance knows to use Mini Claude.

---

## What Is Mini Claude?

Mini Claude is an MCP server that gives you (Claude Code):
1. **Smart memory** - Persistent, auto-tagged, clustered, with contextual injection
2. **Mistake tracking** - Warns you about past errors
3. **Work journaling** - Tracks what you do
4. **Loop detection** - Warns when you're editing same file 3+ times
5. **Scope guard** - Warns when you edit outside declared scope
6. **Impact analysis** - Shows what breaks before you break it

Runs locally with Ollama + `qwen2.5-coder:7b`.

### Known Limitation: Auto-Detection for Failed Commands

Claude Code's PostToolUse hooks **don't fire for failed bash commands** (exit code ≠ 0).
This means auto-mistake detection only works for:
- ✅ Test runs that succeed but show failures in output
- ✅ Commands that run but produce error messages
- ❌ Commands that crash (ImportError, SyntaxError, etc.)

**For actual command failures, you must manually call `work_log_mistake`.**

See: [GitHub Issue #6371](https://github.com/anthropics/claude-code/issues/6371)

### Smart Memory Features (NEW!)

Session start now automatically:
- **Deduplicates** memories (>85% similar → merged)
- **Clusters** related memories by tags (3+ with same tag → group)
- **Auto-tags** memories (bootstrap, auth, testing, etc.)
- **Indexes** memories by file for contextual lookup

When you edit a file, the hook shows **only relevant memories** for that file, not all 20+ memories.

Use `memory_search` to find specific memories:
```python
# Find memories related to a file
memory_search(project_path="/path", file_path="auth.py")

# Find memories by tag
memory_search(project_path="/path", tags=["bootstrap", "auth"])

# Keyword search
memory_search(project_path="/path", query="httpx timeout")
```

Use `memory_cleanup` for manual control over decay/removal:
```python
# Preview what would be cleaned (dry_run=True by default)
memory_cleanup(project_path="/path")

# Apply cleanup including decay
memory_cleanup(project_path="/path", dry_run=False)
```

---

## All Tools

### Session & Memory (USE THESE!)
- `session_start` - **START HERE** every session (now auto-cleans duplicates + creates clusters!)
- `session_end` - **END HERE** - summarizes + saves
- `memory_remember` - Store something important
- `memory_recall` - Get all memories (flat list)
- `memory_search` - **Search contextually** by file, tags, or keyword (NEW!)
- `memory_cluster_view` - **View grouped memories** with summaries (NEW!)
- `memory_cleanup` - **Clean up memories** - dedup, cluster, decay (NEW!)
- `memory_forget` - Clear project memories

### Work Tracking (YOUR JUNIOR TAKING NOTES)
- `work_log_mistake` - **Log when things break**
- `work_log_decision` - Log why you did something
- `pre_edit_check` - **Unified check before editing** (NEW - replaces 3 tools!)
- ~~`work_pre_edit_check`~~ - DEPRECATED, use `pre_edit_check`
- ~~`work_session_summary`~~ - Use `session_end` instead
- ~~`work_save_session`~~ - Use `session_end` instead

### Code Quality (PREVENT "AI SLOP")
- `code_quality_check` - Check code BEFORE writing
- `output_validate_code` - Detect fake/silent failure patterns
- `output_validate_result` - Check outputs for fake results

### Loop Detection (PREVENT DEATH SPIRALS)
- `loop_record_edit` - Record file edit
- ~~`loop_check_before_edit`~~ - DEPRECATED, use `pre_edit_check`
- `loop_record_test` - Record test results
- `loop_status` - Get loop detection status

### Scope Guard (PREVENT OVER-REFACTORING)
- `scope_declare` - Declare files in scope for task
- ~~`scope_check`~~ - DEPRECATED, use `pre_edit_check`
- `scope_expand` - Add files to scope (deliberately)
- `scope_status` - Get scope violations
- `scope_clear` - Clear scope when done

### Context Guard (SURVIVE CONTEXT LOSS)
- `context_checkpoint_save` - **Save task state + handoff** (now includes handoff fields!)
- `context_checkpoint_restore` - Restore previous task state (includes handoff info)
- `context_checkpoint_list` - List all saved checkpoints
- `verify_completion` - **Claim + verify** in one call (NEW - replaces 2 tools!)
- `context_instruction_add` - Register critical instruction
- `context_instruction_reinforce` - Get instructions to remember
- ~~`context_claim_completion`~~ - DEPRECATED, use `verify_completion`
- ~~`context_self_check`~~ - DEPRECATED, use `verify_completion`
- ~~`context_handoff_create`~~ - DEPRECATED, use `context_checkpoint_save` with handoff params
- ~~`context_handoff_get`~~ - DEPRECATED, use `context_checkpoint_restore`

### Output Validator (CATCH SILENT FAILURES)
- `output_validate_code` - Detect fake/silent failure patterns
- `output_validate_result` - Check outputs for fake results

### Search & Analysis
- `scout_search` - Search codebase
- `scout_analyze` - Analyze code with LLM
- `file_summarize` - Summarize a file
- `deps_map` - Map dependencies
- `impact_analyze` - Check dependencies before editing

### Conventions
- `convention_add` - Store a rule
- `convention_get` - Get rules
- `convention_check` - Check code against rules
- `code_pattern_check` - **Check code against conventions with LLM** (semantic analysis)

### Pre-Commit Validation (CATCH ISSUES BEFORE COMMITTING!)
- `think_audit` - **Audit file for anti-patterns** (with quick_fix suggestions)
- `audit_batch` - **Audit multiple files at once** (supports glob patterns)
- `find_similar_issues` - **Search codebase for bug patterns** (find all `except: pass`, etc.)

### Testing & Git (AUTO-RUN TESTS, SMART COMMITS)
- `test_run` - Auto-detect and run tests (pytest, npm, go, rust, make)
- `test_can_claim_completion` - Check if tests allow completion claim
- `git_generate_commit_message` - Generate commit message from work logs + decisions
- `git_auto_commit` - Auto-commit with context-aware message

### Momentum Tracking (PREVENT STOPPING MID-TASK)
- `momentum_start_task` - Start tracking multi-step task
- `momentum_complete_step` - Mark step as complete
- `momentum_check` - Check if momentum is maintained
- `momentum_finish_task` - Mark task as finished
- `momentum_status` - Get current momentum status

### Thinking Partner (LOCAL LLM REASONING)
- `think_research` - Search codebase + LLM reasoning (NOTE: web search is limited)
- `think_compare` - Compare multiple approaches with pros/cons
- `think_challenge` - Challenge assumptions (devil's advocate)
- `think_explore` - Explore solution space (simple → ideal)
- `think_best_practice` - Find best practices (uses local LLM)

### Habit Tracker (OPTIONAL)
- `habit_get_stats` - View habit statistics (last 7 days)
- `habit_get_feedback` - Get gamified feedback on your habits
- `habit_session_summary` - Comprehensive session summary (or use `session_end`)

### Status
- `mini_claude_status` - Health check

---

## Why This Exists

AI coding assistants:
- Forget context between sessions
- Don't learn project conventions
- **Repeat the same mistakes**
- Get stuck in death spirals
- Over-refactor and break things
- Generate code that fails silently

Mini Claude fixes this by giving you memory and self-awareness tools.
**But they only work if you use them.**

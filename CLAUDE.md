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
mcp__mini-claude__work_pre_edit_check(file_path="<the file>")
```

This shows past mistakes with that file. **If you skip this, you will repeat mistakes.**

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
| Start of session | `session_start` | Load context + past mistakes + **auto-restore checkpoints** |
| Before editing important files | `work_pre_edit_check` | See past mistakes with file |
| Something breaks | `work_log_mistake` | Remember for next time |
| Make a decision | `work_log_decision` | Explain WHY for future |
| Multi-file task | `scope_declare` | Prevent over-refactoring |
| Before big changes | `impact_analyze` | See what depends on file |
| Audit a file | `think_audit` | Find anti-patterns + get quick fixes |
| Audit many files | `audit_batch` | Scan directory for issues |
| Find similar bugs | `find_similar_issues` | Search codebase for pattern |
| End of session | `work_save_session` | Persist work to memory |
| Before long tasks | `context_checkpoint_save` | **Survive context compaction** |
| When claiming done | `context_self_check` | Verify you actually did it |

---

## CRITICAL: Surviving Context Compaction

When context gets long, it will be compacted (summarized). **You WILL lose context.**

To survive compaction:

1. **Before long tasks**: `context_checkpoint_save(task_description, current_step, ...)`
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
1. **Persistent memory** - Survives across sessions
2. **Mistake tracking** - Warns you about past errors
3. **Work journaling** - Tracks what you do
4. **Loop detection** - Warns when you're editing same file 3+ times
5. **Scope guard** - Warns when you edit outside declared scope
6. **Impact analysis** - Shows what breaks before you break it

Runs locally with Ollama + `qwen2.5-coder:7b`.

---

## All 60 Tools

### Session & Memory (USE THESE!)
- `session_start` - **START HERE** every session
- `memory_remember` - Store something important
- `memory_recall` - Get memories
- `memory_forget` - Clear project memories

### Work Tracking (YOUR JUNIOR TAKING NOTES)
- `work_log_mistake` - **Log when things break**
- `work_log_decision` - Log why you did something
- `work_pre_edit_check` - **Check before editing**
- `work_session_summary` - See session work
- `work_save_session` - Persist to memory

### Code Quality (PREVENT "AI SLOP")
- `code_quality_check` - Check code BEFORE writing

### Loop Detection (PREVENT DEATH SPIRALS)
- `loop_record_edit` - Record file edit
- `loop_check_before_edit` - Check if editing might loop
- `loop_record_test` - Record test results
- `loop_status` - Get loop detection status

### Scope Guard (PREVENT OVER-REFACTORING)
- `scope_declare` - Declare files in scope for task
- `scope_check` - Check if file is in scope
- `scope_expand` - Add files to scope (deliberately)
- `scope_status` - Get scope violations
- `scope_clear` - Clear scope when done

### Context Guard (SURVIVE CONTEXT LOSS)
- `context_checkpoint_save` - **Save task state** before compaction
- `context_checkpoint_restore` - Restore previous task state
- `context_checkpoint_list` - List all saved checkpoints
- `context_instruction_add` - Register critical instruction
- `context_instruction_reinforce` - Get instructions to remember
- `context_claim_completion` - Claim task is complete
- `context_self_check` - **Verify claimed work was done**
- `context_handoff_create` - Create handoff for next session
- `context_handoff_get` - Get previous session's handoff

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

### Thinking Partner (OVERCOME TUNNEL VISION!)
- `think_research` - Deep research (web + codebase + LLM reasoning)
- `think_compare` - Compare multiple approaches with pros/cons
- `think_challenge` - Challenge assumptions (devil's advocate)
- `think_explore` - Explore solution space (simple → ideal)
- `think_best_practice` - Find current (2026) best practices

### Habit Tracker (BUILD GOOD HABITS!)
- `habit_get_stats` - View habit statistics (last 7 days)
- `habit_get_feedback` - Get gamified feedback on your habits
- `habit_session_summary` - **Call before ending session** - Creates comprehensive handoff

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

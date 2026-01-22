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
mcp__mini-claude__work(
  operation="log_mistake",
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
mcp__mini-claude__scope(
  operation="declare",
  task_description="What you're doing",
  in_scope_files=["file1.py", "file2.py"]
)
```

This prevents scope creep and over-refactoring.

---

## RECOMMENDED: Log Important Decisions

When you choose between approaches or make architectural decisions:

```
mcp__mini-claude__work(
  operation="log_decision",
  decision="What you decided",
  reason="Why"
)
```

Next session, you'll know WHY things are the way they are.

---

## Quick Reference

| When | Tool | Operation | Why |
|------|------|-----------|-----|
| Start of session | `session_start` | - | Load context + past mistakes + auto-cleanup |
| Before editing | `pre_edit_check` | - | Past mistakes + loop risk + scope check |
| Something breaks | `work` | `log_mistake` | Remember for next time |
| Make a decision | `work` | `log_decision` | Explain WHY for future |
| Multi-file task | `scope` | `declare` | Prevent over-refactoring |
| Before big changes | `impact_analyze` | - | See what depends on file |
| Audit a file | `think` | `audit` | Find anti-patterns |
| Audit many files | `audit_batch` | - | Scan directory for issues |
| End of session | `session_end` | - | Summary + save in one call |
| Find memories | `memory` | `search` | Contextual search |
| View clusters | `memory` | `clusters` | Grouped memories |
| Before long tasks | `context` | `checkpoint_save` | Survive compaction |
| When claiming done | `context` | `verify_completion` | Claim + verify |

---

## CRITICAL: Surviving Context Compaction

When context gets long, it will be compacted (summarized). **You WILL lose context.**

To survive compaction:

1. **Before long tasks**:
```python
mcp__mini-claude__context(
  operation="checkpoint_save",
  task_description="...",
  current_step="...",
  completed_steps=[...],
  pending_steps=[...],
  files_involved=[...]
)
```

2. **Periodically**: Save checkpoints at natural breakpoints
3. **After compaction**: `session_start` auto-restores your checkpoint!

If you notice you've lost context mid-task:

```python
mcp__mini-claude__context(operation="checkpoint_restore")
```

### IMPORTANT: When Writing Continuation Summaries

If context is being compacted and you're writing a continuation summary, **ALWAYS INCLUDE**:

```text
CRITICAL: This project uses Mini Claude MCP for persistent memory.
FIRST ACTION after resuming: Call mcp__mini-claude__session_start(project_path="<path>")
This will restore your checkpoint and show what you were working on.
```

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
- Commands that run but produce error messages
- Test runs that succeed but show failures in output

**For actual command failures, you must manually call `work(operation="log_mistake")`.**

---

## All Tools (v2 - Combined for Efficiency)

### Essential Tools (Always Available)
| Tool | Purpose |
|------|---------|
| `session_start` | **START HERE** - loads memories, checkpoints, auto-cleans duplicates |
| `session_end` | **END HERE** - summarizes work, saves to memory |
| `pre_edit_check` | Run before editing - checks mistakes, loops, scope |
| `mini_claude_status` | Health check |

### Memory Tool
```python
memory(operation, project_path, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `remember` | content, category, relevance | Store discovery/note |
| `recall` | - | Get all memories |
| `forget` | - | Clear project memories |
| `search` | file_path, tags, query, limit | Find relevant memories |
| `clusters` | cluster_id | View grouped memories |
| `cleanup` | dry_run, min_relevance, max_age_days | Dedupe/decay old memories |

### Work Tool
```python
work(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `log_mistake` | description, file_path, how_to_avoid | Record errors |
| `log_decision` | decision, reason, alternatives | Record choices |

### Scope Tool
```python
scope(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `declare` | task_description, in_scope_files, in_scope_patterns | Set task scope |
| `check` | file_path | Verify file is in scope |
| `expand` | files_to_add, reason | Add files to scope |
| `status` | - | Get violations |
| `clear` | - | Reset scope |

### Loop Tool
```python
loop(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `record_edit` | file_path, description | Log file edit |
| `record_test` | passed, error_message | Log test result |
| `check` | file_path | Check if safe to edit |
| `status` | - | Get edit counts |

### Context Tool
```python
context(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `checkpoint_save` | task_description, current_step, completed_steps, pending_steps, files_involved | Save task state |
| `checkpoint_restore` | task_id | Restore checkpoint |
| `checkpoint_list` | - | List checkpoints |
| `verify_completion` | task, evidence, verification_steps | Claim + verify done |
| `instruction_add` | instruction, reason, importance | Register critical instruction |
| `instruction_reinforce` | - | Get instructions to remember |

### Think Tool
```python
think(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `research` | question, project_path, depth | Search codebase + reason |
| `compare` | options, context, criteria | Evaluate options |
| `challenge` | assumption, context | Devil's advocate |
| `explore` | problem, constraints, project_path | Solution space |
| `best_practice` | topic, language_or_framework | Find patterns |
| `audit` | file_path, focus_areas, min_severity | Check for anti-patterns |

### Momentum Tool
```python
momentum(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `start` | task_description, expected_steps | Begin tracking |
| `complete` | step | Mark step done |
| `check` | - | Check momentum maintained |
| `finish` | - | Mark task complete |
| `status` | - | Get progress |

### Habit Tool
```python
habit(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `stats` | days | Get habit statistics |
| `feedback` | - | Get gamified feedback |
| `summary` | project_path | Session summary |

### Convention Tool
```python
convention(operation, project_path, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `add` | rule, category, reason, examples, importance | Store rule |
| `get` | category | Get rules |
| `check` | code_or_filename | Check against rules |

### Output Tool
```python
output(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `validate_code` | code, context | Check for fake/silent failures |
| `validate_result` | output, expected_format, should_contain | Check output validity |

### Test Tool
```python
test(operation, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `run` | project_dir, test_command, timeout | Run tests |
| `can_claim` | - | Check if tests allow completion |

### Git Tool
```python
git(operation, project_dir, ...)
```
| Operation | Parameters | Purpose |
|-----------|------------|---------|
| `commit_message` | - | Generate from work logs |
| `commit` | message, files | Auto-commit |

### Standalone Tools
| Tool | Purpose |
|------|---------|
| `scout_search` | Search codebase semantically |
| `scout_analyze` | Analyze code with LLM |
| `file_summarize` | Summarize file purpose |
| `deps_map` | Map file dependencies |
| `impact_analyze` | Analyze change impact |
| `code_quality_check` | Check for AI slop |
| `code_pattern_check` | Check against conventions (LLM) |
| `audit_batch` | Audit multiple files |
| `find_similar_issues` | Search for bug patterns |

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

---

## Token Efficiency (v2)

Mini Claude v2 uses combined tools with operation parameters:
- **Before**: 66 tools, ~20K tokens per message
- **After**: 25 tools, ~5K tokens per message (75% reduction)

This means faster responses and lower costs while maintaining full functionality.

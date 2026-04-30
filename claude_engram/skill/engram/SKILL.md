---
name: engram
description: Claude Engram persistent memory — quick reference for all MCP tools and automatic hook behaviors. Use when you need to remember how to store, search, or manage memories, or query session history.
---

# Claude Engram — Quick Reference

## Automatic (hooks, zero invocation)
- Edit/error/decision tracking, loop warnings, compaction survival
- Session mining: background indexing of conversations after every session
- Smart session start: last session context + recurring patterns
- Predictive context: related files + likely errors before edits
- Tool duration tracking: slow tools surfaced in handoffs

## Memory Tools
- `memory(remember, content="...", project_path="...")` — store a discovery
- `memory(add_rule, content="...", reason="...", project_path="...")` — permanent rule (never archived)
- `memory(list_rules, project_path="...")` — show all rules with IDs
- `memory(search, query="...", project_path="...")` — keyword search
- `memory(hybrid_search, query="...", project_path="...")` — semantic + keyword
- `memory(recent, project_path="...")` — newest memories
- `memory(list_mistakes, project_path="...")` — view tracked mistakes with IDs and file associations
- `memory(acknowledge_mistake, memory_id="...", project_path="...")` — archive a learned mistake (stops pre-edit warnings)
- `memory(cleanup, dry_run=true, project_path="...")` — find dupes/stale
- `memory(consolidate, dry_run=true, project_path="...")` — LLM-powered merge (shows what changes)
- `memory(archive, project_path="...")` — move old memories to cold storage
- `memory(modify, memory_id="...", content="...", project_path="...")` — edit a memory
- `memory(delete, memory_id="...", project_path="...")` — remove a memory

## Work Tools
- `work(log_decision, decision="...", reason="...")` — log architectural choice
- `work(log_mistake, description="...", how_to_avoid="...")` — log complex mistake

## Session Mining Tools
- `session_mine(search, query="...", project_path="...")` — search past conversations (includes tool content)
- `session_mine(decisions, query="...", project_path="...")` — find when/why a decision was made
- `session_mine(replay, file_path="...", project_path="...")` — discussions about a file
- `session_mine(predict, file_path="...", project_path="...")` — predict context for an edit
- `session_mine(struggles, project_path="...")` — recurring struggle files
- `session_mine(errors, project_path="...")` — recurring error patterns
- `session_mine(overview, project_path="...")` — project stats
- `session_mine(reflect, project_path="...")` — LLM root cause analysis
- `session_mine(search, query="...", since="2026-04-01")` — temporal filtering
- `session_mine(reindex, mode="bootstrap", project_path="...")` — rebuild from history (shows results)

## Context Protection
- `context(checkpoint_save, ...)` — save task state for compaction/session recovery
- `context(checkpoint_restore)` — restore last checkpoint
- `context(handoff_create, ..., project_path="...")` — create handoff for next session
- `context(handoff_get, project_path="...")` — retrieve latest handoff (per-project)
- `context(instruction_add, instruction="...", reason="...", project_path="...")` — add a rule (routes to memory system)
- `context(instruction_list, project_path="...")` — list all rules
- `context(instruction_delete, memory_id="...", project_path="...")` — delete a rule by ID

Example:
```
context(
  operation="checkpoint_save",
  task_description="Fixing auth module",
  current_step="Step 3: token validation",
  completed_steps=["Step 1: added middleware", "Step 2: wrote tests"],
  pending_steps=["Step 3: token validation", "Step 4: deploy"],
  files_involved=["auth.py", "middleware.py"],
  project_path="/path/to/project"
)
```

## Memory Categories
| Category | Protected | Auto-captured |
|---|---|---|
| rule | Never archived | Manual (or via instruction_add) |
| mistake | Archivable via acknowledge | Auto from errors in project files |
| decision | No | Auto from prompts + session mining |
| discovery | No | Manual |

## Key Behaviors
- Rules cascade from workspace to sub-projects
- Only file-relevant memories inject before edits (no generic noise)
- Mistakes only logged from errors in project files (not inline python, not pip packages)
- Loop counter resets after git commits
- Scorer server auto-starts on demand (no silent degradation)
- Session mining runs in background after SessionEnd
- Bootstrap: first session on new project auto-mines existing history

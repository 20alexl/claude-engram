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

## Memory Tools
- `memory(remember, content="...", project_path="...")` — store a discovery
- `memory(add_rule, content="...", reason="...", project_path="...")` — permanent rule (never archived)
- `memory(search, query="...", project_path="...")` — keyword search
- `memory(hybrid_search, query="...", project_path="...")` — semantic + keyword
- `memory(recent, project_path="...")` — newest memories
- `memory(cleanup, dry_run=true, project_path="...")` — find dupes/stale
- `memory(archive, project_path="...")` — move old memories to cold storage
- `memory(list_rules, project_path="...")` — show all rules

## Work Tools
- `work(log_decision, decision="...", reason="...")` — log architectural choice
- `work(log_mistake, description="...", how_to_avoid="...")` — log complex mistake

## Session Mining Tools
- `session_mine(search, query="...", project_path="...")` — search past conversations
- `session_mine(decisions, query="...", project_path="...")` — find when/why a decision was made
- `session_mine(replay, file_path="...", project_path="...")` — discussions about a file
- `session_mine(predict, file_path="...", project_path="...")` — predict context for an edit
- `session_mine(struggles, project_path="...")` — recurring struggle files
- `session_mine(errors, project_path="...")` — recurring error patterns
- `session_mine(correlations, project_path="...")` — files always edited together
- `session_mine(overview, project_path="...")` — project stats
- `session_mine(cross_project)` — patterns across all projects
- `session_mine(reflect, project_path="...")` — LLM root cause analysis of recurring errors, patterns, decisions
- `session_mine(search, query="...", since="2026-04-01")` — temporal filtering
- `session_mine(reindex, mode="bootstrap", project_path="...")` — rebuild from history

## Memory Categories
| Category | Protected | Auto-captured |
|---|---|---|
| rule | Never archived | Manual only |
| mistake | Never archived | Auto from errors |
| decision | No | Auto from prompts + session mining |
| discovery | No | Manual |

## Context Protection
- `context(checkpoint_save, ...)` — save task state for compaction/session recovery
- `context(checkpoint_restore)` — restore last checkpoint
- `context(handoff_create, ...)` — create handoff for next session
- `context(handoff_get)` — retrieve latest handoff

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

## Key Behaviors
- Rules cascade from workspace to sub-projects
- Only file-relevant memories inject before edits (no generic noise)
- Loop counter resets after git commits
- Session mining runs in background after SessionEnd (no hook timeout impact)
- Bootstrap: first session on new project auto-mines existing history

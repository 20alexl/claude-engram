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
- Pre-edit import/export check: proposed imports verified against the per-project code index (AST, LLM-free) — `<engram-precheck>` banner with closest-name suggestions
- Blast-radius: editing a shared module lists its importers — `<engram-blast-radius>`
- Outcome feedback loop: tracks which injection kinds (memory/prediction/precheck/blast) precede passing tests; see `session_mine(reflect)`
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
- `memory(cleanup, dry_run=true, project_path="...")` — find dupes/stale (clustering happens here, internally)
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
- `session_mine(reflect, project_path="...")` — injection precision (which context kinds precede passing tests) + LLM insights from recurring patterns
- `session_mine(commitments, project_path="...")` — what you said you'd do THIS session and whether it's done; scans the LIVE transcript (deferred open-loops + recent in-flight). Run before asking the user "what next?" or on resume
- `session_mine(search, query="...", kind="next-step")` — filter hits by kind: decision / next-step / error / narration
- `session_mine(search, query="...", since="2026-04-01")` — temporal filtering
- `session_mine(reindex, mode="bootstrap", project_path="...")` — rebuild from history (shows results)

## Context Protection
Checkpoint and handoff are ONE construct (a durable ring). `checkpoint_*` are primary; `handoff_*` are deprecated aliases.

**Checkpoint vs mining:** a checkpoint is the durable note *you* write for the next session; session mining is what engram derives from the transcript. For "what's next" on resume, prefer `session_mine(commitments)` (reads the live session) over re-reading a stale checkpoint's pending_steps.
- `context(checkpoint_save, ...)` — save task/session state for compaction/recovery (add handoff_summary/handoff_context_needed/handoff_warnings to bridge to the next session; emits HANDOFF.md)
- `context(checkpoint_restore, project_path="...", index=0)` — restore a checkpoint (0 = latest, N = older from history)
- `context(checkpoint_list, project_path="...")` — list the unified history newest-first (index, age, kind, summary)
- `context(handoff_create | handoff_get | handoff_list, ...)` — deprecated aliases of the checkpoint_* ops above

For rules use the dedicated API: `memory(add_rule / list_rules / delete)`.

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
| rule | Never archived | Manual (via memory add_rule) |
| mistake | Archivable via acknowledge | Auto from errors in project files |
| decision | No | Auto from prompts + session mining |
| discovery | No | Manual |

## Key Behaviors
- Rules cascade from workspace to sub-projects
- Only file-relevant memories inject before edits (no generic noise)
- Pre-edit injection is path-aware: a shared basename across diverging paths (e.g. service-a/.../__init__.py vs service-b/.../__init__.py) is not treated as a match; generic basenames like `__init__.py` or `index.js` require a full-path signal to score
- Mistakes only logged from errors in project files (not inline python, not pip packages)
- Loop counter resets after git commits
- Scorer server auto-starts on demand (no silent degradation)
- Session mining runs in background after SessionEnd
- Bootstrap: first session on new project auto-mines existing history
- Checkpoints/handoffs are durable: one ring buffer (last 20); trivial auto-handoffs don't clobber a substantive or manual one; manual always wins; retrieve any entry via `checkpoint_restore(index=N)` or browse with `checkpoint_list`
- Checkpoints are per-project (multi-project workspaces don't clobber each other)
- Subagents: memory injection and output are skipped (saves context), but file edits are still tracked

# Claude Engram - Persistent Memory for Claude Code

## How It Works

Claude Engram intercepts your tool calls via Claude Code hooks and automatically tracks what you do. Most features require zero invocations - they fire through hooks on every edit, bash command, error, and session event.

You also have MCP tools for things that need semantic judgment (saving discoveries, declaring rules, managing archives).

## What's Fully Automatic

These happen via hooks. You don't call anything:

| What | When It Fires | What You See |
|---|---|---|
| **Session restore** | SessionStart hook | Rules, mistakes, checkpoint, handoff |
| **Edit tracking** | PostToolUse Edit/Write | "Edit tracked: file.py (edit #3)" |
| **Loop warnings** | PreToolUse Edit/Write | Warning when same file edited 3+ times (state lives in per-session hook state, so concurrent sessions don't cross-contaminate) |
| **Scored memory injection** | PreToolUse Edit/Write | Top 3 relevant memories for the file |
| **Test tracking** | PostToolUse Bash | "PASS/FAIL Test tracked" |
| **Error auto-logging** | PostToolUseFailure (all tools) | Mistakes auto-saved from any failed tool |
| **Decision capture** | UserPromptSubmit | "let's use X" parsed via semantic + regex scoring |
| **Checkpoint on compact** | PreCompact | Task state saved before context compaction |
| **Context re-injection** | PostCompact | Rules + mistakes + decisions re-injected |
| **Session handoff on stop** | Stop | Saves last_assistant_message + files for next session |
| **Session summary on end** | SessionEnd | Files edited, memory counts |
| **Search spiral detection** | PostToolUse Bash | Warns after 3+ failed search commands |
| **Memory archiving** | cleanup / session_start | Old inactive memories archived, not deleted |
| **Sub-project scoping** | PreToolUse / PostToolUse | Memories scoped to the right sub-project |
| **Data migrations** | SessionStart (upgrade) | Cheap inline check; full migration in background |
| **Pre-edit import check** | PreToolUse Edit/Write | `<engram-precheck>` when a proposed import won't resolve against the code index (closest-name suggestion) |
| **Blast-radius alert** | PreToolUse Edit/Write | `<engram-blast-radius>` listing modules that import the file being edited |
| **Outcome feedback loop** | PreToolUse + PostToolUse Bash | Injection kinds correlated with test pass/fail; surfaced via `session_mine(reflect)` |

## Multi-Project Workspaces

When run from a workspace root containing multiple projects, memories are automatically scoped to the right sub-project based on which file is being edited. Project boundaries are detected by looking for markers like `pyproject.toml`, `package.json`, `.git`, or `CLAUDE.md`.

Rules and mistakes from the workspace root are inherited by all sub-projects. You don't need to configure anything.

## When To Use Tools

### Use When Helpful

- `memory(remember)` - Save an important discovery about the codebase.
- `memory(add_rule)` - Add a permanent rule (e.g., "always use strict TypeScript").
- `work(log_decision)` - Log an important architectural choice with reasoning.
- `work(log_mistake)` - Log a complex mistake the auto-detection missed.
- `impact_analyze` - Before refactoring shared files.
- `scout_search` - Semantic codebase search when grep isn't enough.

### Advanced (Optional)

- `scope(declare)` - Set explicit file boundaries for a complex task.
- `context(checkpoint_save)` - Manual checkpoint for very long tasks.
- `memory(archive)` - Review and archive old memories.

### You Almost Never Need

- `session_start` - SessionStart hook auto-starts. Only call for deep context load.
- `session_end` - Stop + SessionEnd hooks handle teardown. Just a summary view.
- `pre_edit_check` - PreToolUse hook auto-runs this. Only call manually for impact analysis.

## Quick Reference

### Memory Operations

```python
# Store
memory(operation="remember", content="Important fact", project_path="/path")
memory(operation="add_rule", content="Always do X", reason="Because Y", project_path="/path")

# Find
memory(operation="search", query="auth", project_path="/path")
memory(operation="recent", project_path="/path", limit=10)

# Mistakes
memory(operation="list_mistakes", project_path="/path")                  # View all with IDs
memory(operation="acknowledge_mistake", memory_id="abc123", project_path="/path")  # Archive learned mistake

# Manage (IDs shown in [brackets] at session start and in hook output)
memory(operation="modify", memory_id="abc123", content="Updated", project_path="/path")
memory(operation="delete", memory_id="abc123", project_path="/path")
memory(operation="promote", memory_id="abc123", reason="Important", project_path="/path")
memory(operation="batch_delete", category="context", project_path="/path")

# Cleanup & Archive
memory(operation="cleanup", dry_run=True, project_path="/path")      # Preview: dedupe + archive
memory(operation="archive", dry_run=True, project_path="/path")       # Preview: move old to cold
memory(operation="archive_search", query="auth", project_path="/path") # Search cold tier
memory(operation="restore", memory_id="abc123", project_path="/path") # Bring back from archive
memory(operation="archive_status", project_path="/path")              # Hot vs archive counts
```

### Work Tracking

```python
work(operation="log_mistake", description="What broke", how_to_avoid="How to prevent")
work(operation="log_decision", decision="What you chose", reason="Why", alternatives=["Other options"])
```

### Context Protection

```python
# Checkpoint — save task state before compaction or session end
context(
    operation="checkpoint_save",
    task_description="Migrating auth to OAuth2",
    current_step="Step 3: token refresh",
    completed_steps=["Step 1: added provider config", "Step 2: login flow"],
    pending_steps=["Step 3: token refresh", "Step 4: tests"],
    files_involved=["auth.py", "oauth.py"],
    project_path="/path/to/project"
)

# Restore last checkpoint
context(operation="checkpoint_restore")

# Bridge to next session: checkpoint_save also carries handoff fields
# (handoff_create/get/list remain as deprecated aliases)
context(
    operation="checkpoint_save",
    task_description="OAuth2 migration",
    pending_steps=["Implement refresh_token()", "Add integration tests"],
    handoff_summary="OAuth2 migration 60% done, token refresh next",
    handoff_context_needed=["OAuth provider docs at docs/oauth.md"],
    handoff_warnings=["Don't touch legacy auth.py — still used by mobile"],
    project_path="/path/to/project"
)

# Restore an older entry from the ring (index=N; 0 = latest)
context(operation="checkpoint_restore", project_path="/path/to/project", index=1)

# Browse history newest-first (index, age, kind, summary)
context(operation="checkpoint_list", project_path="/path/to/project")

# Verify completion
context(operation="verify_completion", task="OAuth2 migration", verification_steps=["All tests pass", "Login flow works"])
```

## Memory System

### Categories

| Category | Purpose | Protected | Auto-captured |
|---|---|---|---|
| `rule` | Project rules that always apply | Never archived or decayed | No - manual |
| `mistake` | Errors to avoid repeating | Never archived or decayed | Yes - from failed tools |
| `decision` | Choices and reasoning | No | Yes - from user prompts |
| `discovery` | Facts learned about the codebase | No | No - manual |
| `context` | Session-specific notes | No | No - manual |

### Tiered Storage

- **Hot tier** (`memory.json`) - Rules, mistakes, recent memories. Loaded by hooks on every tool call.
- **Cold tier** (`archive.json`) - Old inactive memories. Searchable, restorable, never loaded on hot path.
- Memories auto-archive after 14 days without access (configurable: `CLAUDE_ENGRAM_ARCHIVE_DAYS`).
- Rules and mistakes never archive. High-relevance (7+) memories stay hot longer.
- `cleanup` archives before deleting. Nothing is lost without review.

### Smart Injection

Before every Edit/Write, the PreToolUse hook scores all hot memories against the current file context:

- 35% file path match (exact file > same dir > same extension > filename in content)
- 20% tag overlap (inferred from file path patterns)
- 20% recency (exponential decay over 30 days)
- 15% importance rating (1-10)
- 10% access frequency
- Rules get +0.3 bonus, mistakes get +0.2

File-path matching is path-aware: a shared basename across diverging paths (e.g. `service-a/myapp/__init__.py` vs `service-b/myapp/__init__.py`) is not treated as a match. Generic basenames like `__init__.py` or `index.js` require a full-path signal to score; specific filenames still match on name alone.

Top 3 are injected as context. You'll see them in the hook output before edits.

In multi-project workspaces, injection includes memories from the sub-project AND workspace-level memories (rules and mistakes cascade down).

Subagents (detected via `agent_id` in hook stdin) are handled differently: memory injection and hook output are skipped to preserve their limited context, but file edits are still tracked so the parent session knows what was modified.

### Decision Capture

User prompts are scored for decision intent using two tiers:

1. **Semantic scoring** (if `sentence-transformers` installed) - embedding cosine similarity against decision templates. A persistent scorer server (~1.1GB RAM with the default `bge-base-en-v1.5`, ~90MB with `all-MiniLM-L6-v2`; ~5-25ms per call) auto-starts on session start and auto-exits after 30 min idle.
2. **Regex fallback** - Weighted keyword + sentence structure analysis. Always available, no dependencies.

Captures patterns like "let's use X", "switch to Y", "don't use Z", "from now on always W". Does not capture questions, requests for info, or ambiguous statements.

## Context Compaction

Handled automatically:

1. **PreCompact** hook saves checkpoint with task state and files in progress.
2. **PostCompact** hook re-injects rules, mistakes, and recent decisions.
3. No manual action needed. If you want deeper restore, call `session_start`.

## Session Mining

Automatically mines Claude Code session JSONL logs for intelligence that hooks can't capture.

**Automatic (no invocation):**
- **Background indexing**: SessionEnd spawns miner that indexes the session, extracts decisions/mistakes/approaches, builds search embeddings
- **Smart session start**: Shows last session context (files edited, activity, errors)
- **Pattern injection**: Recurring struggles and errors shown at session start
- **Predictive context**: Before edits, shows related files and likely errors from history
- **Bootstrap**: First session on a new project auto-detects existing history and mines it

**MCP tool (`session_mine`):**
- `search(query)` — semantic search across all past conversations; accepts a `kind` filter (`decision`/`next-step`/`error`/`narration`) to narrow results by hit type (regex-classified, no LLM)
- `decisions(query)` — find when/why a decision was made, with context
- `replay(file_path)` — find discussions about a specific file
- `predict(file_path)` — predict what context you'll need for an edit
- `commitments` — reads the LIVE transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items: DEFERRED channel scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer mentions; IN-FLIGHT channel scans last ~30 messages for I'll/let me/next actions. Heuristic, LLM-free. Run before asking "what next?" or on resume — it sees the open session, which the post-session mining index cannot.
- `reflect` — injection precision report: which context kinds (memory/prediction/precheck/blast) precede passing tests, plus LLM-synthesized insights from recurring mistakes/patterns
- `cross_project` — patterns across all your projects
- `overview` — project stats (sessions, messages, top files, errors)
- `reindex(mode=bootstrap)` — rebuild index from all session history

## Technical Notes

- Local LLM: Ollama with `gemma3:12b` (configurable via `CLAUDE_ENGRAM_MODEL`) — **optional**. Used only by `scout_search`, `memory(consolidate)`, and `session_mine(reflect)` insight synthesis. Both background ops degrade silently when Ollama is absent. Everything proactive (hooks, code index, precheck, blast-radius, injection scoring) is LLM-free.
- Storage: `~/.claude_engram/` (manifest.json, projects/\<hash\>/{memory.json, embeddings.npy, session_index.json, extractions/}, checkpoints/). Override the location with `CLAUDE_ENGRAM_DIR`.
- Semantic scoring: configured encoder (default `BAAI/bge-base-en-v1.5`) via persistent TCP server on localhost (auto-managed)
- Batch embeddings: `embed_batch` protocol for 22x faster bulk embedding
- Session mining: background subprocess, fire-and-forget, no hook timeout impact
- Keep-alive: Set `CLAUDE_ENGRAM_KEEP_ALIVE=5m` to keep Ollama model loaded
- Hooks timeout: 1-2 seconds per hook. If a hook times out, it silently fails.
- All file writes use atomic temp-then-replace pattern.
- Hook installation merges into existing `~/.claude/settings.json` without destroying other hooks.
- Skill: `/engram` — quick reference installed to `~/.claude/commands/`

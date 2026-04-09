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
| **Loop warnings** | PreToolUse Edit/Write | Warning when same file edited 3+ times |
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
memory(operation="clusters", project_path="/path")

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
context(operation="checkpoint_save", task_description="...", pending_steps=["..."])
context(operation="handoff_create", handoff_summary="...", next_steps=["..."])
context(operation="verify_completion", task="...", verification_steps=["..."])
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

Top 3 are injected as context. You'll see them in the hook output before edits.

In multi-project workspaces, injection includes memories from the sub-project AND workspace-level memories (rules and mistakes cascade down).

### Decision Capture

User prompts are scored for decision intent using two tiers:

1. **Semantic scoring** (if `sentence-transformers` installed) - AllMiniLM cosine similarity against decision templates. A persistent scorer server (~90MB RAM, ~5-25ms per call) auto-starts on session start and auto-exits after 30 min idle.
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
- `search(query)` — semantic search across all past conversations
- `decisions(query)` — find when/why a decision was made, with context
- `replay(file_path)` — find discussions about a specific file
- `predict(file_path)` — predict what context you'll need for an edit
- `cross_project` — patterns across all your projects
- `overview` — project stats (sessions, messages, top files, errors)
- `reindex(mode=bootstrap)` — rebuild index from all session history

## Technical Notes

- Local LLM: Ollama with `gemma3:12b` (configurable via `CLAUDE_ENGRAM_MODEL`)
- Storage: `~/.claude_engram/` (manifest.json, projects/\<hash\>/{memory.json, embeddings.npy, session_index.json, extractions/}, checkpoints/)
- Semantic scoring: AllMiniLM via persistent TCP server on localhost (auto-managed)
- Batch embeddings: `embed_batch` protocol for 22x faster bulk embedding
- Session mining: background subprocess, fire-and-forget, no hook timeout impact
- Keep-alive: Set `CLAUDE_ENGRAM_KEEP_ALIVE=5m` to keep Ollama model loaded
- Hooks timeout: 1-2 seconds per hook. If a hook times out, it silently fails.
- All file writes use atomic temp-then-replace pattern.
- Hook installation merges into existing `~/.claude/settings.json` without destroying other hooks.
- Skill: `/engram` — quick reference installed to `~/.claude/commands/`

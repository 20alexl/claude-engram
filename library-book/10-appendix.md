# Appendix — Reference

[← Back to Table of Contents](./README.md) · [Previous: The Roadmap](./09-the-roadmap.md)

---

## MCP Tool Reference

### Essential Tools

#### `claude_engram_status()`

Check Claude Engram health (Ollama connection, model availability, memory stats, queue stats).

#### `session_start(project_path)`

Deep context load: memories, checkpoints, decisions, memory health, auto-cleanup. The SessionStart hook auto-starts a basic session, but this gives the full picture.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_path` | `str` | Yes | Project directory path |

#### `session_end(project_path?)`

Optional. Shows session summary. All memories auto-save without it.

#### `pre_edit_check(file_path)`

Unified check before editing: past mistakes, loop risk, scope status, scored memories.

---

### `memory` Tool (18 operations)

All operations require `operation` and `project_path`.

| Operation | Additional Parameters | Description |
|-----------|----------------------|-------------|
| `remember` | `content`, `category?`, `relevance?` | Store a memory |
| `recall` | — | Get all memories for project |
| `forget` | — | Clear all project memories |
| `search` | `file_path?`, `tags?`, `query?`, `limit?` | Find memories by criteria |
| `clusters` | `cluster_id?` | View grouped memories |
| `cleanup` | `dry_run?`, `min_relevance?`, `max_age_days?` | Dedupe + archive + decay |
| `consolidate` | `tag?`, `dry_run?` | LLM-powered merge of related memories |
| `add_rule` | `content`, `reason?` | Add permanent rule (never decays) |
| `list_rules` | — | Get all rules for project |
| `modify` | `memory_id`, `content?`, `relevance?`, `category?` | Edit a memory |
| `delete` | `memory_id` | Remove a single memory |
| `batch_delete` | `memory_ids?`, `category?` | Bulk delete (rules/mistakes protected) |
| `promote` | `memory_id`, `reason?` | Promote memory to rule |
| `recent` | `category?`, `limit?` | Recent memories, newest first |
| `archive` | `dry_run?` | Move old memories to cold tier |
| `restore` | `memory_id` | Bring archived memory back to active |
| `archive_search` | `query?`, `tags?`, `limit?` | Search cold tier |
| `archive_status` | — | Hot vs archive counts |

### `work` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `log_mistake` | `description`, `file_path?`, `how_to_avoid?` | Record an error |
| `log_decision` | `decision`, `reason`, `alternatives?` | Record a choice |

### `scope` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `declare` | `task_description`, `in_scope_files`, `in_scope_patterns?` | Set task scope |
| `check` | `file_path` | Verify file is in scope |
| `expand` | `files_to_add`, `reason` | Add files to scope |
| `status` | — | Get violations and scope state |
| `clear` | — | Reset scope |

### `loop` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `record_edit` | `file_path`, `description?` | Log a file edit |
| `record_test` | `passed`, `error_message?` | Log test result |
| `check` | `file_path` | Check loop risk for a file |
| `status` | — | Edit counts and warnings |
| `reset` | — | Clear all tracking |

### `context` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `checkpoint_save` | `task_description`, `current_step?`, `completed_steps?`, `pending_steps?`, `files_involved?` | Save task state |
| `checkpoint_restore` | `task_id?` | Restore (latest if no ID) |
| `checkpoint_list` | — | List all checkpoints |
| `verify_completion` | `task`, `verification_steps`, `evidence?` | Claim + verify done |
| `instruction_add` | `instruction`, `reason?`, `importance?` | Register critical rule |
| `instruction_reinforce` | — | Get instructions to remember |
| `handoff_create` | `handoff_summary`, `next_steps`, `handoff_context_needed?`, `handoff_warnings?` | Create session handoff |
| `handoff_get` | — | Retrieve latest handoff |

### `convention` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `add` | `project_path`, `rule`, `category?`, `reason?`, `examples?`, `importance?` | Store convention |
| `get` | `project_path`, `category?` | Get conventions |
| `check` | `project_path`, `code_or_filename` | Check against conventions (LLM) |
| `remove` | `project_path`, `rule` | Remove by matching text |

### `output` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `validate_code` | `code`, `context?` | Check for silent failures |
| `validate_result` | `output`, `expected_format?`, `should_contain?`, `should_not_contain?` | Validate command output |

### Standalone Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `scout_search` | `query`, `directory`, `max_results?` | Semantic codebase search |
| `scout_analyze` | `code`, `question` | LLM code analysis |
| `file_summarize` | `file_path`, `mode?` | Quick or detailed summary |
| `deps_map` | `file_path`, `project_root?`, `include_reverse?` | Map dependencies |
| `impact_analyze` | `file_path`, `project_root`, `proposed_changes?` | Change impact analysis |
| `code_quality_check` | `code`, `language?` | Detect AI slop patterns |
| `code_pattern_check` | `project_path`, `code` | Check against conventions (LLM) |
| `audit_batch` | `file_paths`, `min_severity?` | Audit multiple files |
| `find_similar_issues` | `issue_pattern`, `project_path`, `file_extensions?`, `exclude_paths?` | Search for bug patterns |

---

## Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `MINI_CLAUDE_MODEL` | `str` | `gemma3:12b` | Ollama model name |
| `MINI_CLAUDE_OLLAMA_URL` | `str` | `http://localhost:11434` | Ollama API URL |
| `MINI_CLAUDE_TIMEOUT` | `float` | `300` | LLM call timeout (seconds) |
| `MINI_CLAUDE_KEEP_ALIVE` | `str/int` | `0` | Ollama model keep-alive (`0`, `5m`, `-1`) |
| `MINI_CLAUDE_ARCHIVE_DAYS` | `int` | `14` | Days until inactive memories archive |
| `MINI_CLAUDE_SCORER_TIMEOUT` | `int` | `1800` | Scorer server idle timeout (seconds) |

## Memory Categories

| Category | Description | Protected | Auto-captured |
|----------|-------------|-----------|---------------|
| `rule` | Permanent project rule | Never archived/decayed | No |
| `mistake` | Error to avoid repeating | Never archived/decayed | Yes (PostToolUseFailure) |
| `decision` | Choice with reasoning | No | Yes (UserPromptSubmit) |
| `discovery` | Learned fact about codebase | No | No |
| `context` | Session-specific note | No | No |
| `priority` | Global priority | No | No |
| `note` | General note | No | No |

## Memory Scoring Weights

| Factor | Weight | Description |
|--------|--------|-------------|
| `file_match` | 0.35 | Exact file > same dir > same ext > filename in content |
| `tag_overlap` | 0.20 | Intersection of context tags and memory tags |
| `recency` | 0.20 | `exp(-age_days / 30)` |
| `relevance` | 0.15 | `entry.relevance / 10.0` |
| `access_freq` | 0.10 | `min(entry.access_count / 10.0, 1.0)` |

Category bonuses: `rule` +0.3, `mistake` +0.2.

## Hook Events

| Event | Matcher | Handler | What It Does |
|-------|---------|---------|-------------|
| `UserPromptSubmit` | `""` | `prompt_json` | Show rules/mistakes, capture decisions |
| `PreToolUse` | `Edit\|Write` | `pre_edit_json` | Inject memories, check loops/scope |
| `PostToolUse` | `Bash` | `bash_json` | Track tests, detect search spirals |
| `PostToolUse` | `Edit\|Write` | `post_edit_json` | Track edits, update loop counter |
| `PostToolUseFailure` | `""` | `tool_failure_json` | Auto-log errors from all tools |
| `Stop` | `""` | `stop_json` | Save handoff with last message |
| `SessionEnd` | `""` | `session_end_json` | Save session state, output summary |
| `SessionStart` | `""` | `session_start_json` | Load context, start scorer server |
| `PreCompact` | `""` | `pre_compact_json` | Auto-save checkpoint |
| `PostCompact` | `""` | `post_compact_json` | Re-inject rules/mistakes/decisions |

## Project Markers (Sub-Project Resolution)

Files that indicate a project root when resolving sub-projects in a workspace:

`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `go.sum`, `pom.xml`, `build.gradle`, `CMakeLists.txt`, `Makefile`, `setup.py`, `setup.cfg`, `.git`, `CLAUDE.md`

## File Storage Layout

```
~/.claude_engram/
├── memory.json              # Hot tier memories (per-project entries)
├── archive.json             # Cold tier (auto-created on first archive)
├── conventions.json         # Project coding conventions
├── hook_state.json          # Hook tracking state (counters, files edited)
├── loop_detector.json       # Per-file edit counts
├── scope_guard.json         # Declared scope state
├── scorer_port              # TCP port for scorer server (auto-managed)
├── scorer_pid               # PID of scorer server (auto-managed)
├── session_active           # Marker for active session (legacy)
├── embeddings/
│   └── decision_templates.json  # Cached AllMiniLM template embeddings
├── checkpoints/
│   ├── latest_checkpoint.json   # Most recent checkpoint
│   ├── latest_handoff.json      # Most recent handoff
│   ├── HANDOFF.md               # Human-readable handoff
│   └── task_*.json              # Individual checkpoints
└── habits.json              # Tool usage tracking (historical)
```

## Changelog

### v0.2.0 — 2026-04-04

- Tiered memory system (hot/archive) with auto-archiving
- Memory scoring and smart injection via `HotMemoryReader`
- PostToolUseFailure hook for all tools (not just Bash)
- PreCompact/PostCompact hooks for compaction survival
- SessionStart/SessionEnd/Stop hooks for native lifecycle management
- Semantic decision capture via AllMiniLM (optional `[semantic]` extra)
- Persistent scorer server (TCP localhost, auto-start/stop)
- Multi-project workspace support with sub-project resolution
- Parent-path memory inheritance (workspace rules cascade to sub-projects)
- Merge-safe hook installation (preserves user's other hooks)
- Default model changed from `qwen2.5-coder:7b` to `gemma3:12b`
- Fixed: handoff key mismatch (`created` vs `created_at`)
- Fixed: `recall()` missing `id`/`category`/`created_at` fields
- Fixed: `install.py` wrong install path (`claude_engram/` → `.`)
- Fixed: hook false fires on `x`/`y`/`data` variable names
- Fixed: `except: pass` detection matching inside comments
- Fixed: generic TypeError/AttributeError auto-logging without parseable message

### v0.1.0 — Initial Release

- MCP server with 20+ combined tools
- Hook-based auto-tracking (edits, tests, errors)
- Memory system with deduplication, tagging, clustering
- Loop detection, scope guard, context guard
- Convention tracking with LLM-based checking
- Scout semantic search and code analysis via Ollama
- Impact analysis and dependency mapping

## Glossary

| Term | Definition |
|------|-----------|
| Hot tier | Active memories in `memory.json`, loaded on every hook call |
| Cold tier | Archived memories in `archive.json`, loaded only on explicit request |
| Scoring | Weighted ranking of memories by relevance to current file context |
| Hook | Shell command executed by Claude Code at specific lifecycle events |
| MCP | Model Context Protocol — how Claude Code communicates with tool servers |
| Compaction | When Claude Code compresses conversation context to fit token limits |
| Handoff | Structured document for session-to-session continuity |
| Checkpoint | Saved task state (steps done, pending, files involved) |

## Links

- [Repository](https://github.com/20alexl/claude-engram)
- [Issue Tracker](https://github.com/20alexl/claude-engram/issues)
- [Project Book Template](https://github.com/20alexl/project-book-template)

---

[← Back to Table of Contents](./README.md)

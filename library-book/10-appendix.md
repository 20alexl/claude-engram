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

### `memory` Tool (20 operations)

All operations require `operation` and `project_path`.

| Operation | Additional Parameters | Description |
|-----------|----------------------|-------------|
| `remember` | `content`, `category?`, `relevance?` | Store a memory |
| `recall` | — | Get all memories for project |
| `forget` | — | Clear all project memories |
| `search` | `file_path?`, `tags?`, `query?`, `limit?` | Find memories by criteria |
| `hybrid_search` | `query`, `file_path?`, `tags?`, `limit?` | Semantic + keyword + scored search (best retrieval) |
| `embed_all` | — | Generate AllMiniLM embeddings for all memories |
| `cleanup` | `dry_run?`, `min_relevance?`, `max_age_days?` | Dedupe + archive + decay (clustering is internal) |
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
| `list_mistakes` | — | View tracked mistakes with IDs, files, age |
| `acknowledge_mistake` | `memory_id` | Archive a learned mistake (stops pre-edit warnings) |

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

Checkpoint and handoff are one unified ring buffer. `checkpoint_*` are the primary names; `handoff_*` are deprecated aliases kept for backward compatibility.

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `checkpoint_save` | `task_description`, `current_step?`, `completed_steps?`, `pending_steps?`, `files_involved?`, `handoff_summary?`, `handoff_context_needed?`, `handoff_warnings?` | Save task state; emits HANDOFF.md when handoff content is present |
| `checkpoint_restore` | `index?`, `task_id?` | Restore a checkpoint: `index=0` latest, `index=N` older from history |
| `checkpoint_list` | — | List unified checkpoint/handoff history newest-first (index, age, kind, summary) |
| `verify_completion` | `task`, `verification_steps`, `evidence?` | Claim + verify done |
| `handoff_create` | `handoff_summary`, `next_steps`, `handoff_context_needed?`, `handoff_warnings?` | [deprecated alias of checkpoint_save] |
| `handoff_get` | `project_path?`, `index?` | [deprecated alias of checkpoint_restore] |
| `handoff_list` | `project_path?` | [deprecated alias of checkpoint_list] |

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
| `audit_batch` | `file_paths`+`min_severity?` (files) · or `code`+`language?` (inline) | Audit files, or lint a snippet for AI-slop patterns |
| `find_similar_issues` | `issue_pattern`, `project_path`, `file_extensions?`, `exclude_paths?` | Search for bug patterns |

### MCP Tool Annotations

All 19 MCP tools carry MCP annotations (`readOnlyHint`, `idempotentHint`, `title`, `openWorldHint`). 10 read-only analysis tools (e.g., `memory(search/recall/recent/list_*)`, `session_mine`, `scope(check/status)`, `loop(check/status)`, `claude_engram_status`, `pre_edit_check`) are marked `readOnlyHint=true` and `idempotentHint=true`. Operation-enum tools that write state are marked `readOnlyHint=false`. All tools are local (`openWorldHint=false`). MCP clients and Claude Code's permission system use these annotations to skip confirmation prompts on read-only calls.

### `session_mine` Tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `search` | `query`, `project_path`, `limit?`, `method?`, `since?`, `until?`, `kind?` | Semantic search across past conversations. `kind` filters by hit type: `decision`/`next-step`/`error`/`narration` — regex-classified, LLM-free. |
| `decisions` | `query`, `project_path` | Find when/why a decision was made, with context |
| `replay` | `file_path`, `project_path`, `limit?` | Find discussions about a specific file |
| `struggles` | `project_path` | Files/areas with repeated difficulty |
| `errors` | `project_path` | Recurring error patterns across sessions |
| `correlations` | `project_path` | Files frequently edited together |
| `timeline` | `project_path` | Project development timeline |
| `summaries` | `project_path` | Auto-generated session summaries |
| `overview` | `project_path` | High-level project stats |
| `status` | `project_path` | Mining index coverage |
| `reindex` | `project_path`, `mode?` | Trigger background re-indexing (post_session, bootstrap, full) |
| `predict` | `file_path`, `project_path` | Predict context needed for a file edit |
| `cross_project` | — | Patterns across all projects |
| `reflect` | `project_path` | Injection precision report: which context kinds (memory/prediction/precheck/blast) precede passing tests, plus LLM-synthesized insights from recurring mistakes/patterns |
| `commitments` | `project_path` | Reads the LIVE transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items. Two channels: DEFERRED scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer mentions; IN-FLIGHT scans last ~30 messages for "I'll"/"let me"/"next" actions. Heuristic, LLM-free. The post-session mining index cannot see the open session; this op fills that gap. Run before asking "what next?" or on session resume. |

---

## Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `CLAUDE_ENGRAM_MODEL` | `str` | `gemma3:12b` | Ollama model name |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `str` | `http://localhost:11434` | Ollama API URL |
| `CLAUDE_ENGRAM_TIMEOUT` | `float` | `300` | LLM call timeout (seconds) |
| `CLAUDE_ENGRAM_KEEP_ALIVE` | `str/int` | `0` | Ollama model keep-alive (`0`, `5m`, `-1`) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `int` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `int` | `1800` | Scorer server idle timeout (seconds) |

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
├── manifest.json            # Maps project paths to hash directories (v3)
│                            #   migrations_applied: list of completed migration IDs
├── global.json              # Global entries (cross-project)
├── projects/
│   └── <hash>/              # Per-project storage (hash from manifest)
│       ├── memory.json      # This project's hot tier memories
│       ├── archive.json     # This project's cold tier
│       ├── embeddings.npy   # Binary AllMiniLM vectors (numpy, optional)
│       ├── embeddings_index.json  # ID-to-row mapping for embeddings.npy
│       ├── embeddings_pending.json # Hook embedding writes (merged on load)
│       ├── handoff_history.json   # Per-project capped ring buffer (last 20 handoffs)
│       ├── code_index.json        # Per-project symbol index (exports, imports, classes, functions)
│       ├── session_index.json     # Session metadata + offset cursors
│       ├── session_embeddings.npy # Conversation chunk embeddings for search
│       ├── session_embeddings_index.json # Chunk-to-session mapping
│       ├── patterns.json          # Detected patterns (struggles, errors, correlations)
│       └── extractions/           # Per-session extracted intelligence
│           └── <session_id>.json  # Decisions, mistakes, approaches, corrections
├── conventions.json         # Project coding conventions
├── hook_state.json          # Hook tracking state (counters, files edited)
├── loop_detector.json       # Per-file edit counts
├── scope_guard.json         # Declared scope state
├── scorer_port              # TCP port for scorer server (auto-managed)
├── scorer_pid               # PID of scorer server (auto-managed)
├── embeddings/
│   └── decision_templates.json  # Cached AllMiniLM template embeddings
├── checkpoints/
│   ├── latest_checkpoint.json   # Most recent checkpoint
│   ├── latest_handoff.json      # Most recent handoff (kept in sync for backward compat)
│   ├── handoff_history.json     # Global slot ring buffer (last 20 handoffs)
│   ├── HANDOFF.md               # Human-readable handoff
│   └── task_*.json              # Individual checkpoints
└── memory.json              # Legacy (auto-migrated to projects/ on first load)
```

## Changelog

### v0.6.1 — 2026-06-01

- **`session_mine(commitments)`** — reads the LIVE session transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items the post-session mining index cannot see. DEFERRED channel scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer language; IN-FLIGHT channel scans last ~30 messages for "I'll"/"let me"/"next" actions. Heuristic, LLM-free.
- **Typed search (`session_mine(search, kind=...)`)** — every search hit is now classified by kind (`decision`/`next-step`/`error`/`narration`) using regex, no LLM. Pass `kind` to filter results to one type.
- **MCP tool annotations** — all 19 MCP tools carry `readOnlyHint`/`idempotentHint`/`title`/`openWorldHint` annotations. 10 read-only analysis tools are marked read-only + idempotent; write-capable tools are marked accordingly; all are local (`openWorldHint=false`). Allows MCP clients and Claude Code's permission system to skip prompts on read-only calls.
- **Consolidation hardening + re-date/down-rank migration** — memory consolidation is more conservative; a background migration re-dates and down-ranks over-promoted entries produced by prior aggressive runs.
- **Memory age at injection** — pre-edit hook output now shows each injected memory's age alongside its score, so Claude can weight stale memories appropriately.
- **Per-project HANDOFF.md + `checkpoint_list` scoping** — `checkpoint_save` writes HANDOFF.md to the project directory (not only global checkpoints/); `checkpoint_list` is scoped to the active project and hides entries older than 7 days by default.

### v0.5.0 — 2026-05-28

- **Durable session handoffs** — replaces the single overwritable `latest_handoff.json` slot with a capped ring buffer (`handoff_history.json`, last 20)
  - Promotion guard: a trivial auto-handoff (no files edited, no decisions) never overwrites a substantive or manual handoff; manual handoffs always win
  - `kind: manual|auto` marker on every handoff
  - Walk-up read resolution: nearest project first, ancestors next, global slot last — a sub-project's handoff is no longer shadowed by the shared global slot
  - New `handoff_list` operation + `index` parameter on `handoff_get` to list and retrieve older handoffs (index 0 = latest, then newest-first)
  - The three handoff writers (`create_handoff`, Stop hook, PreCompact hook) now share one `handoff_store` module
  - Backward compatible: `latest_handoff.json` is kept in sync; an existing slot is seeded into history on first write (old/downgraded clients keep working)
- **Path-aware mistake relevance** — a shared basename across diverging paths (e.g. `V7/.../__init__.py` vs `V8/.../__init__.py`) is no longer treated as a match; generic basenames (`__init__.py`, `index.js`, …) require a full-path signal. Stops cross-version/cross-project mistakes firing on unrelated edits while preserving real matches
- **Actionable recurring errors** — pattern detection groups by a normalized signature (exception class + message with names/paths/numbers templated) instead of the bare exception class. `patterns.json` refreshes on the next mining pass
- **Fixes** — empty `<engram-error></engram-error>` tag suppressed; `last_message_preview` dropped from handoffs; `handoff_get` no longer prints the summary twice; `checkpoint_list` hides checkpoints older than 7 days (opt-in prune)
- **`extract_file_refs` fix** — it used a *capturing* group, so `re.findall` returned only the extension and silently dropped every path, storing basenames only. This was the root data cause of cross-version false positives (`related_files` never carried directory context). Now captures full/relative paths
- **Automatic, idempotent migrations** — on upgrade a version-stamped migration (run from the SessionStart hook and `install.py`, tracked in `manifest.migrations_applied`) seeds handoff history from the old single-slot file and, off the hook hot path, re-extracts `related_files` to full paths for existing memories. Forward-only, safe to re-run, downgrade-safe, no re-mine
- **Versioning** — `pyproject` version corrected (had lagged at 0.2.0 through the 0.3.x–0.4.x feature work)
- New benchmarks: `bench_handoff_durability.py`, `bench_path_relevance.py`

### v0.4.0 — 2026-04-08

- **Session mining platform** — automatically mines Claude Code session JSONL logs for intelligence
  - JSONL parser with streaming reader, path resolution, content extractors
  - Incremental session index with byte-offset cursors (8ms read, 1.5s full build for 330MB)
  - Background miner subprocess (fire-and-forget from SessionEnd hook)
  - Structural + semantic extractors: decisions, mistakes, approaches, user corrections
  - Cross-session semantic search: 7310 chunks indexed, 112ms query time
  - Pattern detection: struggle files, recurring errors, edit correlations
  - Project timeline, auto session summaries, project overview
  - Predictive context: related files + likely errors auto-injected before edits
  - Cross-project learning: aggregate patterns across all projects
  - Retroactive bootstrap: auto-mines existing session history on first use
- **Batch embedding protocol** — `embed_batch` in scorer server, 22x faster than individual calls
- **`session_mine` MCP tool** — 13 operations (search, decisions, replay, predict, cross_project, etc.)
- **`/engram` skill** — slash command installed to `~/.claude/commands/`
- **Smart session start** — shows last session context + recurring patterns
- **Obsidian vault compatibility** verified (25/25 benchmark with PARA + CLAUDE.md structure)

### v0.3.0 — 2026-04-07

- Per-project memory storage (manifest.json + projects/\<hash\>/ directories)
- Binary numpy embeddings (`.npy` with mmap, ~10x faster load than JSON)
- Lazy project loading (only active project loaded, not all projects)
- Pending embeddings pattern (hook writes to small file, merged on full load)
- Embed-on-capture: decisions and mistakes get AllMiniLM embeddings immediately
- Typo normalization for decision capture (edit-distance correction on trigger words)
- Vectorized dot products for vector search and reranking (numpy)
- Integration benchmark suite: 6 benchmarks testing actual product behavior
- Typo tolerance benchmark
- Auto-migration from v2 monolithic format (backup preserved)
- Regex F1 improved 53.3% → 57.6% via typo normalization

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
- Fixed: `session_start` crash when `recall()` returns `{"project": None}` for new sub-projects
- Fixed: scorer server visible console window on Windows

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

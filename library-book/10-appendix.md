# Appendix: Reference

[← Back to Table of Contents](./README.md) · [Previous: The Roadmap](./09-the-roadmap.md)

---

## MCP tool reference

### Essential tools

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

### `memory` tool (20 operations)

All operations require `operation` and `project_path`.

| Operation | Additional Parameters | Description |
|-----------|----------------------|-------------|
| `remember` | `content`, `category?`, `relevance?` | Store a memory |
| `recall` | none | Get all memories for project |
| `forget` | none | Clear all project memories |
| `search` | `file_path?`, `tags?`, `query?`, `limit?` | Find memories by criteria |
| `hybrid_search` | `query`, `file_path?`, `tags?`, `limit?` | Semantic + keyword + scored search (best retrieval) |
| `embed_all` | none | Generate embeddings for all memories |
| `cleanup` | `dry_run?`, `min_relevance?`, `max_age_days?` | Dedupe + archive + decay (clustering is internal) |
| `add_rule` | `content`, `reason?` | Add permanent rule (never decays) |
| `list_rules` | none | Get all rules for project |
| `modify` | `memory_id`, `content?`, `relevance?`, `category?` | Edit a memory |
| `delete` | `memory_id` | Remove a single memory |
| `batch_delete` | `memory_ids?`, `category?` | Bulk delete (rules/mistakes protected) |
| `promote` | `memory_id`, `reason?` | Promote memory to rule |
| `recent` | `category?`, `limit?` | Recent memories, newest first |
| `archive` | `dry_run?` | Move old memories to cold tier |
| `restore` | `memory_id` | Bring archived memory back to active |
| `archive_search` | `query?`, `tags?`, `limit?` | Search cold tier |
| `archive_status` | none | Hot vs archive counts |
| `list_mistakes` | none | View tracked mistakes with IDs, files, age |
| `acknowledge_mistake` | `memory_id` | Archive a learned mistake (stops pre-edit warnings) |

### `work` tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `log_mistake` | `description`, `file_path?`, `how_to_avoid?` | Record an error |
| `log_decision` | `decision`, `reason`, `alternatives?` | Record a choice |

### `scope` tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `declare` | `task_description`, `in_scope_files`, `in_scope_patterns?` | Set task scope |
| `check` | `file_path` | Verify file is in scope |
| `expand` | `files_to_add`, `reason` | Add files to scope |
| `status` | none | Get violations and scope state |
| `clear` | none | Reset scope |

> The `loop` tool was removed in v0.8.0. Loop detection is hook-automatic: edits and test results are tracked in per-session hook state by the PreToolUse/PostToolUse hooks, which warn on real spirals (repeat edits with failing tests). There is no agent-callable loop op.

### `context` tool

Checkpoint and handoff are one unified ring buffer. `checkpoint_*` are the primary names; `handoff_*` are deprecated aliases kept for backward compatibility.

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `checkpoint_save` | `task_description`, `current_step?`, `completed_steps?`, `pending_steps?`, `files_involved?`, `handoff_summary?`, `handoff_context_needed?`, `handoff_warnings?` | Save task state; emits HANDOFF.md when handoff content is present |
| `checkpoint_restore` | `index?`, `task_id?` | Restore a checkpoint: `index=0` latest, `index=N` older from history |
| `checkpoint_list` | none | List unified checkpoint/handoff history newest-first (index, age, kind, summary) |
| `verify_completion` | `task`, `verification_steps`, `evidence?` | Claim + verify done |
| `handoff_create` | `handoff_summary`, `next_steps`, `handoff_context_needed?`, `handoff_warnings?` | [deprecated alias of checkpoint_save] |
| `handoff_get` | `project_path?`, `index?` | [deprecated alias of checkpoint_restore] |
| `handoff_list` | `project_path?` | [deprecated alias of checkpoint_list] |

### `convention` tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `add` | `project_path`, `rule`, `category?`, `reason?`, `examples?`, `importance?` | Store convention |
| `get` | `project_path`, `category?` | Get conventions |
| `check` | `project_path`, `code_or_filename` | Deterministic pattern check against stored conventions (no LLM) |
| `remove` | `project_path`, `rule` | Remove by matching text |

> The `output` tool (`validate_code` / `validate_result`) was removed in v0.8.0. Its inline checks are covered by `audit_batch`'s inline mode (`code` + `language`).

### Standalone tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `scout_search` | `query`, `directory`, `max_results?` | Semantic codebase search (uses Ollama when available) |
| `file_summarize` | `file_path` | Structural summary (purpose, exports, dependencies, complexity); pattern-based, no LLM |
| `deps_map` | `file_path` or `symbol`, `project_root?`, `include_reverse?` | Map a file's dependencies, or locate a symbol (file, signature, importers) via the code index |
| `impact_analyze` | `file_path`, `project_root`, `proposed_changes?` | Change impact analysis |
| `audit_batch` | `file_paths`+`min_severity?` (files) · or `code`+`language?` (inline) | Audit files or lint a snippet for AI-slop patterns; pure regex/AST, no LLM |
| `find_similar_issues` | `issue_pattern`, `project_path`, `file_extensions?`, `exclude_paths?` | Search for bug patterns; pure regex/AST, no LLM |

> `scout_analyze` was removed in v0.8.0 (zero recorded use: the agent reads code better than a 12B commentary pass).

### MCP tool annotations

All 16 MCP tools carry MCP annotations (`readOnlyHint`, `idempotentHint`, `title`, `openWorldHint`). 8 read-only analysis tools (`claude_engram_status`, `pre_edit_check`, `scout_search`, `file_summarize`, `deps_map`, `impact_analyze`, `find_similar_issues`, `audit_batch`) are marked `readOnlyHint=true` and `idempotentHint=true`. Operation-enum tools that bundle reads and writes under one name (e.g. `memory`, `session_mine`, `scope`, `context`) are marked `readOnlyHint=false`. All tools are local (`openWorldHint=false`). MCP clients and Claude Code's permission system use these annotations to skip confirmation prompts on read-only calls.

### `session_mine` tool

| Operation | Parameters | Description |
|-----------|-----------|-------------|
| `search` | `query`, `project_path`, `limit?`, `method?`, `since?`, `until?`, `kind?` | Semantic search across past conversations. `kind` filters by hit type: `decision`/`next-step`/`error`/`narration`, regex-classified and LLM-free. |
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
| `cross_project` | none | Patterns across all projects |
| `reflect` | `project_path` | Injection precision report: which context kinds (memory/prediction/precheck/blast) precede passing tests, plus LLM-synthesized insights from recurring mistakes/patterns |
| `commitments` | `project_path` | Reads the LIVE transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items. Two channels: DEFERRED scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer mentions; IN-FLIGHT scans last ~30 messages for "I'll"/"let me"/"next" actions. Heuristic, LLM-free. The post-session mining index cannot see the open session; this op fills that gap. Run before asking "what next?" or on session resume. |

---

## Configuration reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `CLAUDE_ENGRAM_DIR` | `str` | `~/.claude_engram` | Storage location override (also the supported test-isolation seam) |
| `CLAUDE_ENGRAM_MODEL` | `str` | `gemma3:12b` | Ollama model name (optional LLM: `scout_search`, `memory(consolidate)`, `session_mine(reflect)`) |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `str` | `http://localhost:11434` | Ollama API URL (optional LLM) |
| `CLAUDE_ENGRAM_TIMEOUT` | `float` | `300` | LLM call timeout (seconds) |
| `CLAUDE_ENGRAM_KEEP_ALIVE` | `str/int` | `0` | Ollama model keep-alive (`0`, `5m`, `-1`) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `int` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `int` | `1800` | Scorer server idle timeout (seconds) |
| `CLAUDE_ENGRAM_HEADSUP_FRACTION` | `float` | `0.10` | Context-pressure heads-up, as a fraction of the window before the compaction point |
| `CLAUDE_ENGRAM_OUTPUT_RESERVE` | `int` | `32000` | Tokens Claude Code keeps below the configured number before it compacts (measured) |
| `CLAUDE_ENGRAM_CHECKPOINT_MARGIN` | `int` | `20000` (`10000` on ≤200K) | `CHECKPOINT NOW` nudge, this many tokens above the auto-compaction trigger |
| `CLAUDE_ENGRAM_CHECKPOINT_CADENCE` | `int` | `60` | Fallback: turns with neither a deliberate checkpoint nor a completed step before a reminder |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | `int` | unset | Claude Code's own variable; engram reads it as the compaction point (else `autoCompactWindow`, else the model default) |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `str` | `BAAI/bge-base-en-v1.5` | sentence-transformers embedding model; also `embed_model` in `config.json` |
| `CLAUDE_ENGRAM_EMBED_DIM` | `int` | model native | Matryoshka truncation dim; also `embed_dim` in `config.json` |
| `CLAUDE_ENGRAM_DEVICE` | `str` | smart | Unset: daemon on cpu, bulk jobs in a transient GPU worker; `cuda` or `cpu` forces one device |
| `CLAUDE_ENGRAM_GPU_BULK_MIN` | `int` | `512` | Job size in texts that routes to the GPU worker |
| `CLAUDE_ENGRAM_GPU_BATCH` | `int` | `64` | Rows per forward pass on the GPU |
| `CLAUDE_ENGRAM_NO_DAEMON` | flag | unset | Run every hook in-process; never start the daemon |
| `CLAUDE_ENGRAM_LIVE_MINE` | `int` | `300` | Live mining tick interval in seconds; `0` disables |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `int` | `0` (keep all) | Prune session-search shards older than N days |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | `str` | unset | The Read hook mirrors the last-read file path here |
| `CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT` | `int` | `90` | Usage-window nudge threshold, 5-hour window |
| `CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT` | `int` | `95` | Usage-window nudge threshold, 7-day window |
| `CLAUDE_ENGRAM_STALL_TURNS` | `int` | `3` | Consecutive no-effect turns per strike |
| `CLAUDE_ENGRAM_STALL_DECAY` | `int` | `5` | Consecutive good turns that remove one strike |
| `CLAUDE_ENGRAM_STRIKE_CAP` | `int` | `3` | Strikes to the cap (the halt in autonomy mode) |
| `CLAUDE_ENGRAM_GOAL_TURN_CAP` | `int` | `150` | Turns under a `/goal` before the halt arms; also `goal_turn_cap` in `.engram/config.json` |
| `CLAUDE_ENGRAM_AUTONOMY` | flag | unset | `1` arms the halt and the alerts outside a `/goal`; the launcher sets it |
| `CLAUDE_ENGRAM_ALERT_COMMAND` | `str` | unset | Shell command for alerts; `{message}` is replaced or the message arrives on stdin; also `alert_command` in `.engram/config.json` |
| `CLAUDE_ENGRAM_RESUME_SLACK` | `int` | `90` | Seconds the launcher waits past a usage-window reset before resuming |
| `CLAUDE_ENGRAM_COMPLIANCE`, `_ROTATION`, `_STRUCTURE`, `_DEFAULT_RULES`, `_WORKFLOW_RULES`, `_CODE_RULES` | flag | on | Environment overrides for the `.engram/config.json` switches; `off` disables, `ROTATION` also takes `auto` |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | flag | unset | `1` prints a stderr breadcrumb per hook |
| `CLAUDE_ENGRAM_GIT_TRACE` | `str` | unset | A file path; every git call the hooks make is appended there |
| `CLAUDE_ENGRAM_NON_PROJECT_DIRS` | `str` | unset | Comma-separated directory names that are never a project of their own; also `non_project_dirs` in `config.json`. Built in: `node_modules`, `.venv`, `venv`, `__pycache__` |

## Memory categories

| Category | Description | Protected | Auto-captured |
|----------|-------------|-----------|---------------|
| `rule` | Permanent project rule | Never archived/decayed | No |
| `mistake` | Error to avoid repeating | Never archived/decayed | Yes (PostToolUseFailure) |
| `decision` | Choice with reasoning | No | Yes (UserPromptSubmit) |
| `discovery` | Learned fact about codebase | No | No |
| `context` | Session-specific note | No | No |
| `priority` | Global priority | No | No |
| `note` | General note | No | No |

## Memory scoring weights

| Factor | Weight | Description |
|--------|--------|-------------|
| `file_match` | 0.35 | Exact file > same dir > same ext > filename in content |
| `tag_overlap` | 0.20 | Intersection of context tags and memory tags |
| `recency` | 0.20 | `exp(-age_days / 30)` |
| `relevance` | 0.15 | `entry.relevance / 10.0` |
| `access_freq` | 0.10 | `min(entry.access_count / 10.0, 1.0)` |

Category bonuses: `rule` +0.3, `mistake` +0.2.

## Hook events

| Event | Matcher | Handler | What It Does |
|-------|---------|---------|-------------|
| `UserPromptSubmit` | `""` | `prompt_json` | Show rules/mistakes, capture decisions |
| `PreToolUse` | `Edit\|Write` | `pre_edit_json` | Inject memories, check loops/scope |
| `PostToolUse` | `Bash` | `bash_json` | Track tests, detect search spirals |
| `PostToolUse` | `Edit\|Write` | `post_edit_json` | Track edits, update loop counter |
| `PostToolUse` | `ExitPlanMode\|TaskUpdate` | `post_milestone_json` | Plan approved → bank it with its steps pending; task completed → milestone nudge |
| `PostToolUseFailure` | `""` | `tool_failure_json` | Auto-log errors from all tools |
| `Stop` | `""` | `stop_json` | Save handoff with last message; read it for a "step done" claim (milestone) |
| `SessionEnd` | `""` | `session_end_json` | Save session state, write the run report (`.engram/runs/`), spawn the miner |
| `SessionStart` | `""` | `session_start_json` | Load context, start scorer server |
| `PreCompact` | `""` | `pre_compact_json` | Auto-save checkpoint |
| `PostCompact` | `""` | `post_compact_json` | Re-inject rules/mistakes/decisions + the compaction rhythm |

Every injecting handler above (prompt, pre-edit, pre-read, bash, post-edit) also attaches the context-pressure nudge when one is due (`hooks/context_pressure.py`). The statusline is not a hook, but it is the signal source: `python -m claude_engram.hooks.context_pressure statusline` or a custom script that records the mirror.

## Project markers (sub-project resolution)

Files that indicate a project root when resolving sub-projects in a workspace:

`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `go.sum`, `pom.xml`, `build.gradle`, `CMakeLists.txt`, `Makefile`, `setup.py`, `setup.cfg`, `.git`, `CLAUDE.md`

## File storage layout

```
~/.claude_engram/
├── manifest.json            # Maps project paths to hash directories (v3)
│                            #   migrations_applied: list of completed migration IDs
├── global.json              # Global entries (cross-project)
├── projects/
│   └── <hash>/              # Per-project storage (hash from manifest)
│       ├── memory.json      # This project's hot tier memories
│       ├── archive.json     # This project's cold tier
│       ├── embeddings.npy   # Binary embedding vectors (numpy, optional)
│       ├── embeddings_index.json  # ID-to-row mapping for embeddings.npy
│       ├── embeddings_pending.json # Hook embedding writes (merged on load)
│       ├── handoff_history.json   # Per-project capped ring buffer (last 20 handoffs)
│       ├── code_index.json        # Per-project symbol index (exports, imports, classes, functions)
│       ├── session_index.json     # Session metadata + offset cursors
│       ├── session_embeddings/  # Monthly .npy shards of chunk embeddings
│       ├── session_embeddings_index.json # Shards, chunks, per-session watermarks
│       ├── patterns.json          # Detected patterns (struggles, errors, correlations)
│       └── extractions/           # Per-session extracted intelligence
│           └── <session_id>.json  # Decisions, mistakes, approaches, corrections
├── conventions.json         # Project coding conventions
├── sessions/                # Per-session hook state (edit counts, test results); keyed by session_id, auto-pruned
│   └── <session_id>.json    #   Loop-detection state lives here now — concurrent sessions stay isolated
├── hook_state.json          # Legacy/global fallback hook counters (superseded by sessions/)
├── loop_detector.json       # Abandoned in v0.8.0 (loop state moved to sessions/<sid>.json; old file is harmless if present)
├── scope_guard.json         # Declared scope state
├── scorer_port              # TCP port for scorer server (auto-managed)
├── scorer_pid               # PID of scorer server (auto-managed)
├── embeddings/
│   └── decision_templates.json  # Cached template embeddings
├── checkpoints/
│   ├── latest_checkpoint.json   # Most recent checkpoint
│   ├── latest_handoff.json      # Most recent handoff (kept in sync for backward compat)
│   ├── handoff_history.json     # Global slot ring buffer (last 20 handoffs)
│   ├── HANDOFF.md               # Human-readable handoff
│   └── task_*.json              # Individual checkpoints
└── memory.json              # Legacy (auto-migrated to projects/ on first load)
```

## Changelog

### v0.8.42 (2026-09-11)

The trade-lab model's honest answer to "did engram find why the constant is 0.15": no. `session_mine(decisions)` raised `FileNotFoundError` on the sub-project's missing embeddings index; `replay` returned edit timestamps with no reasons. Git found it: a pickaxe on the constant led to the introducing commit of 2026-08-16, whose message carried the only reason ever written.

- **Decisions never crash on a missing index.** `search_sessions` had already walked up to the workspace root's index; the context expansion then reopened the sub-project's own store and died. `_resolve_project_with_inheritance` returns the project that actually holds the index and its store dir, and the expansion reads that index and that project's transcript folder. The search runs hybrid, not semantic-only, so a scorer that is down or a store built by another model still answers by keyword.
- **The repository is a record engram now reads.** `git_pickaxe(project, query)` runs `git log -S` with the most specific needles first (an identifier near a number as a regex, then the number, the identifiers, the longest words), scoped to the files a query token names (`sync_edgar` narrows to `sync_edgar.py`; a bare `0.15` over the whole history matched three unrelated commits), then repository-wide. Each hit carries the added lines around the needle from that commit's diff, because the reason for a constant is a comment above it more often than a commit message. Results are kind `git` with the sha in `session_id`; `find_decision` appends them. `git_file_history` (`git log --follow`) rides along with `replay`. Replayed on the live store with the query that failed: the first result is the 2026-08-16 introducing commit with "We stay well under" in its excerpt.
- **The MCP layer maps a worktree to its repository.** `server.call_tool` passes every `project_path` through `canonical_project_root`, so a tool called from `trade-lab/.scratch/<wt>` reads trade-lab's store, not an unregistered worktree's.

### v0.8.41 (2026-09-11)

The third report from the trade-lab session: the restore after the machine went down carried the exact state back three and a half hours later, the compaction resume re-injected the loader checkpoint, and since 0.8.40 the noise had dropped (no test-tracker false positives, quieter edit reminders, the nudge once instead of every message). Still there: the rule count at start and the cross-project errors in a fresh banner. The user's rulings: the rules stay in the banner (a model that does not see them does not follow them); the checkpoint gate before a commit stays off; the cwd-is-not-the-project bug gets fixed everywhere with one loader.

- **One loader for the session's project.** `session_project(project_dir, state)` in `hooks/remind.py`: the transcript's own Edit and Write calls first, the hook state's lists second, the cwd mapped to its repository last, cached in the session state against the transcript's size. Every hook that files, reads or scopes by project goes through it: the pressure and stall delivery (`_with_pressure`, whose strike-2 bearings had teased another session's checkpoint into an engram session), the goal bracket, the Stop and compaction handoffs, the session-end report and rotation, the prompt hook, the shell-command and batch compliance checks, and the session-start banner. A file outside the workspace (the memory directory under `~/.claude`) no longer votes for the root.
- **Recurring errors wait for the first edit on a fresh start.** The block (struggles, recurring errors, known-good test commands) is one function, `_recurring_lines`, that walks the ancestors for the mined report and keeps only what names the session's project; on a resume it prints at start, on a fresh start it is deferred (`patterns_deferred`) to the first pre-edit, when the file names the project, instead of printing the root's errors at a root-cwd start. The known-good commands for a project now come through even when the project has no store of its own (the ancestor walk finds the root's file).
- Not built, by ruling: a smaller rules banner; the commit gate.

### v0.8.40 (2026-09-11)

The second trial report, written from inside the trade-lab session by the model that lived it, checked against that session's transcript before anything was changed: four milestone nudges, all quoting status-report lines to the person; about four hundred "edits without running tests" warnings on frontend files; about three hundred and eighty "PASS Test tracked" lines; edit reminders carrying a 128-day-old workspace rule; a banner listing another project's web UI files as the last session and V11's error as recurring. The session ran from the workspace root, so every banner block was the root's.

- **The project a session is about comes from Claude Code's own record.** The user's question: "isn't there a better way to identify projects from the .claude logs we actually parse?" There is. `autorun.recent_edit_files` reads the transcript's Edit and Write tool calls; `_session_edit_files` and the session-start banner use it first, the hook state second. On a resume or after a compaction the banner's recurring errors, struggles, last session and known-good test commands are scoped to that project (`work_project`), and a workspace-root index answers with the latest session that touched it (`SessionIndex.get_latest_session_for`), listing and counting only its files. Engram's own failures (paths inside `.claude_engram`) never appear as a project's recurring errors.
- **A prose claim needs a turn effect, never a bullet, one an hour.** `_turn_corroborates_a_close` stages the milestone nudge only when the turn that made the claim edited, committed or delegated (the stall accounting already knows); a list bullet relays someone else's work and never counts; `MILESTONE_NUDGE_GAP_SECS` swallows a second prose nudge inside an hour. Task-tool closes stay structural and unlimited. The nudge text names the one-string form, `context(checkpoint_save, task_description="...")`, which was always enough; the skill now leads with it.
- **Loop warnings latch.** At eight edits and every eight after, not on every edit past eight. Under a non-project directory, never.
- **Test tracking speaks only on news.** The first result and each flip; a same-verdict rerun is tracked in silence. `_is_test_invocation` reads every segment of a chain (`cd proj; python -m pytest` is a test run), and known-good commands pass the same gate at read time, so the `sed -n ... tests/x.py` shapes recorded before 0.8.39 stop being suggested; an ancestor's commands are inherited only when they name the project.
- **Edit reminders rank by relevance, not by a filename token.** A rule rides along only when it names the file or its directory; an entry older than thirty days (`STALE_CONTEXT_DAYS`) needs a full-path match; `errors.md`, `learnings.md`, `handoff.md`, `notes.md`, `todo.md`, `plan.md` join the generic basenames.
- **The destructive-command rule can see what the session knows.** `UserPromptSubmit` keeps the last prompt; `PostToolBatch` keeps the paths the session created (Write targets, `mkdir` arguments). Before a matching shell command the injected text says when the last prompt reads as approval and when every target is a path this session created, and the unattended wording no longer tells the model to stop for a deletion the person just approved.
- **Migration `0.8.40:drop_worktree_projects`.** Ten `trade-lab/.scratch/*-wt` entries and the `.scratch` dir itself were registered as projects with empty stores; the resolver can no longer reach them, so they are unregistered and their directories parked under `_unregistered/` in the store. A store with entries is kept. The non-project segment set is re-read when the config file changes, so a long-lived daemon sees an edit without a restart.
- Known-good test commands still cannot tell a run from a main checkout apart from a run in a worktree; the banner shows the project's own file first and an ancestor's only by name.

### v0.8.39 (2026-09-10)

The first trial on another project, a fourteen-hour trade-lab session run from a git worktree. Its report, most important first: checkpoints carried everything across a compaction and the resume, the context-pressure warning fired once at the right moment with an accurate number, the milestone nudge was right both times. Then the list to fix.

- **A session started in a worktree belongs to its main repository.** The cwd was `trade-lab/.scratch/<worktree>`; the worktree's `.git` file is a project marker, so the resolver made the worktree the project, nothing was registered there, and the fallbacks reached the workspace root: claude-engram's checkpoint was teased at a trade-lab session, two checkpoint blocks from two projects on the resume, another project's rule count, another project's recurring errors and test commands at every start. `paths.worktree_main` reads the `gitdir:` pointer and maps the worktree to the main working directory when git can see it; `canonical_project_root` also pulls a cwd inside a vendored or virtualenv directory up to the project above it. `get_project_dir` and the marker walk both use it. Smoke test with a real worktree layout. The scratch name is configuration now, not a rule engram ships: `.scratch` was this workspace's convention, so the built-in list is `node_modules`, `.venv`, `venv` and `__pycache__`, and `non_project_dirs` in `~/.claude_engram/config.json` (or `CLAUDE_ENGRAM_NON_PROJECT_DIRS`) adds a workspace's own.
- **Output-based test detection only for commands that can run something.** A grep over a test file, a `git log` on a path containing the word pytest, a `cat` of a report: their OUTPUT quoted "3 passed" or "collected 2 items" and the tracker logged a passing test. The markers are now read only when the first command's executable is not a read-only tool (`grep`, `rg`, `cat`, `sed`, `git`, `find`, `jq`, and the like).
- **No loop warning for files under a scratch directory.** Eighteen "edits without running tests" for a markdown plan under `.scratch/`. The warning already ignored non-code suffixes; it now also skips any path with a scratch, vendored or virtualenv segment.
- **The per-edit "Edit tracked: x (edit #3)" line is gone.** It carried no decision. The count still feeds the loop warning; only the pressure nudges ride the post-edit hook.
- The skill tells the model to keep `task_description` a title and put the state in the structured checkpoint fields, which restore as lists rather than one paragraph.

### v0.8.38 (2026-09-10)

Two things the second live `/goal` run exposed, and the documentation pass.

- **A met goal stayed stamped on every later checkpoint.** The bracket wrote the goal into the session's run record at start and never removed it, so `goal_for_session` kept returning it hours after the evaluator had said met; the post-compaction banner showed the morning's pytest goal as the checkpoint's goal. `autorun.stop` now drops the record for goal-sourced runs, and the transcript fallback reads the goal through `scan_goal` (active only), never the raw sentinel. Regression check in `test_smoke`.
- **The bracket filed a run under the workspace root because the turn that set the goal edited nothing.** Every Stop calls `mark_session_ended()`, which moves `files_edited_this_session` into `last_session_files` and clears it, so at a Stop the live list holds only the turn that just ended. `_session_edit_files` now falls back to the previous turn's files and then to every absolute path the loop tracker counted this session, so the manifest and the report land in the sub-project the session is about.
- **README rebuilt from the code surface and verified against it under a `/goal`.** Every registered hook, all fifteen tools with every operation, the memory model, the compaction rhythm, the bracket, detectors, the project defaults, the run report, mining scope, all thirty-six environment variables and the storage layout; nine claims corrected in the pass (the cadence default is 60, not 25; `patterns` is not a mining operation; the lesson bonus; the benchmark tables are the bench scripts, not the book; the installer's steps; the statusline's usage field; alert scope; how rules and context entries get written). The `/engram` skill still said the checkpoint nudge fires "3% out" and now states the measured rule. The library book went through the humanizer pass (no em or en dashes in prose, sentence-case headings, plain copulas, every fact kept), chapter 0 included, and the environment tables in chapter 6 and this appendix now list every variable.

### v0.8.37 (2026-09-10)

Six things the MCP tools got wrong when exercised live, found by using them rather than by reading them.

- **`claude_engram_status` reported v0.8.20 from a 0.8.36 checkout.** The version came from `importlib.metadata`, and an editable install (`pip install -e .`) freezes its dist-info at install time while the code stays live, so every release after the last `pip install` was invisible, for sixteen of them. `claude_engram.__version__` is a literal again, the single source of truth that ships with the code; `_installed_version()` is kept as a diagnostic and status appends "(pip metadata says X - stale editable install)" when the two disagree. A smoke test parses `pyproject.toml` and asserts the status line equals it, which is what the metadata lookup was there to guarantee.
- **`memory(hybrid_search)` answered a no-match query with three unrelated mistakes at 0.000.** Two causes, both fixed. The score half of the fusion contributes candidates for *any* query (it ranks by file, tag and recency, never by the query), and `_rerank` scores an entry that has no vector `0.0`; a zero is "no evidence", so those results are now dropped and the op says `No match for: <query>`, adding "N memories have no vector yet" when that is why. And the vectors were missing because mined entries are inserted with `auto_embed=False` and nothing ever embedded them: the background miner now embeds exactly the projects that just received entries (`extractors.projects_fed_last_run()`), right after extraction, in the miner process and never in a hook.
- **`memory(list_rules)` said "No rules defined for this project" while the banner listed 35.** The op read only the project's own store; rules live where they were written, and a workspace-level rule binds everything under it. `MemoryStore.get_rules_with_inheritance()` walks the registered ancestors, returns the project's own first and marks the rest `[inherited from <ancestor>]` (the live workspace: 0 own, 37 inherited), keeping the `[detector]` mark and deduping by id and by identical text.
- **`session_mine(commitments)` said "no live transcript found for this project" mid-session.** A session started from a workspace root writes its JSONL under the ROOT's projects dir, so the sub-project lookup found nothing. It now uses the same resolution the run report does (`commitments.session_transcript`): the hook-recorded `run.transcript_path` wins, then the file named by the session id anywhere under Claude's projects dir, then the project's newest.
- **Attribution filed worktree and scratch paths under the wrong project.** A git worktree carries a `.git` FILE, which is a project marker, so marker-walking resolved `E:/workspace/trade-lab/.scratch/<name>-wt/...` to the worktree, and nine such worktrees were registered as projects in the live store. `target_project_for_files(..., known_projects=…)`: given the store's registered projects, a file votes for the DEEPEST one containing it, with no marker walking, and a file under none of them does not vote; a path inside another project's `.scratch/`, `node_modules/`, `.venv/`, `venv/` or `__pycache__/` is never a destination (without the list, the walk's answer is pulled back to the nearest ancestor that is not). A RELATIVE `related_files` entry no longer votes at all: `Path.resolve()` pinned it to whatever directory the process ran in, which is how `'v2/tests/test_orders.py'` and `'SUBMISSION.ts'` became claude-engram's own mistakes: the 0.8.36 migration ran from the engram checkout. The migration re-ran under the corrected rule (`0.8.37:reattribute_pooled`) on the live store, from the pre-0.8.36 backup: 33 entries moved, 30 to trade-lab (which had 4), 2 to kaggriculture, 1 to sabir, none to claude-engram, which has no mined mistake naming a file of its own. 986 of the root's 1122 mined entries name no file at all and stay pooled at the root by design.
- **`session_mine(overview)` for a sub-project is the workspace's, and now says so.** Claude Code indexes a transcript under the directory the session was started from, so every mining view for a sub-project under a workspace root is the root's; nothing in engram can re-cut it. Documented in the README ("Session mining scope") and as a gotcha in chapter 7, next to the thing that *is* per project: memory, attributed by the files an entry names.

### v0.8.36 (2026-09-10)

- **Mined entries are filed under the project their files name.** Sessions run from a workspace root mined every mistake and decision into the root store, so a sub-project's own store stayed empty while the root pooled every sibling's tracebacks. `hooks/paths.target_project_for_files(root, files, content)`: each named file resolves to the closest marked project under the root, the majority wins, files outside the root (temp dirs, other drives) do not vote, and a project whose name appears in the entry's text (`trade_lab` in a traceback) wins over the file vote, because a session that edits two projects lists both projects' files. The miner routes new entries through it; a heavy migration (`0.8.36:reattribute_pooled`, background, via the pydantic store, keeping id, timestamps and flags, never touching a person's own entries) moved the already-pooled ones, 99 on the live store: trade-lab now shows 28 of its own, kaggriculture 2, the root keeps the 109 that name no file.
- **A rule outranks a mistake on the same file.** Both scorers clipped the score at 1.0 before comparing, so a rule (bonus 0.3) and a mistake (0.2) tied and insertion order decided; the clip is gone. `bench_scoring` runs on an isolated store now (it wrote its `/tmp/bench_*` projects into the live store on every run) and accepts the mistake about `api/routes.py` as a correct #1 for that file.
- **The report's errors table names a bare shell exit for what it is**, "a shell command exited 1 with no output captured", and ranks it after the errors that say something.

### v0.8.35 (2026-09-10)

- **Engram's context cost, measured, and the largest recurring item removed.** On the build session since its last compaction (21 prompts, ~545K context) engram had injected 80 blocks, ~12.9K tokens, 2.4% of the context: the session banner and the prompt reminder ~430 tokens each, pressure and milestone nudges ~110, pre-edit reminders ~70, post-edit and test notes ~20. The prompt reminder had fired 7 times in 21 prompts, re-injecting the restored checkpoint, the rules and the mistakes, because `check_session_active` gated on the resolved project equalling the one the session started in, and the resolved project flips between the workspace root and a sub-project with every edit. The state has been keyed by the Claude Code session id since 0.8.6, so the gate is gone: one session is one session for four hours whichever sub-project its last edit named. The legacy `session_active` marker file moves under the store directory so it honors `CLAUDE_ENGRAM_DIR` (a test had overwritten the live marker through `Path.home()`). Expected steady-state cost: one banner per session start or compaction plus ~100 tokens per working turn.

### v0.8.34 (2026-09-10)

- **The banner lists only the project's own mistakes.** Ranking by file was not enough: 94 of the 148 pooled mistakes name no file at all, so the top of the list was still another project's tracebacks. `load_project_memory` now marks entries that come from an ancestor store (`_inherited`, in memory only); `get_past_mistakes` scopes them 0 (the project's own, or pooled but naming a file here), 1 (pooled, no file), 2 (pooled, a file elsewhere); the prompt banner lists scope 0 only and says how many are pooled; they still surface before an edit when they name the file. A project whose sessions ran from the workspace root reads "none recorded for this project; N pooled".

### v0.8.33 (2026-09-10)

- **The MCP checkpoint hang, found and fixed.** Since 0.8.26 a `context(checkpoint_save)` through the MCP server could run for minutes (Claude Code's log: "Tool 'context' still running (210s elapsed)") and the user had to reconnect the server. Driven over stdio with the MCP client library, a fresh server's save took exactly 4.0 s, the git timeout, while the same handler took 40 ms in-process; with no `project_path` (no git call) it took 0 s. Cause: the git child inherited the server's stdin, the JSON-RPC pipe from Claude Code, and stalled inside the stdio server; `stdin=subprocess.DEVNULL` on that call brought the save to 0.0 s. Every `subprocess` call in the package now detaches stdin (repo_state, the stall fingerprint, the report's git, the launcher, alerts), a smoke test guards the rule, and `CLAUDE_ENGRAM_GIT_TRACE=<file>` logs each git call's outcome and time for the next such hunt. Reconnect the server (`/mcp`) once to load it.
- **The session banner shows this project's mistakes first.** The workspace-root store pools every sub-project's mined mistakes, so a session in one project saw another's tracebacks at the top of "PAST MISTAKES". `get_past_mistakes(project_memory, project_dir)` ranks mistakes that name a file under the project first, then ones that name no file, then the rest.

### v0.8.32 (2026-09-10)

- **The first live /goal run, examined.** The user typed `/goal python -m pytest -q tests exits 0 …` in the build session: engram's directive arrived at the goal's first prompt, the manifest was written at the start, the evaluator judged met on its first verdict (94 s, 6,378 tokens), the alert was recorded ("no alert_command configured") and the report gained its "Goal run (met)" section with the run's two compactions and their restores joined. Three things it exposed, fixed: the bracket resolved the project from the cwd (the workspace root) instead of the session's edited files, so the manifest and report were filed one level up, and `_goal_bracket` now uses `_resolve_session_project`; `scan_goal` would have read a tool_result that echoes `<command-name>/goal</command-name>` (a fixture read back) as a clear, so only a plain-string user record is a command now; the report's "prompts" came from the state's counter (2 for a day-long run), and the run-scoped transcript count wins. Also new: `tests/test_smoke.py`, six fast pytest unit tests on the day's measured facts, so `python -m pytest -q tests` is a meaningful command beside the benches (pytest is not a package dependency; install it in the venv).

### v0.8.31 (2026-09-10)

- **The noise list from a day of normal use, fixed.** (1) The milestone nudge asked for a checkpoint that had just been banked, twice: the save had been made from another process (a script under the session's id), which reaches the ring but not this state's flag. `nudge()` now reads the project's ring (`_ring_manual_after`): a deliberate entry newer than the claim answers the nudge; an automatic one does not. (2) Editing engram's README surfaced another project's `src/README.md` mistake and its CLAUDE.md a trade repo's worktree decisions: `README.md`, `CLAUDE.md`, `pyproject.toml`, `package.json`, `Makefile`, `config.py`, `utils.py`, `main.py` and their kin join `_GENERIC_BASENAMES`, so only a full-path signal matches them. (3) The run report of a session id resumed for months listed compactions from June: `collect()` reads the transcript from the run's start when the transcript demonstrably spans past it (head and tail timestamps on either side of the cut; a clock mismatch never empties the report), and the restore join lands on the run's own compactions. (4) The hook daemon served an hour of stale code after an edit: it now watches the package's newest source mtime and exits when it moves, so the next hook restarts it on the new code; and `CLAUDE_ENGRAM_NO_DAEMON`, set by the benches for years and read by nothing, is honored by both spawn paths, so a hook run against a temporary store no longer leaves a daemon holding a loaded model on a deleted directory.

### v0.8.30 (2026-09-10)

- **`/goal` is the loop; engram brackets it.** The user: "that's the reason we tested /goal, we should use it." The 0.8.28 engram-owned Stop-hook loop is gone. A goal is set only by typing `/goal` (verified on the docs and on a headless run: no flag, setting, hook output or tool call sets one, and the model cannot type a slash command), so `hooks/autorun.py` now *watches*: `scan_goal()` reads the transcript tail for the verified records: the `goal_status` sentinel on set, the verdicts (`met`, `reason`, `failed: true`), the `/goal clear` command record, and a met goal clears itself. `observe()` at Stop, UserPromptSubmit and SessionEnd keeps `run.auto` in step: `running`, `met`, `failed`, `cleared`, `halted` (strike cap), `capped` (`goal_turn_cap`, 150; it arms the same halt because engram cannot end a /goal loop, and the alert asks a person to `/goal clear`). Autonomy mode is on while a goal runs. A start writes the manifest and stages one directive (the park hint, since a not-met verdict re-prompts at once and starves cron unless the model parks; the checkpoint rhythm; the deny note); an end sends one alert and writes the report's "Goal run" section. `session_mine` keeps `run_status` only; the skill's `/engram run` hands the person the exact `/goal` line and `/engram stop` says `/goal clear`. The halt texts name their cause (strikes or the turn cap). `tests/bench_autorun.py` rewritten around transcript fixtures in the observed shapes and the real hooks.

### v0.8.29 (2026-09-10)

- **The auto compaction, measured, and two defects it exposed.** The build session itself compacted automatically at 717,578 tokens against a 750K `autoCompactWindow`: the heads-up had fired at 651K and the model had banked a checkpoint, but the `CHECKPOINT NOW` band (then "3% out" = 720K) sat inside the ~32K room Claude Code keeps for the model's output and never fired; and after the compaction the checkpoint was not shown to the model, because `PostCompact` printed plain stdout (shown to the person, never added to the context; the hooks reference says `hookSpecificOutput.additionalContext` is what enters) and the SessionStart(compact) banner skipped the restore on the belief that PostCompact carried it. Fixes: `thresholds()` now places the last band an absolute margin above the measured trigger (`OUTPUT_RESERVE` 32K, `CHECKPOINT_MARGIN` 20K, 10K on ≤ 200K windows, both env-tunable; heads-up pulled under it on small windows), which is 698K on the 750K setting; `PostCompact` emits `additionalContext` with the rhythm and does the cycle bookkeeping only; SessionStart(compact) re-injects rules, mistakes and the banked checkpoint with its goal and staleness line, like a resume. `bench_context_pressure` gains a replay of the session's numbers through the real `post_compact_json` and `session_start_json` hooks (183 checks).

### v0.8.28 (2026-09-10)

- **`/engram run` inside the session, like `/goal` or `/loop`.** The user: "it all works in Claude Code like normal and can be invoked like normal, and by Claude itself if needed." No second process. `session_mine(run_start, goal, check, max_turns)` arms a run in the session state (`hooks/autorun.py`); from the next stop engram's own Stop hook answers `{"decision": "block", "reason": <directive>}`, the documented loop primitive, and the directive is the next prompt: the goal, the check's last exit code and output tail, the turn count, the park hint and the deny note. Engram never judges the sentence: the **check command** is the truth (exit 0 = met). Without a check the run ends only on `session_mine(run_done, evidence)`, recorded as self-declared and said so in the report. The other ends: the turn cap (`capped`), the strike-cap halt (`halted`), `session_mine(run_stop)` (`stopped`). Each end sends one alert and writes the run report, which gains an "Engram run" section. Autonomy mode now reads the session state as well as the environment (`stall.autonomy_on(state)`), so a running in-session run arms the halt, the alerts and unattended = deny, and they switch off when it ends; the compliance, notification and failure paths pass the state through. The skill's `/engram run <goal> check: <cmd>`, `/engram stop`, `/engram done` map onto the ops, and Claude may start a run itself when the plan says to execute unattended and the goal is checkable. The launcher (`python -m claude_engram.run --headless`) stays for cron and overnight, outside any session. `tests/bench_autorun.py`: 54 checks covering the state machine, the check runner, the block/end decisions, the real Stop hook driven through two blocks and a clean end with the alert and the report, the MCP ops in-process.

### v0.8.27 (2026-09-10)

- **The foreground is the default.** The user: "not behind a curtain where you can't see." `python -m claude_engram.run` now opens the normal interactive session in your terminal with the goal as its first prompt and autonomy armed (halt, alerts, unattended = deny, the 75% compaction window, the manifest); you watch, interject and stop it like any session, and the interactive client handles its own usage-limit resume. `--headless` is the old behaviour (`claude -p`, no terminal, the hard `--max-turns`, the sleep-and-resume loop) for cron and overnight. `/engram run` from a session prints the foreground command for you (a session cannot open a second terminal UI) and runs headless in the background only when asked to. Cost is the same as any session: a plan pays with its usage windows, an API key or enterprise provider per token; the headless `total_cost_usd` is Claude Code's client-side estimate.

### v0.8.26 (2026-09-10)

- **Checkpoint provenance (Phase 7).** Every deliberate checkpoint now records the commit the repo stood at and the active `/goal` condition (the launcher primes it before launch; an interactive session's comes from the transcript's own goal record). A restore, whether the session-start banner or `context(checkpoint_restore)`, prints the goal and one staleness line: "Since this checkpoint: 2 commits, 5 files changed -- incl. app.py", or "no commits", or that the checkpoint's commit is not in this history, so the model reads how far the repo moved before it acts on the last session's framing. Best effort, silent outside a repo; older entries print neither line. The halt's deny reason now orders the record: checkpoint first, then the notification, then stop.
- **Unattended = deny.** From the question "can a session hand its plan to `/engram run` and go?": yes, and one gap closed first. A detector can carry `unattended: deny`; in autonomy mode a matching shell command is refused with the rule as the reason ("refused by rule […]; this run is unattended: nobody can approve an ask-first action; record what you need approved, notify, continue with allowed work or stop; do not work around it"). The pack's destructive, kill-by-name and leaves-the-machine detectors carry it (pack version 6), and a re-seed upgrades an older pack-shaped detector in place. An attended session, a person at the terminal even in bypass mode, is never denied, only shown the rule; only the launcher's flag refuses. `tests/bench_compliance.py` 149, `tests/bench_phase7.py` 28.

### v0.8.25 (2026-09-10)

- **Autonomy mode: the halt, the alerts, the launcher.** Engram does not invent a loop; `/goal` is the loop, and this brackets it. *The halt:* with `CLAUDE_ENGRAM_AUTONOMY=1`, the strike cap arms a halt at Stop and a new catch-all PreToolUse hook (daemon-served, a single state read when nothing is halted) denies every tool call with a reason the model sees, every call except PushNotification, ToolSearch (PushNotification is deferred on the newest models and needs its schema loaded; seen on the first live halt) and engram's checkpoint call, so the model can bank where things stand, send one line, and stop. A deny ends the turn; with no tool use the goal's own stall rule closes the loop, and engram never fights the Stop hook (hooks merge most-restrictive, so it could not win there anyway). Turns after the halt are neutral, not more strikes. `python -m claude_engram.hooks.stall release <session>` lifts it and resets strikes; `status` prints the record. *The alerts:* a halt, an API failure (`StopFailure`), a run waiting on a person (permission prompt, needs input, idle, through the `Notification` hook), the launcher pausing for a usage limit and the run ending each send one line under 200 characters through the owner's `alert_command` (`.engram/config.json`, `CLAUDE_ENGRAM_ALERT_COMMAND`, or `--alert-command`; `{message}` shell-quoted, or on stdin). No service is built in. Every alert is recorded in the session state and the run report whether or not a command exists. PushNotification is the model's tool, not a hook's (verified), and a headless run has no desktop to notify, which is why the command is the channel. *The launcher* (`python -m claude_engram.run`, or `/engram run <goal>` from a session, which launches it in the background): writes a manifest (goal, model, permission mode, the rules in scope with their detectors, the start commit), chooses the session id, sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 75% of the model's window, a number that fits the model, sets a hard `--max-turns` (the evaluator's own "or stop after N turns" is not honored), appends the park-on-a-wait-primitive instruction, and runs `claude -p --output-format json`. On exit it reads the session state: a `rate_limit` failure with a known reset inside six hours sleeps until the window resets and resumes the same session (`claude -p --resume`, which restores an active goal; up to three times); a halt or anything else ends the run. Then the run report and the closing alert. `--dry-run` prints the plan. Live-verified on a Sonnet run built to stall: the third read was denied, the model stopped polling and sent its notification, the launcher's turn cap closed the run; $0.27. `tests/bench_autonomy.py`: 83 checks, the hooks and a fake `claude` driven end to end (limit → sleep → resume → done).
- **The code tier.** The user asked for the standards on how code is written, not only how work flows. Thirteen rules in the wording of their most refined project rulebook plus their standing preferences: one function, one purpose; names semantically accurate and comments that explain why; nothing left lying around; verify by quoting what it printed; never swallow an error on the decision path; same inputs, same outputs; the real thing over a stand-in (a simulator is not a mock; a mock is a thing that agrees with you); secrets never in code, commits, logs or pull requests; performance from the start; both Windows and Linux; pick the fast path on purpose (the right structure and algorithm, then the fastest library for the job); never do work twice; smart over busy (measure, then optimize what the profile names). Seeded with the pack (version 5), written as `## Code` in the scaffolded `CLAUDE.md`, `"code_rules": false` opts out.

### v0.8.24 (2026-09-10)

- **Usage budget.** The user's question: "what about the 5-hour limit and the 7-day limit?" A subscription run that hits a window ends on an API error, not at a Stop: `StopFailure` fires with `error_type: rate_limit`, headless mode exits non-zero, and Claude Code does not retry a limit (its retry watchdog covers capacity errors, not the spend limit), verified in the docs. The goal loop cannot save it. Two hook pieces now: the statusline's `rate_limits.five_hour / seven_day` (`used_percentage`, `resets_at`; Claude.ai plans only) are mirrored beside the token counts, and at 90% of the 5-hour window (95% of the weekly) one `<engram-context>` per window says so with the reset time and asks for a checkpoint and a park on a ScheduleWakeup or Monitor until the reset, instead of running into the limit mid-step. A new `stop_failure_json` hook records every API failure into `run.failures` with its type, message, permission mode, and for a limit the window's reset; the run report shows how the run ended and when a resume makes sense. The third piece, sleeping until `resets_at` and relaunching `claude -p --resume <id>` (a resume restores an active `/goal`, verified), belongs to the Phase 6 launcher. The shipped statusline shows `5h 93%`; the author's own script mirrors the same fields. `tests/bench_context_pressure.py`: 170 checks.

### v0.8.23 (2026-09-10)

- **The compliance trail.** Rules stay natural language; a rule may now carry a hand-written detector (tool names, a regex against a shell command, globs against an edited path, a regex against the tool input) stored on the rule entry itself, so it travels with the rule and is inherited from a workspace-level rule by every project under it. With a detector, every matching tool call is recorded: the turn, an excerpt of the input, and a verdict that is only what the hooks can see: `unattended` when the permission mode was bypass, auto or dontAsk (no person approved the call), `prompted` when Claude Code's own permission prompt stood between the model and the call, `plan` in plan mode. A rule without one is advisory, and the run report says so per rule. Detector health is reported too, so a regex that stopped compiling is visible rather than silently ignored; `set_detector` refuses a broken one outright. No language model sits in this path. Inferring detectors from the rule text was the option rejected, because it is where a dishonest trail creeps in. The live half runs at PreToolUse on `Bash|PowerShell` (a new daemon-served hook): a matching command gets the rule injected before it runs, the reminder at the moment it matters; PostToolBatch records every other tool. Matches are deduped by `tool_use_id`; subagent calls are recorded and flagged, never nudged. `memory(add_rule, detector=…)`, `memory(set_detector)`, `list_rules` marks the rules that have one. `"compliance": false` opts out.
- **The pack ships its detectors.** Destructive shell commands (`rm` outside `--cached`, recursive or forced `Remove-Item`, `rmdir /s`, hard resets, `git clean -f`, `branch -D`, force-push, `DROP`/`TRUNCATE`, disk formats, `dd`, `taskkill`, `pkill`), kill by image name (`taskkill /IM`, `Stop-Process -Name`, `pkill`, `killall`), and anything that leaves the machine (`git push`, `gh pr create|merge|comment`, `npm publish`, `twine upload`, `docker push`, an outbound `curl -X POST`) sit on the pack rules that name them (pack version 4). A project whose own rule already covers that ground adopts the pack detector if it has none (`seed_rules` walks up to the ancestor project that owns the rule id), and `add_rule` does the same for a similar existing rule. The "rm" pattern is anchored to command position: `grep -rn rm .` and `npm run build` are not deletes.
- Verified on Windows and Linux (WSL): `tests/bench_compliance.py` 137 checks, including the real PreToolUse and PostToolBatch entry points and the run report; every other bench green.

### v0.8.22 (2026-09-09)

The open list, closed before Phase 5. Four fixes, all in engram code.

- **The memory store now sees what another process wrote.** The MCP server is one long-lived `MemoryStore`; hooks and the CLI are others. It served the copy it took at first touch, and `_save()` falls back to "all loaded projects" for the seventeen callers that never mark a project dirty, so a save for one project rewrote every other loaded project from a stale copy. Observed as a delete-by-id "not found" after a CLI re-seed; implied and now reproduced: lost writes. Each loaded `memory.json` and the manifest carry a disk stamp (mtime, size). A read reloads a copy the disk has moved past; a project registered by another writer is found by re-reading the manifest; a save skips a stale project this process never mutated, and merges by entry id when it did mutate one on a stale base (a write is never lost; an entry the other writer deleted in that instant can come back). `tests/bench_memory_freshness.py`: 15 checks, two stores over one directory. The "one rule writer per session" rule is retired.
- **Milestone classifier: restated history is not a claim.** Two more real false positives from the day: "…and `ef0bb83` (the pushback and follow-plan rules) landed after it was saved" (a unit noun hiding in a hyphenated compound, past tense about a commit already in history) and a bold header followed by a quoted sentence discussing the first one. Quoted spans are removed before matching; a sentence with a history marker (`already`, `earlier`, `last session`, `after it was …`, `had landed`, `as of …`) is not a claim; a unit noun inside a hyphenated compound or a path (`follow-plan`, `goal-test/`) is not the unit; a sentence ends at `.**` as well as at `.`.
- **Loop detector: "edits without tests" is a code signal.** Eight edits to a markdown, config or data file are a document being written; the warning now gates on a code suffix.
- **Managed settings are read.** `managed-settings.json`, the `managed-settings.d/` drop-ins (alphabetical, later wins) and on Windows the `HKLM`/`HKCU` `SOFTWARE\Policies\ClaudeCode` policy value, per the docs' paths and precedence: managed outranks every project and user file; the env var still wins. The source label says `managed`.

### v0.8.21 (2026-09-09)

- **Stall detection: strikes that count effect, not activity.** `/goal`'s own stall rule stops a loop after several turns with no tool use; the overnight failure that matters is the other one, a run that uses a tool every turn and changes nothing (seen live the same day: nine turns of `cat` on a file that was never going to change, $3.68, the stall rule silent because every turn used a tool). `hooks/stall.py` judges each turn at Stop by what it changed: a file (Edit/Write/NotebookEdit, a mutating shell command by text, or the git working tree moved since the last effect-free reading), a test status that flipped, a commit, or work delegated to an agent is *good*; tools with none of that is *no effect*; no tools at all, or a turn parked on a wait primitive (Monitor, ScheduleWakeup, a cron, a background task), is *neutral* and touches neither streak. Three consecutive no-effect turns are one strike, staged at Stop and delivered once at the next injection point: strike 1 names the pattern and asks for a wait primitive over polling; strike 2 re-injects the latest checkpoint and the rules and forces a bearings check; strike 3 is the cap, the halt once autonomy mode lands. Strikes decay rather than reset: five consecutive good turns remove one, repeatedly. Every increment and decrement is an event with its turn number; the run report gains a Stalls section. Tool calls are accounted from the new `PostToolBatch` hook (every call in a batch with its response, matcher-free, so NotebookEdit, MCP writes and wait primitives are seen without a PostToolUse entry each) and from the Edit/Bash PostToolUse handlers as a fallback; the batch event runs in the hook daemon like the other high-frequency ones. Subagent batches are counted, never nudged. Turns, not time: a four-hour foreground command is one turn, so long runs and long suites never trip the ladder on duration; a test run that is not a repeat of the last (command, verdict) pair is verification and neutral, the same pair again is the re-run-and-hope pattern and counts as no effect. `tests/bench_stall.py`: 159 checks, including the reference case replayed and the hook entry points driven end to end.
- **The setpoint notice.** `autoCompactWindow` is a token count and Claude Code caps it at the model's window: `/autocompact 750k` is 75% of a 1M model and the whole window of a 200K one, no headroom for the checkpoint call. A hook cannot change a live session's point, so engram now says so once, at the first context reading, with the number that fits the model (75%, e.g. `/autocompact 150k`); a 200K model with no setting gets the same line. The PostCompact rhythm names the cap too. `CLAUDE_CONFIG_DIR` is honored when looking for the user settings file.

### v0.8.20 (2026-09-09)

- **The workflow tier.** The pack's rules were the working rules; the user asked for the working *method* too: how work is planned, gated, delegated, verified and landed. Eight more rules, distilled from the author's best-kept project rulebooks in their own wording: plan before code (nothing is implemented until the design is written and agreed; an approved design is not an approval to build); proposed, open and decided are three different things, and a decision carries a "revisit if"; every milestone has a gate written before the work and a verdict after, and a large one gets an independent review before anything is built on it; delegate by size with a cheap model for maintenance, a strong one for review, and a hard agent budget on every prompt; verify before claiming done (targeted tests plus one unmocked end-to-end path, every created file listed, no run on a known-broken input); numbers get a source and the run behind them is kept; nothing leaves the machine without the owner, never force-push main, one idea per pull request, never squash a stacked base; write the learning when it happens. (PR-only main is a team convention, not a default: a solo repo pushes its own main.) The same text lands as a `## Workflow` section in the scaffolded `CLAUDE.md`, which is where the author's projects keep it. `"workflow_rules": false` turns the tier off on its own; pack version 3 re-seeds existing projects with only what they lack.

### v0.8.19 (2026-09-09)

- **The default pack.** Engram now ships the opinion its author's workspace runs on, on by default and one line to turn off in `<project>/.engram/config.json`. *Structure*: the workspace scaffold, created only where pieces are missing and only in a directory that is already a project: a nav-headered `CLAUDE.md` with Purpose / Testing / Structure, `.learnings/ERRORS.md`, `.learnings/LEARNINGS.md`, `session-logs/`. A multi-person layout (`.learnings/<name>/`, `session-logs/<name>/`) is recognised and left alone. *Rules*: the workspace rules in their own words. No destructive commands without asking, search first, quality over speed, prerequisites first, be direct, try before asking, private stays private, never kill by image name, session maintenance is not optional, checkpoint when you judge a step done: all seeded once into the project's memory on its first fresh session. Any rule the project or an ancestor already carries in substance is skipped (word overlap), so a workspace that wrote its own rules keeps them and gets no duplicates.
- **Rotation.** Nothing is deleted, ever. Dailies older than 30 days move to `session-logs/archive/<YYYY-MM>/` and the month gets a digest beside them (title and first bullet per section, rebuilt from the archived originals). Dated `ERRORS.md` entries older than 90 days move to `.learnings/archive/ERRORS-<year>.md`; `LEARNINGS.md` holds patterns, which do not age out, so it rotates only when over the cap (`rotation_learnings_days` turns age on). Either file still over 500 lines sheds its oldest 30-day-plus entries until it fits, and that cap, not the age rule, is what the dry run bit with: the 3,500-line V11 learnings and a 2,000-line chappie file both land under 500 while claude-engram's own 326-line LEARNINGS stays whole. Every heading shape seen in real files is parsed; undated sections and anything marked STANDING / permanent / RULE never move. Files keep their line endings and nav headers; one `> Rotated …` line lands under the title and is replaced on the next rotation, not stacked. Per-person folders rotate inside themselves. By default SessionEnd only plans and SessionStart announces the pending plan; `session_mine(rotate, dry_run=false)` or `python -m claude_engram.rotation --apply` applies it; `"rotation": "auto"` applies at every session end.
- Dry run against the author's own projects on the day it shipped: the 3,500-line V11 learnings and the 51 dailies were the case it was built for; every project's plan is one line and none of it is destructive.
- New `tests/bench_phase3.py`: config precedence, both rotations across every heading shape, the line cap, CRLF preservation, the note, nothing-lost checks against the archive, plan persistence and the auto mode, the per-person layouts, the pack's similarity check and idempotence, structure creation and the opt-outs, source guards.

### v0.8.18 (2026-09-09)

- **`/loop` and `/goal` tested live, in two interactive sessions.** The loop alone behaved: the skill created a cron job (`*/2 * * * *`), each fire arrived as a user prompt, three appends landed two minutes apart, and the job was deleted. With a goal set in the same session the model appended the last two lines itself, seventeen seconds apart, and said why: *"the cron can only fire while the session is idle, which the hook prevents."* Two more sessions settled it, and the fourth showed both halves in one run. Loop first, then a goal whose condition forbade the model from appending: after every not-met verdict the goal re-prompted at once: nine verdicts in two minutes, about fourteen seconds per cycle, the model checking the file and ending the turn each time. The 02:28 cron fire was lost: there was no idle gap. Then the model parked on a background Monitor; a goal defers evaluation while background work or a wakeup is pending, the session idled, and the cron fired at 02:30 and 02:32, the file written only inside the fires, goal met. So a not-met goal starves scheduled tasks unless the model parks on a wait primitive, and parked, they compose. Two further facts from the storm: the evaluator did not honor "or stop after 8 turns" (still not-met at turn nine), and `/goal`'s own stall rule never fired because every turn used a tool: nine turns of `cat` with no effect, which is exactly the no-progress case Phase 4 is for. That session cost $3.68 against $0.86 to $1.46 for the others; context went 65K→95K. Across all four, the floor (system prompt, skills, banners) at 50K to 65K dwarfs per-turn growth of 1K to 5K.
- **Loop sessions get a report.** The loop-only session appended through Bash, touched no Edit, set no goal, and so left nothing. Three or more Stop events now qualify a session (a one-shot question has one). The report also counts scheduled work: cron jobs created and deleted, self-paced wakeups.
- **Milestone classifier: three false positives fixed.** All three fired on the assistant's own sentences to the user: an instruction ("Exit after it says the goal is met"), a prediction ("the next verdict should say met"), and a quote of the prediction. Imperatives and second-person sentences are now rejected outright, and the modal / conditional guard (`should`, `would`, `will`, `after`, `once`, `when`, `if`, `until`…) applies anywhere before the completion word rather than in a 14-character window. "Run 3 of 3 done" is now a claim (numeric progress reaching its total) while "Run the suite until it is green" is not. Replayed over the three test transcripts and this session's own 654 assistant texts: 47 flagged, roughly half genuine; a nudge only ever fires on a turn's final message and once per claim, so the live rate is well below that. Precision over recall, on purpose.

### v0.8.17 (2026-09-09)

- **Goal verdicts are in the run report, from verified records.** Three headless `/goal` runs on a scratch project (`claude -p "/goal …"`, Sonnet 5, Haiku evaluator) established the transcript shape: `attachment.type == "goal_status"`, a sentinel when the goal is set (`sentinel: true`, `condition`), then one entry per evaluator verdict with `met`, `reason`, `iterations`, `durationMs`, `tokens`; a goal judged impossible carries `failed: true` (the docs' "failed entry"). The report now shows the condition, when it was set, every verdict with its reason, and the outcome: met, failed, unresolved, or set with no verdict recorded. The 0.8.16 "not parsed" note is gone.
- **A goal run always gets its report.** The first real run wrote `done.txt` through Bash, never touched Edit, and so was not "substantial", which meant no report. `substantial()` now also fires on a test run and on a goal (a bounded head scan of the transcript for the sentinel). Verified: the next two runs wrote `.engram/runs/<date>-<session8>.md` at SessionEnd on their own.
- **The session-start teaser labelled a foreign checkpoint with the new project's name.** A brand-new project has no ring, so the global ring served the last deliberate checkpoint from another project, correct as a fallback, but the label inferred the project from the entry's first edited file *resolved against the cwd*, which yields the cwd. An engram checkpoint appeared as `goal-test`. The entry's own `project_path` now names it (files remain the fallback for old autos only).
- Milestone classifier: `goal` / `objective` join the unit nouns and `met` / `achieved` / `reached` / `satisfied` / `resolved` the completion words, so "Goal met: …" is a claim and "the goal is not met yet" is not.
- Gotcha recorded: from Git Bash on Windows, `claude -p "/goal …"` needs `MSYS_NO_PATHCONV=1`, or the leading `/goal` is rewritten into a filesystem path and no goal is set.
- `/loop` cannot be exercised headlessly: scheduled tasks fire only while an interactive session is idle. That test belongs to a live session.

### v0.8.16 (2026-09-09)

- **Run report.** Every substantial session now leaves one auditable artifact in the repo: `<project>/.engram/runs/<date>-<session8>.md` plus a `.json` twin, written at SessionEnd (an edit, a compaction, or five prompts qualifies) or on demand via `session_mine(run_report)` and `python -m claude_engram.run_report --session <id>`. Nothing in it is self-reported by the model.
  - Sources: the per-session hook state (files with per-file edit counts, test runs and first/last status, prompts, the `run` block, the `pressure` block), the transcript (model, branch, `/goal` command text, tool errors, every `compact_boundary`), this session's ring entries, the statusline mirror (final tokens and cost, which the mirror now records), git for the end commit, and `patterns.json` for which errors were already known.
  - **Compaction sizes come from Claude Code itself.** The transcript's `compact_boundary` record carries `compactMetadata` with `trigger`, `preTokens`, `postTokens`, `cumulativeDroppedTokens` and `durationMs`, verified on a real transcript (33 boundaries in one session, e.g. `489107 → 28251`). The report joins each with what PostCompact restored, pinned to the compaction record by the hook.
  - Provenance the hooks now record: SessionStart stores the start commit, the permission mode and the transcript path in a `run` block; SessionEnd stores the end reason and writes the report before clearing state; PostCompact pins the restored ring entry; Stop counts turns; manual `checkpoint_save` ring entries carry `session_id` like the auto entries always did.
  - Honest gaps, listed in the report rather than omitted: stall strikes (Phase 4), rules compliance (Phase 5), goal evaluator verdicts (no local transcript has ever carried a `/goal` run, so the format is unverified and not guessed), a missing transcript or mirror. Automatic per-turn saves contend only for the ring's latest pointer, so deliberate checkpoints are the record and at most one auto is listed.
- New `tests/bench_run_report.py`: collection from a seeded state + transcript + ring, the compaction join, error grouping and known-before matching, session scoping of checkpoints, rendering, atomic idempotent writes, the substantial gate, the CLI, and source guards on every hook that feeds the report.

### v0.8.15 (2026-09-09)

- **Milestones are the model's call.** The follow-up to 0.8.14's pressure nudges: the other moment a checkpoint belongs is when a unit of work closes, and the fixed 25-turn cadence was a stand-in for a judgment only the model can make. It is now the trigger. The rule in the skill and CLAUDE.md: when you judge a phase, step, or part of a plan done, `checkpoint_save` before you say so.
  - Engram catches the misses. The Stop hook receives the model's final message verbatim (verified: `last_assistant_message` is the documented field for exactly this). `hooks/milestones.py` classifies it, two-tier like decision capture: a completion word near a unit noun in one sentence is a strong match (`Phase 1 is built`, `step 3 done`, `all 60 checks pass`, `that closes part A`); negation, partials, future markers and questions never fire (`not done yet`, `half done`, `when step 3 is complete`, `I'll mark the task complete`, `is phase 1 done?`); a weak match consults the scorer daemon against completion vs non-completion templates. Commit sentences are not a trigger by design.
  - A claim with no deliberate checkpoint that turn is staged and asked for once at the next injection point, quoting the sentence. One turn late in an interactive session by construction: a Stop hook cannot add context to the turn that just ended, so the rule is the ideal path and the nudge is the miss-catcher. In a loop it lands at the next tool call. A checkpoint that lands after the claim answers it silently. Subagent stops are ignored.
  - `ExitPlanMode` and `TaskUpdate` get a `PostToolUse` handler: a plan approval asks for the plan to be banked with its steps as `pending_steps`, so every later "done" maps onto that list; a task marked completed is the same claim stated structurally. Verified: Claude Code leaves the task tools out on Opus 4.8, Sonnet 5 and the Fable models unless the user opts in (`TaskCompleted` exists as a hook event but will not fire there), so that path is a bonus, not the design.
  - The turn cadence is demoted to a fallback at 60, and reworded: that many turns with neither a checkpoint nor a completed step is closer to a stall signal than a save schedule. A completion claim resets it.
- `bench_context_pressure` grows to 130 checks: 9 positive and 15 negative claims, a claim inside a long message, the semantic tier through a patched embed seam (margin, negative margin, scorer down), staging at Stop, delivery once, the ideal path (checkpoint the same turn stages nothing), silent answer, the task path, slot priority against a pressure band, and source guards on the Stop wiring, the new handler, the installer and the skill rule.

### v0.8.14 (2026-09-09)

- **Deliberate checkpoints before compaction.** Auto-compaction used to be the thing that decided checkpoint quality: `PreCompact` wrote an automatic entry and that was all a long run had. Hooks receive no context-usage numbers, so the fix crosses from the statusline, which gets `context_window.total_input_tokens` and `context_window_size` on every update. The statusline mirrors them to `sessions/<session_id>.ctx.json`; the hooks read the mirror and compute the **distance to the compaction point**.
  - The point is not 100% of the window. Verified against the model-config docs: with nothing set, a 200K model compacts at the 200K boundary and a native-1M model at about 967K; `CLAUDE_CODE_AUTO_COMPACT_WINDOW` beats everything, then `autoCompactWindow` in settings (local → project → user, in every documented form: plain count, `500k`, `1M`, bare 100 to 1000 = thousands), capped at the window. A window set only by the `--autocompact` launch flag is invisible to a hook; engram falls back to the model default and names its source in the nudge. Raw `used_percentage` is never used: on a 1M model a "65%" heads-up against the raw window would fire ~300K tokens early.
  - Two nudges, once each per compaction cycle: a heads-up 10% of the window before the point (finish the step, start nothing long) and `CHECKPOINT NOW` 3% before it (5% on a ≤200K window, where 3% is 6K tokens): write a deliberate `checkpoint_save`, then continue. `PreCompact`'s automatic entry stays as the floor. `PostCompact` opens the next cycle and restates the rhythm ("heads-up at ~650K, checkpoint at ~720K, compaction at ~750K"), so after the first compaction the model plans around the next. A cadence reminder fires every 25 turns without a deliberate save (`CLAUDE_ENGRAM_CHECKPOINT_CADENCE`), counted at Stop, reset by `checkpoint_save`.
  - Delivered from every injecting hook (UserPromptSubmit, PreToolUse Edit/Write/Read, PostToolUse Bash/Edit/Write) through one state-latched `_with_pressure()`. That breadth is deliberate: an unattended `/goal` loop has no user prompts, so PostToolUse is the only delivery point that fires every turn. Never via the Stop hook: it cannot add context, and engram never blocks there.
  - Right after `/compact` the statusline still shows the pre-compaction count until the next API response. A mirror older than the compaction is ignored, so there is no false `CHECKPOINT NOW` in the first turn of a new cycle.
  - No statusline means no reading; that is announced at session start (no `statusLine`) or after five silent minutes (configured but not recording), never silently absent. `python -m claude_engram.hooks.context_pressure statusline` is a ready-made statusline; `assess <session_id>` prints the current reading.
- **Restore prints its ring again.** The 0.8.8 provenance line (`**From:** project · age`) keyed on a top-level `project_path`, which the auto entries write and manual `checkpoint_save` did not, since it stored the path only under `metadata`. So the guard built to catch a cross-project restore was blind to every deliberate checkpoint, the common case. Manual ring entries now carry it top-level; the restore and the session-start banner both fall back to `metadata` for records already on disk.
- `remind.py`'s `main()` crossed pyright's complexity ceiling ("code is too complex to analyze", which also switches off every check inside it). The SessionStart, PostCompact and Read branches are now `_hook_session_start` / `_hook_post_compact` / `_hook_pre_read`. Zero pyright errors again.
- New `tests/bench_context_pressure.py` (60 checks).

### v0.8.13 (2026-08-27)

- **Fixed a real memory leak in the scorer daemon: ~0.73 MB per request, unbounded.** The daemon handles each connection on a fresh thread and ran the model call on that thread. PyTorch keeps per-thread state it does not release when the thread dies, so every request permanently retained ~0.73 MB. Measured dead-linear at **+146 MB per 200 requests across eight consecutive rounds with no plateau**, which is what walks a long-running daemon past 4 GB.
  - Isolated before fixing: `model.encode()` called 800× on the main thread is flat (1041.3 → 1041.4 MB); the same encode called once per fresh thread grows +0.73 MB each, matching the daemon exactly. Bare thread churn with no model call is flat, and thread/handle counts stayed constant throughout, so it was neither thread accumulation nor a socket/handle leak.
  - Every model call now runs on one long-lived pinned thread (`_on_model_thread`, a `max_workers=1` executor). That costs nothing: the GIL and torch serialized these calls already. After the fix the same workload is flat: 1043.0 → 1043.4 MB over 800 requests, committed bytes pinned at 2519 MB.
  - Measure committed/private bytes, not just working set, when checking this on Windows: Windows does not trim working sets without memory pressure, so working set alone can mislead in both directions. Both metrics grew here, which is what confirmed a true leak.
- **Bounded the VRAM spike.** The transient bulk worker encoded with `batch_size=256` against the encoder's full 512-token window, a multi-GB activation footprint. Measured on a 1500-text job with long inputs: **peak 8049 MiB at batch 256 vs 3147 MiB at batch 64**, against an 833 MiB idle baseline (7216 MiB → 2305 MiB of actual job footprint, a 3.1x cut). On a 12 GB card the old peak contends with anything else training. Batch is now 64 (`CLAUDE_ENGRAM_GPU_BATCH` to override). The spike itself is by design and not a leak: VRAM returned to 833-836 MiB after every run, because the worker exits and process exit is the only way to fully release a CUDA context.
- **Capped encoder input at `MAX_ENCODE_CHARS = 2000`, server-side.** The encoder discards anything past its 512-token window anyway, so oversized text was tokenized and padded at full cost and then thrown away, ratcheting the allocator's high-water mark. `embed_batch` truncated at the client; `embed` and the scorer's no-sentence-break fallback (a pasted log, code, one long line) did not. Applied in the daemon so every caller is covered. Two 20k-word blobs now cost +6 MB instead of hundreds.
- **The resident daemon's batch path was capped too.** The first pass capped only the transient bulk worker. The daemon's own `embed_batch` still used 256, which fires when `CLAUDE_ENGRAM_DEVICE=cuda` puts it on the GPU, and there it is strictly worse than the case already fixed: the worker exits and releases its CUDA context, the daemon never does, so a 256-row batch parks multi-GB of activations for the life of the process. Both paths now share `gpu_batch_size()`, and `CLAUDE_ENGRAM_GPU_BATCH` is in the README config table rather than only the changelog.
- New `tests/bench_scorer_thread_affinity.py` (10 checks): model work never runs on the caller's thread, 40 concurrent caller threads share one model thread, results and exceptions propagate unchanged, and a source guard fails if any call site in `_handle_client` bypasses the pool; the leak returns silently the moment one does.

### v0.8.12 (2026-08-03)

- **Consolidation deleted the memories it merged.** `_consolidate_group_with_llm` kept the 5 highest-relevance originals and dropped the rest by reassigning `proj.entries`. Nothing wrote them anywhere else, so they were gone for good. That contradicts the rule the rest of the store follows ("cleanup archives before deleting; nothing is lost without review"), and it was latent only because `consolidate` had no dispatch branch until v0.8.9; wiring the operation is what made it reachable.
  - It bites hardest exactly where consolidation is most tempting: auto-captured decisions are all minted at the same relevance, so "keep the top 5 by relevance" degenerates to "keep whichever 5 come first". One `dry_run=false` call on the reference store's decision group would have destroyed roughly 200 memories with no way back.
  - Merged members now go through `_move_entries_to_archive`, the same restorable path everything else uses. The response and the tool description say so, and both now warn that a very large group compresses into one paragraph and loses the specifics worth recalling.
  - New `tests/bench_consolidate_safety.py` (7 checks): every dropped member lands in the archive, nothing evaporates (`hot_before == hot_after - digest + archived`), an archived member restores by id, the digest reaches the hot tier, and rules/mistakes are never consolidated. It uses a fake LLM client, so the safety property is pinned without needing Ollama.

### v0.8.11 (2026-08-03)

- **The hot tier could not shrink: two constants collided.** The miner mints auto-captured decisions with a hardcoded `relevance=7` (`extractors.py`, `work_tracker.py`), and `_is_archivable` exempted anything with `relevance >= 7`. Every auto-captured decision was therefore born permanently exempt from age-archiving. On the reference store that left **231 decisions untouched for over two weeks and still un-archivable**, with relevance taking exactly two values across all 444 (417 at 7, 27 at 6): a constant, not a judgment.
  - The exemption is now `ARCHIVE_EXEMPT_RELEVANCE = 8`, a named constant documented as *"must stay above every default"*: manual `remember` is 5, auto-decisions are 7, rules are 9 and exempt by category anyway. It now means "someone marked this important" instead of "it exists". Injection scoring is untouched: relevance still carries its 15% weight, so what gets injected does not change.
  - This is the real cause of unbounded hot growth, not a missing consolidator. `cleanup` was correct to report zero: it removes near-duplicates (0.85 similarity, the same memory stored twice), which is a different job.
  - New `tests/bench_archive_exemption.py` (12 checks). Beyond the regression itself it pins the *property*: it parses the real mint sites with `ast` and fails if any age-eligible hardcoded relevance ever reaches the exemption again. Written with `ast` rather than regex because the two kwargs appear in either order, and a "nearest preceding `category=`" heuristic mis-attributed a call that passed `relevance` first.

### v0.8.10 (2026-08-03)

- **One name per concept on the ring record.** Every checkpoint written to the ring carried both vocabularies: the checkpoint one (`pending_steps`, `files_involved`, `handoff_warnings`, `handoff_context_needed`, `key_decisions`, `timestamp`) and the handoff one (`next_steps`, `files_in_progress`, `warnings`, `context_needed`, `decisions`, `created`). Audited before changing anything: across the 129 stored records carrying both, all six pairs were identical in **every single record**. The checkpoint twin is no longer written.
  - **`task_description` / `summary` is not a twin pair and was left alone.** `summary` is the handoff note (`handoff_summary or task_description`) and differed from the task title in **110 of those 129 records**, so collapsing it would have merged "what the task is" with "where things stand" and lost one.
  - **No migration.** Records on disk keep both names and every reader accepts either. Two readers did *not*: the SessionStart banner checked only `pending_steps` and `checkpoint_restore` checked only `key_decisions`, both with no fallback, so a handoff-shaped record (written by `create_handoff`, which only ever emits the handoff vocabulary) silently lost its "Pending: N steps" and "Key decisions: N recorded" lines. Both fixed here.
  - A side effect worth naming: `checkpoint_restore` passes the whole record as `data`, and `to_formatted_string` renders every list in it, so a dual-vocabulary record printed **each list twice**, once per name. The collapse removes the repeat without losing a line.
  - New `tests/bench_ring_vocabulary.py` (19 checks): canonical name written and twin absent, `task_description`/`summary` both surviving with different values, a collapsed record rendering the same as a legacy one through both the banner and restore, and a handoff-shaped record rendering every line.

### v0.8.9 (2026-08-03)

- **`memory(consolidate)` and `memory(clusters)` were unreachable.** Both were fully implemented (LLM tag-group consolidation with a 10-entry floor, rules and mistakes exempt; cluster listing) and both were named in the tool's own "Use: …" error string as valid operations, but neither appeared in the MCP schema `enum`, and neither had a dispatch branch. So they could not be called at all, while the error you got for trying said they were valid. Now wired, schema'd, and documented.
  - This is why a store could reach hundreds of hot decisions while `cleanup` honestly reported nothing to merge: cleanup removes **near-duplicates** (Jaccard and cosine at 0.85, the same memory stored twice), which is a different job from compressing a topic. On the reference store, `consolidate` immediately found 4 groups worth merging, one of them 402 memories.
  - Both responses pass a compact `data` payload. `to_formatted_string` renders a list-of-dicts as memory entries (`id`/`content`/`tags`), so handing it the raw report printed `[] () {'tag': …}` per group, the same double-render trap `hybrid_search` documents.

### v0.8.8 (2026-08-03)

- **Fix: a project-scoped restore could silently return stale state.** `_handoff_candidate_dirs` resolved a project's own ring plus its ANCESTORS, never its descendants, so a `checkpoint_restore` at a workspace root could only read the root ring while the session's real final checkpoint sat in a sub-project ring. Because the root ring is rarely empty, the call returned an hours-old entry **and reported success**. Observed live: a root-scoped restore returned an 11.8h checkpoint while the actual 9.7h one sat in the sub-project's ring. A query now sees every ring at or beneath the path it asked about. Siblings still can't leak in (that is what kept the cross-project global ring a fallback rather than an always-on candidate), and ordering doesn't decide the winner; the newest deliberate checkpoint does.
- **Restores and saves now say which store they used.** `checkpoint_restore` prints `**From:** <project> · <age>h` and warns when the winning entry belongs to a different sub-project than the one asked from; `checkpoint_save` reports the ring it filed under, calling out the global fallback for unregistered projects. A confident payload with no origin let a cross-project or stale restore pass for "yours".
- **`claude_engram_status` no longer fails wholesale when Ollama is down.** It reported `FAILED` with "cannot function without a working Ollama connection" while storage, checkpoints, hooks, injection scoring, the code index, precheck and blast-radius were all working, every one of them LLM-free. Status is now per-capability, and names the three operations that actually degrade (`scout_search`, `memory(consolidate)`, `session_mine(reflect)` synthesis). A health check that cries wolf gets ignored on the day it is right.
- **`memory(embed_all)` distinguishes its two zero cases.** "All memories already embedded (or scorer server not running)" was returned identically whether there was nothing to do or the scorer was dead. It now reports the actual pending count and says plainly when the scorer is unreachable.
- **Mined fixes reject narration.** The fix for a recurring error was taken from the first sentence of the next assistant message, so a real stored fix read `"Let me check the correct path:"`, an intention replayed later as if it were guidance. Extraction now scans the next few assistant messages for a sentence that states a resolution, and the pattern reader filters legacy records the same way, so no migration is needed.
- **Dropped `progress_percent` from checkpoint saves.** Each save re-derives its step lists, so the number fell (56% → 42%) across a productive night as the remaining work came into focus. Raw done/remaining counts replace it.
- **Two silent-feature-loss bugs.** Pattern injection joined a path on a possibly-`None` project dir, and the pre-edit import check read an unbound `data` when stdin was empty. Both raised into an enclosing `except`, so the features simply never ran for those cases instead of reporting anything.
- **`MiniClaudeResponse` → `EngramResponse`** (131 references). The class is never serialized, so this is internal only.
- **Type-check clean:** 98 package errors → 0, mostly by typing the `subprocess` kwargs dicts that made Pyright re-check every parameter as `int`. Includes a real annotation bug (`tuple[list[str], any]` used the builtin `any` instead of `typing.Any`) and `None` defaults on parameters declared non-optional.

### v0.8.7 (2026-07-26)

- **Removed: session titling from restored checkpoints** (shipped in 0.8.6). SessionStart fires on resume and post-compact too, so the title stomped names the user set with `/rename`; and in a multi-project workspace the restored checkpoint can belong to a *different* sub-project than the session: an engram session came back titled `sabir: …`. The session name belongs to Claude Code and the user; engram never writes it back. `bench_session_identity` now pins the inverse invariant: `session_start_json` emits no `sessionTitle` for any checkpoint kind (10 checks, was 18).

### v0.8.6 (2026-07-26)

- **Fix: MCP tools read the live session's state, not a stale one.** Working state lives in `sessions/<session_id>.json`. Hooks learn that id from their stdin payload, but the MCP server has no stdin, so it fell through to the shared `hook_state.json`, a file the per-session hooks never write. `session_end()` therefore reported whatever was last left in that file: on the reference store, a session that had started 15 days earlier with 0 files edited. Claude Code 2.1.154+ exports `CLAUDE_CODE_SESSION_ID` to stdio MCP servers, so the server now adopts it at startup and MCP-side reads line up with hook-side writes.
  - Deliberately scoped to the MCP server rather than folded into `get_state_file()`: the scorer daemon serves many sessions from one long-lived process and clears the id between requests, so an ambient environment fallback there would resurrect exactly the cross-session leak that reset prevents. Only a process that maps 1:1 to a session opts in.
  - Adoption never overrides an id already parsed from stdin: per-call truth beats a process-level variable that outlives any one payload.
- **Session title from a restored checkpoint** (Claude Code 2.1.152+). Resuming a **manual** checkpoint sets `hookSpecificOutput.sessionTitle`, so the row in `claude agents` reads `myproj: Migrating auth to OAuth2` instead of a generic title. Autos never title, the same deliberate-beats-automatic rule the teaser follows, so "Session stopped. 2 files edited." can never overwrite a name you chose.
- **`CLAUDE_PROJECT_DIR` as the MCP last resort.** Two MCP paths (`deps_map` symbol lookup, `session_end`) fell back to the server process's cwd, which is wherever Claude Code happened to spawn it, not your project. Both now defer to `get_project_dir()`, which prefers `CLAUDE_PROJECT_DIR` (now exported to stdio MCP servers).
- **Docs:** a large `session_mine(reindex, mode="bootstrap")` can exceed Claude Code's 2-minute MCP call limit and auto-continue in the background; re-run the query once it settles rather than re-triggering the rebuild.
- New `tests/bench_session_identity.py` (18 checks): identity precedence (stdin > env > shared fallback), the `session_end` regression against a stale-vs-live store, title selection, and the real SessionStart hook subprocess asserting a valid schema with the title set for manuals and absent for autos.

### v0.8.5 (2026-06-30)

- **Checkpoint-injection fix.** The SessionStart `CHECKPOINT` teaser could surface a trivial per-turn auto ("Session stopped. 2 files edited.") while the substantive manual handoff sat correctly at ring index 0. The two selectors were identical but read *different rings*: auto handoffs targeted the cwd (workspace root) ring, manual saves the sub-project ring, and the candidate walk only ascends. Six coordinated changes:
  1. **The history ring is deliberate-checkpoints-only.** Autos contend only for the latest pointer; they never append (Stop fires every turn, and per-turn autos evicted real checkpoints from the 20-slot FIFO within one session). Newest auto stays restorable via the pointer fold-in; legacy single-slot seeding preserved on every write.
  2. **Teaser resolution by session source.** Resume → resolve the project from THIS session's own edited files (captured before the per-session reset; concurrency-safe, never the pooled "last session"). Fresh → newest MANUAL across the workspace subtree as a labeled breadcrumb, else the plain walk-up.
  3. **Stop + pre-compact autos write to the file-resolved project ring** (majority vote over recent edits), not the cwd.
  4. **Manuals exempt from the 48h teaser cutoff** (14 days; autos keep 48h), so a weekend away no longer silently expires the handoff you wrote for yourself.
  5. **Self-identifying teaser label**: kind + sub-project + task_id (`CHECKPOINT [manual, 2.1h ago, grommet, task_…]`) so the model can restore exactly what was teased.
  6. **Subagent stop guard**: a Stop carrying `agent_id` doesn't write the parent's ring.
- **Fix: `get_state_file` honors `CLAUDE_ENGRAM_DIR`**, the last storage path hardcoded to `~/.claude_engram`, which broke the documented test-isolation seam for per-session hook state.
- `bench_handoff_durability` updated to the new ring contract (autos pointer-only; second manual at index 1; auto-only fallback via pointer).

### v0.8.4 (2026-06-11)

- **Curated-lessons bridge (opt-in).** Dated entries (`YYYY-MM-DD — insight`) in user-curated note files sync as protected `lesson` memories: never archived, decayed, or deduped (the file owns the lifecycle: edits update, removals retire), +0.25 injection bonus, and code-index-joined triggers: a lesson naming a module gains `related_files` = the files importing it, so it surfaces exactly when that code is touched. Strictly opt-in via `config.json` `lessons_globs` (e.g. `["docs/lessons/*.md"]`); the tool ships no default path and never guesses which markdown is a lessons file.
- **Pattern banner is project-scoped and recency-decayed.** Recurring errors carry `projects` (attributed from the contributing sessions' edited files) and `last_seen`; the session-start banner filters to the sub-projects the last session touched, and errors quiet for 30 days drop out of the report entirely. Struggles are scoped by their (now full) paths.
- **Struggles metric made causal.** Full-path keys (no more basename pooling across projects) and `errors_nearby` counts only sessions where an extracted mistake actually references the file (via `related_files` or a traceback mention). Files with zero attributable errors are not struggles.
- **TDD-aware mistake capture.** Failing test invocations (`pytest`, `npm test`, `python tests/...`, suite-marker outputs) are tracked as test FAILs but never auto-logged as mistakes, because RED-phase failures are deliberate. Shared `_is_test_invocation()` across both bash handlers.
- **Migration `0.8.4:modernize_mistake_store`** (automatic on next SessionStart / install): legacy in-place `archived_at` flags move into archive.json for real, and machine-written mistakes provably fixed against the current code index (missing module now resolves, missing attribute now exists on that class) are archived. Never deletes; never touches manual `log_mistake` entries.
- **Stale-mistake hygiene now covers `session_mining`.** The 0.8.1 gate only matched `auto-detected`, 18 of 282 mistakes on the reference store; the transcript miner stamps `session_mining`. Both are machine-written. Live effect with the migration: 282 → 71 hot mistakes, all restorable.
- **Decision capture stores full sentences** (word-boundary cut at 300; banner display word-boundary at 200) instead of a hard 150-char slice mid-word.
- **Honest activity counts.** New `prompt_count` (real typed prompts) alongside `user_message_count` (every type=user line, incl. tool results, with semantics preserved for the re-mine watermarks). The banner now reads "N prompts" / "N tool errors".
- **Rule banners deduped against CLAUDE.md.** A rule whose significant words are ≥70% covered by the project's CLAUDE.md is suppressed from session-start/post-compact display (still enforced, still listable), which ends the triple CLAUDE.md / rules / MEMORY.md injection.
- **Fix: Windows memory-embeddings save.** `embed_all_memories` kept the loader's live mmap of embeddings.npy while saving to the same path: Errno 22, silently freezing memory-embedding updates on Windows. Handle dropped after copying rows.

### v0.8.3 (2026-06-11)

- **GPU policy split: cpu-resident daemon, transient GPU worker.** The v0.8.2 resident-GPU default parked model weights plus a CUDA context (~1GB VRAM) for the daemon's entire lifetime, and live-mining ticks keep the daemon warm all day, which is indistinguishable from a VRAM leak in practice. Device policy is now: resident consumers (scorer daemon, in-process fallbacks) always load on cpu; bulk embedding jobs of `CLAUDE_ENGRAM_GPU_BULK_MIN`+ texts (default 512: bootstrap re-embeds, model-change rebuilds, store sweeps) run in `claude_engram.embed_worker`, a short-lived process that loads on cuda, encodes one job, writes `.npy`, and exits. Process exit fully releases the CUDA context, so the GPU is borrowed for seconds, never parked. The worker declines (and the caller falls back to the daemon) when no GPU exists. `CLAUDE_ENGRAM_DEVICE` remains a global override in both directions. Measured: cuda/cpu vectors identical at cos 1.000000, so device changes never rebuild stores; daemon RSS 1.2GB (cuda) → 680MB (cpu), VRAM 0.
- **In-process fallback model cached.** The daemon-down fallback in `score_decision_semantic` loaded a fresh model per call; now one cached load per process, on cpu.
- **Single-instance daemon startup.** `serve()` exits immediately when a live, signature-matching server already owns `PORT_FILE`, closing the two-session spawn race that left an orphan daemon holding a loaded model for up to 30 minutes.

### v0.8.2 (2026-06-11)

- **GPU embeddings, auto-detected.** `load_sentence_transformer()` resolves the device once: `CLAUDE_ENGRAM_DEVICE` override, else `cuda` when a CUDA-enabled torch is present, else cpu, and a broken CUDA runtime degrades to cpu instead of killing the scorer. The device is deliberately not part of the embedding signature (cuda and cpu produce identical vectors), so switching devices never rebuilds stores. `embed_batch` runs batch 256 on GPU / 64 on CPU; the scorer writes a `scorer_device` breadcrumb that `claude_engram_status` reports.
- **Live mining ticks keep engram fresh during the session.** The Stop hook fires a debounced (`CLAUDE_ENGRAM_LIVE_MINE`, default 300s) background mine in the new `live` mode: session index, extraction, search embeddings, and the two most-recent code indexes, every phase cursor/watermark-incremental, so each tick costs only the new transcript tail. Cross-session search and `replay`/`predict` now see the running session's earlier turns; previously everything waited for SessionEnd.
- **Decision-gate retune for bge-base.** `AMBIGUITY_MARGIN` 0.05 → 0.025 (the old value was tuned on MiniLM): semantic F1 72.7% → 76.9%, combined 77.4% → 79.0% on the 220-prompt bench. Recall +10.8 for precision -3.8: lost decisions are unrecoverable, noise captures get deduped, so the recall side wins. `DECISION_THRESHOLD` measured as a dead knob below 0.575 (the `score >= 0.45` capture cutoff already implies sim >= 0.525) and left at 0.45.

### v0.8.1 (2026-06-11)

- **Error deja-vu at failure time.** PostToolUseFailure now matches the fresh error against mined recurring errors (`patterns.json`) and the hot mistake store, and injects the past fix inline: `Deja vu: TypeError hit in 3 past session(s) - fix: ...`. Template matching reuses the miner's signature normalization, guarded by quoted-identifier overlap (an unrelated class never inherits someone else's fix); class-less failures (Edit conflicts, CLI errors) match manual mistakes by word overlap. Runs before auto-log so it can't match itself.
- **Symbol lookup via `deps_map(symbol="X")`.** Answers "where is X defined?" from the background code index: defining file, signature (`__init__` + method list for classes), dotted module, and reverse-import blast radius. Typo-tolerant (closest-name suggestion). No grep, no LLM, no build.
- **Sub-project code indexes no longer go stale.** The miner only built the mined project's index, and the workspace walk prunes nested project dirs, so in workspace setups the sub-project indexes (read by precheck, blast-radius, read-context, and the new symbol lookup) silently froze. Miner phase 6 now also refreshes every sub-project edited in the last ~10 sessions (incremental, mtime-keyed, cheap).
- **Mistake hygiene.** Auto-captured mistakes that never recurred (3+ weeks old, signature absent from mined recurring errors, no overlap with recently-edited files) are moved to the archive by miner phase 5. Manual `log_mistake` entries and rules are never touched. Archived mistakes stay searchable (`archive_search`) and restorable (`restore`).
- **Fix: `archived_at` is now honored by hook readers.** `acknowledge_mistake` set the flag but hot readers and banner counters never filtered it, so acknowledged mistakes kept appearing in pre-edit warnings. Hook readers now skip archived entries, and `acknowledge_mistake` performs a real move into `archive.json` (restorable) instead of an in-place flag.
- **Known-good test commands.** Test invocations the bash hooks already classify as test runs are tracked per project with pass/fail counts (`test_commands.json`, capped at 30). Session start surfaces the top currently-passing commands. Inline `python -c`, heredocs, `.scratch` scripts, and 160+ char contraptions are never recorded; a command whose latest run failed drops out until it passes again.

### v0.8.0 (2026-06-10)

- **Tool surface trimmed (19 → 16).** Removed `loop` (loop detection is hook-automatic and per-session now), `output` (its `validate_code`/`validate_result` checks are covered by `audit_batch`'s inline mode), and `scout_analyze` (zero recorded use). The remaining 16: `claude_engram_status`, `session_start`, `session_end`, `pre_edit_check`, `memory`, `work`, `scope`, `context`, `convention`, `scout_search`, `file_summarize`, `deps_map`, `impact_analyze`, `find_similar_issues`, `audit_batch`, `session_mine`.
- **LLM role narrowed: Ollama is now an optional flavor.** It is used only by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently without it), plus `scout_search` when available. Everything proactive is LLM-free: hooks, code index, precheck, blast-radius and injection scoring.
- **`convention(check)` is now a deterministic pattern check** against stored conventions (the LLM mode was removed: its "no check-mark means violation" heuristic was a false-positive machine with zero recorded use).
- **`file_summarize` is structural only.** The `mode` parameter and the LLM "detailed" mode are gone. It returns purpose, exports, dependencies, and a complexity estimate from pattern/structure analysis.
- **`audit_batch` and `find_similar_issues` are pure regex/AST**, with no LLM and no network (they never were; the docs are now explicit).
- **Loop-detection state is per-session.** Edit counts and test results live in the session's hook state (`sessions/<sid>.json`), not the shared `~/.claude_engram/loop_detector.json`, so two concurrent sessions no longer cross-contaminate. The old `loop_detector.json` is abandoned (harmless if present).
- **Pre-edit no longer records file edits** (only post-edit does), so denied or failed edits aren't counted toward the loop threshold.
- **Session-mining merge + per-phase error isolation.** A session that grows after being indexed (PreCompact then SessionEnd) now MERGES counts instead of resetting them; each miner phase is error-isolated and `mining_status.json` records which phase failed (`phase_errors`).
- **Auto-logged mistakes/decisions in a brand-new project are no longer dropped**; the project is auto-registered in the manifest first.
- **New env var `CLAUDE_ENGRAM_DIR`** overrides the storage location (default `~/.claude_engram`) and is the supported test-isolation seam.
- **`memory(embed_all)` fixed.** It crashed with a `NameError` since the args rename; it now reads its `force` flag from the call args.
- **Pre-edit hook ~2x faster** (~400ms → ~220ms median): stdlib-only `hooks/hot_reader.py` scoring path, lazy `tools/__init__`, one `memory.json` parse per hook, banner dedup.
- **Configurable embedding model** via `CLAUDE_ENGRAM_EMBED_MODEL` / `CLAUDE_ENGRAM_EMBED_DIM` (or `config.json`). Every embedding store is signature-stamped (`model@dim`) and rebuilds on model change; unstamped legacy stores read as the pinned `LEGACY_SIGNATURE` (`all-MiniLM-L6-v2@native`).
- **Default encoder is `BAAI/bge-base-en-v1.5`**, ungated (no HF account/token; `embeddinggemma` was evaluated and reverted: license-gated, ~3.3GB scorer RSS). Decision-capture semantic F1 at shipped thresholds: MiniLM 37.7% → bge-base 72.7%; live combined capture 77.4%. MiniLM remains the one-line ~90MB lightweight option.
- **Session-search embeddings are sharded by month** (`session_embeddings/<YYYY-MM>.npy`) instead of one ever-growing matrix fully rewritten at every session end; v1 stores migrate automatically. Optional `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` prunes old months.
- **Append-aware re-mining.** Sessions that grow after indexing contribute their new tail to search embeddings (per-file watermarks) and are re-extracted for decisions/mistakes; previously they were skipped as already-seen.
- **JSONL schema canary.** The miner tracks what fraction of session-log lines it recognizes; a collapse vs the historical baseline warns at session start instead of degrading mining silently.
- **Hook daemon.** The scorer server doubles as a warm hook dispatcher; high-frequency hooks are thin `python -S` clients (one TCP round trip, in-daemon ~15-25ms, full in-process fallback). Heaviest hook measured 313ms → 216ms median on Windows; Linux gains more.
- **Proactive recall before Read.** `<engram-read-context>` with code-index orientation + the file's most relevant memories, once per file per session. Optional `CLAUDE_ENGRAM_LAST_FILE_PATH` statusline mirror.
- **Outcome feedback loop closed.** Per-kind injection pass-rate lift becomes a bounded (0.8-1.2x) multiplier on the memory-injection relevance gate (miner-computed `injection_weights.json`).
- **Isolated-storage daemons.** `scorer_port`/`scorer_pid`/`scorer_model` and the decision-template cache honor `CLAUDE_ENGRAM_DIR`.
- **MCP launch hardening.** `install.py` points `.mcp.json` straight at the venv python instead of the `.bat` wrapper.
- **No emojis in any output.**

### v0.7.1 (2026-06-02)

- **Fix: `checkpoint_restore` / `checkpoint_list` could seat a stale checkpoint at index 0.** A sub-project query (e.g. `myproject/service-c`) walks up to ancestor rings; `read_latest` returned the *first* candidate ring's `latest_handoff.json` regardless of age, so a weeks-old handoff could occupy index 0 while the genuine latest sat lower, and an autonomous resume trusting index 0 could act on the wrong plan. Restore now selects the newest **deliberate (manual)** checkpoint across the resolved scope: a newer manual outranks an older one (kills the stale win), and a routine auto session-stop never buries a deliberate checkpoint; it falls back to newest-of-any-kind only when no manual is in scope. `read_history` now folds each ring's `latest` pointer into the merged view (a legacy single-slot handoff is never missed), and `read_ordered` pins this corrected latest at index 0, so `checkpoint_restore index=0` == `checkpoint_list[0]` == `get_by_index(0)`. Read-path only, so there is no migration; existing rings are re-interpreted correctly. New regression test: `tests/bench_restore_recency_scope.py`.

### v0.7.0 (2026-06-01)

- **`session_mine(commitments)`** reads the LIVE session transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items the post-session mining index cannot see. DEFERRED channel scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer language; IN-FLIGHT channel scans last ~30 messages for "I'll"/"let me"/"next" actions. Heuristic, LLM-free.
- **Typed search (`session_mine(search, kind=...)`)**: every search hit is now classified by kind (`decision`/`next-step`/`error`/`narration`) using regex, no LLM. Pass `kind` to filter results to one type.
- **MCP tool annotations**: all 19 MCP tools carry `readOnlyHint`/`idempotentHint`/`title`/`openWorldHint` annotations. 10 read-only analysis tools are marked read-only + idempotent; write-capable tools are marked accordingly; all are local (`openWorldHint=false`). Allows MCP clients and Claude Code's permission system to skip prompts on read-only calls.
- **Consolidation hardening + re-date/down-rank migration**: memory consolidation is more conservative; a background migration re-dates and down-ranks over-promoted entries produced by prior aggressive runs.
- **Memory age at injection**: pre-edit hook output now shows each injected memory's age alongside its score, so Claude can weight stale memories appropriately.
- **Per-project HANDOFF.md + `checkpoint_list` scoping**: `checkpoint_save` writes HANDOFF.md to the project directory (not only global checkpoints/); `checkpoint_list` is scoped to the active project and hides entries older than 7 days by default.

### v0.5.0 (2026-05-28)

- **Durable session handoffs** replace the single overwritable `latest_handoff.json` slot with a capped ring buffer (`handoff_history.json`, last 20)
  - Promotion guard: a trivial auto-handoff (no files edited, no decisions) never overwrites a substantive or manual handoff; manual handoffs always win
  - `kind: manual|auto` marker on every handoff
  - Walk-up read resolution: nearest project first, ancestors next, global slot last, so a sub-project's handoff is no longer shadowed by the shared global slot
  - New `handoff_list` operation + `index` parameter on `handoff_get` to list and retrieve older handoffs (index 0 = latest, then newest-first)
  - The three handoff writers (`create_handoff`, Stop hook, PreCompact hook) now share one `handoff_store` module
  - Backward compatible: `latest_handoff.json` is kept in sync; an existing slot is seeded into history on first write (old/downgraded clients keep working)
- **Path-aware mistake relevance**: a shared basename across diverging paths (e.g. `service-a/.../__init__.py` vs `service-b/.../__init__.py`) is no longer treated as a match; generic basenames (`__init__.py`, `index.js`, …) require a full-path signal. Stops cross-version/cross-project mistakes firing on unrelated edits while preserving real matches
- **Actionable recurring errors**: pattern detection groups by a normalized signature (exception class + message with names/paths/numbers templated) instead of the bare exception class. `patterns.json` refreshes on the next mining pass
- **Fixes**: empty `<engram-error></engram-error>` tag suppressed; `last_message_preview` dropped from handoffs; `handoff_get` no longer prints the summary twice; `checkpoint_list` hides checkpoints older than 7 days (opt-in prune)
- **`extract_file_refs` fix.** It used a *capturing* group, so `re.findall` returned only the extension and silently dropped every path, storing basenames only. This was the root data cause of cross-version false positives (`related_files` never carried directory context). Now captures full/relative paths
- **Automatic, idempotent migrations**: on upgrade a version-stamped migration (run from the SessionStart hook and `install.py`, tracked in `manifest.migrations_applied`) seeds handoff history from the old single-slot file and, off the hook hot path, re-extracts `related_files` to full paths for existing memories. Forward-only, safe to re-run, downgrade-safe, no re-mine
- **Versioning**: `pyproject` version corrected (had lagged at 0.2.0 through the 0.3.x to 0.4.x feature work)
- New benchmarks: `bench_handoff_durability.py`, `bench_path_relevance.py`

### v0.4.0 (2026-04-08)

- **Session mining platform**: automatically mines Claude Code session JSONL logs for intelligence
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
- **Batch embedding protocol**: `embed_batch` in scorer server, 22x faster than individual calls
- **`session_mine` MCP tool**: 13 operations (search, decisions, replay, predict, cross_project, etc.)
- **`/engram` skill**: slash command installed to `~/.claude/commands/`
- **Smart session start**: shows last session context + recurring patterns
- **Obsidian vault compatibility** verified (25/25 benchmark with PARA + CLAUDE.md structure)

### v0.3.0 (2026-04-07)

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

### v0.2.0 (2026-04-04)

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

### v0.1.0 (initial release)

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
| MCP | Model Context Protocol, how Claude Code communicates with tool servers |
| Compaction | When Claude Code compresses conversation context to fit token limits |
| Handoff | Structured document for session-to-session continuity |
| Checkpoint | Saved task state (steps done, pending, files involved) |

## Links

- [Repository](https://github.com/20alexl/claude-engram)
- [Issue Tracker](https://github.com/20alexl/claude-engram/issues)
- [Project Book Template](https://github.com/20alexl/project-book-template)

---

[← Back to Table of Contents](./README.md)

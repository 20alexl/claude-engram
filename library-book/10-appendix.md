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
| `embed_all` | — | Generate embeddings for all memories |
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

> The `loop` tool was removed in v0.8.0. Loop detection is hook-automatic: edits and test results are tracked in per-session hook state by the PreToolUse/PostToolUse hooks, which warn on real spirals (repeat edits with failing tests). There is no agent-callable loop op.

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
| `check` | `project_path`, `code_or_filename` | Deterministic pattern check against stored conventions (no LLM) |
| `remove` | `project_path`, `rule` | Remove by matching text |

> The `output` tool (`validate_code` / `validate_result`) was removed in v0.8.0. Its inline checks are covered by `audit_batch`'s inline mode (`code` + `language`).

### Standalone Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `scout_search` | `query`, `directory`, `max_results?` | Semantic codebase search (uses Ollama when available) |
| `file_summarize` | `file_path` | Structural summary (purpose, exports, dependencies, complexity) — pattern-based, no LLM |
| `deps_map` | `file_path` or `symbol`, `project_root?`, `include_reverse?` | Map a file's dependencies, or locate a symbol (file, signature, importers) via the code index |
| `impact_analyze` | `file_path`, `project_root`, `proposed_changes?` | Change impact analysis |
| `audit_batch` | `file_paths`+`min_severity?` (files) · or `code`+`language?` (inline) | Audit files or lint a snippet for AI-slop patterns — pure regex/AST, no LLM |
| `find_similar_issues` | `issue_pattern`, `project_path`, `file_extensions?`, `exclude_paths?` | Search for bug patterns — pure regex/AST, no LLM |

> `scout_analyze` was removed in v0.8.0 (zero recorded use — the agent reads code better than a 12B commentary pass).

### MCP Tool Annotations

All 16 MCP tools carry MCP annotations (`readOnlyHint`, `idempotentHint`, `title`, `openWorldHint`). 8 read-only analysis tools (`claude_engram_status`, `pre_edit_check`, `scout_search`, `file_summarize`, `deps_map`, `impact_analyze`, `find_similar_issues`, `audit_batch`) are marked `readOnlyHint=true` and `idempotentHint=true`. Operation-enum tools that bundle reads and writes under one name (e.g. `memory`, `session_mine`, `scope`, `context`) are marked `readOnlyHint=false`. All tools are local (`openWorldHint=false`). MCP clients and Claude Code's permission system use these annotations to skip confirmation prompts on read-only calls.

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
| `CLAUDE_ENGRAM_DIR` | `str` | `~/.claude_engram` | Storage location override (also the supported test-isolation seam) |
| `CLAUDE_ENGRAM_MODEL` | `str` | `gemma3:12b` | Ollama model name (optional LLM — `scout_search`, `memory(consolidate)`, `session_mine(reflect)`) |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `str` | `http://localhost:11434` | Ollama API URL (optional LLM) |
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

### v0.8.4 — 2026-06-11

- **Curated-lessons bridge (opt-in).** Dated entries (`YYYY-MM-DD — insight`) in user-curated note files sync as protected `lesson` memories — never archived, decayed, or deduped (the file owns the lifecycle: edits update, removals retire), +0.25 injection bonus, and code-index-joined triggers: a lesson naming a module gains `related_files` = the files importing it, so it surfaces exactly when that code is touched. Strictly opt-in via `config.json` `lessons_globs` (e.g. `["docs/lessons/*.md"]`); the tool ships no default path and never guesses which markdown is a lessons file.
- **Pattern banner is project-scoped and recency-decayed.** Recurring errors carry `projects` (attributed from the contributing sessions' edited files) and `last_seen`; the session-start banner filters to the sub-projects the last session touched, and errors quiet for 30 days drop out of the report entirely. Struggles are scoped by their (now full) paths.
- **Struggles metric made causal.** Full-path keys (no more basename pooling across projects) and `errors_nearby` counts only sessions where an extracted mistake actually references the file (via `related_files` or a traceback mention). Files with zero attributable errors are not struggles.
- **TDD-aware mistake capture.** Failing test invocations (`pytest`, `npm test`, `python tests/...`, suite-marker outputs) are tracked as test FAILs but never auto-logged as mistakes — RED-phase failures are deliberate. Shared `_is_test_invocation()` across both bash handlers.
- **Migration `0.8.4:modernize_mistake_store`** (automatic on next SessionStart / install): legacy in-place `archived_at` flags move into archive.json for real, and machine-written mistakes provably fixed against the current code index (missing module now resolves, missing attribute now exists on that class) are archived. Never deletes; never touches manual `log_mistake` entries.
- **Stale-mistake hygiene now covers `session_mining`.** The 0.8.1 gate only matched `auto-detected` — 18 of 282 mistakes on the reference store; the transcript miner stamps `session_mining`. Both are machine-written. Live effect with the migration: 282 → 71 hot mistakes, all restorable.
- **Decision capture stores full sentences** (word-boundary cut at 300; banner display word-boundary at 200) instead of a hard 150-char slice mid-word.
- **Honest activity counts.** New `prompt_count` (real typed prompts) alongside `user_message_count` (every type=user line, incl. tool results — semantics preserved for the re-mine watermarks). The banner now reads "N prompts" / "N tool errors".
- **Rule banners deduped against CLAUDE.md.** A rule whose significant words are ≥70% covered by the project's CLAUDE.md is suppressed from session-start/post-compact display (still enforced, still listable) — ends the triple CLAUDE.md / rules / MEMORY.md injection.
- **Fix: Windows memory-embeddings save.** `embed_all_memories` kept the loader's live mmap of embeddings.npy while saving to the same path — Errno 22, silently freezing memory-embedding updates on Windows. Handle dropped after copying rows.

### v0.8.3 — 2026-06-11

- **GPU policy split — cpu-resident daemon, transient GPU worker.** The v0.8.2 resident-GPU default parked model weights plus a CUDA context (~1GB VRAM) for the daemon's entire lifetime, and live-mining ticks keep the daemon warm all day — indistinguishable from a VRAM leak in practice. Device policy is now: resident consumers (scorer daemon, in-process fallbacks) always load on cpu; bulk embedding jobs of `CLAUDE_ENGRAM_GPU_BULK_MIN`+ texts (default 512 — bootstrap re-embeds, model-change rebuilds, store sweeps) run in `claude_engram.embed_worker`, a short-lived process that loads on cuda, encodes one job, writes `.npy`, and exits. Process exit fully releases the CUDA context — the GPU is borrowed for seconds, never parked. The worker declines (and the caller falls back to the daemon) when no GPU exists. `CLAUDE_ENGRAM_DEVICE` remains a global override in both directions. Measured: cuda/cpu vectors identical at cos 1.000000, so device changes never rebuild stores; daemon RSS 1.2GB (cuda) → 680MB (cpu), VRAM 0.
- **In-process fallback model cached.** The daemon-down fallback in `score_decision_semantic` loaded a fresh model per call; now one cached load per process, on cpu.
- **Single-instance daemon startup.** `serve()` exits immediately when a live, signature-matching server already owns `PORT_FILE`, closing the two-session spawn race that left an orphan daemon holding a loaded model for up to 30 minutes.

### v0.8.2 — 2026-06-11

- **GPU embeddings, auto-detected.** `load_sentence_transformer()` resolves the device once: `CLAUDE_ENGRAM_DEVICE` override, else `cuda` when a CUDA-enabled torch is present, else cpu — and a broken CUDA runtime degrades to cpu instead of killing the scorer. The device is deliberately not part of the embedding signature (cuda and cpu produce identical vectors), so switching devices never rebuilds stores. `embed_batch` runs batch 256 on GPU / 64 on CPU; the scorer writes a `scorer_device` breadcrumb that `claude_engram_status` reports.
- **Live mining ticks — engram stays fresh during the session.** The Stop hook fires a debounced (`CLAUDE_ENGRAM_LIVE_MINE`, default 300s) background mine in the new `live` mode: session index, extraction, search embeddings, and the two most-recent code indexes — every phase cursor/watermark-incremental, so each tick costs only the new transcript tail. Cross-session search and `replay`/`predict` now see the running session's earlier turns; previously everything waited for SessionEnd.
- **Decision-gate retune for bge-base.** `AMBIGUITY_MARGIN` 0.05 → 0.025 (the old value was tuned on MiniLM): semantic F1 72.7% → 76.9%, combined 77.4% → 79.0% on the 220-prompt bench. Recall +10.8 for precision -3.8 — lost decisions are unrecoverable, noise captures get deduped, so the recall side wins. `DECISION_THRESHOLD` measured as a dead knob below 0.575 (the `score >= 0.45` capture cutoff already implies sim >= 0.525) and left at 0.45.

### v0.8.1 — 2026-06-11

- **Error deja-vu at failure time.** PostToolUseFailure now matches the fresh error against mined recurring errors (`patterns.json`) and the hot mistake store, and injects the past fix inline: `Deja vu: TypeError hit in 3 past session(s) - fix: ...`. Template matching reuses the miner's signature normalization, guarded by quoted-identifier overlap (an unrelated class never inherits someone else's fix); class-less failures (Edit conflicts, CLI errors) match manual mistakes by word overlap. Runs before auto-log so it can't match itself.
- **Symbol lookup via `deps_map(symbol="X")`.** Answers "where is X defined?" from the background code index: defining file, signature (`__init__` + method list for classes), dotted module, and reverse-import blast radius. Typo-tolerant (closest-name suggestion). No grep, no LLM, no build.
- **Sub-project code indexes no longer go stale.** The miner only built the mined project's index, and the workspace walk prunes nested project dirs — in workspace setups, sub-project indexes (read by precheck, blast-radius, read-context, and the new symbol lookup) silently froze. Miner phase 6 now also refreshes every sub-project edited in the last ~10 sessions (incremental, mtime-keyed, cheap).
- **Mistake hygiene.** Auto-captured mistakes that never recurred — 3+ weeks old, signature absent from mined recurring errors, no overlap with recently-edited files — are moved to the archive by miner phase 5. Manual `log_mistake` entries and rules are never touched. Archived mistakes stay searchable (`archive_search`) and restorable (`restore`).
- **Fix: `archived_at` is now honored by hook readers.** `acknowledge_mistake` set the flag but hot readers and banner counters never filtered it, so acknowledged mistakes kept appearing in pre-edit warnings. Hook readers now skip archived entries, and `acknowledge_mistake` performs a real move into `archive.json` (restorable) instead of an in-place flag.
- **Known-good test commands.** Test invocations the bash hooks already classify as test runs are tracked per project with pass/fail counts (`test_commands.json`, capped at 30). Session start surfaces the top currently-passing commands. Inline `python -c`, heredocs, `.scratch` scripts, and 160+ char contraptions are never recorded; a command whose latest run failed drops out until it passes again.

### v0.8.0 — 2026-06-10

- **Tool surface trimmed (19 → 16).** Removed `loop` (loop detection is hook-automatic and per-session now), `output` (its `validate_code`/`validate_result` checks are covered by `audit_batch`'s inline mode), and `scout_analyze` (zero recorded use). The remaining 16: `claude_engram_status`, `session_start`, `session_end`, `pre_edit_check`, `memory`, `work`, `scope`, `context`, `convention`, `scout_search`, `file_summarize`, `deps_map`, `impact_analyze`, `find_similar_issues`, `audit_batch`, `session_mine`.
- **LLM role narrowed — Ollama is now an optional flavor.** It is used only by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently without it), plus `scout_search` when available. Everything proactive — hooks, code index, precheck, blast-radius, injection scoring — is LLM-free.
- **`convention(check)` is now a deterministic pattern check** against stored conventions (the LLM mode was removed: its "no check-mark means violation" heuristic was a false-positive machine with zero recorded use).
- **`file_summarize` is structural only** — the `mode` parameter and the LLM "detailed" mode are gone. It returns purpose, exports, dependencies, and a complexity estimate from pattern/structure analysis.
- **`audit_batch` and `find_similar_issues` are pure regex/AST** — no LLM, no network (they never were; the docs are now explicit).
- **Loop-detection state is per-session.** Edit counts and test results live in the session's hook state (`sessions/<sid>.json`), not the shared `~/.claude_engram/loop_detector.json` — two concurrent sessions no longer cross-contaminate. The old `loop_detector.json` is abandoned (harmless if present).
- **Pre-edit no longer records file edits** (only post-edit does), so denied or failed edits aren't counted toward the loop threshold.
- **Session-mining merge + per-phase error isolation.** A session that grows after being indexed (PreCompact then SessionEnd) now MERGES counts instead of resetting them; each miner phase is error-isolated and `mining_status.json` records which phase failed (`phase_errors`).
- **Auto-logged mistakes/decisions in a brand-new project are no longer dropped** — the project is auto-registered in the manifest first.
- **New env var `CLAUDE_ENGRAM_DIR`** overrides the storage location (default `~/.claude_engram`) and is the supported test-isolation seam.
- **`memory(embed_all)` fixed** — it crashed with a `NameError` since the args rename; it now reads its `force` flag from the call args.
- **Pre-edit hook ~2x faster** (~400ms → ~220ms median): stdlib-only `hooks/hot_reader.py` scoring path, lazy `tools/__init__`, one `memory.json` parse per hook, banner dedup.
- **Configurable embedding model** via `CLAUDE_ENGRAM_EMBED_MODEL` / `CLAUDE_ENGRAM_EMBED_DIM` (or `config.json`). Every embedding store is signature-stamped (`model@dim`) and rebuilds on model change; unstamped legacy stores read as the pinned `LEGACY_SIGNATURE` (`all-MiniLM-L6-v2@native`).
- **Default encoder is `BAAI/bge-base-en-v1.5`** — ungated (no HF account/token; `embeddinggemma` was evaluated and reverted: license-gated, ~3.3GB scorer RSS). Decision-capture semantic F1 at shipped thresholds: MiniLM 37.7% → bge-base 72.7%; live combined capture 77.4%. MiniLM remains the one-line ~90MB lightweight option.
- **Session-search embeddings are sharded by month** (`session_embeddings/<YYYY-MM>.npy`) instead of one ever-growing matrix fully rewritten at every session end; v1 stores migrate automatically. Optional `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` prunes old months.
- **Append-aware re-mining.** Sessions that grow after indexing contribute their new tail to search embeddings (per-file watermarks) and are re-extracted for decisions/mistakes — previously they were skipped as already-seen.
- **JSONL schema canary.** The miner tracks what fraction of session-log lines it recognizes; a collapse vs the historical baseline warns at session start instead of degrading mining silently.
- **Hook daemon.** The scorer server doubles as a warm hook dispatcher; high-frequency hooks are thin `python -S` clients (one TCP round trip, in-daemon ~15-25ms, full in-process fallback). Heaviest hook measured 313ms → 216ms median on Windows; Linux gains more.
- **Proactive recall before Read** — `<engram-read-context>` with code-index orientation + the file's most relevant memories, once per file per session. Optional `CLAUDE_ENGRAM_LAST_FILE_PATH` statusline mirror.
- **Outcome feedback loop closed.** Per-kind injection pass-rate lift becomes a bounded (0.8-1.2x) multiplier on the memory-injection relevance gate (miner-computed `injection_weights.json`).
- **Isolated-storage daemons.** `scorer_port`/`scorer_pid`/`scorer_model` and the decision-template cache honor `CLAUDE_ENGRAM_DIR`.
- **MCP launch hardening** — `install.py` points `.mcp.json` straight at the venv python instead of the `.bat` wrapper.
- **No emojis in any output.**

### v0.7.1 — 2026-06-02

- **Fix: `checkpoint_restore` / `checkpoint_list` could seat a stale checkpoint at index 0.** A sub-project query (e.g. `myproject/service-c`) walks up to ancestor rings; `read_latest` returned the *first* candidate ring's `latest_handoff.json` regardless of age, so a weeks-old handoff could occupy index 0 while the genuine latest sat lower — an autonomous resume trusting index 0 could act on the wrong plan. Restore now selects the newest **deliberate (manual)** checkpoint across the resolved scope: a newer manual outranks an older one (kills the stale win), and a routine auto session-stop never buries a deliberate checkpoint; it falls back to newest-of-any-kind only when no manual is in scope. `read_history` now folds each ring's `latest` pointer into the merged view (a legacy single-slot handoff is never missed), and `read_ordered` pins this corrected latest at index 0, so `checkpoint_restore index=0` == `checkpoint_list[0]` == `get_by_index(0)`. Read-path only — no migration; existing rings are re-interpreted correctly. New regression test: `tests/bench_restore_recency_scope.py`.

### v0.7.0 — 2026-06-01

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
- **Path-aware mistake relevance** — a shared basename across diverging paths (e.g. `service-a/.../__init__.py` vs `service-b/.../__init__.py`) is no longer treated as a match; generic basenames (`__init__.py`, `index.js`, …) require a full-path signal. Stops cross-version/cross-project mistakes firing on unrelated edits while preserving real matches
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

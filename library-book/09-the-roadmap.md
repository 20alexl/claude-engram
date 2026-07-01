# Chapter 9 — The Roadmap

[← Back to Table of Contents](./README.md) · [Previous: Contributing](./08-contributing.md) · [Next: Appendix →](./10-appendix.md)

---

## Current State

| Feature | Status | Since |
|---------|--------|-------|
| Hook-based auto-tracking (edits, tests, errors) | Stable | v0.1.0 |
| MCP memory tools (remember, recall, search, etc.) | Stable | v0.1.0 |
| Loop detection | Stable | v0.1.0 |
| Scope guard | Stable | v0.1.0 |
| Context guard (checkpoints, handoffs) | Stable | v0.1.0 |
| Convention tracking | Stable | v0.1.0 |
| Scout search (LLM semantic search) | Stable | v0.1.0 |
| Tiered memory (hot/archive) | Stable | v0.2.0 |
| Memory scoring + smart injection | Stable | v0.2.0 |
| PostToolUseFailure hook (all tools) | Stable | v0.2.0 |
| PreCompact/PostCompact hooks | Stable | v0.2.0 |
| SessionStart/SessionEnd/Stop hooks | Stable | v0.2.0 |
| Semantic decision capture (AllMiniLM) | Stable | v0.2.0 |
| Persistent scorer server | Stable | v0.2.0 |
| Multi-project workspace support | Stable | v0.2.0 |
| Merge-safe hook installation | Stable | v0.2.0 |
| Per-project storage (manifest + hash dirs) | Stable | v0.3.0 |
| Binary numpy embeddings (mmap) | Stable | v0.3.0 |
| Typo normalization in decision capture | Stable | v0.3.0 |
| Session mining (JSONL parsing + extraction) | Stable | v0.4.0 |
| Cross-session semantic search | Stable | v0.4.0 |
| Batch embedding protocol (22x faster) | Stable | v0.4.0 |
| Pattern detection (struggles, recurring errors) | Stable | v0.4.0 |
| Predictive context before edits | Stable | v0.4.0 |
| Cross-project learning | Stable | v0.4.0 |
| Retroactive bootstrap (mine existing history) | Stable | v0.4.0 |
| `/engram` skill (slash command) | Stable | v0.4.0 |
| Durable handoffs (ring buffer, promotion guard, walk-up) | Stable | v0.5.0 |
| `handoff_list` + `handoff_get` index | Stable | v0.5.0 |
| Path-aware memory relevance (`file_match`) | Stable | v0.5.0 |
| Recurring error grouping by normalized signature | Stable | v0.5.0 |
| Idempotent version-stamped migrations | Stable | v0.5.0 |

## Done / Shipped (v0.6)

| Feature | Notes |
|---------|-------|
| Tool surface consolidation (21 → 19) | Removed `code_pattern_check` (dup of `convention`); folded `code_quality_check` into `audit_batch` (file-paths mode vs inline code/language mode); `instruction_*` context ops removed (use `memory add_rule`); `checkpoint_*` are now primary, `handoff_*` are deprecated aliases. |
| Per-project code index (`mining/code_index.py`) | Miner Phase 6. AST/regex symbol table per project: exports, classes, methods+signatures, imports, reverse-dependency edges. Sub-project scoped, mtime-incremental, LLM-free. |
| Pre-edit import/export verification (`hooks/precheck.py`) | Capability 1. Warns before an edit if an import won't resolve against the code index; suggests the closest valid name. Advisory, Python-only, conservative (stays silent on anything it can't verify with high confidence). |
| Blast-radius on pre-edit | Capability 4. Lists all importers of a shared module before an edit; `impact_analyze` reads this cache instead of scanning cold. |
| Outcome feedback loop (`mining/outcomes.py`) | Capability 6. Logs injection kinds (memory/prediction/precheck/blast) + following test pass/fail; `session_mine(reflect)` surfaces injection precision and LLM-synthesized insights. |
| Hybrid search auto-refresh (miner Phase 5) | `memory(hybrid_search)` no longer requires a prior `embed_all` — the miner auto-refreshes embeddings. |

## Done / Shipped (v0.8)

| Feature | Notes |
|---------|-------|
| Tool surface trimmed (19 → 16) | Removed `loop` (loop detection is hook-automatic and per-session), `output` (its `validate_code`/`validate_result` checks are covered by `audit_batch`'s inline mode), and `scout_analyze` (zero recorded use). |
| Ollama is now optional | Used only by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently) plus `scout_search` when available. Everything proactive — hooks, code index, precheck, blast-radius, injection scoring — is LLM-free. |
| `convention(check)` made deterministic | Pattern check against stored conventions; the LLM mode (a false-positive machine) was removed. |
| `file_summarize` is structural only | The `mode` parameter and the LLM "detailed" mode were removed — purpose/exports/deps/complexity from structure analysis. |
| `audit_batch` / `find_similar_issues` documented as LLM-free | Pure regex/AST, no network (they always were; now the docs say so). |
| Per-session loop-detection state | Edit counts and test results moved from the shared `loop_detector.json` to `sessions/<sid>.json`; two concurrent sessions no longer cross-contaminate. The old file is abandoned (harmless). |
| Pre-edit no longer records edits | Only post-edit records, so denied/failed edits aren't counted toward the loop threshold. |
| Session-mining robustness | A session that grows after indexing (PreCompact then SessionEnd) MERGES counts instead of resetting; miner phases are error-isolated and `mining_status.json` records which phase failed (`phase_errors`). |
| New-project auto-registration | Auto-logged mistakes/decisions in a brand-new project are no longer dropped — the project is registered in the manifest first. |
| `CLAUDE_ENGRAM_DIR` env var | Overrides the storage location (default `~/.claude_engram`); also the supported test-isolation seam. |
| `memory(embed_all)` fix | Crashed with a `NameError` since the args rename; now reads `force` from the call args. |
| Configurable embedding model | `CLAUDE_ENGRAM_EMBED_MODEL` / `CLAUDE_ENGRAM_EMBED_DIM` (or `config.json`). All embedding stores are signature-stamped (`model@dim`) and rebuild on model change — vector spaces are never mixed. |
| Default encoder → `BAAI/bge-base-en-v1.5` | Ungated (no HF account or token), ~440MB on first use. Decision-capture semantic F1 measured at fixed thresholds: `all-MiniLM-L6-v2` 37.7%, `embeddinggemma-300m@256` 67.3% (license-gated), `bge-small-en-v1.5` 70.7%, `bge-base-en-v1.5` 72.7%. MiniLM stays one config line away for low-RAM setups. |
| Pre-edit hook ~2x faster | ~400ms to ~220ms median: stdlib-only `hooks/hot_reader.py`, lazy `tools/__init__`, one memory.json parse per hook, and banner dedup (a mistake no longer appears in two sections). |
| MCP launch hardening | `install.py` points `.mcp.json` straight at the venv python instead of the `.bat` wrapper (fewer process layers between the host and the server under load). |
| Sharded session-search embeddings | Monthly `.npy` shards replace the single ever-growing matrix (an 80MB+ full rewrite at every session end); v1 stores migrate automatically; optional `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` pruning. |
| Append-aware re-mining | A session that grows after indexing (PreCompact then SessionEnd, or resumed days later) now contributes its new tail to search embeddings (per-file watermarks) and is re-extracted for decisions/mistakes. Previously grown sessions were skipped as already-seen. |
| JSONL schema canary | The miner tracks what fraction of log lines it recognizes; a collapse vs the historical baseline (a Claude Code log-format change) warns at session start instead of degrading silently. |
| Hook daemon | The scorer server doubles as a warm hook dispatcher; high-frequency hooks become thin `python -S` clients (one TCP round trip, in-daemon ~15-25ms) with a full in-process fallback. Heaviest hook measured 313ms → 216ms median on Windows; Linux gains more (cheaper process spawn). |
| Proactive recall before Read | `<engram-read-context>` before Read of an indexed file: code-index orientation (module, key symbols, dependents) + the file's most relevant memories. Once per file per session; subagents skipped. Optional `CLAUDE_ENGRAM_LAST_FILE_PATH` statusline mirror. |
| Outcome feedback loop CLOSED | Cap 6 graduates from measure-only: per-kind pass-rate lift becomes a bounded (0.8-1.2x) multiplier on the memory-injection relevance gate, computed by the miner, applied by the pre-edit scorer. Kinds without enough samples stay neutral. |
| Isolated-storage servers | `scorer_port`/`scorer_pid`/`scorer_model` and the decision-template cache honor `CLAUDE_ENGRAM_DIR` — tests and parallel storage roots get their own daemon instead of colliding with the real one. |
| No emojis in any output | — |

## Done / Shipped (v0.8.1)

| Feature | Notes |
|---------|-------|
| Error deja-vu | PostToolUseFailure matches the fresh error against mined recurring errors (`patterns.json` — real how-to-avoid text) and the hot mistake store, and injects the past fix inline at failure time. Template matching reuses the miner's signature normalization, guarded by quoted-identifier overlap so an unrelated class never inherits someone else's fix. |
| Symbol lookup | `deps_map(symbol="X")` answers "where is X defined?" from the code index: defining file, signature (`__init__` + methods for classes), and reverse-import blast radius. Typo-tolerant (closest-name suggestion). No grep, no LLM. |
| Sub-project code-index freshness | The miner's code-index phase only built the mined project's index, and the workspace walk prunes nested project dirs — sub-project indexes went stale forever (one real index was 13 days old; another had never been built). Phase 6 now also refreshes every sub-project edited in the last ~10 sessions. |
| Mistake hygiene | Auto-captured mistakes that never recurred (3+ weeks old, signature absent from mined recurring errors, no overlap with recently-edited files) move to the archive in miner phase 5. Manual `log_mistake` entries and rules are untouched; archived entries stay searchable and restorable. |
| `archived_at` honored by hook readers | Pre-existing bug: `acknowledge_mistake` set the flag but hook readers never filtered it, so acknowledged mistakes kept injecting. Hot readers and banner counters now skip archived entries, and `acknowledge_mistake` does a real move into `archive.json`. |
| Known-good test commands | PASS/FAIL bash test runs are tracked per project (`test_commands.json`); session start surfaces the top currently-passing commands. Throwaway shapes (inline `python -c`, heredocs, `.scratch` scripts) are never recorded; a command whose latest run failed drops out until it passes again. |

## Done / Shipped (v0.8.2)

| Feature | Notes |
|---------|-------|
| GPU embeddings (auto) | The encoder loads on `cuda` automatically when a CUDA torch is installed (`CLAUDE_ENGRAM_DEVICE` overrides; a broken CUDA runtime degrades to cpu instead of killing the scorer). Vectors are device-identical, so the device is deliberately NOT part of the embedding signature — switching never rebuilds stores. `embed_batch` uses batch 256 on GPU (64 on CPU); 512 chunks measured at ~430ms through the TCP daemon on an RTX 4070 SUPER. `claude_engram_status` reports the active device via the `scorer_device` breadcrumb. |
| Live mining ticks | The Stop hook (every turn end) spawns a debounced incremental mine (`CLAUDE_ENGRAM_LIVE_MINE`, default 300s; `0`/`off` disables): session index, extraction, search embeddings, and the two most-recent code indexes refresh DURING the session. All phases are cursor/watermark-keyed, so a tick costs the new transcript tail. `session_mine(search)` now sees this session's earlier work. Patterns and memory maintenance stay session-end work. |
| Decision-gate retune for bge-base | `AMBIGUITY_MARGIN` 0.05 → 0.025 (the 0.05 was tuned on MiniLM). Bench: semantic F1 72.7% → 76.9% (recall 66.7 → 77.5, precision 80.0 → 76.2), combined 77.4% → 79.0%. `DECISION_THRESHOLD` confirmed a dead knob below 0.575 (the capture cutoff binds first) and left at 0.45. |

## Done / Shipped (v0.8.3)

| Feature | Notes |
|---------|-------|
| GPU policy split: cpu-resident, GPU-transient | Supersedes the v0.8.2 resident-GPU default, which parked weights + a CUDA context (~1GB VRAM) on the card for the daemon's whole lifetime — and live-mining ticks keep that daemon warm all day, so it read as a VRAM leak. Now: the resident daemon and every in-process fallback stay on cpu (zero VRAM parked); bulk jobs (>= `CLAUDE_ENGRAM_GPU_BULK_MIN`, default 512 texts) run in a transient worker (`embed_worker.py`) that loads on cuda, encodes once, and exits — process exit is the only way to fully release a CUDA context. `CLAUDE_ENGRAM_DEVICE` forces one device everywhere. Verified cuda/cpu vectors identical (cos 1.000000) — device switching never rebuilds stores. |
| In-process fallback model cached | `score_decision_semantic`'s daemon-down fallback loaded a fresh SentenceTransformer per call, uncached — any long-lived process hitting it re-paid ~500ms + ~1GB per prompt (and briefly, on v0.8.2, did so on the GPU). Now cached once per process, on cpu. |
| Single-instance daemon startup | Two sessions racing to spawn the scorer left an orphan (last PORT_FILE writer wins; the loser idled 30 min holding a loaded model). `serve()` now exits immediately when a live server with the same embedding signature already owns PORT_FILE. |

## Done / Shipped (v0.8.4)

| Feature | Notes |
|---------|-------|
| Curated-lessons bridge (opt-in) | Dated entries (`YYYY-MM-DD — insight`) in user-curated note files sync as protected `lesson` memories: never archived/decayed/deduped (the file is the source of truth — edits update, removals retire), injected with a +0.25 scoring bonus, and triggered through the code index (a lesson naming a module gets `related_files` = the files importing it). STRICTLY opt-in via config.json `lessons_globs`; no default path ships. |
| Project-scoped, recency-decayed pattern banner | Recurring errors are attributed to the sub-projects whose sessions produced them and filtered at session start by what the LAST session touched — project A's session no longer opens with project B's errors. Errors unseen for 30 days drop out entirely (fixed errors used to pin the top slots forever by raw session count). |
| Struggles metric made causal | Was: basename-keyed + "the session had an error somewhere" — every often-edited file looked like a struggle ("CLAUDE.md, 4 sessions, 4 errors") and all `__init__.py` files pooled into one phantom. Now: full-path keys, and errors_nearby counts only sessions where an extracted mistake actually references the file. Zero attributable errors = not a struggle. |
| TDD-aware mistake capture | Failing test invocations are tracked as test results but no longer auto-logged as mistakes — deliberate RED-phase failures (ModuleNotFoundError before implementing, expected assertion fails) were drowning the mistake store. Real bugs that only manifest in tests keep failing and surface via the transcript miner. |
| Mistake-store modernization (migration `0.8.4`) | One-time, automatic, archive-never-delete: (1) legacy in-place `archived_at` flags move into archive.json for real; (2) machine-written mistakes PROVABLY fixed against the current code index (module now resolves / class now has that attribute) are archived. Manual `log_mistake` entries untouched. |
| Hygiene gate widened to `session_mining` | The 0.8.1 stale-mistake hygiene only matched `source="auto-detected"` — but 90%+ of real stores are miner-stamped `session_mining`. Both are machine-written; both now age out. Live effect on the reference store: 282 → 71 hot mistakes (all archived, restorable). |
| Decision capture: word-boundary cuts | Decisions were stored sliced at 150 chars mid-word ("well probaly do all if i..."). Capture now keeps the full matched sentence to 300 chars cut at a word boundary; banner displays cut at 200 the same way. |
| Honest activity counts | "893 prompts" counted every `type=user` JSONL line — in Claude Code logs every tool result is one. New `prompt_count` field counts real typed prompts (`user_message_count` keeps its semantics: the append-aware re-mine watermarks compare it); banner shows "N prompts" / "N tool errors". |
| Rule banner deduped vs CLAUDE.md | Rules whose content is already in the project's CLAUDE.md (in context every turn) are suppressed from session-start and post-compact banners — ends the CLAUDE.md / engram-rules / MEMORY.md triple-injection. Rules remain enforced and listable. |
| Windows embeddings-save fix | `embed_all_memories` held the live mmap returned by the loader while `np.save` targeted the same embeddings.npy — Errno 22 on Windows, silently freezing memory-embedding updates once a store had both existing vectors and pending work. The mmap handle is dropped after rows are copied. |

## Done / Shipped (v0.8.5)

| Feature | Notes |
|---------|-------|
| History ring is deliberate-checkpoints-only | Autos (per-turn Stop, pre-compact snapshots) now contend ONLY for the latest pointer — they never enter the 20-slot ring, so they can't evict manual checkpoints (Stop fires every turn; the ring filled with "Session stopped" within one working session). The newest auto stays restorable via the pointer fold-in; the legacy single-slot seed still migrates on any write. |
| Teaser resolves the RIGHT ring | The SessionStart CHECKPOINT teaser and `checkpoint_restore` used the same selector but read different rings: autos were written to the cwd (workspace root) ring while manual saves went to the sub-project ring, and the candidate walk only goes up. Now: on **resume**, the teaser resolves the project from THIS session's own edited files (concurrency-safe — never "last session"); on a **fresh** start it surfaces the newest MANUAL across the workspace subtree as a labeled breadcrumb, else falls back to the walk-up. |
| Stop/pre-compact write to the file-resolved project ring | Auto handoffs land in the ring of the sub-project the session actually worked in (majority vote over recent edited files), not the cwd. |
| Manual checkpoints exempt from the 48h teaser cutoff | A deliberate handoff now gets 14 days in the teaser (restore always found it; the teaser silently dropped it over a weekend). Autos keep 48h. |
| Teaser label is self-identifying | `CHECKPOINT [manual, 2.1h ago, grommet, task_1782849358]` — kind + project + task_id, so the model can `checkpoint_restore(task_id=…)` exactly what was teased, and a cross-project breadcrumb is obviously not yours. |
| Subagent stop guard | A hook stop carrying `agent_id` no longer writes the parent project's ring (insurance — engram registers only Stop, but background agents may fire it). |
| `get_state_file` honors `CLAUDE_ENGRAM_DIR` | The per-session hook-state path was the one storage path still hardcoded to `~/.claude_engram`, breaking the documented test-isolation seam. |

## What's Next

- [ ] **Formal test suite** — pytest tests for memory, scoring, archiving, hooks, and sub-project resolution. Partially addressed: `bench_handoff_durability.py`, `bench_path_relevance.py`, `bench_migrations.py`, and others in `tests/` cover key behaviors, but full pytest coverage with fixtures and CI integration is still pending.
- [ ] **Split `remind.py`** — At ~2800 lines, it works but is hard to maintain. Split into `hooks/prompt.py`, `hooks/edit.py`, `hooks/bash.py`, etc.
- [ ] **Ollama-powered session summaries** — Use local LLM to generate human-readable session summaries instead of metadata-only.
- [ ] **Obsidian export** — Export session insights, decisions, and project timelines as Obsidian-compatible markdown with wikilinks.
- [ ] **Multi-language symbol indexing** — Extend code index beyond Python (tree-sitter for JS/TS/Rust/Go). Currently Python-only (ast).

## What's Aspirational

- **Team memory sync** — Share rules and mistakes across team members via git-tracked memory files. Not clear yet how to scope this without leaking personal context.
- **Memory visualization** — A simple web UI showing memory clusters, scoring, and archive status. Would help debug injection behavior.
- **Smarter archiving** — LLM-powered archive decisions: "should this memory be archived or is it still relevant?" Currently uses simple age + access heuristics.
- **Knowledge graph** — Lightweight graph connecting files, concepts, decisions, and errors. Queryable for "what's related to X?"

## What Was Deliberately Left Out

| Feature | Why Not |
|---------|---------|
| Cloud storage | Claude Engram is privacy-first. All data stays local in `~/.claude_engram/`. |
| Database backend (SQLite, Redis) | Adds dependencies. JSON files work for the scale we target (<1000 memories per project). |
| GUI / web dashboard | Out of scope. This is a library, not an app. |
| Python 3.9 support | 3.10+ for `match/case`, `X | Y` type unions, and cleaner code. |
| Auto-memory from Read/Grep tool output | Too noisy. Every file read would create a memory. Targeted capture (errors, decisions, edits) is the right granularity. |
| Real-time collaboration | Memory is per-machine. Multi-user would need conflict resolution, access control, and a server. Different project. |

## Versioning and Stability

Claude Engram follows semantic versioning:
- **Patch** (0.2.x): Bug fixes, hook improvements, scoring tuning
- **Minor** (0.x.0): New features, new hook events, memory system changes
- **Major** (x.0.0): Breaking changes to memory format or MCP tool signatures

The `manifest.json` format includes a `version` field (currently v3). Migrations from older single-file formats happen automatically on first load.

---

[Next: Appendix →](./10-appendix.md)

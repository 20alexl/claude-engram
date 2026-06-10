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
| Configurable embedding model | `CLAUDE_ENGRAM_EMBED_MODEL` / `CLAUDE_ENGRAM_EMBED_DIM` (or `config.json`). All embedding stores are signature-stamped (`model@dim`) and rebuild on model change — vector spaces are never mixed. Decision-capture semantic F1 measured 36.9% (MiniLM) vs 67.3% (`embeddinggemma-300m@256`). |
| Pre-edit hook ~2x faster | ~400ms to ~220ms median: stdlib-only `hooks/hot_reader.py`, lazy `tools/__init__`, one memory.json parse per hook, and banner dedup (a mistake no longer appears in two sections). |
| MCP launch hardening | `install.py` points `.mcp.json` straight at the venv python instead of the `.bat` wrapper (fewer process layers between the host and the server under load). |
| No emojis in any output | — |

## What's Next

- [ ] **Formal test suite** — pytest tests for memory, scoring, archiving, hooks, and sub-project resolution. Partially addressed: `bench_handoff_durability.py`, `bench_path_relevance.py`, `bench_migrations.py`, and others in `tests/` cover key behaviors, but full pytest coverage with fixtures and CI integration is still pending.
- [ ] **Split `remind.py`** — At ~2800 lines, it works but is hard to maintain. Split into `hooks/prompt.py`, `hooks/edit.py`, `hooks/bash.py`, etc.
- [ ] **Ollama-powered session summaries** — Use local LLM to generate human-readable session summaries instead of metadata-only.
- [ ] **Obsidian export** — Export session insights, decisions, and project timelines as Obsidian-compatible markdown with wikilinks.
- [ ] **Multi-language symbol indexing** — Extend code index beyond Python (tree-sitter for JS/TS/Rust/Go). Currently Python-only (ast).
- [ ] **Proactive recall before Read** — Inject relevant memories before Read/Grep tool calls, not just before edits. Requires a PreToolUse Read hook (not yet implemented).

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

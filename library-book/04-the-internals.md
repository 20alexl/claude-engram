# Chapter 4 — The Internals

[← Back to Table of Contents](./README.md) · [Previous: Quick Start](./03-quick-start.md) · [Next: Usage Guide →](./05-usage-guide.md)

---

## Architecture

```
Claude Code
    │
    ├── Hooks (remind.py + precheck.py)      ← Intercepts tool calls
    │   ├── UserPromptSubmit                     → auto-capture decisions
    │   ├── PreToolUse Edit/Write                → inject memories, precheck imports,
    │   │                                          blast-radius banner, loop check
    │   ├── PostToolUse Bash/Edit/Write          → track edits, tests, search spirals
    │   ├── PostToolUseFailure (all tools)       → auto-log errors as mistakes
    │   ├── SessionStart / SessionEnd / Stop     → lifecycle management
    │   └── PreCompact / PostCompact             → checkpoint + re-inject context
    │
    ├── MCP Server (server.py → handlers.py)  ← Tools for manual operations (16)
    │   ├── memory, work (log_mistake, log_decision)
    │   ├── scope, context, convention
    │   ├── audit_batch (file mode + inline mode — both pure regex/AST)
    │   └── scout_search, file_summarize, deps_map, impact_analyze, find_similar_issues, session_mine
    │
    ├── Scorer Server (scorer_server.py)      ← Persistent AllMiniLM process
    │   └── TCP localhost, ~90MB RAM, ~5-25ms per score, batch embedding
    │
    ├── Session Mining (mining/)              ← Background intelligence from session logs
    │   ├── JSONL parser, session index, incremental cursors
    │   ├── Structural + semantic extractors (decisions, mistakes, approaches)
    │   ├── Cross-session search (AllMiniLM embeddings, 112ms query)
    │   ├── Pattern detection (struggles, recurring errors, edit correlations)
    │   ├── Predictive context (related files, likely errors before edits)
    │   ├── Cross-project learning (aggregate insights across all projects)
    │   ├── Code index (ast-only symbol table per project, incremental by mtime)
    │   └── Outcome log (injection precision: which kinds precede passing tests)
    │
    └── Ollama (local LLM, optional)          ← memory(consolidate), session_mine(reflect)
        └── gemma3:12b (configurable); scout_search uses it when present

Storage: ~/.claude_engram/
    ├── manifest.json        ← Maps project paths to hash dirs; migrations_applied list
    ├── global.json          ← Global entries (cross-project)
    ├── projects/
    │   └── <hash>/
    │       ├── memory.json         ← This project's memories (hot tier)
    │       ├── archive.json        ← This project's cold tier
    │       ├── embeddings.npy          ← Binary AllMiniLM vectors (numpy)
    │       ├── embeddings_index.json   ← ID-to-row mapping
    │       ├── embeddings_pending.json ← Hook writes (merged on load)
    │       ├── handoff_history.json    ← Capped ring buffer (last 20 handoffs)
    │       └── code_index.json         ← Per-project symbol table (mtime-keyed, ast)
    ├── checkpoints/         ← Task state, handoffs
    │   ├── latest_handoff.json      ← Most recent handoff (kept in sync; backward-compatible)
    │   └── handoff_history.json     ← Global slot ring buffer (last 20 handoffs)
    ├── embeddings/          ← Cached AllMiniLM decision templates
    ├── sessions/
    │   └── <session_id>.json        ← Per-session hook state: edit counts, test results (loop detection lives here; auto-prune after 7 days)
    ├── hook_state.json      ← Hook tracking counters (legacy/global fallback)
    ├── loop_detector.json   ← Abandoned in v0.8.0 (state moved to sessions/<sid>.json; old file harmless)
    ├── scope_guard.json     ← Declared scope state
    ├── conventions.json     ← Project coding rules
    ├── injection_outcomes.json ← Pre-edit injection vs test-outcome correlation log
    ├── scorer_port          ← TCP port for scorer server
    └── scorer_pid           ← PID of scorer server
```

## Core Components

### MemoryStore (`tools/memory.py`)

**What it does:** Persists and retrieves memories across sessions. Handles tiered storage (hot/archive), deduplication, scoring, tagging, clustering, and cleanup.

**Why it's separate:** Memory is the foundation everything else builds on. Hooks write to it, MCP tools read from it, session management depends on it.

**Key internals:**
- Entries are Pydantic models with `id`, `content`, `category`, `relevance`, `tags`, `related_files`, `last_accessed`, `access_count`, `archived_at`
- Path normalization (`D:\Code` → `d:/Code`, lowercase drive, forward slashes) prevents duplicate project buckets
- Deduplication uses Jaccard similarity (word-set overlap) with 0.85 threshold
- Scoring: `0.35*file_match + 0.20*tag_overlap + 0.20*recency + 0.15*relevance + 0.10*access_freq` plus category bonuses
- Archive: entries with `last_accessed > 14 days` and `relevance < 7` move to `archive.json`. Rules/mistakes never archive.

### HotMemoryReader (`tools/memory.py`)

**What it does:** Lightweight, read-only memory reader for hooks. Reads raw JSON dicts (no Pydantic parsing) for speed.

**Why it's separate:** Hooks run in a separate Python process with 1-2s timeout. Full `MemoryStore` initialization is too slow. `HotMemoryReader` loads only the active project's memory via manifest lookup, scores entries, and returns in ~5ms.

**Key internals:**
- Parent-path fallback: when looking up a sub-project path, also checks parent paths for inherited workspace-level memories
- Scoring logic duplicated (simplified) from `MemoryStore._score_memory_relevance` to avoid Pydantic imports
- Shared constants (`SCORE_WEIGHTS`, `CATEGORY_BONUSES`) keep the two implementations in sync
- Path-aware `file_match` (v0.5.0): a shared basename across diverging paths (`service-a/.../foo.py` vs `service-b/.../foo.py`) is not treated as a match. Generic basenames (`__init__.py`, `index.js`, `__main__.py`, etc.) require a full-path signal to match; specific filenames still match by name. Scoring weights are unchanged.

### Hook System (`hooks/remind.py`)

**What it does:** Entry point for all Claude Code hooks. Routes hook events to handlers that auto-capture data and inject context.

**Why it's separate:** Hooks are shell commands invoked by Claude Code as child processes. They receive JSON on stdin, output JSON on stdout. They must be fast, stateless, and crash-safe.

**Key internals:**
- `main()` dispatches on `hook_type` argument (e.g., `prompt_json`, `pre_edit_json`, `bash_json`)
- All JSON hooks read stdin via `_read_stdin_with_timeout(0.5)` — a cross-platform reader with a daemon thread
- `get_project_dir(file_path)` resolves sub-projects by walking up from the file looking for project markers
- `_auto_capture_from_prompt()` uses two-tier scoring: AllMiniLM via scorer server (if available) → regex fallback
- Hook output uses Claude Code's `hookSpecificOutput.additionalContext` format for conversation injection

### Scorer Server (`hooks/scorer_server.py`)

**What it does:** Persistent TCP server that keeps AllMiniLM loaded in memory. Hooks connect, send a prompt, get a decision score back in ~5-25ms instead of ~500ms cold start.

**Why it's separate:** Loading `sentence-transformers` + AllMiniLM takes ~500ms per process. Hooks spawn a new process each time. A persistent server amortizes the load cost across all hook calls in a session.

**Key internals:**
- Binds to `127.0.0.1:0` (OS picks port), writes port to `~/.claude_engram/scorer_port`
- Protocol: JSON lines over TCP (`{"text": "..."}\n` → `{"score": 0.85, "text": "..."}\n`)
- Auto-starts on SessionStart hook (fire-and-forget, non-blocking)
- Auto-exits after 30 min idle (configurable via `CLAUDE_ENGRAM_SCORER_TIMEOUT`)
- Thread-per-connection for concurrent hook requests

### Handlers (`handlers.py`)

**What it does:** Routes MCP tool calls from the server to the appropriate tool classes. Contains all handler logic.

**Why it's separate:** Keeps `server.py` as a thin routing layer. All business logic lives in handlers, making it testable without the MCP protocol.

### LLM Client (`llm.py`)

**What it does:** Communicates with Ollama for semantic search and code analysis. Includes retry logic, request queueing (serializes parallel requests to prevent GPU contention), and health checking.

**Why it's separate:** Isolates the optional Ollama dependency. LLM (gemma3:12b via Ollama) is used only by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently if Ollama is down), plus `scout_search` when available. Everything else — all hooks, the code index, import precheck, blast-radius, the outcome log, `convention(check)`, `file_summarize`, `audit_batch`, `find_similar_issues` — is LLM-free.

### Code Index (`mining/code_index.py`)

**What it does:** Builds and maintains an incremental, mtime-keyed symbol table for a project. For each Python module it records: dotted module path, public exports (`__all__` or all public top-level names), classes (bases, methods with signatures, `self.x` attributes), functions (with signatures), and raw imports. A derived `symbol_to_modules` reverse map enables O(1) name lookup. A `module_to_dependents` map records which modules import each module — the blast-radius cache.

**Why it's separate:** The index is built in the background miner (Phase 6) after a session ends, then queried at pre-edit hook time with zero I/O overhead. Keeping build and query in one module keeps the hook import surface small.

**Key internals:**
- Walk stops at nested project markers (`pyproject.toml`, `.git`, `CLAUDE.md`, etc.) so a workspace root does not index sibling sub-projects
- Up to 4000 files per project (configurable); truncation is recorded, not silent
- Parse errors leave the prior record in place (no garbage symbols injected)
- Atomic save via temp-then-replace; incremental (only re-parses files whose mtime changed)
- Storage: `~/.claude_engram/projects/<hash>/code_index.json`
- `resolve_code_index()` walks up to a parent project if a sub-project has no index yet (workspace inheritance)

### Pre-Edit Import Verification + Blast Radius (`hooks/precheck.py`)

**What it does:** On `PreToolUse Edit/Write`, reads the proposed edit content and checks its import statements against the code index. Two banners may be injected:

- `<engram-precheck>` — lists imports that won't resolve: name not exported by a known internal module (with closest-match suggestion), or internal module path not found. Capped at 2 findings.
- `<engram-blast-radius>` — when editing a module imported by ≥2 others, lists those dependents from the cached reverse-edge map.

**Why it's separate:** Keeps the import-checking logic isolated and testable independently of the main `remind.py` hook. The module is pure regex + index lookup — no AST parsing at hook time (that already happened during the miner phase).

**Key internals:**
- Conservative by design: silent on relative imports, external/stdlib imports, `import *`, multiline parenthesised imports, missing/stale index, or any exception
- `check_imports()` uses `index.known_roots()` to decide which imports are internal (verifiable) vs external (leave alone)
- `blast_radius()` reads `index.dependents_of(module_path)` — no filesystem walk
- Both functions return `""` on any error, never raise

### Session Mining Background Worker (`mining/background.py`)

**What it does:** Spawns a detached background subprocess after `SessionEnd` to run the full mining pipeline without blocking the hook. The worker runs these phases in order:

| Phase | What | When |
|-------|------|------|
| 1 | Index sessions (JSONL parse, session index, incremental cursors) | always |
| 2 | Extract decisions, mistakes, approaches from session text | post_session, bootstrap, full |
| 3 | Build/refresh session search embeddings (AllMiniLM, incremental) | post_session, embed, bootstrap, full |
| 4 | Pattern detection (struggles, recurring errors, edit correlations) | post_session, bootstrap, full |
| 5 | Memory cleanup (dedup, decay) + embed all memories (keeps hybrid_search current) | post_session, bootstrap, full |
| 6 | Code index build (per-project ast symbol table) | post_session, bootstrap, full |

**Why it matters:** Phases 3 and 4 previously ran only on bootstrap, leaving `patterns.json` and session embeddings stale between sessions. Moving them to every `post_session` keeps the recurring-errors banner and `hybrid_search` current without manual intervention.

**Key internals:**
- Single global lock (`~/.claude_engram/mining.lock`) — one miner process at a time
- Status written atomically to `mining_status.json` per phase
- Each phase wrapped in its own try/except — a failure in one phase does not abort subsequent phases

### Injection Outcome Log (`mining/outcomes.py`)

**What it does:** Records what the pre-edit hook injected (`memory`, `prediction`, `precheck`, `blast`) and the test outcomes that followed in the same session. `session_mine(reflect)` reads this log to compute injection precision per kind (how often each channel precedes a passing vs failing test), plus LLM-synthesized insights from recurring mistakes.

**Why it's separate:** Outcome correlation is session-scoped and workspace-pooled (a test run in one file correlates with the pre-edit injection on a different file in the same session). Keeping this in a dedicated module with a single global log at `~/.claude_engram/injection_outcomes.json` sidesteps the sub-project vs cwd mismatch between the edit hook and the bash hook.

**Key internals:**
- Events are `{t:"inj", kinds:[...], sid, ts}` and `{t:"out", passed, sid, ts}`
- Bounded ring: last 1000 events; atomic write
- `reflect()` correlates outcomes with the most recent injection in the same session (resets per-session state after each outcome)
- Under two concurrent sessions the last writer may drop a few events — acceptable for a precision metric

## How a Hook Call Flows

```
1. Claude calls Edit(file_path="auth.py")
       │
       ▼
2. Claude Code fires PreToolUse hook
       │  Sends JSON to stdin: {hook_event_name, tool_name, tool_input, ...}
       ▼
3. remind.py main() → "pre_edit_json" handler
       │  Reads stdin, extracts file_path="auth.py"
       ▼
4. resolve_project_for_file("auth.py", workspace_root)
       │  Walks up from auth.py looking for pyproject.toml, CLAUDE.md, etc.
       │  Returns project path (e.g., ~/projects/my-project)
       ▼
5. reminder_for_edit(project_dir, file_path)
       │  ├── _auto_run_pre_edit_check() → loads memory, checks mistakes
       │  ├── get_contextual_memories() → HotMemoryReader scores + ranks
       │  ├── precheck_edit() → import/export check against code index
       │  ├── blast_radius() → reverse-edge lookup from code index
       │  ├── check_loop_detected() → reads per-session state (sessions/<sid>.json)
       │  └── get_scope_status() → reads scope_guard.json
       │  └── record_injection() → logs injection kinds to outcome log
       ▼
6. Output JSON: {hookSpecificOutput: {additionalContext: "..."}}
       │
       ▼
7. Claude sees: past mistakes, loop warnings, top 3 relevant memories,
       │        <engram-precheck> import issues, <engram-blast-radius> callers
       │
       ▼
8. Edit proceeds (or Claude reconsiders based on warnings)
       │
       ▼
9. Claude Code fires PostToolUse hook
       │
       ▼
10. post_edit_json handler: auto-records edit, updates loop counter
```

## Directory Structure

```
claude_engram/
├── claude_engram/
│   ├── __init__.py          # Package version
│   ├── server.py            # MCP server entry point (thin router)
│   ├── handlers.py          # All MCP handler logic (~2000 lines)
│   ├── schema.py            # MiniClaudeResponse Pydantic model
│   ├── llm.py               # Ollama client with queueing
│   ├── tool_definitions_v2.py  # MCP tool schemas (combined tools)
│   ├── handoff_store.py     # Shared handoff ring-buffer read/write (v0.5.0)
│   ├── migrations.py        # Idempotent version-stamped migrations (v0.5.0)
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── remind.py        # Hook entry point (~2100 lines)
│   │   ├── intent.py        # Semantic intent scorer (AllMiniLM)
│   │   ├── scorer_server.py # Persistent AllMiniLM TCP server
│   │   ├── precheck.py      # Import/export verification + blast-radius
│   │   ├── paths.py         # Storage path helpers (shared by hooks + mining)
│   │   └── storage.py       # Atomic file I/O helpers
│   ├── mining/
│   │   ├── __init__.py
│   │   ├── background.py    # Background subprocess spawner + 6-phase worker
│   │   ├── jsonl_reader.py  # Streaming JSONL session-log reader
│   │   ├── session_index.py # Session index, incremental byte-offset cursors
│   │   ├── extractors.py    # Structural + semantic extractors (decisions, etc.)
│   │   ├── search.py        # Cross-session search (AllMiniLM embeddings)
│   │   ├── patterns.py      # Pattern detection (struggles, errors, correlations)
│   │   ├── predictive.py    # Predictive context (related files, likely errors)
│   │   ├── cross_project.py # Cross-project aggregate insights
│   │   ├── timeline.py      # Project timeline builder
│   │   ├── commitments.py   # Live-transcript open-loop scan (session_mine commitments)
│   │   ├── reflect.py       # LLM-synthesized insights from recurring patterns (optional Ollama)
│   │   ├── code_index.py    # Per-project ast symbol table (Phase 6)
│   │   └── outcomes.py      # Pre-edit injection vs test-outcome correlation log
│   └── tools/
│       ├── __init__.py
│       ├── memory.py         # MemoryStore + HotMemoryReader
│       ├── session.py        # SessionManager
│       ├── work_tracker.py   # WorkTracker (mistakes, decisions)
│       ├── scope_guard.py    # ScopeGuard
│       ├── context_guard.py  # ContextGuard (checkpoints, handoffs)
│       ├── conventions.py    # ConventionTracker (deterministic convention check)
│       ├── code_quality.py   # Inline regex/AST lint (audit_batch inline mode)
│       ├── scout.py          # Semantic search (optional Ollama)
│       ├── summarizer.py     # Structural file summarizer (no LLM)
│       ├── dependencies.py   # Dependency mapper
│       ├── impact.py         # Impact analyzer (reads code index; regex fallback)
│       └── thinker.py        # Code audit / pattern finder — regex/AST (audit_batch file mode, find_similar_issues)
├── hooks_config.json         # Reference hook config
├── install.py                # Installer (hooks, MCP, launcher scripts)
├── pyproject.toml
├── CLAUDE.md                 # Instructions for Claude (copy to projects)
├── .mcp.json                 # MCP server config (copy to projects)
└── library-book/             # You are here
```

## Key Design Decisions

| Decision | Why | What Would Break If Changed |
|----------|-----|---------------------------|
| Flat JSON files, not SQLite | Zero dependencies, atomic writes, human-readable | Scale past ~1000 entries per project |
| Separate hot/cold tiers | Hooks must be fast (<2s). Loading archive on every edit is too slow. | Hook timeouts if merged |
| Hooks as separate processes | Claude Code's hook system spawns child processes. No choice. | N/A — this is a Claude Code constraint |
| Scorer server as TCP, not HTTP | Minimal overhead, no web framework dependency | Harder to debug (no browser tools) |
| Parent-path memory inheritance | Workspace-level rules must apply to all sub-projects | Sub-project isolation if someone wants it |
| `remind.py` as single file | All hook logic in one place. No cross-file imports to slow startup. | Harder to maintain as it grows |
| Regex fallback for decision scoring | sentence-transformers is optional. Must work without it. | Fewer decisions captured without [semantic] |
| Handoff ring buffer (last 20) + promotion guard | A single overwritable slot meant a trivial auto-handoff could silently replace a substantive one. Ring buffer preserves history; promotion guard skips writes that add no signal. | Lose historical handoffs on downgrade (backward-safe: latest_handoff.json kept in sync) |
| Walk-up handoff resolution (project → ancestors → global) | A sub-project's handoff was previously shadowed by the shared global slot written by the Stop hook. | Sub-projects would again lose their handoff to the global slot |
| Code index is ast-only, built in miner (not hooks) | LLM is too slow for pre-edit hooks. Incremental ast parse in background keeps pre-edit check at O(1) index lookup. | Import checks would require per-hook LLM calls (impossible within 2s timeout) |
| Per-session hook state files (`sessions/<sid>.json`) | Concurrent sessions from one workspace share the same project dir. A single `hook_state.json` means session A's loop counters overwrite session B's. | Cross-session pollution of loop detection and injection logging |
| Conservative silence in precheck | A wrong import warning trains the agent to ignore the channel. Any uncertainty → emit nothing. | More false positives would erode trust in `<engram-precheck>` banners |
| Outcome log is global, keyed by session_id | The edit hook and bash hook see different cwds; sub-project attribution is ambiguous. Session-scoped correlation sidesteps the mismatch. | Per-project precision metrics would be unreliable due to cwd mismatch |
| Miner phases 3+4 run every post_session | Previously they ran only on bootstrap, leaving patterns.json and session embeddings stale. | `hybrid_search` returns stale results; recurring-errors banner stays frozen |

---

[Next: Usage Guide →](./05-usage-guide.md)

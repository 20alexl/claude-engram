# Chapter 4 — The Internals

[← Back to Table of Contents](./README.md) · [Previous: Quick Start](./03-quick-start.md) · [Next: Usage Guide →](./05-usage-guide.md)

---

## Architecture

```
Claude Code
    │
    ├── Hooks (remind.py)                    ← Intercepts tool calls
    │   ├── UserPromptSubmit                     → auto-capture decisions
    │   ├── PreToolUse Edit/Write                → inject scored memories, check loops
    │   ├── PostToolUse Bash/Edit/Write          → track edits, tests, search spirals
    │   ├── PostToolUseFailure (all tools)       → auto-log errors as mistakes
    │   ├── SessionStart / SessionEnd / Stop     → lifecycle management
    │   └── PreCompact / PostCompact             → checkpoint + re-inject context
    │
    ├── MCP Server (server.py → handlers.py)  ← Tools for manual operations
    │   ├── memory (18 operations)
    │   ├── work (log_mistake, log_decision)
    │   ├── scope, loop, context, convention, output
    │   └── scout_search, impact_analyze, code_quality_check, ...
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
    │   └── Cross-project learning (aggregate insights across all projects)
    │
    └── Ollama (local LLM)                    ← Semantic search, code analysis
        └── gemma3:12b (configurable)

Storage: ~/.claude_engram/
    ├── manifest.json        ← Maps project paths to hash dirs
    ├── global.json          ← Global entries (cross-project)
    ├── projects/
    │   └── <hash>/
    │       ├── memory.json  ← This project's memories (hot tier)
    │       ├── archive.json ← This project's cold tier
    │       ├── embeddings.npy          ← Binary AllMiniLM vectors (numpy)
    │       ├── embeddings_index.json   ← ID-to-row mapping
    │       └── embeddings_pending.json ← Hook writes (merged on load)
    ├── checkpoints/         ← Task state, handoffs
    ├── embeddings/          ← Cached AllMiniLM decision templates
    ├── hook_state.json      ← Hook tracking counters
    ├── loop_detector.json   ← Edit counts per file
    ├── scope_guard.json     ← Declared scope state
    ├── conventions.json     ← Project coding rules
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

**Why it's separate:** Isolates the Ollama dependency. Everything except `scout_search`, `scout_analyze`, `file_summarize`, and LLM-based convention checking works without Ollama.

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
       │  ├── check_loop_detected() → reads loop_detector.json
       │  └── get_scope_status() → reads scope_guard.json
       ▼
6. Output JSON: {hookSpecificOutput: {additionalContext: "..."}}
       │
       ▼
7. Claude sees: past mistakes, loop warnings, top 3 relevant memories
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
│   ├── hooks/
│   │   ├── __init__.py
│   │   ├── remind.py        # Hook entry point (~2100 lines)
│   │   ├── intent.py        # Semantic intent scorer (AllMiniLM)
│   │   └── scorer_server.py # Persistent AllMiniLM TCP server
│   └── tools/
│       ├── __init__.py
│       ├── memory.py         # MemoryStore + HotMemoryReader
│       ├── session.py        # SessionManager
│       ├── work_tracker.py   # WorkTracker (mistakes, decisions)
│       ├── loop_detector.py  # LoopDetector
│       ├── scope_guard.py    # ScopeGuard
│       ├── context_guard.py  # ContextGuard (checkpoints, handoffs)
│       ├── conventions.py    # ConventionTracker
│       ├── output_validator.py
│       ├── code_quality.py
│       ├── scout.py          # Semantic search
│       ├── summarizer.py     # File summarizer
│       ├── dependencies.py   # Dependency mapper
│       ├── impact.py         # Impact analyzer
│       ├── thinker.py        # Code audit / pattern finder
│       └── habit_tracker.py  # Session statistics
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

---

[Next: Usage Guide →](./05-usage-guide.md)

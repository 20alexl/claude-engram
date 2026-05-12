# Claude Engram

Persistent memory and session intelligence for AI coding assistants. Hooks into Claude Code's lifecycle to auto-track mistakes, decisions, and context — then mines your full session history to surface patterns, predict what you'll need, and search across everything you've ever discussed.

Zero manual effort. Works with any MCP-compatible client.

## What It Does

**Automatic (hooks — zero invocation):**
- Tracks every edit, error, test result, and session event
- Auto-captures decisions from your prompts ("let's use X", "switch to Y")
- Injects the 3 most relevant memories before every file edit
- Warns when you're about to repeat a past mistake
- Detects edit loops (same file 3+ times without progress)
- Survives context compaction — checkpoints before, re-injects after
- Mines your session history in the background after every session

**Session Mining (automatic, background):**
- Parses Claude Code's full conversation logs (JSONL) after every session — including subagent conversations (Explore, Plan, code-reviewer, etc.)
- Extracts decisions, mistakes, approaches, and user corrections using structural analysis + AllMiniLM semantic scoring (typo-tolerant)
- Builds a searchable index across all past conversations (20k+ chunks with subagents)
- Detects recurring struggles, error patterns, and file edit correlations
- Predicts what files and context you'll need before edits
- Reflects on patterns using local LLM to synthesize root causes and architectural insights
- On first install, retroactively mines your entire session history

**On-demand (MCP tools):**
- `memory` — store, search, archive, and manage memories
- `session_mine` — search past conversations, find decisions, replay file history, detect patterns
- `work` — log decisions and mistakes with reasoning
- Plus: scope guard, context checkpoints, convention tracking, impact analysis

## How It Works

```
Claude Code
    |
    +-- Hooks (remind.py)                    <- Intercepts every tool call
    |   SessionStart / Edit / Bash / Error / Compact / Stop
    |
    +-- Session Mining (mining/)             <- Background intelligence
    |   JSONL parser -> Extractors -> Search index -> Pattern detection
    |
    +-- MCP Server (server.py)              <- Tools for manual operations
    |   memory, session_mine, work, scope, context, ...
    |
    +-- Scorer Server (scorer_server.py)    <- Persistent AllMiniLM process
        TCP localhost, ~90MB RAM, batch embeddings
```

Hooks fire on every tool call (1-2s budget each). Heavy processing happens in a background subprocess after session end. The scorer server stays loaded in memory for fast semantic scoring.

## Benchmarks

### Integration benchmarks

These test what the product actually does.

| Benchmark | What it tests | Result |
|---|---|---|
| **Decision Capture** (220 prompts) | Auto-detect decisions from user prompts | 97.8% precision, 36.7% recall |
| **Injection Relevance** (50 memories, 15 cases) | Right memories surface before edits | 14/15 passed, 100% isolation |
| **Compaction Survival** (6 scenarios) | Rules/mistakes survive context compression | 6/6 |
| **Error Auto-Capture** (53 payloads) | Extract errors, reject noise, deduplicate | 100% recall, 97% precision |
| **Multi-Project Scoping** (11 cases) | Sub-project isolation + workspace inheritance | 11/11 |
| **Edit Loop Detection** (12 scenarios) | Detect spirals vs iterative improvement | 12/12 |
| **Session Mining** (27 tests) | JSONL parsing, indexing, search, incremental processing | 27/27 |
| **Obsidian Vault** (25 tests) | Compatibility with PARA + CLAUDE.md vault structure | 25/25 |

Reproduce: `python tests/bench_integration.py`, `bench_session_mining.py`, `bench_obsidian_vault.py`

### Retrieval benchmarks

Retrieval-only (recall@k) — whether the right memory is found in top results.

| Benchmark | Score |
|---|---|
| **LongMemEval** Recall@5 (500 questions) | 0.966 |
| **LongMemEval** Recall@10 | 0.982 |
| **ConvoMem** (250 items, 5 categories) | 0.960 |
| **LoCoMo** R@10 (1,986 questions) | 0.649 |
| **Speed** | 43ms/query |
| **Cross-session search** | 112ms/query over 7310 chunks |

Reproduce: `python tests/bench_longmemeval.py`, `bench_locomo.py`, `bench_convomem.py`

## Compatibility

| Platform | What Works | Auto-Capture |
|---|---|---|
| **Claude Code** (CLI, desktop, VS Code, JetBrains) | Everything | Full — hooks + session mining |
| **Cursor** | MCP tools (memory, search, etc.) | No hooks |
| **Windsurf** | MCP tools | No hooks |
| **Continue.dev** | MCP tools | No hooks |
| **Zed** | MCP tools | No hooks |
| **Any MCP client** | MCP tools | No hooks |
| **Obsidian vaults** | Full (with CLAUDE.md at root) | Full with Claude Code |

## Install

```bash
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Core
pip install -e ".[semantic]"    # + AllMiniLM for vector search and semantic scoring

python install.py               # Configure hooks, MCP server, and /engram skill
```

### Per-Project Setup

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` to your project root.

**Note:** The `CLAUDE.md` in this repo is engram-specific documentation — it's not required for engram to work. Hooks fire automatically and the `/engram` skill provides a quick reference on demand. If you already have a `CLAUDE.md` for your project, keep it as-is and don't copy ours over it. If you want engram docs alongside your project rules, rename it to `CLAUDE-ENGRAM.md` (or similar) so it doesn't clobber your existing file — Claude will see it when relevant.

### Updating

```bash
cd claude-engram
git pull
pip install -e ".[semantic]"    # Reinstall if dependencies changed
python install.py               # Re-run to update hooks and /engram skill
```

Hooks and MCP tools pick up code changes immediately (editable install). Reconnect the MCP server in Claude Code (`/mcp`) to reload the server process.

### Mid-Project Adoption

Already deep in a project? Install normally. On first session, engram auto-detects your existing Claude Code session history and mines it in the background — extracting decisions, mistakes, and patterns from all past conversations. No manual effort.

## Key Features

### Memory System
- **Hybrid search** — keyword + AllMiniLM vector + reranking. No ChromaDB.
- **Scored injection** — top 3 memories by file match, tags, recency, importance before every edit.
- **Tiered storage** — hot (fast) + archive (cold, searchable, restorable). Rules and mistakes never archive.
- **Multi-project** — memories scoped per sub-project. Workspace rules cascade down.

### Session Mining
- **Structural extraction** — analyzes conversation flow (confirmations, redirects, error->fix sequences, approach changes) instead of template matching.
- **Tool content indexing** — bash commands + output, edit diffs, and error tracebacks are searchable alongside conversation text.
- **Batch embeddings** — 22x faster than individual calls via batched TCP protocol.
- **Cross-session search** — 44k+ conversation chunks indexed, semantic + keyword + hybrid search.
- **Pattern detection** — recurring struggles, error patterns, edit correlations across sessions.
- **Predictive context** — before edits, surfaces related files and likely errors from history.
- **Cross-project learning** — aggregates patterns across all your projects.
- **Retroactive bootstrap** — mines all existing session history on first install.
- **Scorer auto-start** — AllMiniLM server starts on demand if not running. No silent degradation.

### Lifecycle
- **Auto-captures decisions** — structural patterns (confirmations, redirects, explicit choices) + semantic scoring as bonus.
- **Auto-tracks mistakes** from any failed tool. Only logs errors in project files (filters transient noise). Warns before repeat edits.
- **Survives compaction** — checkpoints with session decisions/mistakes, re-injects after. Checkpoints and handoffs are per-project scoped.
- **Subagent awareness** — memory injection and hook output are skipped for subagents (saves context), but file edits are still tracked.
- **Edit loop detection** — flags when the same file is edited 3+ times without progress.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model (optional — only for scout_search, convention checking) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | AllMiniLM server idle timeout (seconds) |

## Reindexing

If search quality is poor or you want to rebuild after an update:

```bash
python scripts/reindex.py "E:\workspace" --force            # rebuild search index
python scripts/reindex.py "E:\workspace" --force --extract   # also re-extract decisions/mistakes
```

Or via MCP: `session_mine(operation="reindex", mode="bootstrap")`

## Documentation

**[Library Book](./library-book/)** — design philosophy, internals, full usage guide, API reference, gotchas, and changelog.

**`/engram`** — slash command with quick tool reference (installed by `install.py`).

## License

MIT

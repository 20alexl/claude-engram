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
- Parses Claude Code's full conversation logs (JSONL) after every session
- Extracts decisions, mistakes, approaches, and user corrections using structural analysis + AllMiniLM semantic scoring (typo-tolerant)
- Builds a searchable index across all past conversations
- Detects recurring struggles, error patterns, and file edit correlations
- Predicts what files and context you'll need before edits
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

Or copy `.mcp.json` and `CLAUDE.md` to your project root.

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
- **Structural extraction** — analyzes conversation flow (error->fix sequences, user redirects, approach changes) instead of fragile regex.
- **Semantic classification** — AllMiniLM scores candidates against decision/correction templates. Naturally typo-tolerant (100% in benchmarks).
- **Batch embeddings** — 22x faster than individual calls via batched TCP protocol.
- **Cross-session search** — 7310 conversation chunks indexed, 112ms semantic query.
- **Pattern detection** — recurring struggles, error patterns, edit correlations across sessions.
- **Predictive context** — before edits, surfaces related files and likely errors from history.
- **Cross-project learning** — aggregates patterns across all your projects.
- **Retroactive bootstrap** — mines all existing session history on first install.

### Lifecycle
- **Auto-captures decisions** from prompts via semantic + structural scoring.
- **Auto-tracks mistakes** from any failed tool. Warns before repeat edits.
- **Survives compaction** — checkpoints before, re-injects rules/mistakes/decisions after.
- **Edit loop detection** — flags when the same file is edited 3+ times without progress.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model (optional — only for scout_search, convention checking) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | AllMiniLM server idle timeout (seconds) |

## Documentation

**[Library Book](./library-book/)** — design philosophy, internals, full usage guide, API reference, gotchas, and changelog.

**`/engram`** — slash command with quick tool reference (installed by `install.py`).

## License

MIT

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
- Verifies imports in proposed edits against a per-project code index (AST, no LLM) — `<engram-precheck>` with closest-name suggestions
- Shows blast radius before editing a shared module — lists its importers (`<engram-blast-radius>`)
- Measures injection precision — tracks which injected context precedes passing tests (view via `session_mine(reflect)`)

**Session Mining (automatic, background):**
- Parses Claude Code's full conversation logs (JSONL) after every session — including subagent conversations (Explore, Plan, code-reviewer, etc.)
- Extracts decisions, mistakes, approaches, and user corrections using structural analysis + AllMiniLM semantic scoring (typo-tolerant)
- Builds a searchable index across all past conversations (20k+ chunks with subagents)
- Detects recurring struggles, error patterns, and file edit correlations
- Predicts what files and context you'll need before edits
- Logs which injected context precedes passing tests; `session_mine(reflect)` reports that precision + LLM-synthesized patterns
- On first install, retroactively mines your entire session history

**On-demand (MCP tools):**
- `memory` — store, search, archive, and manage memories
- `session_mine` — search past conversations (taggable by kind: decision / next-step / error), find decisions, replay file history, detect patterns, and surface what you said you'd do this session (`commitments`)
- `work` — log decisions and mistakes with reasoning
- Plus: scope guard, context checkpoints (`checkpoint_save/restore/list`; `handoff_*` are deprecated aliases), convention tracking, impact analysis

All MCP tools carry annotations (read-only / idempotent hints + a title), so clients and permission systems know which are safe to call without a prompt.

## A Note From the Author

How I actually use it, since I built it:

Mostly it just works in the background — you don't have to think about it. The few things worth doing on purpose:

- **Pull `/engram`** when you want Claude to actively reach for the tools — the command loads the reference so Claude knows what's there and uses it. (Background tracking happens either way; this is for the on-demand stuff.)
- When you half-remember something from a while back ("what did we decide about X?"), ask Claude to mine the sessions for it — it searches *everything* you've ever discussed, not just what's in context.
- If there's something it should never forget, save it as a **rule**. Rules are scoped: a **per-project** rule applies to that project; a **global** one (saved at your workspace root) cascades down to every project under it. Broad conventions → global, project-specific → per-project.
- Before compacting, it auto-saves a checkpoint — but I make one with what I'm doing + what's left and ask it to pull that back up after. Resumes a lot cleaner.
- When you come back, ask what you said you'd do this session — it skims the live conversation for open loops vs. what's done. It's a best-effort read (not a perfect list), but a quick way to reorient.

The less you poke at it, the better it works.

This is a work in progress — if something's off or you hit a bug, please open an issue.

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

**Retrieval (recall@k):** LongMemEval 0.966 R@5 / 0.982 R@10 (500 questions), ConvoMem 0.960 (250 items), LoCoMo 0.649 R@10 (~2k questions); ~43ms/query, 112ms cross-session over 7,310 chunks.

**Product behavior:** eight integration suites green — decision capture (97.8% precision), error auto-capture (100% recall), compaction survival (6/6), multi-project isolation (11/11), edit-loop detection (12/12), session mining (27/27), Obsidian-vault compat (25/25).

Full tables and the `tests/bench_*.py` reproduction commands are in the **[library-book](./library-book/)**.

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

Data migrations run automatically: a cheap inline check fires on the next SessionStart, and a full migration runs in the background. `install.py` also runs migrations synchronously (step 9). Migrations are forward-only, idempotent, and downgrade-safe — no data is lost.

### Mid-Project Adoption

Already deep in a project? Install normally. On first session, engram auto-detects your existing Claude Code session history and mines it in the background — extracting decisions, mistakes, and patterns from all past conversations. No manual effort.

## Key Features

**Memory** — hybrid search (keyword + AllMiniLM vector + rerank, no ChromaDB); path-aware scored injection (top 3 by file/tags/recency/importance, with age shown); tiered hot/cold storage (rules and mistakes never archive); per-sub-project scoping with cascading workspace rules.

**Session mining** — structural extraction (conversation flow, not template matching) over conversation *and* tool content; cross-session semantic/keyword/hybrid search, typed by kind (decision / next-step / error) and filterable; `session_mine(commitments)` reads the *live* transcript for open loops the post-session index can't see; pattern detection, predictive context, cross-project learning; retroactive bootstrap on first install.

**Lifecycle** — auto-captured decisions + mistakes; survives compaction (per-project checkpoints in a durable ring); edit-loop detection; subagent-aware; automatic, idempotent, downgrade-safe migrations on upgrade.

Internals, the full feature list, gotchas, and API reference live in the **[library-book](./library-book/)**.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model (optional — only for scout_search, convention checking) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | AllMiniLM server idle timeout (seconds) |

## Reindexing

If search quality is poor or you want to rebuild after an update:

```bash
python scripts/reindex.py "/path/to/your/workspace" --force            # rebuild search index
python scripts/reindex.py "/path/to/your/workspace" --force --extract   # also re-extract decisions/mistakes
```

Or via MCP: `session_mine(operation="reindex", mode="bootstrap")`

## Documentation

**[Library Book](./library-book/)** — design philosophy, internals, full usage guide, API reference, gotchas, and changelog.

**`/engram`** — slash command with quick tool reference (installed by `install.py`).

## License

MIT

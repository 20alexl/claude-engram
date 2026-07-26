# Claude Engram

Persistent memory and session intelligence for Claude Code. Hooks into the session lifecycle to auto-track mistakes, decisions, and context — then mines your full session history so past work resurfaces exactly when it's relevant.

Zero manual effort. Works with any MCP-compatible client.

## What It Does

Everything below is automatic (hooks) unless marked as a tool:

- Tracks every edit, error, test result, and session event; captures decisions straight from your prompts ("let's use X")
- Injects the 3 most relevant memories before each file edit; warns before you repeat a past mistake
- Error deja-vu: a failure matching a known recurring error gets the past fix injected at failure time
- Verifies imports and shows blast radius before edits, and orients before reads — all from a per-project code index (AST, no LLM)
- Lists the project's known-good test commands at session start
- Survives compaction: checkpoint before, re-inject after; deliberate checkpoints live in a durable per-project ring
- Mines your full history in the background (and live, mid-session): decisions, mistakes, recurring struggles — searchable across everything you've ever discussed, scoped to the right sub-project
- Stays honest: failing TDD runs aren't logged as mistakes, edit loops get flagged, subagents are tracked without wasting their context
- **Tools** (on demand): `memory`, `session_mine`, `work`, `context` checkpoints, `deps_map`, `impact_analyze`, `scout_search` — all annotated read-only/idempotent where true. `/engram` loads the full reference.

## How to Use It Effectively

From the author — mostly it just works in the background. The few things worth doing on purpose:

- **Pull `/engram`** when you want Claude to actively reach for the tools (background tracking happens either way).
- Half-remember something from weeks ago? Ask Claude to **mine the sessions** for it — it searches everything, not just what's in context.
- Something it should never forget → save it as a **rule**. Per-project rules stay local; rules at your workspace root cascade to every project under it.
- Before compacting, it auto-checkpoints — but a **manual checkpoint** with what you're doing and what's left resumes far cleaner. Deliberate saves always beat automatic ones.
- On return, ask **what you said you'd do this session** (`session_mine(commitments)`) — a quick, best-effort reorient from the live transcript.

The less you poke at it, the better it works. Work in progress — issues welcome.

## How It Works

```
Claude Code
    |
    +-- Hooks (remind.py)          <- intercept every tool call (1-2s budget)
    +-- Session mining (mining/)   <- background + live-tick intelligence
    +-- MCP server (server.py)     <- on-demand tools
    +-- Scorer daemon              <- warm encoder + hook dispatch, cpu-resident;
                                      bulk embeddings in a transient GPU worker
```

## Benchmarks

**Retrieval (recall@k):** LongMemEval 0.966 R@5 / 0.982 R@10 (500 questions), ConvoMem 0.960 (250 items), LoCoMo 0.649 R@10 (~2k questions); ~43ms/query, 112ms cross-session over 7,310 chunks.

**Product behavior:** integration suites green — decision capture (97.8% precision), error auto-capture (100% recall), compaction survival (6/6), multi-project isolation (11/11), edit-loop detection (12/12), session mining (64/64), Obsidian-vault compat (25/25).

Full tables and reproduction commands: **[library-book](./library-book/)**.

## Compatibility

| Platform | What Works | Auto-Capture |
|---|---|---|
| **Claude Code** (CLI, desktop, VS Code, JetBrains) | Everything | Full — hooks + session mining |
| **Cursor / Windsurf / Continue.dev / Zed / any MCP client** | MCP tools | No hooks |
| **Obsidian vaults** | Full (with CLAUDE.md at root) | Full with Claude Code |

## Install

```bash
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Core
pip install -e ".[semantic]"    # + embedding model for vector search and semantic scoring

python install.py               # Hooks, MCP server, /engram skill, migrations
```

### Per-Project Setup

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` to your project root. That's the only per-project file — hooks and the `/engram` skill are global. (The `CLAUDE.md` in this repo documents engram for people working *on* engram; your projects don't need it.)

### Updating

```bash
cd claude-engram
git pull
pip install -e ".[semantic]"    # Reinstall if dependencies changed
python install.py               # Re-run to update hooks and /engram skill
```

Hooks pick up code changes immediately (editable install); reconnect the MCP server (`/mcp`) to reload it. Data migrations run automatically and are forward-only, idempotent, and downgrade-safe.

### Mid-Project Adoption

Install normally. On first session, engram detects your existing Claude Code history and mines it in the background — decisions, mistakes, and patterns from every past conversation.

## Configuration

All optional. Deep detail on each lives in the [library-book](./library-book/).

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model — only `scout_search`, `memory(consolidate)`, `session_mine(reflect)` use it |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `BAAI/bge-base-en-v1.5` | Embedding model (~1.1GB scorer RAM). `all-MiniLM-L6-v2` for a ~90MB setup at lower accuracy |
| `CLAUDE_ENGRAM_EMBED_DIM` | model native | Matryoshka truncation dim. Stores are signature-stamped — model changes rebuild them automatically |
| `CLAUDE_ENGRAM_DEVICE` | smart | Unset: daemon stays on cpu, bulk jobs use a transient GPU worker (full VRAM release). `cuda`/`cpu` forces one device |
| `CLAUDE_ENGRAM_GPU_BULK_MIN` | `512` | Job size (texts) that routes to the GPU worker |
| `CLAUDE_ENGRAM_LIVE_MINE` | `300` | Live mining tick interval (seconds); `0` disables |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | Scorer daemon idle timeout (seconds) |
| `CLAUDE_ENGRAM_DIR` | `~/.claude_engram` | Storage location (also the test-isolation seam) |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `0` (keep all) | Prune session-search shards older than N days |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | unset | Mirror last-read file path to this file (statusline integration) |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | unset | `1` prints a stderr breadcrumb per hook |

`~/.claude_engram/config.json` additionally accepts `embed_model`, `embed_dim`, and `lessons_globs` (opt-in lessons bridge: globs of curated markdown whose dated entries sync as protected memories).

## Reindexing

If search quality degrades or after a big update:

```bash
python scripts/reindex.py "/path/to/your/workspace" --force            # rebuild search index
python scripts/reindex.py "/path/to/your/workspace" --force --extract  # also re-extract decisions/mistakes
```

Or via MCP: `session_mine(operation="reindex", mode="bootstrap")`

## Documentation

**[Library Book](./library-book/)** — design, internals, full usage guide, API reference, gotchas, changelog.

**`/engram`** — quick tool reference (installed by `install.py`).

## License

MIT

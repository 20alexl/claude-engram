# Claude Engram

Persistent memory for AI coding assistants. Auto-tracks mistakes, decisions, and context. Retrieves the right memory at the right time using hybrid search (keyword + vector + reranking). Works with any MCP-compatible tool.

## Benchmarks

### Retrieval benchmarks

Retrieval-only (recall@k). These measure whether the right memory is found in the top results — not end-to-end QA with answer generation and judge scoring, which is what the published LongMemEval leaderboard measures. MemPalace comparison uses the same retrieval-only methodology (their raw mode, no LLM reranking, top_k=10).

| Benchmark | Claude Engram | MemPalace (raw) |
|---|---|---|
| **LongMemEval** Recall@5 (500 questions) | 0.966 | 0.966 |
| **LongMemEval** Recall@10 | 0.982 | 0.982 |
| **LongMemEval** NDCG@10 | 0.889 | 0.889 |
| **ConvoMem** (250 items, 5 categories) | 0.960 | 0.929 |
| **LoCoMo** R@10 (1,986 questions, top_k=10) | 0.649 | 0.603 |
| **Speed** | 43ms/query | ~600ms/query |
| **Dependencies** | AllMiniLM (optional) | ChromaDB |

Reproduce: `python tests/bench_longmemeval.py`, `bench_locomo.py`, `bench_convomem.py`

### Integration benchmarks

These test what the product actually does — not just search retrieval.

| Benchmark | What it tests | Result |
|---|---|---|
| **Decision Capture** (220 prompts) | Auto-detect decisions from user prompts | 97.8% precision, 36.7% recall |
| **Injection Relevance** (50 memories, 15 cases) | Right memories surface before edits | 14/15 passed, 100% cross-domain isolation |
| **Compaction Survival** (6 scenarios) | Rules/mistakes survive context compression | 6/6 passed |
| **Error Auto-Capture** (53 payloads) | Extract errors, reject noise, deduplicate | 100% recall, 97% precision |
| **Multi-Project Scoping** (11 cases) | Sub-project isolation + workspace inheritance | 11/11 passed |
| **Edit Loop Detection** (12 scenarios) | Detect spirals vs iterative improvement | 12/12 passed |

Reproduce: `python tests/bench_integration.py` (runs from `tests/` directory)

### Comparison with MemPalace

Different approaches. MemPalace is a conversation archive with a spatial palace structure, knowledge graph, AAAK compression, and specialist agents. Claude Engram is live-capture: hooks into the coding lifecycle to auto-track mistakes, decisions, and context as you work. Comparable retrieval, different strengths.

## Compatibility

| Platform | What Works | Auto-Capture |
|---|---|---|
| **Claude Code** (CLI, desktop, VS Code, JetBrains) | Everything | Yes — 10 hook events |
| **Cursor** | MCP tools (memory, search, scope, etc.) | No hooks |
| **Windsurf** | MCP tools | No hooks |
| **Continue.dev** | MCP tools | No hooks |
| **Zed** | MCP tools | No hooks |
| **Any MCP client** | MCP tools | No hooks |
| **Python code** | `MemoryStore` SDK directly | N/A |

With Claude Code, hooks auto-capture mistakes, decisions, edits, test results, and session state. With other tools, you use the MCP tools manually — the memory system, hybrid search, archiving, and scoring all work the same.

## Features

- **Hybrid search** — keyword + AllMiniLM vector + reranking. No ChromaDB dependency.
- **Auto-tracks mistakes** from any failed tool. Warns before editing the same file.
- **Auto-captures decisions** from prompts ("let's use X") via semantic + regex scoring.
- **Detects edit loops** when the same file is edited 3+ times.
- **Survives compaction** — auto-checkpoint before, re-inject rules/mistakes after.
- **Tiered storage** — hot (fast) + archive (cold, searchable, restorable). Rules and mistakes never archive.
- **Scored injection** — top 3 memories by file match, tags, recency, importance before every edit.
- **Multi-project** — memories scoped per sub-project. Workspace rules cascade down.

## Install

```bash
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Core
pip install -e ".[semantic]"    # + AllMiniLM for vector search and decision capture

python install.py               # Configure hooks + MCP server
```

### Per-Project Setup

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` and `CLAUDE.md` to your project root.

### Mid-Project Adoption

Already deep in a project? Install normally, then tell your AI to dump what it knows:

```
Save everything you know about this project:
- memory(add_rule) for each project convention
- memory(remember) for key facts about the architecture
- work(log_decision) for decisions we've made and why
```

## Ollama (Optional)

Only needed for `scout_search`, `scout_analyze`, and LLM-based convention checking. Everything else works without it.

```bash
ollama pull gemma3:4b                    # or gemma3:12b for better semantic search
export CLAUDE_ENGRAM_MODEL="gemma3:4b"   # Linux/Mac
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | AllMiniLM server idle timeout (seconds) |

## Documentation

**[Library Book](./library-book/)** — design, internals, full usage guide, API reference, gotchas.

## License

MIT

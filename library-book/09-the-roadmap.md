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

## What's Next

- [ ] **Formal test suite** — pytest tests for memory, scoring, archiving, hooks, and sub-project resolution. Currently tested via benchmarks and inline scripts.
- [ ] **Split `remind.py`** — At ~2800 lines, it works but is hard to maintain. Split into `hooks/prompt.py`, `hooks/edit.py`, `hooks/bash.py`, etc.
- [ ] **Ollama-powered session summaries** — Use local LLM to generate human-readable session summaries instead of metadata-only.
- [ ] **Obsidian export** — Export session insights, decisions, and project timelines as Obsidian-compatible markdown with wikilinks.

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

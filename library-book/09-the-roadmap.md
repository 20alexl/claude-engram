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

## What's Next

- [ ] **Formal test suite** — pytest tests for memory, scoring, archiving, hooks, and sub-project resolution. Currently tested via inline scripts.
- [ ] **Split `remind.py`** — At ~2100 lines, it works but is hard to maintain. Split into `hooks/prompt.py`, `hooks/edit.py`, `hooks/bash.py`, etc.
- [ ] **Auto-capture from Bash output** — Targeted capture of useful command output (git status, dependency lists) without being noisy.
- [ ] **Conversation-aware memory** — Use the `Stop` hook's `last_assistant_message` to extract what Claude was working on and auto-summarize.

## What's Aspirational

- **Team memory sync** — Share rules and mistakes across team members via git-tracked memory files. Not clear yet how to scope this without leaking personal context.
- **Memory visualization** — A simple web UI showing memory clusters, scoring, and archive status. Would help debug injection behavior.
- **Smarter archiving** — LLM-powered archive decisions: "should this memory be archived or is it still relevant?" Currently uses simple age + access heuristics.
- **Cross-project learning** — When you fix a bug pattern in one project, suggest checking for the same pattern in others. Requires careful scoping to avoid noise.

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

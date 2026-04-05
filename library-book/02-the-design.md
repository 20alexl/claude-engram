# Chapter 2 — The Design

[← Back to Table of Contents](./README.md) · [Previous: The Why](./01-the-why.md) · [Next: Quick Start →](./03-quick-start.md)

---

## Design Principles

### 1. Automatic by default, manual when it matters

If something can be captured from a hook (errors, edits, test results, session boundaries), it should be. Claude should never have to invoke a tool for routine tracking. Manual invocation is reserved for semantic decisions that need LLM judgment: "this discovery is important," "this is now a project rule."

### 2. Inject context at the moment it's useful

Memories are worthless if they're buried in a database. The system surfaces the right memories at the right time: past mistakes before you edit a file, rules after compaction, decisions at session start. Relevance scoring (file match, tags, recency, importance) ensures you see the 3 most useful memories, not a dump of everything.

### 3. Never lose, always degrade gracefully

Memories are archived, not deleted. Rules and mistakes are protected from decay. Hot tier keeps things fast, cold tier keeps things safe. If the scorer server is down, regex fallback works. If Ollama is down, everything except semantic search still works. If a hook times out, it fails silently — never blocks Claude.

### 4. Scope memory to where it matters

In a multi-project workspace, editing `auth.py` in project A should surface project A's memories, not project B's. But workspace-level rules cascade down to all sub-projects. The system resolves sub-projects automatically from file paths.

### 5. Zero infrastructure beyond Ollama

No cloud services, no databases, no background daemons (except the optional ~90MB scorer server). Everything persists to flat JSON files in `~/.mini_claude/`. The MCP server runs as a stdio process managed by Claude Code. Hooks are plain Python scripts.

## Key Tradeoffs

| We Chose | Over | Because |
|----------|------|---------|
| File-based JSON storage | SQLite/Redis | Zero dependencies. Atomic writes via temp-then-replace. Good enough for hundreds of memories per project. |
| Hook-based auto-capture | Requiring manual tool invocations | Users won't call tools consistently. Hooks make tracking invisible. |
| Tiered hot/cold storage | Single memory file | Hot path (hooks) must be fast. Loading 1000 archived memories on every edit is too slow. |
| Regex + optional AllMiniLM | LLM-based intent scoring | Hooks have 2s timeout. LLM calls take 500ms+. AllMiniLM at ~5ms via server, regex at ~0ms, both fit the budget. |
| Workspace-aware sub-project scoping | Single flat memory namespace | Real workspaces have multiple projects. Cross-contamination makes memories useless. |
| Merge-safe hook installation | Overwriting settings.json | Users have other hooks. Destroying them is unacceptable. |

## What This Library Is NOT

- This is not an AI agent framework. It doesn't make decisions for Claude — it provides context so Claude makes better decisions.
- This is not a replacement for CLAUDE.md. Static rules belong in CLAUDE.md. Mini Claude tracks dynamic state that changes across sessions.
- If you need full-text search across thousands of documents, use a real search engine. Mini Claude's `scout_search` is for quick semantic queries against a codebase, not enterprise search.
- If you need real-time collaboration memory shared across team members, this isn't it. Memory is per-machine, stored locally.

---

[Next: Quick Start →](./03-quick-start.md)

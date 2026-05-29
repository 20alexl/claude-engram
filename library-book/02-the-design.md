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

In a multi-project workspace, editing `auth.py` in project A should surface project A's memories, not project B's. But workspace-level rules cascade down to all sub-projects. The system resolves sub-projects automatically from file paths. The same scoping applies to the code index (see Principle 6): each project gets its own symbol table; a workspace root does not bleed into sibling sub-projects.

### 5. Zero infrastructure beyond Ollama

No cloud services, no databases, no background daemons (except the optional ~90MB scorer server). Everything persists to flat JSON files in `~/.claude_engram/`. The MCP server runs as a stdio process managed by Claude Code. Hooks are plain Python scripts.

### 6. Proactive code awareness — no LLM, no latency

After each session the background miner builds a per-project code index (pure `ast`, no LLM, incremental by mtime). That index is then used at pre-edit time to answer two questions automatically:

- **Are the imports in the proposed edit valid?** If a name being imported is not exported by the target module, a terse `<engram-precheck>` banner is injected before the edit, with the closest-match suggestion. Advisory only — wrong imports aren't blocked, just flagged.
- **What is the blast radius of this edit?** If the file being edited is imported by two or more other modules in the project, a `<engram-blast-radius>` banner lists those dependents, drawn from the cached reverse-edge map (no filesystem walk at hook time).

Both checks are LLM-free, fit comfortably inside the hook timeout, and degrade silently when the index is missing or stale. The `impact_analyze` tool also reads this cache (falling back to a regex scan only when the file is not indexed).

A fourth signal — the outcome feedback loop — logs which injection kinds (memory, prediction, precheck, blast) preceded passing vs failing tests, so injection precision is measurable rather than assumed. `session_mine(reflect)` surfaces this report plus LLM-synthesized insights from recurring mistakes.

## Key Tradeoffs

| We Chose | Over | Because |
|----------|------|---------|
| File-based JSON storage | SQLite/Redis | Zero dependencies. Atomic writes via temp-then-replace. Good enough for hundreds of memories per project. |
| Hook-based auto-capture | Requiring manual tool invocations | Users won't call tools consistently. Hooks make tracking invisible. |
| Tiered hot/cold storage | Single memory file | Hot path (hooks) must be fast. Loading 1000 archived memories on every edit is too slow. |
| Regex + optional AllMiniLM | LLM-based intent scoring | Hooks have 2s timeout. LLM calls take 500ms+. AllMiniLM at ~5ms via server, regex at ~0ms, both fit the budget. |
| Workspace-aware sub-project scoping | Single flat memory namespace | Real workspaces have multiple projects. Cross-contamination makes memories useless. |
| Merge-safe hook installation | Overwriting settings.json | Users have other hooks. Destroying them is unacceptable. |
| Pure `ast` for code index + precheck | LLM-based code analysis | LLM is too slow for pre-edit hooks. `ast` is deterministic, fast, and produces zero false-positives on syntax errors (returns None, leaves prior record in place). |
| Advisory-only import warnings | Blocking edits on unresolved imports | A wrong proactive warning trains the agent to ignore the channel. Conservative silence is safer than a noisy false positive. |
| Per-session hook state files keyed by session_id | Single shared hook_state.json | Two concurrent sessions from one workspace otherwise clobber each other's loop counters and injection logs. |

## What This Library Is NOT

- This is not an AI agent framework. It doesn't make decisions for Claude — it provides context so Claude makes better decisions.
- This is not a replacement for CLAUDE.md. Static rules belong in CLAUDE.md. Claude Engram tracks dynamic state that changes across sessions.
- If you need full-text search across thousands of documents, use a real search engine. Claude Engram's `scout_search` is for quick semantic queries against a codebase, not enterprise search.
- If you need real-time collaboration memory shared across team members, this isn't it. Memory is per-machine, stored locally.

---

[Next: Quick Start →](./03-quick-start.md)

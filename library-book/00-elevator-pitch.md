# Chapter 0 — The Elevator Pitch

[← Back to Table of Contents](./README.md) · [Next: The Why →](./01-the-why.md)

---

## What is Claude Engram?

Claude Engram gives Claude Code persistent memory across sessions. It automatically tracks your mistakes, decisions, and context through Claude Code's hook system, then surfaces the right information at the right time — before you edit a file, after an error, or when context gets compacted. It also builds a per-project code index (symbol table, imports, reverse-dependency edges) and uses it to warn proactively about broken imports before edits land. A local LLM (via Ollama) powers semantic code search and analysis, but the core system — hooks, memory, code index, pre-edit checks — runs without it.

## Who is it for?

Anyone using Claude Code for serious work across multiple sessions. If you've ever had Claude break the same thing twice because it forgot the first time, or lost all context after a compaction, Claude Engram is for you.

## What does it replace?

Before Claude Engram, you either:
- Started every session from scratch, re-explaining project rules and past mistakes
- Manually maintained a CLAUDE.md with rules and hoped Claude read it
- Lost all working context when the conversation compacted
- Had no way to detect when Claude was stuck in an edit loop

## Show Me

```python
# Everything below happens automatically via hooks. Zero invocations needed.

# When you start a session:
#   → Claude Engram loads rules, past mistakes, checkpoints, and handoffs

# When the user says "let's switch to PostgreSQL instead of SQLite":
#   → Auto-captured as a decision memory

# Before every Edit/Write:
#   → Past mistakes for this file are surfaced
#   → Loop detection warns at 3+ edits
#   → The 3 most relevant memories are injected, ranked by file match + recency
#   → If the edit adds an import that doesn't resolve (Python), a warning fires
#   → If the file being edited is imported by other modules, those importers are listed

# When a Bash command fails:
#   → The error is auto-logged as a mistake (ImportError, TypeError, etc.)
#   → Test failures are auto-tracked

# Before context compaction:
#   → Checkpoint auto-saved with task state and files in progress

# After compaction:
#   → Rules, mistakes, and recent decisions re-injected into context

# When the session stops:
#   → Handoff saved with last assistant message for next session
#   → Code index updated incrementally (changed files only)
```

## The One-Liner

> Persistent memory, mistake tracking, proactive code-awareness, and context survival for Claude Code — mostly automatic, powered by hooks.

---

[Next: The Why →](./01-the-why.md)

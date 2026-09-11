# Chapter 1: The Why

[← Back to Table of Contents](./README.md) · [Previous: Elevator Pitch](./00-elevator-pitch.md) · [Next: The Design →](./02-the-design.md)

---

## The problem

Claude Code is stateless. Every session starts blank. After context compaction, everything is gone: the file you were editing, the bug you just fixed, the decision you made about the architecture. This creates four concrete failures:

1. **Repeated mistakes.** Claude breaks the same thing twice because it doesn't remember breaking it the first time. Nothing tells it that this approach was already tried and already failed.

2. **Lost context on compaction.** Long sessions compact the conversation and drop what Claude learned about the codebase. Rules from CLAUDE.md fade, and earlier decisions go with them.

3. **Death spiral loops.** Claude edits the same file 5+ times, trying the same approach that keeps failing. Nothing detects that it has been here before.

4. **Session amnesia.** When you start a new session, Claude has no context about what happened last time, because nothing hands over a checkpoint or a summary from the previous one.

## What exists already

| Approach | What It Gets Right | Where It Falls Short |
|----------|-------------------|---------------------|
| CLAUDE.md files | Static rules persist across sessions | Can't track dynamic state (what was I doing?). Gets ignored as context grows. No mistake tracking. |
| Claude Code's built-in memory | Auto-generates memories from conversations | No structured mistake/decision tracking. No pre-edit injection. No compaction survival. No loop detection. |
| Manual note-taking | User writes notes in files | Requires discipline. Claude can't auto-surface notes at the right moment. Doesn't scale. |
| MCP servers (general) | Extend Claude's capabilities | None specifically solve the memory + mistake tracking + compaction survival problem as an integrated system. |

## The gap

Nobody is intercepting Claude's tool calls to build a structured memory of mistakes, decisions, and context, then injecting the right memories at the right moment (before an edit, after an error, on compaction). That is what Claude Engram does.

---

[Next: The Design →](./02-the-design.md)

# Chapter 1 — The Why

[← Back to Table of Contents](./README.md) · [Previous: Elevator Pitch](./00-elevator-pitch.md) · [Next: The Design →](./02-the-design.md)

---

## The Problem

Claude Code is stateless. Every session starts blank. After context compaction, everything is gone — the file you were editing, the bug you just fixed, the decision you made about the architecture. This creates four concrete failures:

1. **Repeated mistakes.** Claude breaks the same thing twice because it doesn't remember breaking it the first time. There's no "hey, you tried this before and it failed" signal.

2. **Lost context on compaction.** Long sessions compact the conversation, dropping everything Claude learned about the codebase. Rules from CLAUDE.md fade. Decisions evaporate.

3. **Death spiral loops.** Claude edits the same file 5+ times, trying the same approach that keeps failing. There's no "you've been here before" detector.

4. **Session amnesia.** When you start a new session, Claude has zero context about what happened last time. No handoff, no checkpoint, no continuity.

## What Exists Already

| Approach | What It Gets Right | Where It Falls Short |
|----------|-------------------|---------------------|
| CLAUDE.md files | Static rules persist across sessions | Can't track dynamic state (what was I doing?). Gets ignored as context grows. No mistake tracking. |
| Claude Code's built-in memory | Auto-generates memories from conversations | No structured mistake/decision tracking. No pre-edit injection. No compaction survival. No loop detection. |
| Manual note-taking | User writes notes in files | Requires discipline. Claude can't auto-surface notes at the right moment. Doesn't scale. |
| MCP servers (general) | Extend Claude's capabilities | None specifically solve the memory + mistake tracking + compaction survival problem as an integrated system. |

## The Gap

Nobody is intercepting Claude's tool calls to automatically build a structured memory of mistakes, decisions, and context — then injecting the right memories at the right moment (before an edit, after an error, on compaction). That's what Claude Engram does.

---

[Next: The Design →](./02-the-design.md)

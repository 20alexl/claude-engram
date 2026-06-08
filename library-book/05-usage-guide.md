# Chapter 5 — Usage Guide

[← Back to Table of Contents](./README.md) · [Previous: The Internals](./04-the-internals.md) · [Next: Advanced Usage →](./06-advanced-usage.md)

---

## Overview

Most of Claude Engram works automatically via hooks. This chapter covers the MCP tools you invoke manually — organized by what you're trying to do.

---

## Saving Knowledge

### Remember a Discovery

```python
memory(operation="remember", content="The auth module validates JWTs in middleware, not in individual routes", project_path="/path")
```

Discoveries are auto-tagged by content (auth, testing, database, etc.) and scored for relevance injection.

### Add a Permanent Rule

```python
memory(operation="add_rule", content="Always use parameterized queries, never string interpolation for SQL", reason="SQL injection prevention", project_path="/path")
```

Rules are never archived, never decayed, and always surfaced at session start and in pre-edit injection with a +0.3 scoring bonus.

### Log a Decision

```python
work(operation="log_decision", decision="Use FastAPI instead of Flask", reason="Async support and auto-generated OpenAPI docs", alternatives=["Flask + async extensions", "Django REST"])
```

Decisions are also auto-captured from user prompts. Use manual logging for complex decisions with alternatives.

### Log a Mistake

```python
work(operation="log_mistake", description="Removed the session validation middleware thinking it was unused", file_path="auth/middleware.py", how_to_avoid="Check all route files for middleware references before removing")
```

Most mistakes are auto-captured from `PostToolUseFailure` hooks. Use manual logging for logical mistakes that don't produce errors.

---

## Finding Memories

### Search by Keyword

```python
memory(operation="search", query="authentication", project_path="/path")
```

### Search by File

```python
memory(operation="search", file_path="auth/middleware.py", project_path="/path")
```

### Search by Tags

```python
memory(operation="search", tags=["auth", "security"], project_path="/path")
```

### View Recent

```python
memory(operation="recent", project_path="/path", limit=10)
```

Shows memories newest-first with IDs for management.

---

## Managing Memories

Memory IDs are shown in `[brackets]` at session start and in hook output.

### Edit a Memory

```python
memory(operation="modify", memory_id="abc123", content="Updated understanding of auth flow", project_path="/path")
memory(operation="modify", memory_id="abc123", relevance=9, project_path="/path")
```

### Delete

```python
memory(operation="delete", memory_id="abc123", project_path="/path")
memory(operation="batch_delete", memory_ids=["id1", "id2"], project_path="/path")
memory(operation="batch_delete", category="context", project_path="/path")  # Bulk by category
```

### Promote to Rule

```python
memory(operation="promote", memory_id="abc123", reason="This applies to all future work", project_path="/path")
```

### Cleanup (Dedupe + Archive)

```python
memory(operation="cleanup", dry_run=True, project_path="/path")   # Preview
memory(operation="cleanup", dry_run=False, project_path="/path")  # Apply
```

---

## Safety Checks

### Before Editing (automatic)

Before every Edit or Write, hooks fire automatically:

- **Memory injection** — top 3 scored memories for the file are shown (`<engram-context>`)
- **Import/export check** — if an import won't resolve (name not exported, module not found), you get a terse `<engram-precheck>` warning with the closest suggestion (Python only, advisory)
- **Blast-radius** — if the file is imported by 2 or more other modules, the importers are listed (`<engram-blast-radius>`) so you see the damage radius before touching it
- **Loop warning** — fires when the same file has been edited 3+ times without a passing test

You rarely need to call `pre_edit_check` manually. It's available for an explicit impact check:

```python
# Rarely needed — the PreToolUse hook runs this automatically
pre_edit_check(file_path="auth/middleware.py")
```

Memory injection is path-aware: a mistake stored for `service-a/auth/middleware.py` will not fire when editing `service-b/auth/middleware.py` even if the basename matches. Generic filenames (`__init__.py`, `index.js`) require a full-path signal; specific filenames still match by name.

### Declare Scope

```python
scope(operation="declare", task_description="Fix the login bug", in_scope_files=["auth/login.py", "auth/session.py"])
scope(operation="check", file_path="database/models.py")  # "OUT OF SCOPE"
scope(operation="expand", files_to_add=["database/models.py"], reason="Login query needs model changes")
```

### Check Loop Status

```python
loop(operation="status")   # See edit counts per file
loop(operation="reset")    # Clear after changing approach
```

---

## Context Protection

Checkpoints and handoffs are one construct (a durable ring buffer). `checkpoint_*` are the primary names; `handoff_*` exist as deprecated aliases for back-compat.

### Save a Checkpoint

```python
context(operation="checkpoint_save", task_description="Refactoring auth module", current_step="Updating middleware", completed_steps=["Extracted JWT validation", "Added tests"], pending_steps=["Update routes", "Migration"], files_involved=["auth/middleware.py", "auth/jwt.py"])
```

Add `handoff_summary`, `handoff_context_needed`, and `handoff_warnings` to bridge the state to the next session (emits HANDOFF.md):

```python
context(operation="checkpoint_save", task_description="Auth refactor", handoff_summary="Auth refactor 60% done. Middleware updated, routes pending.", handoff_context_needed=["JWT validation moved from routes to middleware"], handoff_warnings=["Don't edit auth/legacy.py — being removed in next PR"])
```

### Restore a Checkpoint

```python
# Restore the latest checkpoint
context(operation="checkpoint_restore")

# Restore an older entry by index (0 = latest, 1 = previous, ...)
context(operation="checkpoint_restore", index=2)
```

### Browse Checkpoint History

```python
# List all checkpoints newest-first with index, age, kind (manual|auto), and summary
context(operation="checkpoint_list", project_path="/path")
```

---

## Code Analysis (requires Ollama)

### Semantic Search

```python
scout_search(query="how does the payment processing work", directory="/path/to/project")
```

Reads actual code files, uses LLM to find semantically relevant results. Better than grep for natural language queries.

### Impact Analysis

```python
impact_analyze(file_path="models/user.py", project_root="/path")
```

Shows what depends on a file, what it exports, and risk level for changes.

### Audit Files (LLM)

```python
# Audit one or more files for bugs, missing error handling, security issues, TODOs, anti-patterns
audit_batch(file_paths=["src/auth.py", "src/models/*.py"], min_severity="warning")
```

`min_severity`: `"critical"` (bugs only) | `"warning"` (bugs + smells) | `"info"` (everything).

### Lint a Code Snippet (no LLM)

```python
# Fast structural/naming lint of an inline snippet — no I/O, no Ollama required
audit_batch(code="def f(a,b,c,d,e,f): ...", language="python")
```

Checks long functions, vague names, deep nesting, too many parameters. Use this for quick checks before committing a block of new code.

---

## Recipes

### Start of a new session

Nothing to do — `SessionStart` hook auto-loads context. For deep load:

```python
session_start(project_path="/path")
```

### Before a big refactor

```python
scope(operation="declare", task_description="Refactor auth to use JWT", in_scope_files=["auth/*"])
impact_analyze(file_path="auth/middleware.py", project_root="/path")
context(operation="checkpoint_save", task_description="Auth refactor", pending_steps=["..."])
```

### After fixing a tricky bug

```python
work(operation="log_mistake", description="The retry logic was using the wrong backoff formula", how_to_avoid="Check the backoff calculation matches the spec in RFC 7231")
memory(operation="remember", content="The retry module uses exponential backoff with jitter — base * 2^attempt + random(0, base)", project_path="/path")
```

### Memory getting cluttered

```python
memory(operation="archive_status", project_path="/path")  # Check counts
memory(operation="cleanup", dry_run=True, project_path="/path")  # Preview
memory(operation="cleanup", dry_run=False, project_path="/path")  # Apply
```

---

[Next: Advanced Usage →](./06-advanced-usage.md)

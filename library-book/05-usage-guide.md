# Chapter 5 — Usage Guide

[← Back to Table of Contents](./README.md) · [Previous: The Internals](./04-the-internals.md) · [Next: Advanced Usage →](./06-advanced-usage.md)

---

## Overview

Most of Mini Claude works automatically via hooks. This chapter covers the MCP tools you invoke manually — organized by what you're trying to do.

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

### Before Editing (usually automatic)

```python
pre_edit_check(file_path="auth/middleware.py")
```

Returns: past mistakes for this file, loop risk level, scope status, and scored contextual memories.

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

### Save a Checkpoint

```python
context(operation="checkpoint_save", task_description="Refactoring auth module", current_step="Updating middleware", completed_steps=["Extracted JWT validation", "Added tests"], pending_steps=["Update routes", "Migration"], files_involved=["auth/middleware.py", "auth/jwt.py"])
```

### Create a Handoff

```python
context(operation="handoff_create", handoff_summary="Auth refactor 60% done. Middleware updated, routes pending.", next_steps=["Update route handlers to use new middleware", "Run full test suite"], handoff_context_needed=["The JWT validation was moved from routes to middleware"], handoff_warnings=["Don't edit auth/legacy.py — it's being removed in the next PR"])
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

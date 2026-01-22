# Mini Claude - For Claude Code

Mini Claude gives you **persistent memory** that survives context compaction.

## The Problem It Solves

You (Claude Code) have a critical weakness: **you forget everything between sessions and after context compaction**. This means you:

- Repeat the same mistakes over and over
- Forget why code is structured the way it is
- Lose track of multi-step tasks when context gets summarized
- Can't learn from past errors on a project

Mini Claude fixes this with persistent storage that you can read and write to.

---

## What's Actually Useful

### 1. Checkpoint Restore (Killer Feature)

When context gets compacted, you lose your working memory. But if you saved a checkpoint, `session_start` restores it automatically.

```python
# Before long tasks - save your state
mcp__mini-claude__context(
  operation="checkpoint_save",
  task_description="Implementing auth system",
  current_step="Adding JWT validation",
  completed_steps=["Created user model", "Added login endpoint"],
  pending_steps=["Add refresh tokens", "Add logout"],
  files_involved=["auth.py", "models.py"]
)

# After compaction - get it back
mcp__mini-claude__session_start(project_path="/path/to/project")
# ^ This shows your checkpoint automatically!
```

### 2. Mistake Memory

Log mistakes so you don't repeat them next session:

```python
mcp__mini-claude__work(
  operation="log_mistake",
  description="Forgot to handle None case in user lookup",
  file_path="auth.py",
  how_to_avoid="Always check if user exists before accessing attributes"
)
```

Next time you edit `auth.py`, you'll see this warning.

### 3. Decision Memory

Log WHY you made choices:

```python
mcp__mini-claude__work(
  operation="log_decision",
  decision="Using JWT instead of sessions",
  reason="Stateless API, easier horizontal scaling"
)
```

### 4. Pre-Edit Safety Check

Before editing important files:

```python
mcp__mini-claude__pre_edit_check(file_path="auth.py")
```

This checks:

- Past mistakes with this file
- Loop detection (editing too many times?)
- Scope violations

### 5. Impact Analysis

Before changing a file, see what depends on it:

```python
mcp__mini-claude__impact_analyze(
  file_path="models/user.py",
  project_root="/path/to/project"
)
```

### 6. Code Search (Now Actually Works)

Search the codebase semantically - it reads actual code, not just filenames:

```python
mcp__mini-claude__scout_search(
  query="authentication middleware",
  directory="/path/to/project"
)
```

### 7. Think Tools

For complex decisions:

```python
# Challenge your assumptions
mcp__mini-claude__think(operation="challenge", assumption="We need a database")

# Audit a file for issues
mcp__mini-claude__think(operation="audit", file_path="auth.py")

# Research with actual codebase context
mcp__mini-claude__think(
  operation="research",
  question="How does error handling work in this codebase?",
  project_path="/path/to/project"
)
```

---

## Session Workflow

### Start of Session

```python
mcp__mini-claude__session_start(project_path="/path/to/project")
```

This loads: memories, past mistakes, saved checkpoint (if any).

### During Work

- `pre_edit_check` before editing important files
- `work(log_mistake)` when something breaks
- `work(log_decision)` for architectural choices
- `context(checkpoint_save)` before long tasks

### End of Session

```python
mcp__mini-claude__session_end(project_path="/path/to/project")
```

---

## Quick Reference

| When | What to Call |
|------|--------------|
| Start session | `session_start(project_path)` |
| Before editing | `pre_edit_check(file_path)` |
| Something broke | `work(operation="log_mistake", ...)` |
| Made a decision | `work(operation="log_decision", ...)` |
| Before long task | `context(operation="checkpoint_save", ...)` |
| Lost context | `context(operation="checkpoint_restore")` |
| Check dependencies | `impact_analyze(file_path, project_root)` |
| End session | `session_end(project_path)` |

---

## All Tools

### Essential

| Tool | Purpose |
|------|---------|
| `session_start` | Load memories + checkpoint |
| `session_end` | Save work summary |
| `pre_edit_check` | Safety check before editing |

### Memory

| Operation | Purpose |
|-----------|---------|
| `memory(remember)` | Store a discovery/note |
| `memory(search)` | Find memories by file/tag/query |
| `memory(clusters)` | View grouped memories |

### Work Tracking

| Operation | Purpose |
|-----------|---------|
| `work(log_mistake)` | Record errors to avoid |
| `work(log_decision)` | Record why you chose something |

### Context Protection

| Operation | Purpose |
|-----------|---------|
| `context(checkpoint_save)` | Save task state |
| `context(checkpoint_restore)` | Restore after compaction |

### Analysis

| Tool | Purpose |
|------|---------|
| `impact_analyze` | See what depends on a file |
| `deps_map` | Map file dependencies |
| `scout_search` | Search codebase semantically |

### Thinking

| Operation | Purpose |
|-----------|---------|
| `think(research)` | Research with codebase context |
| `think(audit)` | Find issues in a file |
| `think(challenge)` | Challenge assumptions |
| `think(compare)` | Compare options |

---

## When Context Gets Compacted

If you're writing a continuation summary, include:

```text
MINI CLAUDE: Call session_start(project_path="...") to restore checkpoint.
```

This ensures you (or the next Claude) remembers to check for saved state.

---

## Technical Notes

- Runs locally with Ollama (`qwen2.5-coder:7b`)
- State stored in `~/.mini_claude/`
- Hooks are context-aware (won't spam you every message)
- Search tools read actual code, not just filenames

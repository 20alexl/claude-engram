# Mini Claude - For Claude Code

Persistent memory that survives context compaction. Also: loop detection, scope guards, code analysis, and a local LLM for second opinions.

## The Problem

You forget everything between sessions and after context compaction:

- Repeat the same mistakes
- Forget why code is structured a certain way
- Lose track of multi-step tasks
- Can't learn from past errors

Mini Claude stores state locally and gives you tools to avoid these problems.

---

## Core Features

### 1. Checkpoint Restore

Save task state before long work. After compaction, `session_start` restores it.

```python
mcp__mini-claude__context(
  operation="checkpoint_save",
  task_description="Implementing auth system",
  current_step="Adding JWT validation",
  completed_steps=["Created user model", "Added login endpoint"],
  pending_steps=["Add refresh tokens", "Add logout"],
  files_involved=["auth.py", "models.py"]
)

# After compaction - restored automatically
mcp__mini-claude__session_start(project_path="/path/to/project")
```

### 2. Mistake Memory

Log mistakes. They show up in `pre_edit_check` and `session_start`.

```python
mcp__mini-claude__work(
  operation="log_mistake",
  description="Forgot to handle None case in user lookup",
  file_path="auth.py",
  how_to_avoid="Always check if user exists before accessing attributes"
)
```

### 3. Decision Memory

Log WHY you chose something. Future you will thank you.

```python
mcp__mini-claude__work(
  operation="log_decision",
  decision="Using JWT instead of sessions",
  reason="Stateless API, easier horizontal scaling"
)
```

### 4. Loop Detection

Warns when you're editing the same file too many times (death spiral prevention).

```python
mcp__mini-claude__loop(operation="check", file_path="auth.py")
# Returns warning if you've edited this file 3+ times
```

### 5. Scope Guard

Declare what files you're allowed to touch. Prevents over-refactoring.

```python
mcp__mini-claude__scope(
  operation="declare",
  task_description="Fix login bug",
  in_scope_files=["auth.py", "login.py"]
)
# Now pre_edit_check warns if you try to edit other files
```

### 6. Impact Analysis

See what depends on a file before changing it.

```python
mcp__mini-claude__impact_analyze(
  file_path="models/user.py",
  project_root="/path/to/project"
)
```

### 7. Convention Storage

Store project rules. Check code against them.

```python
mcp__mini-claude__convention(
  operation="add",
  project_path="/path/to/project",
  rule="All API endpoints must return JSON with 'data' and 'error' keys",
  category="pattern",
  reason="Consistent API responses"
)

# Later: check if code follows conventions
mcp__mini-claude__code_pattern_check(
  project_path="/path/to/project",
  code="def get_user(): return user"
)
```

### 8. Code Quality Checks

Detect AI slop: long functions, vague names, deep nesting.

```python
mcp__mini-claude__code_quality_check(code="def foo(): ...")
```

### 9. Think Tools (Local LLM)

Get a second opinion from a local 7B model. Different perspective, not better.

```python
# Challenge assumptions
mcp__mini-claude__think(operation="challenge", assumption="We need a database")

# Audit a file
mcp__mini-claude__think(operation="audit", file_path="auth.py")

# Research (now reads actual code)
mcp__mini-claude__think(
  operation="research",
  question="How does error handling work?",
  project_path="/path/to/project"
)

# Compare options
mcp__mini-claude__think(
  operation="compare",
  options=["Redis cache", "In-memory cache", "File cache"],
  context="Need caching for API responses",
  criteria=["speed", "simplicity", "persistence"]
)
```

### 10. Output Validation

Check if generated code might silently fail.

```python
mcp__mini-claude__output(
  operation="validate_code",
  code="try: ... except: pass",
  context="Error handling"
)
```

---

## Session Workflow

### Start

```python
mcp__mini-claude__session_start(project_path="/path/to/project")
```

Loads: memories, mistakes, checkpoint (if any).

### During Work

- `pre_edit_check(file_path)` before editing important files
- `work(log_mistake)` when something breaks
- `work(log_decision)` for choices
- `context(checkpoint_save)` before long tasks
- `scope(declare)` for multi-file changes

### End

```python
mcp__mini-claude__session_end(project_path="/path/to/project")
```

---

## All Tools

### Session

| Tool | Purpose |
|------|---------|
| `session_start` | Load memories, mistakes, checkpoint |
| `session_end` | Save work summary |
| `pre_edit_check` | Check mistakes, loops, scope before editing |

### Memory

| Operation | Purpose |
|-----------|---------|
| `memory(remember)` | Store discovery/note |
| `memory(search)` | Find by file/tag/query |
| `memory(clusters)` | View grouped memories |
| `memory(cleanup)` | Dedupe and decay old memories |

### Work Tracking

| Operation | Purpose |
|-----------|---------|
| `work(log_mistake)` | Record error + how to avoid |
| `work(log_decision)` | Record choice + reasoning |

### Context Protection

| Operation | Purpose |
|-----------|---------|
| `context(checkpoint_save)` | Save task state |
| `context(checkpoint_restore)` | Restore after compaction |
| `context(verify_completion)` | Verify task is actually done |

### Scope & Loop

| Tool | Purpose |
|------|---------|
| `scope(declare)` | Set allowed files for task |
| `scope(check)` | Verify file is in scope |
| `loop(check)` | Check if editing too much |
| `loop(status)` | See edit counts |

### Code Analysis

| Tool | Purpose |
|------|---------|
| `impact_analyze` | What depends on this file |
| `deps_map` | Map imports/dependencies |
| `scout_search` | Semantic codebase search |
| `scout_analyze` | Analyze code snippet with LLM |
| `file_summarize` | Quick file purpose summary |
| `code_quality_check` | Detect AI slop |
| `code_pattern_check` | Check against conventions |
| `audit_batch` | Audit multiple files |
| `find_similar_issues` | Find bug patterns in codebase |

### Think (Local LLM)

| Operation | Purpose |
|-----------|---------|
| `think(research)` | Research with codebase context |
| `think(compare)` | Evaluate options |
| `think(challenge)` | Devil's advocate |
| `think(explore)` | Solution space |
| `think(audit)` | Find issues in file |
| `think(best_practice)` | Find patterns for topic |

### Conventions

| Operation | Purpose |
|-----------|---------|
| `convention(add)` | Store project rule |
| `convention(get)` | Get rules by category |
| `convention(check)` | Check code against rules |

### Validation

| Operation | Purpose |
|-----------|---------|
| `output(validate_code)` | Check for silent failures |
| `output(validate_result)` | Check output format |

### Git

| Operation | Purpose |
|-----------|---------|
| `git(commit_message)` | Generate from work logs |

---

## When Context Gets Compacted

Include in continuation summary:

```text
MINI CLAUDE: Call session_start(project_path="...") to restore checkpoint.
```

---

## Technical Notes

- Runs locally with Ollama (`qwen2.5-coder:7b`)
- State stored in `~/.mini_claude/`
- Hooks are context-aware (won't spam every message)
- Search/research tools read actual code

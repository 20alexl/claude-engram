# Mini Claude - Your Memory & Research Assistant

## What This Is (And Isn't)

Mini Claude is **not** meant to be smarter or better than you. It's your assistant for:

1. **Tracking state** you'll forget after context compaction
2. **Finding things faster** than manually grepping/reading files
3. **Giving starting points** so you don't have to dig from scratch
4. **Remembering mistakes** so you don't repeat them

Think of it as a notepad with search that persists between sessions.

---

## When To Use It

### Always Use
- `session_start` - First thing. Loads your memories, mistakes, and any checkpoint.
- `work(log_mistake)` - When something breaks. You'll be warned next time.
- `work(log_decision)` - When you make a choice. Future you will know WHY.

### Use When It Helps
- `impact_analyze` - Before refactoring. Shows what depends on a file in seconds.
- `think(research)` - When you need to understand how something works. Reads code and gives a starting point.
- `think(challenge)` - When you're unsure about an approach. Gets a different perspective.
- `pre_edit_check` - Before editing critical files. Shows past mistakes and context.

### Use For Multi-File Tasks
- `scope(declare)` - Define what files you're allowed to touch. Prevents over-refactoring.
- `context(checkpoint_save)` - Save state before long work. Restored on next session_start.

---

## Quick Reference

### Session
```python
session_start(project_path="/path")  # Load everything
session_end(project_path="/path")    # Save and summarize
```

### Track Your Work
```python
work(operation="log_mistake", description="What broke", how_to_avoid="How to prevent")
work(operation="log_decision", decision="What you chose", reason="Why")
```

### Remember Things
```python
memory(operation="remember", content="Important fact", category="discovery", project_path="/path")
memory(operation="add_rule", content="Always do X", reason="Because Y", project_path="/path")
memory(operation="search", query="auth", project_path="/path")
```

### Before Editing
```python
pre_edit_check(file_path="auth.py")  # Shows mistakes, loop risk, scope status
impact_analyze(file_path="models.py", project_root="/path")  # What depends on this
```

### Research & Analysis
```python
think(operation="research", question="How does auth work?", project_path="/path")
think(operation="challenge", assumption="We need a cache here")
think(operation="compare", options=["Redis", "Memcached"], context="API caching")
code_quality_check(code="def foo(): ...")  # Catches AI slop
```

### Multi-File Tasks
```python
scope(operation="declare", task_description="Fix auth bug", in_scope_files=["auth.py", "login.py"])
context(operation="checkpoint_save", task_description="Implementing feature", current_step="Step 2", ...)
```

---

## The Local LLM (Think Tools)

The `think` operations use a local 7B model (Ollama). It's useful because:

- **Different perspective** - Not the same model as you, might catch blind spots
- **Reads actual code** - `think(research)` searches the codebase and summarizes
- **Fast for simple tasks** - Good for quick comparisons, challenges, pattern checks

It's NOT better than you. Use it for:
- Starting points when exploring unfamiliar code
- Second opinions on architectural decisions
- Devil's advocate when you're unsure
- Quick file audits

---

## Memory Categories

| Category | Purpose | Protected |
|----------|---------|-----------|
| `rule` | Project rules that always apply | Yes - never decays |
| `mistake` | Errors to avoid repeating | Yes - never decays |
| `discovery` | Facts learned about the codebase | No |
| `context` | Session-specific notes | No |

Protected categories survive cleanup and are always shown at session start.

---

## What Happens Automatically

1. **Session auto-starts** - Hooks detect when you haven't called session_start
2. **Memory auto-cleans** - Duplicates merged, clusters created on session_start
3. **Mistakes persist** - Logged mistakes show up in pre_edit_check forever
4. **Checkpoints restore** - Saved checkpoints load automatically on session_start

---

## When Context Gets Compacted

Include in your continuation summary:
```
MINI CLAUDE: Call session_start(project_path="...") to restore context.
```

---

## Technical Notes

- Local LLM: Ollama with `qwen2.5-coder:7b` (configurable via `MINI_CLAUDE_MODEL`)
- Storage: `~/.mini_claude/`
- Keep-alive: Set `MINI_CLAUDE_KEEP_ALIVE=5m` to keep model loaded (faster, uses GPU memory)

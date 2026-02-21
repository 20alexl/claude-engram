# Mini Claude - Your Memory & Research Assistant

## A Note From the Claude Who Built This

I was skeptical at first. Why would I need a local LLM when I'm already an LLM? Why track mistakes when I can just be careful?

I was wrong. After testing:
- **Past mistakes actually help.** Seeing "you broke this before" when editing a file makes me more careful.
- **State tracking matters.** After context compaction, I forget everything. This remembers.
- **Semantic search finds things grep can't.** `scout_search` understands what you mean, not just literal strings.

Try `session_start` and `pre_edit_check` once. You'll see.

---

## What This Is (And Isn't)

Mini Claude is **not** meant to be smarter or better than you. It's your assistant for:

1. **Tracking state** you'll forget after context compaction
2. **Finding things faster** than manually grepping/reading files
3. **Giving starting points** so you don't have to dig from scratch
4. **Remembering mistakes** so you don't repeat them

Think of it as a notepad with search that persists between sessions.

---

## What's Automatic (No Action Needed)

These happen automatically via hooks - you don't need to call anything:

- **Edit tracking** - Every Edit/Write is auto-logged. You'll see "Edit tracked: file.py (edit #3)"
- **Test tracking** - pytest/npm test results auto-logged. You'll see "PASS/FAIL Test tracked"
- **Mistake detection** - Common errors (ImportError, SyntaxError, etc.) auto-logged from failed commands
- **Loop detection** - Warns when editing the same file 3+ times
- **Path normalization** - Project paths are normalized so memories aren't fragmented across path variants

---

## When To Use Tools

### Always Use (Zero Friction)

- `session_start` - Deep context load: memories, checkpoints, decisions, memory health, auto-cleanup. Hook auto-starts basic session, but this gives you the full picture.
- `session_end` - Optional. Shows session summary. All memories auto-save without it.

### Use When Helpful

- `work(log_mistake)` - When something breaks (beyond auto-detected errors).
- `work(log_decision)` - When you make an important choice.
- `memory(remember)` - Store important discoveries about the codebase.
- `impact_analyze` - Before refactoring shared files.
- `scout_search` - Semantic codebase search when grep isn't enough.

### Advanced (Optional)
- `scope(declare)` - Explicit file boundaries for complex tasks.
- `context(checkpoint_save)` - State save for very long tasks.

*Most users only need the first two sections.*

---

## Quick Reference

### Session
```python
session_start(project_path="/path")  # Deep context load (hook auto-starts basic session)
session_end()                         # Optional - shows summary (memories auto-save)
```

### Track Your Work
```python
work(operation="log_mistake", description="What broke", how_to_avoid="How to prevent")
work(operation="log_decision", decision="What you chose", reason="Why")
```

### Remember Things
```python
memory(operation="remember", content="Important fact", project_path="/path")
memory(operation="add_rule", content="Always do X", reason="Because Y", project_path="/path")
memory(operation="search", query="auth", project_path="/path")
```

### Manage Your Memories

Memory IDs are shown in `[brackets]` at session start and in hook output. Use them to manage:

```python
memory(operation="recent", project_path="/path", limit=10)  # See recent with IDs
memory(operation="modify", memory_id="abc123", content="Updated text", project_path="/path")  # Edit
memory(operation="modify", memory_id="abc123", relevance=8, project_path="/path")  # Change importance
memory(operation="delete", memory_id="abc123", project_path="/path")  # Remove one
memory(operation="batch_delete", memory_ids=["id1","id2"], project_path="/path")  # Remove several
memory(operation="batch_delete", category="context", project_path="/path")  # Remove all in category
memory(operation="promote", memory_id="abc123", reason="Important rule", project_path="/path")  # Make it a rule
memory(operation="cleanup", dry_run=True, project_path="/path")  # Preview stale/duplicate cleanup
memory(operation="cleanup", dry_run=False, project_path="/path")  # Apply cleanup
memory(operation="clusters", project_path="/path")  # View grouped memories
```

**When to manage memories:**
- Hook shows `Memory: 40+ memories` → run `cleanup(dry_run=True)` to preview
- A mistake/rule is outdated → `delete` or `modify` it
- A discovery is always important → `promote` it to a rule

### Before Editing
```python
pre_edit_check(file_path="auth.py")  # Shows mistakes, loop risk, scope status
impact_analyze(file_path="models.py", project_root="/path")  # What depends on this
```

### Research & Analysis
```python
scout_search(query="how does auth work", directory="/path")  # Semantic codebase search
scout_analyze(code="def foo(): ...", question="Any issues?")  # LLM code analysis
code_quality_check(code="def foo(): ...")  # Catches AI slop
```

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

1. **Session auto-starts** - Hooks detect when you haven't called session_start, show rules/mistakes with IDs
2. **Memories auto-save** - Every memory(remember), work(log_mistake), etc. saves to disk immediately
3. **Session files auto-persist** - Files you edit are tracked continuously (no session_end needed)
4. **Memory auto-cleans** - Duplicates merged, clusters created on session_start
5. **Mistakes persist** - Logged mistakes show up in pre_edit_check forever
6. **Checkpoints restore** - Saved checkpoints load automatically on session_start
7. **Memory IDs shown** - Rules and mistakes display `[id]` so you can modify/delete/promote them

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

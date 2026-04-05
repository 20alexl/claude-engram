# Chapter 6 — Advanced Usage

[← Back to Table of Contents](./README.md) · [Previous: Usage Guide](./05-usage-guide.md) · [Next: The Gotchas →](./07-the-gotchas.md)

---

## Tiered Memory System

### How Tiers Work

| Tier | File | What Lives Here | Loaded By |
|------|------|----------------|-----------|
| Hot | `memory.json` | Rules, mistakes, recent discoveries, active context | Every hook call |
| Cold | `archive.json` | Old inactive memories | Only on explicit archive operations |

### Archiving

Memories auto-archive when:
- `last_accessed` is older than 14 days (configurable)
- `relevance` is below 7
- Category is NOT `rule` or `mistake` (these are protected forever)

```python
# Preview what would be archived
memory(operation="archive", dry_run=True, project_path="/path")

# Execute archiving
memory(operation="archive", dry_run=False, project_path="/path")

# Search the archive
memory(operation="archive_search", query="old auth pattern", project_path="/path")

# Bring something back
memory(operation="restore", memory_id="abc123", project_path="/path")

# Check tier counts
memory(operation="archive_status", project_path="/path")
```

Archiving also happens automatically during `cleanup`:

```python
memory(operation="cleanup", dry_run=False, project_path="/path")
# This: removes broken → deduplicates → archives old → decays → clusters
```

### Memory Scoring Algorithm

Every memory is scored against the current context before injection:

```
score = 0.35 * file_match      # Exact file > same dir > same ext > filename in content
       + 0.20 * tag_overlap     # Inferred tags from file path patterns
       + 0.20 * recency         # exp(-age_days / 30)
       + 0.15 * (relevance/10)  # Manual importance rating
       + 0.10 * min(access/10, 1) # How often this memory was useful

# Category bonuses (added on top)
if category == "rule":    score += 0.3
if category == "mistake": score += 0.2
```

Top 3 by score are injected as `additionalContext` in the PreToolUse hook.

---

## Semantic Decision Capture

### How It Works

User prompts are scored for decision intent using two tiers:

1. **AllMiniLM semantic scoring** (if `sentence-transformers` installed) — Compares the prompt against ~35 decision templates and ~18 non-decision templates via cosine similarity. A persistent TCP server keeps the model loaded (~90MB, ~5-25ms per call).

2. **Regex fallback** — Weighted keyword analysis: decision verbs (switch to, adopt, replace, get rid of) + directive markers (let's, we should, from now on, please) + contrast signals (instead of, rather than) + negation (don't, stop, avoid, never). Instant, no dependencies.

The system captures when the combined score exceeds 0.45. It does NOT capture questions, hypotheticals ("what if"), or ambiguous statements ("maybe").

### Installing Semantic Scoring

```bash
pip install -e ".[semantic]"
```

The scorer server auto-starts on `SessionStart` and auto-exits after 30 min idle.

### What Gets Captured

| Prompt | Captured? | Why |
|--------|-----------|-----|
| "let's use PostgreSQL instead of SQLite" | Yes | Decision verb + contrast |
| "from now on always validate inputs" | Yes | Directive + rule language |
| "stop using console.log for debugging" | Yes | Negation + verb |
| "should we use Redis or Memcached?" | No | Question, not decision |
| "maybe we could try GraphQL" | No | Tentative/exploratory |
| "fix the login bug" | No | Task, not decision |

---

## Multi-Project Workspaces

### Automatic Sub-Project Resolution

When Claude runs from a workspace root with multiple projects:

```
~/projects/              ← Claude runs from here
  backend/               ← pyproject.toml → project "backend"
  frontend/              ← package.json → project "frontend"
  shared-lib/            ← CLAUDE.md → project "shared-lib"
```

Claude Engram walks up from the edited file looking for project markers:
`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `.git`, `CLAUDE.md`, `setup.py`, `Makefile`, etc.

### Memory Inheritance

Sub-projects inherit workspace-level memories. If you store a rule under the workspace root, it's visible when editing files in any sub-project.

```
~/projects memories:
  [rule] "Always run tests before committing"    ← visible everywhere

~/projects/backend memories:
  [mistake] "Broke the database migration"        ← only visible in backend

~/projects/frontend memories:
  [decision] "Use React Server Components"        ← only visible in frontend
```

### Scoping Control

If you want a memory only in a sub-project, use the sub-project path:
```python
memory(operation="remember", content="...", project_path="/home/user/projects/backend")
```

For workspace-wide rules:
```python
memory(operation="add_rule", content="...", project_path="/home/user/projects")
```

---

## Performance Tuning

| Situation | Recommendation |
|-----------|---------------|
| Many memories (50+) | Run `memory(cleanup)` to dedupe + archive old entries |
| Slow pre-edit hooks | Check `memory(archive_status)` — hot tier should be <50 entries |
| Scorer server using too much RAM | Set `MINI_CLAUDE_SCORER_TIMEOUT=300` (5 min idle timeout) |
| Ollama too slow | Use a smaller model: `export MINI_CLAUDE_MODEL="gemma3:4b"` |
| Hook timeouts | Keep `memory.json` small. Archive aggressively. |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MINI_CLAUDE_MODEL` | `gemma3:12b` | Ollama model for search/analysis |
| `MINI_CLAUDE_OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `MINI_CLAUDE_TIMEOUT` | `300` | LLM call timeout (seconds) |
| `MINI_CLAUDE_KEEP_ALIVE` | `0` | How long Ollama keeps model loaded (`0`, `5m`, `-1`) |
| `MINI_CLAUDE_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `MINI_CLAUDE_SCORER_TIMEOUT` | `1800` | Scorer server idle timeout (seconds) |

---

[Next: The Gotchas →](./07-the-gotchas.md)

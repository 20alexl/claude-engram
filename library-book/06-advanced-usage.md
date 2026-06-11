# Chapter 6 — Advanced Usage

[← Back to Table of Contents](./README.md) · [Previous: Usage Guide](./05-usage-guide.md) · [Next: The Gotchas →](./07-the-gotchas.md)

---

## Tiered Memory System

### How Tiers Work

| Tier | File | What Lives Here | Loaded By |
|------|------|----------------|-----------|
| Hot | `projects/<hash>/memory.json` | Rules, mistakes, recent discoveries, active context | Hook calls (per-project) |
| Cold | `projects/<hash>/archive.json` | Old inactive memories | Only on explicit archive operations |

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
# This: removes broken → deduplicates → archives old → decays
# Note: memory clustering is internal to cleanup; there is no standalone agent-callable op for it.
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

1. **Semantic scoring** (if `sentence-transformers` installed) — Compares the prompt against ~35 decision templates and ~18 non-decision templates via cosine similarity. A persistent TCP server keeps the model loaded (~1.1GB RAM with the default `bge-base-en-v1.5`, ~5-25ms per call).

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

## Checkpoint / Handoff History

Checkpoints and handoffs are a single unified ring buffer (last 20 per project, plus a global slot). `checkpoint_save` is the primary write op; `handoff_create` is a deprecated alias. Use `checkpoint_list` to browse history and `checkpoint_restore` with `index=N` to retrieve a specific entry.

```python
# Save task state (optionally with handoff content for the next session)
context(
    operation="checkpoint_save",
    task_description="Refactoring auth module",
    current_step="Step 2: token refresh",
    completed_steps=["Step 1: provider config"],
    pending_steps=["Step 3: tests"],
    files_involved=["auth.py", "oauth.py"],
    project_path="/path"
)

# Browse the unified ring, newest-first (index, age, kind: manual|auto, summary)
context(operation="checkpoint_list", project_path="/path")

# Restore by index (0 = latest, N = older entry)
context(operation="checkpoint_restore", project_path="/path", index=0)
context(operation="checkpoint_restore", project_path="/path", index=3)
```

The `kind` field tells you whether the entry was written manually or automatically by the Stop/PreCompact hook. Manual checkpoints always win: an auto-checkpoint with no files edited and no decisions never overwrites a substantive one.

Reads walk up from the nearest project to ancestor projects to the global slot — a sub-project's entry is not shadowed by the shared global slot.

`handoff_create`, `handoff_get`, and `handoff_list` remain as deprecated aliases and work identically.

---

## Session Mine: Live Transcript Mining

### Commitments

`session_mine(commitments)` scans the **live** session transcript for things that were said but not yet done. The post-session mining index is built at `SessionEnd` so it cannot see the current open session — this op fills that gap.

Two channels:

- **DEFERRED** — scans the most recent ~450 messages for next-session/remaining/TODO/follow-up/defer language. Surfaces open loops you said you'd handle later.
- **IN-FLIGHT** — scans the last ~30 messages for "I'll", "let me", "next" language. Surfaces actions that were announced but may not have completed.

Heuristic-based, LLM-free. Run before asking the user "what next?" or when resuming a long session.

```python
session_mine(operation="commitments", project_path="/path/to/project")
```

### Typed Search

`session_mine(search)` classifies every hit by kind — `decision`, `next-step`, `error`, or `narration` — using regex (no LLM). Pass `kind` to filter:

```python
# All hits, with kind shown
session_mine(operation="search", query="auth refactor", project_path="/path")

# Only hits classified as decisions
session_mine(operation="search", query="auth refactor", kind="decision", project_path="/path")

# Only hits classified as errors
session_mine(operation="search", query="migration", kind="error", project_path="/path")
```

Valid `kind` values: `decision`, `next-step`, `error`, `narration`.

### Reflect

`session_mine(reflect)` tells you how well the injection pipeline is actually working. It reports:

- **Injection precision** — which context kinds (memory, prediction, precheck, blast) appeared before tests that passed. High precision means the right context is landing before the right edits.
- **LLM-synthesized insights** — patterns across recurring mistakes and struggles, synthesized by the local LLM (gemma3:12b) into actionable observations.

```python
session_mine(operation="reflect", project_path="/path/to/project")
```

Use this after a long session or when injection feels noisy. The output will show which injection types are correlated with success and flag any systematic gaps (e.g., precheck firing but not blast, or memories injected on files that never fail).

This op requires Ollama for the insights portion. Precision data is always available; the LLM synthesis section is skipped if Ollama is unavailable.

---

## Code-Index-Backed Pre-Edit Signals

The miner builds a per-project code index (`projects/<hash>/code_index.json`) incrementally during Phase 6 of background mining. The index records per-module exports, classes, functions, and raw imports using only `ast` — no LLM, no network. It updates automatically whenever files change (mtime-keyed, deleted files pruned).

Two hook-level signals are emitted before every Edit/Write, visible in hook output:

**`<engram-precheck>`** — import/export verification. Checks proposed edit content for import statements that won't resolve against the index: a name not exported by a known internal module, or an internal module path that doesn't exist. Capped at 2 findings; conservatively silent on relative imports, stdlib, `import *`, or anything it cannot verify with high confidence.

**`<engram-blast-radius>`** — dependency fan-out. Shows how many project modules import the file being edited and lists them. Silent for near-leaf modules (< 3 dependents). Reads cached reverse-edges from the index — no filesystem walk at hook time.

```
<engram-precheck>
- `utils.helpers`: name `format_date` not found in exports [did you mean `format_datetime`?]
</engram-precheck>

<engram-blast-radius>
- `core.session` is imported by 7 module(s): auth.login, auth.oauth, api.views, ...
  Check these callers if you change its signatures or exports.
</engram-blast-radius>
```

Both signals appear in the `reflect` output as `precheck` and `blast` precision buckets. `impact_analyze` also reads the cached index (reverse edges) for faster blast-radius estimates.

The index is scoped to a single project — sub-projects each get their own index, preventing cross-version symbol pollution.

---

## Automatic Migrations on Upgrade

When you upgrade Claude Engram to a new version, storage migrations run automatically. They are version-stamped, idempotent (safe to re-run), and forward-only. The list of applied migrations is tracked in `manifest.json` under `migrations_applied`.

Migrations triggered by v0.5.0:

- **Seed handoff history** — the existing `latest_handoff.json` is seeded into the new ring buffer on the first write. No data is lost.
- **Re-extract related_files** — existing memories get their `related_files` re-populated with full paths (fixing a bug where only basenames were stored).

Cheap steps run inline on SessionStart. Heavier steps run in a detached background process so the hook is not delayed. Migrations also run synchronously when you run `python install.py` or `python -m claude_engram.migrations`.

---

## Performance Tuning

| Situation | Recommendation |
|-----------|---------------|
| Many memories (50+) | Run `memory(cleanup)` to dedupe + archive old entries |
| Slow pre-edit hooks | Check `memory(archive_status)` — hot tier should be <50 entries |
| Scorer server using too much RAM | Set `CLAUDE_ENGRAM_SCORER_TIMEOUT=300` (5 min idle timeout) |
| Ollama too slow | Use a smaller model: `export CLAUDE_ENGRAM_MODEL="gemma3:4b"` |
| Hook timeouts | Keep `memory.json` small. Archive aggressively. |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_ENGRAM_DIR` | `~/.claude_engram` | Storage location override (also the supported test-isolation seam) |
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Optional Ollama model — `scout_search`, `memory(consolidate)`, `session_mine(reflect)` synthesis |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `BAAI/bge-base-en-v1.5` | sentence-transformers embedding model (scorer server, decision capture, memory + session embeddings). Also `embed_model` in `config.json` |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `0` (keep all) | Prune session-search embedding shards older than N days (whole months at a time) |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | unset | Read hook mirrors the last-read file path here (statusline integration; replaces a separate user hook) |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | unset | `1` prints a stderr breadcrumb per hook: served by daemon vs fallback (and why) |
| `CLAUDE_ENGRAM_EMBED_DIM` | model native | Matryoshka truncation dim (e.g. `256` for `google/embeddinggemma-300m`). Also `embed_dim` in `config.json` |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint (optional LLM) |
| `CLAUDE_ENGRAM_TIMEOUT` | `300` | LLM call timeout (seconds) |
| `CLAUDE_ENGRAM_KEEP_ALIVE` | `0` | How long Ollama keeps model loaded (`0`, `5m`, `-1`) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | Embedding server idle timeout (seconds) |

Embedding stores (decision-template cache, memory embeddings, session-search
embeddings) are stamped with the active `model@dim` signature. Changing the
model discards and rebuilds them in the background — two models' vectors are
never mixed. Measured on the decision-capture bench (precision held ~77-81%):
`all-MiniLM-L6-v2` semantic F1 37.7%, `embeddinggemma-300m@256` 67.3% (license-gated:
HF token + `sentence-transformers>=5`), `bge-small-en-v1.5` 70.7%,
`BAAI/bge-base-en-v1.5` (the default) 72.7%.

---

[Next: The Gotchas →](./07-the-gotchas.md)

# Chapter 6: Advanced Usage

[← Back to Table of Contents](./README.md) · [Previous: Usage Guide](./05-usage-guide.md) · [Next: The Gotchas →](./07-the-gotchas.md)

---

## Tiered memory system

### How tiers work

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

### Memory scoring algorithm

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

## Semantic decision capture

### How it works

User prompts are scored for decision intent using two tiers:

1. **Semantic scoring** (if `sentence-transformers` installed): compares the prompt against ~35 decision templates and ~18 non-decision templates via cosine similarity. A persistent TCP server keeps the model loaded (~1.1GB RAM with the default `bge-base-en-v1.5`, ~5-25ms per call).

2. **Regex fallback**: weighted keyword analysis over decision verbs (switch to, adopt, replace, get rid of), directive markers (let's, we should, from now on, please), contrast signals (instead of, rather than) and negation (don't, stop, avoid, never). Instant, no dependencies.

The best of the two has to reach 0.6 (`CAPTURE_THRESHOLD` in `hooks/intent.py`), and the sentence then has to pass the shape gate (`mining/decision_gate.py`): no question, no acknowledgement, no count, table row, commit-hash line, path or markup (a tag with attributes included), not a request, not a one-off instruction (step numbers, an ordinal pick, "yet", "go ahead with"), not a status assessment ("should be fine now"), no email address or key-like token, one sentence (a line break inside is a paste unless the lines are a list under one lead), a deciding word, no hedge. One function does all of this, `capture_decision`, and the session miner sends every correction it finds in a transcript through the same function before storing a "USER PREFERENCE", so a sentence is kept or dropped by one rule whether it was typed live or mined from history. `tests/bench_correction_gate.py` scores the function on the neutral corpus (2026-09-23: precision 1.00, recall 0.95 on the 40 corrections, with the scorer daemon up or the regex tier alone).

### Installing semantic scoring

```bash
pip install -e ".[semantic]"
```

The scorer server auto-starts on `SessionStart` and auto-exits after 30 min idle. One runs per store, held by a process lock; `claude_engram_status` lists every engram process by role and size and warns when a second scorer or miner is alive.

### What gets captured

| Prompt | Captured? | Why |
|--------|-----------|-----|
| "let's use PostgreSQL instead of SQLite" | Yes | Decision verb + contrast |
| "from now on always validate inputs" | Yes | Directive + rule language |
| "stop using console.log for debugging" | Yes | Negation + verb |
| "should we use Redis or Memcached?" | No | Question, not decision |
| "maybe we could try GraphQL" | No | Tentative/exploratory |
| "fix the login bug" | No | Task, not decision |

---

## Multi-project workspaces

### Automatic sub-project resolution

When Claude runs from a workspace root with multiple projects:

```
~/projects/              ← Claude runs from here
  backend/               ← pyproject.toml → project "backend"
  frontend/              ← package.json → project "frontend"
  shared-lib/            ← CLAUDE.md → project "shared-lib"
```

Claude Engram walks up from the edited file looking for project markers:
`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `.git`, `CLAUDE.md`, `setup.py`, `Makefile`, etc.

### Memory inheritance

Sub-projects inherit workspace-level memories. If you store a rule under the workspace root, it's visible when editing files in any sub-project.

```
~/projects memories:
  [rule] "Always run tests before committing"    ← visible everywhere

~/projects/backend memories:
  [mistake] "Broke the database migration"        ← only visible in backend

~/projects/frontend memories:
  [decision] "Use React Server Components"        ← only visible in frontend
```

### Scoping control

If you want a memory only in a sub-project, use the sub-project path:
```python
memory(operation="remember", content="...", project_path="/home/user/projects/backend")
```

For workspace-wide rules:
```python
memory(operation="add_rule", content="...", project_path="/home/user/projects")
```

---

## Checkpoint / handoff history

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

Reads walk up from the nearest project to ancestor projects to the global slot, so a sub-project's entry is not shadowed by the shared global slot.

`handoff_create`, `handoff_get`, and `handoff_list` remain as deprecated aliases and work identically.

---

## Session mine: live transcript mining

### Commitments

`session_mine(commitments)` scans the **live** session transcript for things that were said but not yet done. The post-session mining index is built at `SessionEnd`, so it cannot see the current open session. This op fills that gap.

Two channels:

- **DEFERRED**: scans the most recent ~450 messages for next-session/remaining/TODO/follow-up/defer language. Surfaces open loops you said you'd handle later.
- **IN-FLIGHT**: scans the last ~30 messages for "I'll", "let me", "next" language. Surfaces actions that were announced but may not have completed.

Heuristic-based, LLM-free. Run before asking the user "what next?" or when resuming a long session.

```python
session_mine(operation="commitments", project_path="/path/to/project")
```

### Typed search

`session_mine(search)` classifies every hit by kind (`decision`, `next-step`, `error`, or `narration`) using regex, with no LLM. Pass `kind` to filter:

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

`session_mine(reflect)` tells you how well the injection pipeline is working. It reports:

- **Injection precision**: which context kinds (memory, prediction, precheck, blast) appeared before tests that passed. High precision means the right context is landing before the right edits.
- **LLM-synthesized insights**: patterns across recurring mistakes and struggles, synthesized by the local LLM (gemma3:12b) into observations you can act on.

```python
session_mine(operation="reflect", project_path="/path/to/project")
```

Use this after a long session or when injection feels noisy. The output shows which injection types correlate with success and flags systematic gaps (e.g., precheck firing but not blast, or memories injected on files that never fail).

This op requires Ollama for the insights portion. Precision data is always available; the LLM synthesis section is skipped if Ollama is unavailable.

---

## Code-index-backed pre-edit signals

The miner builds a per-project code index (`projects/<hash>/code_index.json`) incrementally during Phase 6 of background mining. The index records per-module exports, classes, functions, and raw imports using only `ast`, with no LLM and no network. It updates automatically whenever files change (mtime-keyed, deleted files pruned).

Two hook-level signals are emitted before every Edit/Write, visible in hook output:

**`<engram-precheck>`**: import/export verification. Checks proposed edit content for import statements that won't resolve against the index: a name not exported by a known internal module, or an internal module path that doesn't exist. Capped at 2 findings; conservatively silent on relative imports, stdlib, `import *`, or anything it cannot verify with high confidence.

**`<engram-blast-radius>`**: dependency fan-out. Shows how many project modules import the file being edited and lists them. Silent for near-leaf modules (< 3 dependents). Reads cached reverse-edges from the index, with no filesystem walk at hook time.

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

The index is scoped to a single project. Sub-projects each get their own index, which prevents cross-version symbol pollution.

---

## Automatic migrations on upgrade

When you upgrade Claude Engram to a new version, storage migrations run automatically. They are version-stamped, idempotent (safe to re-run), and forward-only. The list of applied migrations is tracked in `manifest.json` under `migrations_applied`.

Migrations triggered by v0.5.0:

- **Seed handoff history**: the existing `latest_handoff.json` is seeded into the new ring buffer on the first write. No data is lost.
- **Re-extract related_files**: existing memories get their `related_files` re-populated with full paths, a fix for a bug where only basenames were stored.

Cheap steps run inline on SessionStart. Heavier steps run in a detached background process so the hook is not delayed. Migrations also run synchronously when you run `python install.py` or `python -m claude_engram.migrations`.

---

## Performance tuning

| Situation | Recommendation |
|-----------|---------------|
| Many memories (50+) | Run `memory(cleanup)` to dedupe + archive old entries |
| Slow pre-edit hooks | Check `memory(archive_status)`: the hot tier should be <50 entries |
| Scorer server using too much RAM | Set `CLAUDE_ENGRAM_SCORER_TIMEOUT=300` (5 min idle timeout) |
| Ollama too slow | Use a smaller model: `export CLAUDE_ENGRAM_MODEL="gemma3:4b"` |
| Hook timeouts | Keep `memory.json` small. Archive aggressively. |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_ENGRAM_DIR` | `~/.claude_engram` | Storage location override (also the supported test-isolation seam) |
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Optional Ollama model for `scout_search`, `memory(consolidate)` and `session_mine(reflect)` synthesis |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `BAAI/bge-base-en-v1.5` | sentence-transformers embedding model (scorer server, decision capture, memory + session embeddings). Also `embed_model` in `config.json` |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `0` (keep all) | Prune session-search embedding shards older than N days (whole months at a time) |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | unset | Read hook mirrors the last-read file path here (statusline integration; replaces a separate user hook) |
| `CLAUDE_ENGRAM_HEADSUP_FRACTION` | `0.10` | Context-pressure heads-up this fraction of the window before the compaction point |
| `CLAUDE_ENGRAM_OUTPUT_RESERVE` | `32000` | Tokens Claude Code keeps below the configured number before it compacts (measured) |
| `CLAUDE_ENGRAM_CHECKPOINT_MARGIN` | `20000` (`10000` on ≤200K) | `CHECKPOINT NOW` nudge this many tokens above the auto-compaction trigger |
| `CLAUDE_ENGRAM_CHECKPOINT_CADENCE` | `60` | Fallback: turns (Stop events) with neither a deliberate checkpoint nor a completed step before a reminder. Milestones, not this, are the normal trigger |
| `CLAUDE_ENGRAM_STALL_TURNS` | `3` | Consecutive turns with tool use and no effect per stall strike |
| `CLAUDE_ENGRAM_STALL_DECAY` | `5` | Consecutive good turns (real effect) that remove one strike |
| `CLAUDE_ENGRAM_STRIKE_CAP` | `3` | The ladder's top; the halt in autonomy mode |
| `CLAUDE_ENGRAM_COMPLIANCE` | on | `off` disables detector matching and the compliance section (or `"compliance": false` in `.engram/config.json`) |
| `CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT` | `90` | Percent of the 5-hour usage window at which the once-per-window budget nudge fires (subscription sessions) |
| `CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT` | `95` | Same for the 7-day window |
| `CLAUDE_ENGRAM_AUTONOMY` | off | `1` arms autonomy mode: the strike-cap halt and the alerts. The launcher sets it for its child |
| `CLAUDE_ENGRAM_ALERT_COMMAND` | unset | Shell command for out-of-session alerts; `{message}` is replaced (shell-quoted) or the message arrives on stdin. Also `"alert_command"` in `.engram/config.json` |
| `CLAUDE_ENGRAM_RESUME_SLACK` | `90` | Seconds the launcher waits past a usage window's reset before resuming |
| `CLAUDE_ENGRAM_CODE_RULES` | on | `off` keeps the pack's code tier out of a project (or `"code_rules": false`) |
| `CLAUDE_ENGRAM_ROTATION` | unset | `0` disables rotation planning; `auto` applies at session end (overrides `.engram/config.json`) |
| `CLAUDE_ENGRAM_DEFAULT_RULES` | unset | `0` skips seeding the default rule pack |
| `CLAUDE_ENGRAM_STRUCTURE` | unset | `0` skips creating the project scaffold |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | unset (Claude Code's) | Not engram's variable, but engram reads it: the compaction point the nudges are measured against. Set it for unattended runs (e.g. `750000` on a 1M model) |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | unset | `1` prints a stderr breadcrumb per hook: served by daemon vs fallback (and why) |
| `CLAUDE_ENGRAM_EMBED_DIM` | model native | Matryoshka truncation dim (e.g. `256` for `google/embeddinggemma-300m`). Also `embed_dim` in `config.json` |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint (optional LLM) |
| `CLAUDE_ENGRAM_TIMEOUT` | `300` | LLM call timeout (seconds) |
| `CLAUDE_ENGRAM_KEEP_ALIVE` | `0` | How long Ollama keeps model loaded (`0`, `5m`, `-1`) |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | Embedding server idle timeout (seconds) |
| `CLAUDE_ENGRAM_DEVICE` | smart | Unset: the daemon stays on cpu and bulk jobs run in a transient GPU worker. `cuda` or `cpu` forces one device everywhere |
| `CLAUDE_ENGRAM_GPU_BULK_MIN` | `512` | Job size in texts that routes to the GPU worker |
| `CLAUDE_ENGRAM_GPU_BATCH` | `64` | Rows per forward pass on the GPU (about 26 MiB per row) |
| `CLAUDE_ENGRAM_CPU_BATCH` | `16` | Rows per forward pass in the resident daemon on the CPU. The daemon keeps the activation arena of its largest batch for life: 64 rows parked 1.2 GB more than 16 at the same speed |
| `CLAUDE_ENGRAM_NO_DAEMON` | unset | Set to run every hook in-process and never start the daemon (tests, benches) |
| `CLAUDE_ENGRAM_LIVE_MINE` | `300` | Live mining tick interval in seconds; `0` disables |
| `CLAUDE_ENGRAM_GOAL_TURN_CAP` | `150` | Turns under a `/goal` before the halt arms (also `goal_turn_cap` in `.engram/config.json`) |
| `CLAUDE_ENGRAM_WORKFLOW_RULES` | on | `off` keeps the pack's workflow tier out of a project (or `"workflow_rules": false`) |
| `CLAUDE_ENGRAM_GIT_TRACE` | unset | A file path; every git call the hooks make is appended there with its duration |
| `CLAUDE_ENGRAM_NON_PROJECT_DIRS` | unset | Comma-separated directory names that are never a project of their own, added to `node_modules`, `.venv`, `venv`, `__pycache__`; also `non_project_dirs` in `~/.claude_engram/config.json` |

Embedding stores (decision-template cache, memory embeddings, session-search
embeddings) are stamped with the active `model@dim` signature. Changing the
model discards and rebuilds them in the background; two models' vectors are
never mixed. Measured on the decision-capture bench (precision held ~77-81%):
`all-MiniLM-L6-v2` semantic F1 37.7%, `embeddinggemma-300m@256` 67.3% (license-gated:
HF token + `sentence-transformers>=5`), `bge-small-en-v1.5` 70.7%,
`BAAI/bge-base-en-v1.5` (the default) 72.7%.

---

[Next: The Gotchas →](./07-the-gotchas.md)

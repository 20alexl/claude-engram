# Claude Engram - Persistent Memory for Claude Code

## How It Works

Claude Engram intercepts your tool calls via Claude Code hooks and automatically tracks what you do. Most features require zero invocations - they fire through hooks on every edit, bash command, error, and session event.

You also have MCP tools for things that need semantic judgment (saving discoveries, declaring rules, managing archives).

## What's Fully Automatic

These happen via hooks. You don't call anything:

| What | When It Fires | What You See |
|---|---|---|
| **Session restore** | SessionStart hook | Rules, mistakes, checkpoint, handoff. Every hook scopes by `session_project(project_dir, state)` (the transcript's Edit/Write calls via `autorun.recent_edit_files`, then the hook state, then the cwd mapped to its repo; cached against the transcript size), never by the cwd. The recurring-errors block (`_recurring_lines`) prints at start on resume/compact and is deferred to the first pre-edit on a fresh start (`patterns_deferred`); engram's own `.claude_engram` failures never listed as a project's |
| **Edit tracking** | PostToolUse Edit/Write | Nothing printed; the count feeds the loop warning before the next edit (files under node_modules/, venvs, or a `non_project_dirs` name from `~/.claude_engram/config.json` never warn) |
| **Loop warnings** | PreToolUse Edit/Write | Warning when same file edited 3+ times (state lives in per-session hook state, so concurrent sessions don't cross-contaminate) |
| **Scored memory injection** | PreToolUse Edit/Write | Top 3 file-relevant memories; a rule rides along only when it names the file; an entry older than 30 days (`STALE_CONTEXT_DAYS`) only with a full-path match; ERRORS.md / LEARNINGS.md / plan.md are generic basenames |
| **Test tracking** | PostToolUse Bash | "PASS/FAIL Test tracked" on the first run and on each flip only (the status is one per session and survives every Stop); output markers are trusted when the command names a test runner (`_is_test_invocation`) or when no segment of the chain merely reads (`_segment_kind`: run / read / noise, wrappers peeled; `cat log; bash count.sh` is never a test run), and the output must read as a verdict (`_output_has_test_markers`; a bare "N errors" is not one). A failure's mistake attaches to the traceback's files, else the session's edited code files |
| **Error auto-logging** | PostToolUseFailure (all tools) | Mistakes auto-saved from any failed tool. The miner's error→fix extractor skips a message that is a source line or a grep line ("141:def ...") and one under four words unless it is a single quoted token |
| **Decision capture** | UserPromptSubmit | "let's use X" judged by ONE function, `hooks/intent.capture_decision`: semantic + regex scoring, the 0.6 threshold, then the shape gate (`mining/decision_gate.py`): one declarative sentence of four or more words (a line break inside is a paste unless the lines are a list under one lead), no question, not an acknowledgement, count, table row, commit report or hash-led line, no markup (tags with attributes included), not a request, not a one-off instruction (step numbers, an ordinal pick, "yet", "go ahead with"), not a status assessment ("should be fine now"), not an approval verdict with no other deciding word ("the plan is approved"), not a question typed without its mark ("would it be better to split it"), no email or key-like token, with a deciding word; hedges (including "probably", "I guess", "up to you", a trailing "or not"), history and third parties excluded; an edit verb only with a transition or a scope; a preference needs four words. The miner mines only typed prompts (`extractors._typed_prompt`: under 500 chars, one paragraph, no relayed teammate/agent message, no markup), stores the sentence the pattern matched, sends every correction it finds through the same function (`server_only=True`) before storing a USER PREFERENCE, applies the gate to its structural decisions, and stores a bare sentence once across the hook's "(from user)" copy, its own decision and preference copies, the destination store and its ancestors; migrations `0.8.46`–`0.8.48:prune_junk_decisions*`, `0.8.49:rejudge_preferences` (heavy) and `0.8.56:rejudge_mined_decisions` archived what was stored before. Tuned and pinned on the neutral 220-prompt corpus by `tests/bench_correction_gate.py` (decision 1.00 / 0.93, correction 0.97 / 0.80, shared capture 1.00 / 0.95 with or without the daemon), never on a session's own sentences. The regex tier's typo corrector only fixes a swap or a dropped/doubled letter on words of five letters or more, and the stored text is the typed words, never the corrected working text |
| **Checkpoint on compact** | PreCompact | Task state saved before context compaction |
| **Context re-injection** | SessionStart(compact, resume) | Rules + mistakes + THIS SESSION's newest deliberate checkpoint (the ring record's `session_id`), shown whole (task, current step, every completed and pending step, files, warnings, context notes, handoff note, goal, movement since), plus the compaction rhythm (where the next heads-up / checkpoint / compaction sit). The project's newest deliberate checkpoint is the fallback for a session that has banked nothing yet. A checkpoint this session saved on a branch the user then rewound past (`transcript_chain`: the live chain is the walk from the transcript's last record up its parent links; a rewind fires no hook and leaves only a fork) is skipped and named. `context(checkpoint_restore)` with no arguments picks the same way. PostCompact does bookkeeping only: Claude Code's hook output schema has no PostCompact channel |
| **Context-pressure nudges** | UserPromptSubmit / PreToolUse / PostToolUse | `<engram-context>` heads-up ~10% of the window before the compaction point, `CHECKPOINT NOW` 20K above the auto-compaction trigger (the setting minus a 32K output reserve, measured; 10K on a 200K window), once each per cycle; fallback after 60 turns with neither a checkpoint nor a completed step. Needs a statusline that records the mirror; announced at session start when there is none |
| **Default pack** | SessionStart (fresh start only) | Scaffold pieces created where missing (headered `CLAUDE.md`, `.learnings/*.md`, `session-logs/`; per-person layouts left alone) and ten working rules seeded once, skipping any the project or an ancestor already has. `.engram/config.json`: `"structure": false`, `"default_rules": false` |
| **Rotation** | SessionEnd plans, SessionStart announces; `session_mine(rotate)` | Dailies > 30 d → `session-logs/archive/<month>/` + digest; dated learnings > 90 d (or over 500 lines) → `.learnings/archive/`; nothing deleted; note under the title. `"rotation": "auto"` applies at session end |
| **Run report** | SessionEnd (auto, substantial sessions) or `session_mine(run_report)` | `<project>/.engram/runs/<date>-<session>.md` + `.json`: commits, turns, files with edit counts, tests, errors (grouped, known-before), compactions with sizes and what each restored, checkpoints deliberate vs auto, goal text, and an explicit not-measured list. Hook-captured facts only |
| **Milestone nudges** | Stop (read) → next injection point (deliver); PostToolUse ExitPlanMode / TaskUpdate | The model's own "step done" in its final message, with no deliberate checkpoint that turn, gets one nudge quoting the claim, only when the turn also had an effect (edit, commit, delegated agent; `_turn_corroborates_a_close`), never for a list bullet or a table row, a sentence still in motion (waiting, running, queued, a percentage through), reported speech, a rule or definition, a number beside "passed"/"closed", or a participle used as an adjective, at most one prose nudge an hour (`MILESTONE_NUDGE_GAP_SECS`). A turn that banked state with `memory(remember)` and no `checkpoint_save` (`stall.note_tool` records `name:op` per turn) gets the `claim_remember` variant: a remember is a fact, the restore reads checkpoints only, both together are fine. A plan approval asks for the plan to be banked with its steps pending. Never written for you, never from commits |
| **Session handoff on stop** | Stop | Saves last_assistant_message + files for next session |
| **Session summary on end** | SessionEnd | Files edited, memory counts |
| **Stall detection** | PostToolBatch (account) + PostToolUse Edit/Bash fallback; Stop (judge); next injection point (deliver) | `<engram-stall>` after 3 consecutive turns with tool use and no effect (no file change, no test-status flip, no commit, no delegation); strike 2 re-injects the checkpoint + rules and forces a bearings check; strike 3 is the cap (the halt in autonomy mode). Turns with no tools or parked on Monitor/ScheduleWakeup/cron are neutral. Strikes decay: 5 good turns remove one. Events with turn numbers in the run report |
| **Usage budget** | same injection points as context pressure; StopFailure (record) | Subscription 5-hour / 7-day windows mirrored from the statusline (`rate_limits`); at 90% / 95% one `<engram-context>` per window with the reset time: checkpoint and park on a wakeup until the reset. `stop_failure_json` records every API failure (`error_type`, message, the window's reset) into `run.failures` for the run report; a limit hit is never retried by Claude Code and no Stop hook sees it |
| **Autonomy halt** | Stop (arm at the strike cap when `CLAUDE_ENGRAM_AUTONOMY=1`); PreToolUse `""` (`pre_tool_json`, deny) | Every tool denied with a reason naming `python -m claude_engram.hooks.stall release <session>`; PushNotification, ToolSearch, SendMessage and `context(checkpoint_save)` stay open; a call carrying `agent_id` (a subagent, which shares the session id) is never denied; `<engram-halt>` once at the next injection point; turns after the halt are neutral. Engram never blocks Stop: with no tool use, /goal's stall rule closes the loop |
| **Alerts** | Stop (halt), StopFailure, Notification (`notification_json`: needs input / permission prompt / idle), the launcher | One line under 200 chars through the owner's `alert_command` (`{message}` or stdin); recorded in `state["alerts"]` and the run report whether sent or not. PushNotification is model-only (verified), so the command is the headless channel |
| **The /goal bracket** | Stop, UserPromptSubmit, SessionEnd (observe); `session_mine(run_status)` | `hooks/autorun.py`: `scan_goal()` reads the transcript tail for the verified records (sentinel on set, verdicts, `/goal clear` command); `observe()` keeps `run.auto` in step: `running` from the sentinel, `met`/`failed`/`cleared` from the transcript, `halted` from the strike cap, `capped` from `goal_turn_cap` (150; arms the same halt, since engram cannot end a /goal loop). A met or failed record ends the goal whatever its `sentinel` flag (2.1.268 writes the met record with both), and a running record whose goal no longer appears in the transcript tail ends as `cleared` before it can count toward the cap. Autonomy mode is on while running (`autonomy_on(state)`). A start writes the manifest and stages one directive (park hint, checkpoint rhythm, deny note); an end = one alert + the run report's "Goal run" section. Engram never blocks a Stop of its own; a goal is set only by typing `/goal` |
| **Launcher (cron only)** | `python -m claude_engram.run --headless` | Manifest, `--session-id`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` at 75% of the model's window, `--max-turns`, park hint, `claude -p --output-format json`; a `rate_limit` exit with a known reset sleeps and `--resume`s the same session (max 3); run report + closing alert |
| **Rules compliance** | PreToolUse Bash/PowerShell (match + inject); PostToolBatch (other tools) | A rule with a hand-written detector (tools / command regex / path globs / input regex) has every matching call recorded with turn, input excerpt and verdict (`unattended` = bypass/auto/dontAsk, `prompted` = a permission prompt stood between); `<engram-rule>` injected before a matching shell command runs. Rules without one are advisory, said per rule; detector health shown. Pack rules ship theirs; `"compliance": false` opts out |
| **Search spiral detection** | PostToolUse Bash | Warns after 3+ failed search commands |
| **Memory archiving** | cleanup / session_start | Old inactive memories archived, not deleted |
| **Sub-project scoping** | PreToolUse / PostToolUse | Memories scoped to the right sub-project |
| **Data migrations** | SessionStart (upgrade) | Cheap inline check; full migration in background |
| **Pre-edit import check** | PreToolUse Edit/Write | `<engram-precheck>` when a proposed import won't resolve against the code index (closest-name suggestion) |
| **Blast-radius alert** | PreToolUse Edit/Write | `<engram-blast-radius>` listing modules that import the file being edited |
| **Outcome feedback loop** | PreToolUse + PostToolUse Bash | Injection kinds correlated with test pass/fail; surfaced via `session_mine(reflect)` |
| **Schema canary** | SessionStart | Warning when Claude Code's log format stops being recognized (mining would otherwise degrade silently) |
| **Read context** | PreToolUse Read | `<engram-read-context>`: code-index orientation + the file's most relevant memories, once per file per session |
| **Error deja-vu** | PostToolUseFailure | "Deja vu: TypeError hit in 3 past session(s) - fix: ..." when a fresh failure matches a mined recurring error or stored mistake (identifier-guarded, so an unrelated class never inherits someone else's fix) |
| **Known-good test commands** | SessionStart | The project's top tracked test commands that currently pass — verification starts from what worked, not a guess |
| **Mistake hygiene** | Background miner | Stale auto-captured one-off mistakes (3+ weeks, never recurred, away from current work) move to the archive — banners keep their signal; restorable via `memory(restore)` |
| **Live mining tick** | Stop (per turn, debounced) | Session index, extractions, search embeddings, and the active code indexes refresh DURING the session — `session_mine(search)` sees this session's earlier work, not just past sessions. Interval `CLAUDE_ENGRAM_LIVE_MINE` (default 300s) |
| **Curated-lessons bridge** | Background miner (opt-in) | Dated entries in lesson files sync as protected `lesson` memories with code-index-joined triggers — a lesson mentioning a module surfaces when editing files that import it. The file stays the source of truth (edits update, removals retire). Off unless `lessons_globs` is set in `~/.claude_engram/config.json` (e.g. `["docs/lessons/*.md"]`) — no default path |
| **Project-scoped patterns** | SessionStart | Recurring errors/struggles are attributed to sub-projects and filtered by what the last session touched — a vzip session no longer sees CORTEX errors. A recurring error is the same CONCRETE error (directories, hashes and numbers templated; identifiers and file names kept) seen in two or more sessions, shown with its latest sighting's example and fix. Errors unseen for 30 days drop out |

## Multi-Project Workspaces

When run from a workspace root containing multiple projects, memories are automatically scoped to the right sub-project based on which file is being edited. Project boundaries are detected by looking for markers like `pyproject.toml`, `package.json`, `.git`, or `CLAUDE.md`.

Rules and mistakes from the workspace root are inherited by all sub-projects. You don't need to configure anything.

## When To Use Tools

### Use When Helpful

- `memory(remember)` - Save an important discovery about the codebase.
- `memory(add_rule)` - Add a permanent rule (e.g., "always use strict TypeScript").
- `work(log_decision)` - Log an important architectural choice with reasoning.
- `work(log_mistake)` - Log a complex mistake the auto-detection missed.
- `impact_analyze` - Before refactoring shared files.
- `scout_search` - Semantic codebase search when grep isn't enough.
- `deps_map(symbol="X")` - "Where is X defined?" from the code index: file, signature, importers. Cheaper than a grep + read when you know the name but not its home.

### Advanced (Optional)

- `scope(declare)` - Set explicit file boundaries for a complex task.
- `context(checkpoint_save)` - Manual checkpoint for very long tasks.
- `memory(archive)` - Review and archive old memories.

### You Almost Never Need

- `session_start` - SessionStart hook auto-starts. Only call for deep context load.
- `session_end` - Stop + SessionEnd hooks handle teardown. Just a summary view.
- `pre_edit_check` - PreToolUse hook auto-runs this. Only call manually for impact analysis.

## Quick Reference

### Memory Operations

```python
# Store
memory(operation="remember", content="Important fact", project_path="/path")
memory(operation="add_rule", content="Always do X", reason="Because Y", project_path="/path")

# Find
memory(operation="search", query="auth", project_path="/path")
memory(operation="recent", project_path="/path", limit=10)

# Mistakes
memory(operation="list_mistakes", project_path="/path")                  # View all with IDs
memory(operation="acknowledge_mistake", memory_id="abc123", project_path="/path")  # Archive learned mistake

# Manage (IDs shown in [brackets] at session start and in hook output)
memory(operation="modify", memory_id="abc123", content="Updated", project_path="/path")
memory(operation="delete", memory_id="abc123", project_path="/path")
memory(operation="promote", memory_id="abc123", reason="Important", project_path="/path")
memory(operation="batch_delete", category="context", project_path="/path")

# Cleanup & Archive
memory(operation="cleanup", dry_run=True, project_path="/path")      # Preview: near-dupe removal + decay + archive
memory(operation="consolidate", dry_run=True, project_path="/path")  # Preview: merge a tag group into one digest (LLM)
memory(operation="consolidate", tag="decision", dry_run=False, project_path="/path")
memory(operation="clusters", project_path="/path")                    # List clusters (cluster_id expands one)
memory(operation="archive", dry_run=True, project_path="/path")       # Preview: move old to cold
memory(operation="archive_search", query="auth", project_path="/path") # Search cold tier
memory(operation="restore", memory_id="abc123", project_path="/path") # Bring back from archive
memory(operation="archive_status", project_path="/path")              # Hot vs archive counts
```

### Work Tracking

```python
work(operation="log_mistake", description="What broke", how_to_avoid="How to prevent")
work(operation="log_decision", decision="What you chose", reason="Why", alternatives=["Other options"])
```

### Context Protection

```python
# Checkpoint — save task state before compaction or session end
context(
    operation="checkpoint_save",
    task_description="Migrating auth to OAuth2",
    current_step="Step 3: token refresh",
    completed_steps=["Step 1: added provider config", "Step 2: login flow"],
    pending_steps=["Step 3: token refresh", "Step 4: tests"],
    files_involved=["auth.py", "oauth.py"],
    project_path="/path/to/project"
)

# Restore last checkpoint
context(operation="checkpoint_restore")

# Bridge to next session: checkpoint_save also carries handoff fields
# (handoff_create/get/list remain as deprecated aliases)
context(
    operation="checkpoint_save",
    task_description="OAuth2 migration",
    pending_steps=["Implement refresh_token()", "Add integration tests"],
    handoff_summary="OAuth2 migration 60% done, token refresh next",
    handoff_context_needed=["OAuth provider docs at docs/oauth.md"],
    handoff_warnings=["Don't touch legacy auth.py — still used by mobile"],
    project_path="/path/to/project"
)

# Restore an older entry from the ring (index=N; 0 = latest)
context(operation="checkpoint_restore", project_path="/path/to/project", index=1)

# Browse history newest-first (index, age, kind, summary)
context(operation="checkpoint_list", project_path="/path/to/project")

# Verify completion
context(operation="verify_completion", task="OAuth2 migration", verification_steps=["All tests pass", "Login flow works"])
```

## Memory System

### Categories

| Category | Purpose | Protected | Auto-captured |
|---|---|---|---|
| `rule` | Project rules that always apply | Never archived or decayed | No - manual |
| `lesson` | Curated insights synced from lesson files | Never archived or decayed; the source file owns the lifecycle | Opt-in - miner syncs the globs in `lessons_globs` |
| `mistake` | Errors to avoid repeating | Manual ones never archive; stale machine-written one-offs auto-archive, and provably-fixed ones archive via migration (all restorable) | Yes - from failed tools + transcript mining |
| `decision` | Choices and reasoning | No | Yes - from user prompts |
| `discovery` | Facts learned about the codebase | No | No - manual |
| `context` | Session-specific notes | No | No - manual |

### Tiered Storage

- **Hot tier** (`memory.json`) - Rules, mistakes, recent memories. Loaded by hooks on every tool call.
- **Cold tier** (`archive.json`) - Old inactive memories. Searchable, restorable, never loaded on hot path.
- Memories auto-archive after 14 days without access (configurable: `CLAUDE_ENGRAM_ARCHIVE_DAYS`).
- Rules never archive. Mistakes: manual ones never; auto-captured one-offs that went stale (3+ weeks, never recurred, away from current work) are archived by the background miner. Relevance **8+** exempts a memory from age-archiving entirely — deliberately above every default (manual `remember` is 5; the miner mints auto-captured decisions at 7). It was 7+, which exactly equalled the auto-capture default, so every auto-captured decision was born permanently exempt and the hot tier could not shrink.
- `cleanup` archives before deleting. Nothing is lost without review.
- `consolidate` is non-destructive: it keeps the 5 most relevant originals and **archives** the rest (searchable via `archive_search`, restorable by id). Scope it with `tag` — merging a group of hundreds into one paragraph loses the specifics that made each memory worth recalling.
- `cleanup` and `consolidate` solve different problems: cleanup drops NEAR-DUPLICATES (Jaccard and cosine at 0.85 — effectively the same memory stored twice), which is why it can report "0 duplicates" over hundreds of related decisions. `consolidate` merges a whole tag group into one LLM-written digest and archives the members. It needs 10+ entries in a group and never touches rules or mistakes (summarizing a specific actionable error into a vague blob destroys it).

### Smart Injection

Before every Edit/Write, the PreToolUse hook scores all hot memories against the current file context:

- 35% file path match (exact file > same dir > same extension > filename in content)
- 20% tag overlap (inferred from file path patterns)
- 20% recency (exponential decay over 30 days)
- 15% importance rating (1-10)
- 10% access frequency
- Rules get +0.3 bonus, mistakes get +0.2

File-path matching is path-aware: a shared basename across diverging paths (e.g. `service-a/myapp/__init__.py` vs `service-b/myapp/__init__.py`) is not treated as a match. Generic basenames like `__init__.py` or `index.js` require a full-path signal to score; specific filenames still match on name alone.

Top 3 are injected as context. You'll see them in the hook output before edits.

In multi-project workspaces, injection includes memories from the sub-project AND workspace-level memories (rules and mistakes cascade down).

Subagents (detected via `agent_id` in hook stdin) are handled differently: memory injection and hook output are skipped to preserve their limited context, but file edits are still tracked so the parent session knows what was modified.

### Decision Capture

User prompts are scored for decision intent using two tiers:

1. **Semantic scoring** (if `sentence-transformers` installed) - embedding cosine similarity against decision templates. A persistent scorer server (~1.1GB RAM with the default `bge-base-en-v1.5`, ~90MB with `all-MiniLM-L6-v2`; ~5-25ms per call) auto-starts on session start and auto-exits after 30 min idle. It is the only process that loads the model for a prompt: a hook that gets no answer from it scores with the regex tier, never by loading the model itself (a ~3 GB commit per hook process; it fired on every prompt of every session while no daemon was bound, 2026-09-25).
2. **Regex fallback** - Weighted keyword + sentence structure analysis. Always available, no dependencies.

Captures patterns like "let's use X", "switch to Y", "don't use Z", "from now on always W". Does not capture questions, requests for info, or ambiguous statements.

## Context Compaction

Handled automatically:

1. **Heads-up** ~10% of the window before the compaction point: finish the current step, start nothing long.
2. **`CHECKPOINT NOW`** 20K tokens above the auto-compaction trigger (10K on a 200K window). The trigger is the configured number minus a ~32K output reserve — measured, not documented: a 750K setting compacted at 717,578. Call `context(checkpoint_save)` with task, step, completed/pending steps, files, warnings and a handoff summary, then continue. Act on this one — a deliberate checkpoint beats the automatic entry.
3. **PreCompact** hook saves the automatic checkpoint (the floor) with task state and files in progress.
4. The **SessionStart(compact)** banner opens the next pressure cycle, states its rhythm, and re-injects rules, mistakes and the checkpoint banked before the compaction, with its goal and the repo's movement since. **PostCompact** opens the cycle too (idempotent, the order is undocumented) and pins what was restored for the report, but prints nothing: Claude Code's hook output schema has no PostCompact entry and rejects a `hookSpecificOutput` with that event name (2.1.268), while plain stdout never reaches the model.
5. **Milestones are yours to call.** When you judge a phase, step, or part of a plan done, call `context(checkpoint_save)` before ending the turn. Engram reads your final message at Stop; a completion claim ("Phase 1 built", "step 3 done, next is X", "all 60 checks pass") with no deliberate checkpoint behind it gets a nudge at the next opportunity. After ExitPlanMode, bank the approved plan with its steps as `pending_steps`. Never triggered by commits, never written for you.
6. **Fallback**: 60 turns with neither a deliberate checkpoint nor a completed step, a reminder — that condition is closer to a stall than a save schedule.

The distance is computed from the statusline's token counts (hooks receive none) against the actual compaction point: `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, else `autoCompactWindow` in settings, else the model default (200K boundary, or ~967K on a native-1M model). Never the raw percentage.

## Session Mining

Automatically mines Claude Code session JSONL logs for intelligence that hooks can't capture.

**Automatic (no invocation):**
- **Background indexing**: SessionEnd spawns miner that indexes the session, extracts decisions/mistakes/approaches, builds search embeddings
- **Smart session start**: Shows last session context (files edited, activity, errors)
- **Pattern injection**: Recurring struggles and errors shown at session start
- **Predictive context**: Before edits, shows related files and likely errors from history
- **Bootstrap**: First session on a new project auto-detects existing history and mines it

**MCP tool (`session_mine`):**
- `search(query)` — semantic search across all past conversations; accepts a `kind` filter (`decision`/`next-step`/`error`/`narration`) to narrow results by hit type (regex-classified, no LLM)
- `decisions(query)` — find when/why a decision was made, with context
- `replay(file_path)` — find discussions about a specific file
- `predict(file_path)` — predict what context you'll need for an edit
- `commitments` — reads the LIVE transcript (newest *.jsonl, picked by newest last-message timestamp) for open-loop items: DEFERRED channel scans ~450 recent messages for next-session/remaining/TODO/follow-up/defer mentions; IN-FLIGHT channel scans last ~30 messages for I'll/let me/next actions. Heuristic, LLM-free. Run before asking "what next?" or on resume — it sees the open session, which the post-session mining index cannot.
- `reflect` — injection precision report: which context kinds (memory/prediction/precheck/blast) precede passing tests, plus LLM-synthesized insights from recurring mistakes/patterns
- `cross_project` — patterns across all your projects
- `overview` — project stats (sessions, messages, top files, errors)
- `reindex(mode=bootstrap)` — rebuild index from all session history

## Technical Notes

- Local LLM: Ollama with `gemma3:12b` (configurable via `CLAUDE_ENGRAM_MODEL`) — **optional**. Used only by `scout_search`, `memory(consolidate)`, and `session_mine(reflect)` insight synthesis. Both background ops degrade silently when Ollama is absent. Everything proactive (hooks, code index, precheck, blast-radius, injection scoring) is LLM-free.
- Storage: `~/.claude_engram/` (manifest.json, projects/\<hash\>/{memory.json, embeddings.npy, session_index.json, extractions/}, checkpoints/). Override the location with `CLAUDE_ENGRAM_DIR`.
- Semantic scoring: configured encoder (default `BAAI/bge-base-en-v1.5`) via persistent TCP server on localhost (auto-managed). The resident daemon stays on cpu (zero VRAM parked); bulk embedding jobs (>= `CLAUDE_ENGRAM_GPU_BULK_MIN`, default 512 texts) run in a transient GPU worker that exits after the job — full VRAM release. Smaller batches run in the daemon at `CLAUDE_ENGRAM_CPU_BATCH` rows per pass (default 16): the daemon keeps the activation arena of its largest batch for life (measured 2026-09-15: 64 rows parked 1.2 GB more than 16 at the same speed; per-request growth is flat, no leak). `CLAUDE_ENGRAM_DEVICE` forces one device everywhere; vectors are device-identical so stores never rebuild. `claude_engram_status` shows the daemon's device.
- Scorer daemon threading: connections are handled per-thread, but every MODEL call is submitted to one pinned worker thread (`_on_model_thread`). PyTorch retains per-thread state that is never freed when a thread dies, so encoding on the ephemeral connection thread leaked ~0.73 MB per request (dead-linear, +146 MB per 200 requests, no plateau). Never call the model directly from a request thread. Input is capped at `MAX_ENCODE_CHARS` (2000) server-side — the encoder discards past 512 tokens regardless, and uncapped text ratcheted the allocator high-water mark
- Hook daemon: the same server runs high-frequency hooks in-process (warm imports); hooks are thin `python -S` clients with a full in-process fallback when the daemon is down
- Context pressure (`hooks/context_pressure.py`): the statusline mirrors `context_window.total_input_tokens` / `context_window_size` to `sessions/<session_id>.ctx.json`; every injecting hook calls `_with_pressure()` which computes distance to the compaction point and latches each nudge once per cycle in the session state (`pressure` block). PostCompact opens the next cycle and ignores a mirror older than the compaction (it still shows the pre-compaction count); `checkpoint_save` resets the cadence counter through the same state. `python -m claude_engram.hooks.context_pressure statusline` is a ready-made statusline; `assess <session_id>` prints the current reading. The `--autocompact` launch flag is not visible to hooks, so a window set only that way reads as the model default
- Stall detection (`hooks/stall.py`): tool calls are accounted to the open turn in the session state (`stall.turn`) by the PostToolBatch handler and the Edit/Bash PostToolUse fallbacks; `close_turn()` at Stop judges the turn (good / no-effect / neutral), advances strikes, and stages the strike text in `stall.pending`, which `_with_pressure()` delivers once with `_stall_bearings()` (checkpoint + rules) for strike 2+. The git working-tree fingerprint runs only on turns that otherwise look effect-free. Subagent batches are counted, never nudged
- Store freshness (`tools/memory.py`): `_project_stamps` / `_manifest_stamp` hold the (mtime_ns, size) of each loaded `memory.json` and the manifest; `get_project()` reloads a stale copy and re-reads a manifest another writer extended; `_save_project()` skips a stale project this process never dirtied (the `_save()` all-loaded fallback is what used to clobber) and merges by entry id when it did. Mark `_dirty_projects` in new mutators; the guard is the safety net, not the design
- Managed settings (`hooks/context_pressure.py`): `_managed_files()` (the docs' per-OS dir, `managed-settings.json` + `managed-settings.d/` drop-ins, later wins) and `_managed_registry()` (Windows `HKLM`/`HKCU` `SOFTWARE\Policies\ClaudeCode`) outrank project and user files; the env var still wins; source label `managed`
- Compliance (`hooks/compliance.py`): `MemoryEntry.detector` (rules only) is normalized/compiled by `compile_detector`; `rules_with_detectors(load_project_memory(...))` covers inherited rules; `_compliance_check()` in remind.py matches and records into `state["compliance"]` (matches deduped by `tool_use_id`, per-rule `health`); `_hook_pre_bash` (PreToolUse Bash|PowerShell, daemon-served) injects `rule_text()`; `_hook_post_batch` records the rest. The pack's detectors live in `default_pack.py` (`DESTRUCTIVE_DETECTOR`, `KILL_BY_NAME_DETECTOR`, `OUTBOUND_DETECTOR`); `seed_rules` attaches them to a covering rule via `_attach_detector` (walks up to the ancestor that owns the id). Verdicts are `unattended` / `prompted` / `plan` from `permission_mode`; never a judgment of the rule text
- Autonomy (`hooks/stall.py` §halt, `alerts.py`, `run.py`): `maybe_halt()` after `close_turn()` in the Stop branch arms `state["stall"]["halted"]` only when `autonomy_on()` (env) and strikes reached the cap; `_hook_pre_tool` (catch-all PreToolUse, daemon-served) is a one-read no-op unless halted, then denies all but `HALT_ALLOWED_TOOLS`; `release()` resets strikes and is an event. `alerts.send()` never raises and always records; the launcher passes its own `--alert-command` because its process env is not the child's. `run.py` is subprocess-only (no engram state of its own beyond the manifest); `--claude-bin` ending in `.py` runs under the interpreter (the bench's fake claude). The pack's code tier (`CODE_RULES`, `_CODE_MD`, `"code_rules"` opt-out) is the third tier; pack version 5
- Checkpoint provenance (`repo_state.py`): `save_checkpoint` stamps `commit` (git HEAD of the project) and `goal` (`goal_for_session`: the launcher's `run.goal`, else the transcript's last `goal_status` sentinel) into both the task file and the ring entry; `restore_checkpoint` and `_format_restored_context` print `Goal:` and `since_text(since(commit, project, files))` — commits and files since on this branch, the checkpoint's own files among them, plus commits on other local branches (`rev-list --branches --not <commit>`, worktrees included), or "not in this history". Best effort, silent outside a repo. The launcher's `prime_state()` writes `run.goal` / `run.manifest` before launch and `mark_session_started` keeps them
- `main()` in `remind.py` is at pyright's complexity ceiling: the SessionStart, PostCompact and Read branches live in `_hook_session_start` / `_hook_post_compact` / `_hook_pre_read`. Add new hook logic as a function, not another branch body
- Ring vocabulary: a ring record carries ONE name per concept — `next_steps`, `files_in_progress`, `warnings`, `context_needed`, `decisions`, `created`. The checkpoint-side twins (`pending_steps`, `files_involved`, `handoff_warnings`, `handoff_context_needed`, `key_decisions`, `timestamp`) are no longer written; they were byte-identical in all 129 stored records that had both, and carrying both made the restore payload print every list twice. Records already on disk keep both, and every reader takes either — so there is no migration. **`task_description` and `summary` are NOT a twin pair**: `summary` is the handoff note (`handoff_summary or task_description`) and differed from the task title in 110 of those 129 records. The per-task `task_*.json` file keeps the checkpoint vocabulary and is untouched
- Rewinds (`transcript_chain.py`, stdlib only): Claude Code's rewind (Esc Esc, /rewind) fires no hook and writes no record; the transcript is append-only, the abandoned turns stay in the file, and the next prompt is appended with the parentUuid of the record the user rewound to, so a rewind shows only as a fork. Files are restored from Claude Code's own `file-history-snapshot` records (Write/Edit only; a file written by a shell redirect does not revert). The live chain runs through the system and attachment records between turns. `branch_checkpoints` reads the `task_id: task_N` a `checkpoint_save` result printed, matched to its tool call by id (a `checkpoint_restore` result quotes an id too); `_own_session_checkpoint` reads one 8 MB tail per banner; the miner's `_live_messages` extracts the live branch only (the abandoned turns had been mined as history, 2026-09-26)
- Store hygiene the miner runs after a session: near-duplicate cleanup, stale one-off mistakes to the archive, and checkpoint task files older than 90 days (`handoff_store.TASK_FILE_KEEP_DAYS`) that no ring names any more are removed (every ring keeps its newest 20 full records; 1182 task files had piled up, 2026-09-26). A registered project whose path no longer exists is parked by migration `0.8.58:retire_gone_projects` under `_retired/<hash>/` with a note, never deleted; a path on an absent drive stays registered
- Checkpoint ring scope: a restore/list resolves the project's OWN ring, its DESCENDANT project rings, then its ancestors' — the global `checkpoints/` ring is a fallback used only when none of those exist. Descendants matter because a workspace root is a real place to restore from; without them a root-scoped restore read only the root ring and could return a stale entry while reporting success. Selection is by newest deliberate (manual) checkpoint, not by dir order, and responses name the store they came from
- Session identity: working state lives in `sessions/<session_id>.json` so concurrent sessions never clobber each other. Hooks read the id from their stdin payload; the MCP server adopts `CLAUDE_CODE_SESSION_ID` (exported to stdio MCP servers by Claude Code 2.1.154+) at startup, so MCP tools like `session_end` report THIS session instead of the shared fallback file. The scorer daemon deliberately opts out — one process serves many sessions and re-reads the id per request
- Outcome feedback: injection kinds that precede passing tests above baseline get a bounded scoring boost (0.8-1.2x), computed by the miner from `session_mine(reflect)` data
- Batch embeddings: `embed_batch` protocol for 22x faster bulk embedding (batch 256 on GPU, 64 on CPU)
- One scorer daemon, decided by a process lock (`hooks/proc_lock.py`, `~/.claude_engram/scorer.lock`, msvcrt/fcntl, released by the kernel at exit): `serve()` exits when the lock is held, `is_server_running()` reads the lock and nothing else, and a daemon's exit removes only the files that name its own pid. The old design decided by pid file plus a 0.5 s connect: a stalled daemon (8 pending connections filled its backlog in under a second) read as dead, its files were deleted, a second daemon spawned, the first idled 30 minutes at ~3 GB, and its exit deleted the second's files, so every idle exit orphaned the live daemon; under load the chain became a burst and the machine ran out of commit charge (2026-09-25). Backlog 64. `claude_engram_status` lists every engram process by role, size and store and warns at a second scorer or miner on the same store (`procs.py`; a bench's temp-store daemon is legitimate beside the real one, so the smoke tests set `CLAUDE_ENGRAM_NO_DAEMON` and never start one)
- Session mining: background subprocess, fire-and-forget, no hook timeout impact; the miner holds the same kind of process lock (`mining.lock`; four miners started together all won the old check-then-write pid file), and a post-session run within 600 s of the last completed one (`POST_SESSION_GAP_SECS`) runs as a live tick instead; `mining_status.json` records the peak resident memory of every phase (`rss_by_phase`, sampled by `PhaseMeter`; the patterns phase held 3.1 GB and freed it before its end, because `detect_struggles` walked the whole workspace tree to learn whether ~100 files still exist; it stats them now); plus debounced live ticks at turn end (`CLAUDE_ENGRAM_LIVE_MINE`, default 300s) so the index tracks the running session. A grown session is re-extracted whole but feeds only what the pass ADDED (the previous extraction file is the watermark; the store's dedupe is per project, so a changed destination is not a dedupe). An entry is filed under the registered project its files name; one with no files, or whose files cast no vote (relative traceback paths, files outside the root), goes where the session's own edits point (`SessionExtractions.session_files`), the same answer `session_project` gives the hooks
- Keep-alive: Set `CLAUDE_ENGRAM_KEEP_ALIVE=5m` to keep Ollama model loaded
- Hooks timeout: 1-2 seconds per hook. If a hook times out, it silently fails.
- All file writes use atomic temp-then-replace pattern.
- Hook installation merges into existing `~/.claude/settings.json` without destroying other hooks.
- Skill: `/engram` — quick reference installed to `~/.claude/skills/engram/`

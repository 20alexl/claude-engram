---
name: engram
description: Claude Engram persistent memory — quick reference for all MCP tools and automatic hook behaviors, plus the unattended-run commands (/engram run, status, release, report). Use when you need to remember how to store, search, or manage memories, query session history, or launch and supervise an unattended run.
argument-hint: "[run <goal> | status <session> | release <session> | report <session>]"
---

# Claude Engram — Quick Reference

## Slash commands (`/engram <subcommand>`)

The text after `/engram` is the subcommand. Do exactly this, nothing more:

- **`run <goal>`** — the loop is Claude Code's own `/goal`; engram brackets it. A goal is set only by the person typing `/goal`: you cannot type a slash command and no tool call sets one. So reply with exactly one line for the person to type, `/goal <the goal, written as something your own output can demonstrate; add "or stop after N turns" if a bound is wanted>`, and one sentence: from the next stop engram brackets the goal (autonomy mode on: three no-effect strikes halt every tool, ask-first rules refuse their commands, alerts go out, a turn cap then the halt, the goal stamped into every checkpoint, the run report at the end). Then stop; do not start working until the goal is set. When a plan of yours should run unattended, do the same: hand the person the `/goal` line, never a loop of your own.
- **`stop`** — a goal ends only from the person's keyboard: say "type `/goal clear`" (a met goal clears itself). If the run is halted, also `python -m claude_engram.hooks.stall release <session>`.
- For cron and overnight, outside any session: `python -m claude_engram.run --headless --goal "<goal>"` (the launcher; it puts the `/goal` line in the prompt itself; `--dry-run` prints the plan).
- **`status [<session>]`** — `python -m claude_engram.hooks.stall status <session>` (strikes, halted, alerts) plus `session_mine(run_report, session_id=<session>)` when the run has ended. Without a session id, list `.engram/runs/*.manifest.json` newest first and use the newest.
- **`release <session>`** — a person is lifting a halt: `python -m claude_engram.hooks.stall release <session>`, then say tools are allowed again and strikes are reset. Only on the user's word.
- **`report [<session>]`** — `session_mine(run_report, session_id=<session>)` and summarize: outcome, turns, cost, stalls, compliance matches, alerts, how it ended.
- Anything else, or no subcommand: this quick reference.

Requirements the launcher enforces, not you: `claude` on PATH; a project directory (the run's cwd); permissions `bypassPermissions` by default because nobody is there to answer a prompt.

## Automatic (hooks, zero invocation)
- Edit/error/decision tracking, loop warnings, compaction survival
- Session mining: background indexing after every session PLUS debounced live ticks at turn end — search/extractions/code-index stay fresh mid-session (CLAUDE_ENGRAM_LIVE_MINE, default 300s)
- Embeddings: resident daemon on cpu (zero VRAM parked); bulk jobs (512+ texts) run in a transient GPU worker that exits after the job (CLAUDE_ENGRAM_DEVICE forces one device; status shows the daemon's device)
- Smart session start: last session context + recurring patterns
- Predictive context: related files + likely errors before edits
- Pre-edit import/export check: proposed imports verified against the per-project code index (AST, LLM-free) — `<engram-precheck>` banner with closest-name suggestions
- Blast-radius: editing a shared module lists its importers — `<engram-blast-radius>`
- Read context: before Read of an indexed file, code-index orientation + that file's memories (`<engram-read-context>`, once per file per session)
- Error deja-vu: a failure matching a known recurring error gets the past fix injected inline at failure time ("Deja vu: TypeError hit in 3 past session(s) - fix: ...")
- Known-good test commands: session start lists the project's tracked test commands that currently pass
- Mistake hygiene: stale machine-written one-off mistakes (3+ weeks, never recurred, away from current work) auto-archive in the background — restorable via `memory(restore)`; failing TEST runs are never logged as mistakes (TDD-aware)
- Lessons bridge (opt-in): dated entries in curated note files sync as protected `lesson` memories with code-index triggers — enable with `lessons_globs` in ~/.claude_engram/config.json
- Session-start patterns are project-scoped: recurring errors/struggles filter to the sub-projects the last session touched; errors quiet 30 days drop out
- Outcome feedback loop: tracks which injection kinds (memory/prediction/precheck/blast) precede passing tests AND feeds back a bounded (0.8-1.2x) memory-injection multiplier; see `session_mine(reflect)`
- Tool duration tracking: slow tools surfaced in handoffs

## Memory Tools
- `memory(remember, content="...", project_path="...")` — store a discovery
- `memory(add_rule, content="...", reason="...", project_path="...")` — permanent rule (never archived)
- `memory(list_rules, project_path="...")` — show all rules with IDs
- `memory(search, query="...", project_path="...")` — keyword search
- `memory(hybrid_search, query="...", project_path="...")` — semantic + keyword
- `memory(recent, project_path="...")` — newest memories
- `memory(list_mistakes, project_path="...")` — view tracked mistakes with IDs and file associations
- `memory(acknowledge_mistake, memory_id="...", project_path="...")` — archive a learned mistake (stops pre-edit warnings)
- `memory(cleanup, dry_run=true, project_path="...")` — remove NEAR-duplicates (the same memory stored twice, 0.85 similarity), decay, archive
- `memory(consolidate, dry_run=true, tag="decision", project_path="...")` — merge a whole tag group into one LLM-written digest and archive the members. Different job from cleanup: that drops copies, this compresses a topic. Needs 10+ in a group; rules and mistakes are never touched
- `memory(clusters, project_path="...")` — list clusters and their sizes (`cluster_id` expands one)
- `memory(archive, project_path="...")` — move old memories to cold storage
- `memory(modify, memory_id="...", content="...", project_path="...")` — edit a memory
- `memory(delete, memory_id="...", project_path="...")` — remove a memory

## Work Tools
- `work(log_decision, decision="...", reason="...")` — log architectural choice
- `work(log_mistake, description="...", how_to_avoid="...")` — log complex mistake

## Code Lookup
- `deps_map(symbol="ClassOrFunc")` — where is it defined? File, signature, importers from the code index (typo-tolerant; cheaper than grep + read)
- `deps_map(file_path="...", include_reverse=true)` — a file's dependency graph + who imports it

## Session Mining Tools
- `session_mine(search, query="...", project_path="...")` — search past conversations (includes tool content)
- `session_mine(decisions, query="...", project_path="...")` — find when/why a decision was made
- `session_mine(replay, file_path="...", project_path="...")` — discussions about a file
- `session_mine(predict, file_path="...", project_path="...")` — predict context for an edit
- `session_mine(struggles, project_path="...")` — recurring struggle files
- `session_mine(errors, project_path="...")` — recurring error patterns
- `session_mine(overview, project_path="...")` — project stats
- `session_mine(reflect, project_path="...")` — injection precision (which context kinds precede passing tests) + LLM insights from recurring patterns
- `session_mine(commitments, project_path="...")` — what you said you'd do THIS session and whether it's done; scans the LIVE transcript (deferred open-loops + recent in-flight). Run before asking the user "what next?" or on resume
- `session_mine(search, query="...", kind="next-step")` — filter hits by kind: decision / next-step / error / narration
- `session_mine(search, query="...", since="2026-04-01")` — temporal filtering
- `session_mine(run_report, project_path="...")` — write and return this session's auditable run report (`<project>/.engram/runs/<date>-<session>.md` + `.json`): commits, turns, files with edit counts, tests, errors, compactions with sizes and what each restored, deliberate vs auto checkpoints, goal text, and what was not measured. Hook-captured facts only; SessionEnd writes the same file automatically for substantial sessions
- `session_mine(rotate, project_path="...", dry_run=true)` — rotation plan for session-logs (dailies > 30 d → archive/<month>/ + digest) and .learnings (dated entries > 90 d or over 500 lines → archive/); `dry_run=false` applies. Nothing is deleted. SessionEnd plans and SessionStart announces by default; `"rotation": "auto"` in `.engram/config.json` applies at session end
- `session_mine(reindex, mode="bootstrap", project_path="...")` — rebuild from history (shows results). On a large history this can exceed Claude Code's 2-minute MCP call limit and auto-continue in the background — the rebuild still finishes; re-run the query after it settles rather than re-triggering the rebuild

## Context Protection
Checkpoint and handoff are ONE construct (a durable ring). `checkpoint_*` are primary; `handoff_*` are deprecated aliases.

**Checkpoint vs mining:** a checkpoint is the durable note *you* write for the next session; session mining is what engram derives from the transcript. For "what's next" on resume, prefer `session_mine(commitments)` (reads the live session) over re-reading a stale checkpoint's pending_steps.
- `context(checkpoint_save, ...)` — save task/session state for compaction/recovery (add handoff_summary/handoff_context_needed/handoff_warnings to bridge to the next session; emits HANDOFF.md)
- `context(checkpoint_restore, project_path="...", index=0)` — restore a checkpoint (0 = latest, N = older from history)
- `context(checkpoint_list, project_path="...")` — list the unified history newest-first (index, age, kind, summary)
- `context(handoff_create | handoff_get | handoff_list, ...)` — deprecated aliases of the checkpoint_* ops above

**Compaction is announced, not sprung.** Engram measures the distance to the compaction point (not the raw context percent) and injects `<engram-context>` twice per cycle: a heads-up ~10% of the window out (finish the step, start nothing long) and `CHECKPOINT NOW` ~3% out. Act on the second: write a full `checkpoint_save` (task, step, completed/pending, files, warnings, handoff_summary) and continue — the PreCompact auto entry is only the floor. After a compaction the banner restates the rhythm; a cadence reminder fires after 60 turns with neither a deliberate save nor a completed step. If the banner says the configured compaction point is capped at this model's window, the person at the terminal sets the number it names (`/autocompact 150k` on a 200K model); you cannot. A `Usage budget` line means the 5-hour or 7-day subscription window is nearly spent: a limit hit ends the turn on an API error that nothing retries, so finish the step, checkpoint, and park on a ScheduleWakeup or Monitor until the reset time it names. Needs a statusline that records the mirror (README: Context pressure); engram says so at session start when there is none.

For rules use the dedicated API: `memory(add_rule / list_rules / delete)`.

Example:
```
context(
  operation="checkpoint_save",
  task_description="Fixing auth module",
  current_step="Step 3: token validation",
  completed_steps=["Step 1: added middleware", "Step 2: wrote tests"],
  pending_steps=["Step 3: token validation", "Step 4: deploy"],
  files_involved=["auth.py", "middleware.py"],
  project_path="/path/to/project"
)
```

## Memory Categories
| Category | Protected | Auto-captured |
|---|---|---|
| rule | Never archived | Manual (via memory add_rule) |
| lesson | Never archived; source file owns lifecycle | Opt-in sync from lessons_globs files |
| mistake | Archivable via acknowledge; stale machine-written one-offs self-archive; provably-fixed ones archived by migration | Auto from errors in project files + transcript mining |
| decision | No | Auto from prompts + session mining |
| discovery | No | Manual |

## Key Behaviors
- Rules cascade from workspace to sub-projects
- Only file-relevant memories inject before edits (no generic noise)
- Pre-edit injection is path-aware: a shared basename across diverging paths (e.g. service-a/.../__init__.py vs service-b/.../__init__.py) is not treated as a match; generic basenames like `__init__.py` or `index.js` require a full-path signal to score
- Mistakes only logged from errors in project files (not inline python, not pip packages)
- Loop detection state is per-session: edit counts and test results live in the session's hook state, so two concurrent sessions never cross-contaminate; the counter resets after git commits
- Scorer server auto-starts on demand (no silent degradation)
- Session mining runs in background after SessionEnd
- Bootstrap: first session on new project auto-mines existing history
- Checkpoints/handoffs are durable: the history ring (last 20) holds DELIBERATE manual checkpoints only — per-turn autos contend just for the latest pointer, so they can never evict your saves; manual always wins the teaser (14-day freshness vs 48h for autos); the SessionStart teaser resolves the resumed session's own sub-project and labels entries `[kind, age, project, task_id]` so you can `checkpoint_restore(task_id=...)` exactly what was teased; retrieve any entry via `checkpoint_restore(index=N)` or browse with `checkpoint_list`
- Checkpoints are per-project (multi-project workspaces don't clobber each other)
- **Checkpoint when YOU judge a step done.** Before you declare a phase, step, or part of a plan finished, call `context(checkpoint_save)` — what closed, what is next. Engram reads your final message at Stop; a completion claim with no deliberate checkpoint behind it gets a nudge next turn (`<engram-context>Last turn you closed a step...`). After ExitPlanMode, bank the approved plan with its steps as `pending_steps`. Engram never writes the checkpoint for you and never triggers on commits
- **`<engram-stall>` means you changed nothing for three turns.** Engram judges each turn by effect (a file changed, a test status flipped, a commit, delegated work), not by tool use. Strike 1: if it was research, say what you are looking for; if you are re-reading or re-running the same thing waiting for it to change, name the blocker and either change approach or park on Monitor / ScheduleWakeup instead of polling. Strike 2: answer the bearings check (task, last real change, blocker, different action) in one line each before the next tool call. Strikes decay after five turns with real effect. Turns with no tools or parked on a wait primitive never count
- **A restored checkpoint prints the goal and a staleness line** ("Since this checkpoint: 2 commits, 5 files changed -- incl. app.py"). Read that line before acting on the handoff: the checkpoint carries the last session's framing, and the repo may have moved. In an unattended run, a shell command that matches an ask-first rule (destructive, kill by name, leaves the machine) is refused outright with the rule as the reason: record what you need approved in a checkpoint, send a PushNotification, and continue with allowed work or stop; never work around it.
- **`<engram-rule>` before a shell command means the command matches a rule's detector.** Read the rule. If it says ask first and the mode is unattended (no person at the prompt), stop and ask instead of running it; the match is in the run report either way. Give your own rules teeth with `memory(add_rule, detector={tools, command, paths, input, note})` or `memory(set_detector, memory_id, detector)`; detectors are hand-written, never inferred, and a rule without one is advisory in the report
- Subagents: memory injection and output are skipped (saves context), but file edits are still tracked
- Ollama is optional: only `memory(consolidate)` and `session_mine(reflect)` insight synthesis use it (both background, both degrade silently); `scout_search` uses it when available. Everything else is LLM-free
- No emojis in any output

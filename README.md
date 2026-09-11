# Claude Engram

Persistent memory and session intelligence for Claude Code. Hooks into the session lifecycle to auto-track mistakes, decisions, and context — then mines your full session history so past work resurfaces exactly when it's relevant.

Zero manual effort. Works with any MCP-compatible client.

## What It Does

Everything below is automatic (hooks) unless marked as a tool:

- Tracks every edit, error, test result, and session event; captures decisions straight from your prompts ("let's use X")
- Injects the 3 most relevant memories before each file edit; warns before you repeat a past mistake
- Error deja-vu: a failure matching a known recurring error gets the past fix injected at failure time
- Verifies imports and shows blast radius before edits, and orients before reads — all from a per-project code index (AST, no LLM)
- Lists the project's known-good test commands at session start
- Survives compaction: checkpoint before, re-inject after; deliberate checkpoints live in a durable per-project ring
- Mines your full history in the background (and live, mid-session): decisions, mistakes, recurring struggles — searchable across everything you've ever discussed, scoped to the right sub-project
- Stays honest: failing TDD runs aren't logged as mistakes, edit loops get flagged, subagents are tracked without wasting their context
- **Tools** (on demand): `memory`, `session_mine`, `work`, `context` checkpoints, `deps_map`, `impact_analyze`, `scout_search` — all annotated read-only/idempotent where true. `/engram` loads the full reference.

## How to Use It Effectively

From the author — mostly it just works in the background. The few things worth doing on purpose:

- **Pull `/engram`** when you want Claude to actively reach for the tools (background tracking happens either way).
- Half-remember something from weeks ago? Ask Claude to **mine the sessions** for it — it searches everything, not just what's in context.
- Something it should never forget → save it as a **rule**. Per-project rules stay local; rules at your workspace root cascade to every project under it.
- Before compacting, it auto-checkpoints — but a **manual checkpoint** with what you're doing and what's left resumes far cleaner. Deliberate saves always beat automatic ones.
- On return, ask **what you said you'd do this session** (`session_mine(commitments)`) — a quick, best-effort reorient from the live transcript.

The less you poke at it, the better it works. Work in progress — issues welcome.

## How It Works

```
Claude Code
    |
    +-- Hooks (remind.py)          <- intercept every tool call (1-2s budget)
    +-- Session mining (mining/)   <- background + live-tick intelligence
    +-- MCP server (server.py)     <- on-demand tools
    +-- Scorer daemon              <- warm encoder + hook dispatch, cpu-resident;
                                      bulk embeddings in a transient GPU worker
```

## Benchmarks

**Retrieval (recall@k):** LongMemEval 0.966 R@5 / 0.982 R@10 (500 questions), ConvoMem 0.960 (250 items), LoCoMo 0.649 R@10 (~2k questions); ~43ms/query, 112ms cross-session over 7,310 chunks.

**Product behavior:** integration suites green — decision capture (97.8% precision), error auto-capture (100% recall), compaction survival (6/6), multi-project isolation (11/11), edit-loop detection (12/12), session mining (64/64), Obsidian-vault compat (25/25).

Full tables and reproduction commands: **[library-book](./library-book/)**.

## Compatibility

| Platform | What Works | Auto-Capture |
|---|---|---|
| **Claude Code** (CLI, desktop, VS Code, JetBrains) | Everything | Full — hooks + session mining |
| **Cursor / Windsurf / Continue.dev / Zed / any MCP client** | MCP tools | No hooks |
| **Obsidian vaults** | Full (with CLAUDE.md at root) | Full with Claude Code |

## Install

```bash
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Core
pip install -e ".[semantic]"    # + embedding model for vector search and semantic scoring

python install.py               # Hooks, MCP server, /engram skill, migrations
```

### Per-Project Setup

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` to your project root. That's the only per-project file — hooks and the `/engram` skill are global. (The `CLAUDE.md` in this repo documents engram for people working *on* engram; your projects don't need it.)

### Updating

```bash
cd claude-engram
git pull
pip install -e ".[semantic]"    # Reinstall if dependencies changed
python install.py               # Re-run to update hooks and /engram skill
```

Hooks pick up code changes immediately (editable install); reconnect the MCP server (`/mcp`) to reload it. Data migrations run automatically and are forward-only, idempotent, and downgrade-safe.

### Mid-Project Adoption

Install normally. On first session, engram detects your existing Claude Code history and mines it in the background — decisions, mistakes, and patterns from every past conversation.

## Configuration

All optional. Deep detail on each lives in the [library-book](./library-book/).

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model — only `scout_search`, `memory(consolidate)`, `session_mine(reflect)` use it |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `BAAI/bge-base-en-v1.5` | Embedding model (~1.1GB scorer RAM). `all-MiniLM-L6-v2` for a ~90MB setup at lower accuracy |
| `CLAUDE_ENGRAM_EMBED_DIM` | model native | Matryoshka truncation dim. Stores are signature-stamped — model changes rebuild them automatically |
| `CLAUDE_ENGRAM_DEVICE` | smart | Unset: daemon stays on cpu, bulk jobs use a transient GPU worker (full VRAM release). `cuda`/`cpu` forces one device |
| `CLAUDE_ENGRAM_GPU_BULK_MIN` | `512` | Job size (texts) that routes to the GPU worker |
| `CLAUDE_ENGRAM_GPU_BATCH` | `64` | Rows per forward pass on the GPU. Raise it on a card with headroom; the peak scales linearly (~26 MiB/row) |
| `CLAUDE_ENGRAM_LIVE_MINE` | `300` | Live mining tick interval (seconds); `0` disables |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | Scorer daemon idle timeout (seconds) |
| `CLAUDE_ENGRAM_DIR` | `~/.claude_engram` | Storage location (also the test-isolation seam) |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `0` (keep all) | Prune session-search shards older than N days |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | unset | Mirror last-read file path to this file (statusline integration) |
| `CLAUDE_ENGRAM_HEADSUP_FRACTION` | `0.10` | Heads-up nudge this fraction of the window before the compaction point |
| `CLAUDE_ENGRAM_CHECKPOINT_FRACTION` | `0.03` (`0.05` on a 200K window) | `CHECKPOINT NOW` nudge this fraction of the window before the compaction point |
| `CLAUDE_ENGRAM_CHECKPOINT_CADENCE` | `25` | Turns without a deliberate checkpoint before the cadence reminder |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | unset | `1` prints a stderr breadcrumb per hook |

`~/.claude_engram/config.json` additionally accepts `embed_model`, `embed_dim`, and `lessons_globs` (opt-in lessons bridge: globs of curated markdown whose dated entries sync as protected memories).

## Context pressure

Hooks never see context usage; the statusline does. Engram mirrors the statusline's token counts to a per-session file, and its hooks compute the **distance to the point where auto-compaction fires**. Not the raw percentage: that is against the full 200K/1M window, while a native-1M model compacts at about 967K by default and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `autoCompactWindow` move the point.

| Distance to the compaction point | Engram injects |
|---|---|
| ~10% of the window out | Heads-up: finish the current step, start nothing long |
| 20K tokens above the auto-compaction trigger (10K on a 200K window) | `CHECKPOINT NOW`: write a deliberate `context(checkpoint_save)`. PreCompact's automatic entry is only the floor |
| 60 turns with neither a checkpoint nor a completed step | Fallback reminder. That condition is closer to a stall than a save schedule |

Auto-compaction does not fire at the configured number. Claude Code keeps room for the model's output first, so the trigger sits about 32K tokens below the setting (measured: a 750K setting compacted at 717,578). Engram places the last band above that trigger, not a fraction below the setting; `CLAUDE_ENGRAM_OUTPUT_RESERVE` and `CLAUDE_ENGRAM_CHECKPOINT_MARGIN` tune it. Each band fires once per compaction cycle. After a compaction the PostCompact banner restates the rhythm (`heads-up at ~650K, checkpoint at ~698K, auto-compaction at ~718K`) so the model plans work in units that finish before the checkpoint call, and the session-start banner shows the checkpoint that was banked before it, with its goal and how far the repo has moved since.

**Milestones are the model's call.** The other moment a checkpoint belongs is when a unit of work closes, and the model is the one who knows. The rule in the skill says: when you judge a phase, step, or part of a plan done, checkpoint before you say so. Engram reads the model's final message at Stop; a completion claim ("Phase 1 built", "step 3 done, next is X", "all 60 checks pass") with no deliberate checkpoint behind it gets one nudge at the next opportunity, quoting the sentence. Questions, negations and future tense never fire ("is step 3 done?", "not done yet", "once the tests pass"). After ExitPlanMode it asks for the approved plan to be banked with its steps as `pending_steps`, so every later "done" maps onto that list. On models that have Claude Code's task tools, a task marked completed is the same signal stated structurally. Nothing is ever written for the model, and commits are not a trigger.

**What a checkpoint carries, and what a restore says.** Every deliberate checkpoint records the commit the repo stood at and the active `/goal` condition, if any. A restore, whether the session-start banner or `context(checkpoint_restore)`, prints the goal and one staleness line: how many commits and files changed since the checkpoint was saved, naming the checkpoint's own files among them, or that its commit is not in this history. A handoff carries the last session's framing; that line is what the model reads before acting on it.

**Setup**, one of:

- No statusline yet — use engram's. It prints `Fable 5.1 | ctx 660K/1000K | compact at 750K (90K left) | $1.25 | proj`:

  ```json
  "statusLine": {"type": "command", "command": "<venv python> -m claude_engram.hooks.context_pressure statusline"}
  ```

- Your own statusline script — call `claude_engram.hooks.context_pressure.record_statusline(data)` with the JSON it received, or write the same record to `~/.claude_engram/sessions/<session_id>.ctx.json` yourself (eight flat fields; see the module docstring). No engram import is needed for the second form, which matters when the statusline runs under a different python than the hooks.

Without a statusline engram says so at session start, and only the cadence runs. A window set only by the `--autocompact` launch flag is invisible to hooks; engram falls back to the model default and names the source it used. The setting is read with Claude Code's own precedence: the env var, then managed settings (`managed-settings.json`, the `managed-settings.d/` drop-ins, the Windows policy registry key), then project-local, project and user settings.

For long unattended runs, set the point yourself: `CLAUDE_CODE_AUTO_COMPACT_WINDOW=750000` on a 1M model keeps turns cheaper, leaves headroom against the overflow that ends a `/goal` run, and puts the checkpoint nudge a known distance below a number you chose.

The setting is a token count, not a fraction, and it is capped at the model's window. `/autocompact 750k` is 75% of a 1M model and the whole window of a 200K one, which leaves no room for the checkpoint call. Hooks cannot change a live session's point, so engram tells you once, at the first context reading, when the configured number does not fit the model, with the number that does (`/autocompact 150k` on 200K). A 200K model with no setting gets the same one-line notice.

**Usage limits.** On a Claude.ai plan the statusline also receives the 5-hour and 7-day usage windows, and engram mirrors them beside the token counts. A run that hits a limit ends on an API error that no Stop hook sees and that Claude Code does not retry, so a goal loop dies there. At 90% of the 5-hour window (95% of the weekly) engram says so once per window, with the reset time, and asks for a checkpoint and a park on a wakeup until the reset instead of running into the limit mid-step. The `StopFailure` hook records every API failure with its type and, for a limit, when the window resets; the run report shows it. API-key sessions get no windows and no nudge. Thresholds: `CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT`, `CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT`. A custom statusline script mirrors the two windows by copying `rate_limits.five_hour` / `seven_day` (`used_percentage`, `resets_at`) into the same record as `five_hour_pct` / `five_hour_resets_at` and `seven_day_pct` / `seven_day_resets_at`.

## Stall detection

`/goal`'s own stall rule stops a loop after several turns with **no tool use**. The overnight failure that matters is the other one: a run that uses a tool every turn and changes nothing. Seen live, a goal loop ran nine turns of `cat` on a file that was never going to change; the stall rule never fired because every turn used a tool. Engram judges a turn by its **effect**:

| Turn | Counts as |
|---|---|
| A file changed (Edit/Write/NotebookEdit, a mutating shell command, or the git working tree moved), a test status flipped, a commit landed, work was delegated to an agent | Good |
| Tools were used and none of that happened | No effect |
| No tools at all; the turn parked on a wait primitive (Monitor, ScheduleWakeup, a cron, a background task); or it only ran tests that were not a repeat of the last run | Neutral: touches nothing |

Turns, not time: a four-hour foreground command is one turn, so a long run or a long suite never trips the ladder on duration. Verification is neutral (three different benches in three turns is not circling); the same test command with the same verdict again is the re-run-and-hope pattern and counts as no effect.

Three consecutive no-effect turns are one strike. Strike 1 is a warning that names the pattern and asks for a wait primitive instead of polling. Strike 2 re-injects the latest checkpoint and the rules and asks for a bearings check (task, last real change, blocker, different action). Strike 3 is the cap; in autonomy mode it becomes the halt. **Strikes decay rather than reset**: five consecutive good turns remove one, repeatedly, down to zero. A hard reset would let one edited line wipe a pattern of stalls; no decay would halt an eight-hour run over three stalls spread across it. Every increment and decrement is an event with its turn number in the run report. Tune with `CLAUDE_ENGRAM_STALL_TURNS`, `CLAUDE_ENGRAM_STALL_DECAY`, `CLAUDE_ENGRAM_STRIKE_CAP`.

Accounting arrives from the `PostToolBatch` hook (every call in a batch, no matcher), with the Edit and Bash `PostToolUse` handlers as a fallback for settings that predate it; the turn is judged at Stop, and the strike text is delivered at the next injection point. Re-run `python install.py` to register the batch hook.

## Rules compliance

Rules are natural language and stay that way. A rule may carry a **detector**, hand-written and never inferred: tool names, a regex against a shell command, globs against an edited path, or a regex against the tool input. With one, every matching tool call is recorded in the run report with the turn, an excerpt of the input, and a verdict that is only what the hooks can see: `unattended` (bypass, auto or dontAsk mode, so no person approved the call) or `prompted` (Claude Code's own permission prompt stood between the model and the call). A rule without a detector is advisory, and the report says so per rule. Detector health is shown too, so a regex that stopped compiling is visible rather than silently ignored. No language model sits in this path.

The live half runs at PreToolUse on shell commands: a matching command gets the rule injected before it runs, which in an interactive session is the reminder at the moment it matters. Other tools are matched at PostToolBatch (path globs on edits, MCP tools by name).

```text
memory(add_rule, content="Never push without asking", detector={"tools": ["Bash"], "command": "\\bgit\\s+push\\b", "note": "push"})
memory(set_detector, memory_id=<rule id>, detector={...})   # {} clears
```

A detector may say what to do when nobody is at the prompt: `"unattended": "deny"`. In autonomy mode (the launcher's runs) a matching shell command is then refused with the rule as the reason, and the model is told to record what it needs approved, notify, and continue with allowed work. An attended session, even in bypass mode, is never refused, only shown the rule.

The default pack ships detectors on the rules that need one, all marked deny unattended: destructive shell commands (recursive or forced deletes, hard resets, force-push, DROP and TRUNCATE, disk formats, kills), kill by image name, and anything that leaves the machine (push, pull request, publish, outbound POST). A project whose own rule already covers that ground adopts the pack detector if it has none. `"compliance": false` in `.engram/config.json` or `CLAUDE_ENGRAM_COMPLIANCE=off` turns the trail off; re-run `python install.py` to register the shell PreToolUse hook.

## Autonomy mode

Engram does not invent a loop. `/goal` is the loop; engram brackets it so an unattended run cannot burn a night polling, cannot lose its record, and cannot die silently.

```text
/goal <condition>                        # Claude Code's own loop; engram brackets it from the next stop
/goal clear  ·  /engram status  ·  /engram report  ·  /engram release <session>
python -m claude_engram.run --headless --goal "<goal>" --alert-command 'curl -s -d {message} https://ntfy.sh/<topic>'   # cron / overnight only
```

You type `/goal`, in the session you are in. A goal is set only from the keyboard: no flag, setting, hook output or tool call sets one, and Claude cannot type a slash command, so when a plan should run unattended Claude hands you the exact `/goal` line and waits. From the next stop engram sees the goal in the transcript and brackets it: autonomy mode is on for the goal's life, so ask-first rules refuse their commands, three no-effect strikes halt every tool, alerts go out, the goal is stamped into every checkpoint, and the compaction point and the budget nudges do their work. Engram cannot end a goal loop (hooks merge most-restrictive), so its turn cap arms the same halt and the alert asks you to `/goal clear`. Engram never judges the goal: Claude Code's evaluator does, reading what Claude surfaces in the conversation, so the goal is best written as something Claude's own output can demonstrate. The run ends when the evaluator says met (the goal clears itself), judges it impossible, or you clear it, and engram writes the run report with a "Goal run" section: goal, turns against the cap, verdicts, how it ended.

Every goal run writes a manifest (goal, the rules in scope with their detectors, the start commit) when it starts and an alert when it ends.

For cron and overnight, outside any session, the launcher runs `claude -p` with the same supervision: it sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 75% of the model's window, a hard `--max-turns`, the park instruction, and after a usage-limit exit sleeps until the window resets and resumes the same session. Cost is the same as any session: a Claude.ai plan pays with its usage windows, an API key or an enterprise provider pays per token; the `total_cost_usd` a headless run prints is Claude Code's own client-side estimate.

Inside the run, `CLAUDE_ENGRAM_AUTONOMY=1` arms two things:

- **The halt.** At the strike cap every tool call is denied, with a reason the model sees, except PushNotification, ToolSearch and engram's checkpoint call, so the model can leave a record and a one-line notification, then stop. A deny ends the turn; with no tool use the goal's own stall rule closes the loop. Engram never fights the Stop hook. A person lifts the halt with `python -m claude_engram.hooks.stall release <session>`; strikes reset.
- **Alerts.** A halt, an API failure (`StopFailure`), a run waiting on a person (a permission prompt, needs input, idle), the launcher pausing for a usage limit, and the run ending each send one line under 200 characters through the command you configured (`alert_command` in `.engram/config.json`, `CLAUDE_ENGRAM_ALERT_COMMAND`, or `--alert-command`; `{message}` is replaced, or the message arrives on stdin). No service is built in. Every alert is recorded in the run report whether or not a command was configured. PushNotification is the model's tool, not a hook's; on a headless run the desktop notification has nowhere to land, which is why the command exists.

`/engram status <session>` shows strikes, the halt and the alerts; `/engram report <session>` summarizes the run report. Live-verified on a Sonnet run built to stall: the third read was denied, the model stopped polling and sent its notification, and the turn cap closed the run.

## Defaults: structure, rules, rotation

Engram ships an opinion about how a project is kept, on by default and one line to turn off in `<project>/.engram/config.json`:

- **Structure.** A project (a git repo, a package manifest, or a `CLAUDE.md`) gets the scaffold if pieces are missing: a headered `CLAUDE.md` with Purpose / Testing / Structure, `.learnings/ERRORS.md`, `.learnings/LEARNINGS.md`, `session-logs/`. A multi-person layout (`.learnings/<name>/`, `session-logs/<name>/`) is left as it is. `"structure": false`.
- **Rules.** Three tiers seeded once into the project's memory on its first session. *Code* (how code is written): one function, one purpose; semantic names and comments that explain why; nothing left lying around; verify by quoting what it printed; never swallow an error on the decision path; same inputs, same outputs; the real thing over a stand-in; no secrets anywhere; performance from the start; both Windows and Linux; the fast path on purpose; never do work twice; smart over busy. It lands as `## Code` in the scaffolded `CLAUDE.md`; `"code_rules": false` opts out. *Universal*: no destructive commands without asking, search first, quality over speed, prerequisites first, be direct, try before asking, private stays private, proactively push back, follow the plan sequentially, never kill by image name, session maintenance, checkpoint when you judge a step done. *Workflow*: plan before code; proposed, open and decided are three things; every milestone has a gate before and a verdict after, and a large one gets an independent review; delegate by size with a hard agent budget; verify before claiming done; numbers get a source; anything that leaves the machine is the owner's decision; write the learning when it happens. The same workflow text lands in the scaffolded `CLAUDE.md`. Any rule the project or an ancestor already has in substance is skipped, so your own rules win. `memory(list_rules)` shows them; `"default_rules": false` (all) or `"workflow_rules": false` (the second tier).
- **Rotation.** Nothing is deleted, ever. Dailies older than 30 days move to `session-logs/archive/<month>/` with a monthly digest beside them; dated `ERRORS.md` entries older than 90 days move to `.learnings/archive/ERRORS-<year>.md`; `LEARNINGS.md` holds patterns, which do not age out, so it rotates only when over the cap. Either file over 500 lines sheds its oldest 30-day-plus entries until it fits. Undated and STANDING/permanent entries never move. Each trimmed file gets a one-line note under its title saying what moved and where. Per-person folders rotate inside themselves. By default SessionEnd only plans and SessionStart announces; `session_mine(rotate, dry_run=false)` applies, `"rotation": "auto"` applies at every session end, `"rotation": false` stops planning. Thresholds: `rotation_log_days` (30), `rotation_learn_days` (90, ERRORS), `rotation_learnings_days` (0 = cap only), `rotation_learn_max_lines` (500).

```json
{"rotation": "auto", "default_rules": false, "structure": true}
```

## Run report

Every substantial session leaves one auditable artifact in the repo: `<project>/.engram/runs/<date>-<session>.md` plus a `.json` twin, written at SessionEnd or on demand with `session_mine(run_report)` / `python -m claude_engram.run_report --session <id>`. Add `.engram/runs/` to the project's `.gitignore` (the reports carry session ids, costs and local paths; `.engram/config.json` is the file worth tracking). Every line is hook-captured or read from the transcript, never self-reported by the model:

- the `/goal` condition, every evaluator verdict with its reason, and the outcome (met / failed / unresolved), read from the transcript's own goal records; model, permission mode, branch, start → end commit
- wall time, turns, prompts, context at end and cost
- every compaction with trigger, before → after token sizes (from the transcript's own compaction record) and which checkpoint it restored
- files touched with per-file edit counts; test runs, first and last status
- errors grouped by signature, recurrences, and whether the miner already knew them
- checkpoints written this session, deliberate vs automatic
- stalls: turns with and without effect, every strike and decay with its turn number
- what was **not** measured, listed rather than omitted (rules compliance arrives in a later phase)

Headless goal runs leave the same report: `claude -p "/goal <condition>"` runs the loop to completion and SessionEnd writes it. From Git Bash on Windows, set `MSYS_NO_PATHCONV=1` or the leading `/goal` is rewritten into a filesystem path and Claude gets a plain prompt. `/goal` and `/loop` compose only when the goal is parked. Scheduled tasks fire while the session is idle, and a not-met goal re-prompts at once, so a goal with nothing to do burns turns and starves the loop (seen live: nine verdicts in two minutes, a cron fire lost). A goal idles while it waits on background work, a Monitor or a self-paced wakeup, and the loop fires then. Tell the model to park on such a primitive instead of polling.

## Reindexing

If search quality degrades or after a big update:

```bash
python scripts/reindex.py "/path/to/your/workspace" --force            # rebuild search index
python scripts/reindex.py "/path/to/your/workspace" --force --extract  # also re-extract decisions/mistakes
```

Or via MCP: `session_mine(operation="reindex", mode="bootstrap")`

## Documentation

**[Library Book](./library-book/)** — design, internals, full usage guide, API reference, gotchas, changelog.

**`/engram`** — quick tool reference (installed by `install.py`).

## License

MIT

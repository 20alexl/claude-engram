# Claude Engram

Persistent memory and session intelligence for Claude Code. Engram hooks into the session lifecycle and tracks mistakes, decisions, edits, tests and context on its own. It mines your full session history so past work comes back when it is relevant. It keeps long sessions safe across compaction. And it brackets Claude Code's `/goal` loop so an unattended run cannot poll all night, lose its record, or die silently.

Most of it runs through hooks with nothing to call. The rest is MCP tools, so any MCP client can use the tools, and Claude Code gets the hooks as well.

Contents: [What runs on its own](#what-runs-on-its-own) · [Install](#install) · [Day to day](#day-to-day) · [The tools](#the-tools) · [Memory](#memory) · [Checkpoints and compaction](#checkpoints-and-compaction) · [Unattended runs](#unattended-runs) · [Rules with detectors](#rules-with-detectors) · [Project defaults](#project-defaults) · [Run report](#run-report) · [Session mining](#session-mining) · [Configuration](#configuration) · [Storage](#storage) · [Compatibility](#compatibility) · [Benchmarks](#benchmarks)

## What runs on its own

Every row is a hook. You call nothing.

| Moment | What engram does |
|---|---|
| Session start | Prints the banner: the project's rules (inherited ones marked), its own past mistakes with a count of the pooled ones (every count names the project it was read for, the same store the prompt hook counts), the latest deliberate checkpoint with its `/goal` and how far the repo moved since, on this branch and on other local branches since the checkpoint was saved (worktrees included), last session's files (narrowed to the sub-project most of its edits belong to when the session spanned several, and labeled so) and activity, recurring errors with their known fixes, and the project's known-good test commands that currently pass. Runs data migrations. Every block is scoped to the project the session is about, which engram reads from the session's own Edit and Write calls in the transcript, not from the working directory. On a resume or after a compaction that project is known at start; on a fresh start the recurring errors and known-good commands wait for the first edit, when the file names the project. Engram's own failures never appear as a project's recurring errors. On a project's first session, finds existing Claude Code history and mines it in the background. Seeds the default pack once (see [Project defaults](#project-defaults)) and announces a pending rotation. Warns when Claude Code's transcript format is no longer recognized, and when no statusline records context usage |
| Every prompt | Captures decisions from what you type ("let's use X", "switch to Y", "from now on always Z") by semantic scoring with a regex fallback, then a shape gate shared with the transcript miner: a declarative sentence with a deciding word, never a question, an acknowledgement, a count or a table row. Questions and requests for information are not captured. Delivers any staged nudge |
| Before an edit | Injects the three memories most relevant to the file (a rule only when it names the file, an entry older than a month only when it names the full path), warns before a past mistake tied to that file (a code exception is never predicted for a non-code file), warns after three edits to the same file in one session (edit loop), verifies that a proposed import resolves against the per-project code index (`<engram-precheck>`, with the closest name), lists the modules that import the file (`<engram-blast-radius>`), shows related files and likely errors from history, and checks the declared task scope |
| Before a read | Once per file per session: an orientation from the code index plus the file's most relevant memories (`<engram-read-context>`) |
| Before a shell command | Matches the command against every rule that carries a detector and injects the rule before the command runs (`<engram-rule>`). Under a goal run a deny detector refuses the command |
| After an edit | Counts the edit for the loop warning and prints nothing. Files under `node_modules`, a virtualenv or a listed `non_project_dirs` name never warn |
| After a shell command | Tracks test runs and says so only on the first result and on each flip, with a status that lasts the whole session (the output counts when the command names a test runner, or when nothing in the chain merely reads: `cat run.log; bash count.sh` is never a test run, wrappers like `timeout` and `uv run` are looked through, and a bare "N errors" is not a verdict; a failure's mistake attaches to the traceback's files, else the session's edited code files), warns after three failed searches in a row (search spiral), and records which injections preceded a passing test (the outcome feedback loop) |
| After any batch of tool calls | Accounts the calls to the turn for stall detection and records detector matches on non-shell tools (path globs on edits, MCP tools by name) |
| After a failed tool | Logs the error as a mistake, unless it was a failing test run. When the failure matches a recurring error from past sessions or a stored mistake, injects the past fix at once ("Deja vu: TypeError hit in 3 past sessions, fix: ...") |
| After ExitPlanMode or a task update | Asks for the approved plan to be banked as a checkpoint with its steps pending. A task marked completed counts as a milestone claim |
| Stop (end of a turn) | Saves the handoff (last message, files), reads the final message for a completion claim without a checkpoint behind it, judges the turn for stall detection, brings the `/goal` bracket in step with the transcript, and ticks the live miner (debounced, `CLAUDE_ENGRAM_LIVE_MINE`) |
| Before compaction | Writes the automatic checkpoint (the floor) |
| After compaction | States the pressure rhythm (heads-up, checkpoint, auto-compaction). The session-start banner that follows re-injects the rules, the mistakes and the checkpoint banked before the compaction |
| An API failure | Records the failure with its type and, for a usage limit, the reset time. Sends an alert during a goal run |
| A notification | A permission prompt, a needs-input or an idle notification during a goal run sends an alert |
| Session end | Writes the session summary, the run report for a substantial session, the rotation plan, and spawns the background miner |

Subagents get none of the injections, to save their context, but their edits are still tracked so the parent session knows what changed. Every hook has a one to two second budget and fails silently past it. High-frequency hooks are served by a resident daemon with warm imports and fall back to in-process when it is down.

## Install

```bash
git clone https://github.com/20alexl/claude-engram.git
cd claude-engram
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -e .                # Core
pip install -e ".[semantic]"    # + embedding model for vector search and semantic scoring

python install.py               # Hooks, MCP server launcher, /engram skill, migrations
```

`install.py` creates the storage directory, merges engram's hooks into `~/.claude/settings.json` without touching other hooks, writes a `.mcp.json` in the repo for copying (and a launcher script as the fallback when no venv is active), pre-builds the decision template cache for semantic scoring, installs the `/engram` skill to `~/.claude/skills/engram/`, and runs the data migrations. Ollama is optional. Without it the tools that use a local model degrade silently and everything else is unaffected.

Then, per project:

```bash
python install.py --setup /path/to/your/project
```

Or copy `.mcp.json` into the project root. That is the only per-project file. Hooks and the `/engram` skill are global. The `CLAUDE.md` in this repo is for people working on engram itself, and your projects do not need it.

Open the project in Claude Code and approve the `claude-engram` MCP server when prompted. If the project already has Claude Code history, the first session finds it and mines it in the background.

To update:

```bash
cd claude-engram
git pull
pip install -e ".[semantic]"    # Reinstall if dependencies changed
python install.py               # Re-run to update hooks and /engram skill
```

Hooks pick up code changes at once because the install is editable. Reconnect the MCP server with `/mcp` to reload it. Data migrations run on their own and are forward-only, idempotent and safe to downgrade across.

## Day to day

Most of the time there is nothing to do. The few things worth doing on purpose:

- Type `/engram` when you want Claude to reach for the tools itself. Background tracking runs either way.
- Half remember something from weeks ago? Ask Claude to mine the sessions for it. `session_mine(search)` reads everything you ever discussed, including sessions long gone from context.
- Something Claude must never forget goes in as a rule with `memory(add_rule)`. Rules in a project stay local. Rules at your workspace root cascade to every project under it.
- Before a compaction engram saves a checkpoint on its own, but a deliberate `context(checkpoint_save)` with what you are doing and what is left resumes far cleaner. Engram nudges for one at the right moments (see [Checkpoints and compaction](#checkpoints-and-compaction)).
- On return, ask what you said you would do this session. `session_mine(commitments)` reads the live transcript for open loops, which the post-session index cannot see.
- When a plan should run without you, ask for `/engram run <goal>`. Claude hands you the `/goal` line to type, and engram brackets the run (see [Unattended runs](#unattended-runs)).

## The tools

Every tool takes `project_path`. Tools marked read-only never write anything.

| Tool | Operations | What it is for |
|---|---|---|
| `memory` | `remember`, `recall`, `search`, `hybrid_search`, `recent`, `add_rule`, `list_rules`, `set_detector`, `list_mistakes`, `acknowledge_mistake`, `modify`, `delete`, `batch_delete`, `promote`, `cleanup`, `consolidate`, `clusters`, `archive`, `restore`, `archive_search`, `archive_status`, `embed_all`, `forget` | Store a discovery, a rule (with an optional detector), find memories by query, file or tags, manage mistakes, and keep the store tidy. `hybrid_search` is semantic plus keyword and the best retrieval. `cleanup` drops near-duplicates (the same memory stored twice at 0.85 similarity) and decays and archives old entries. `consolidate` merges a whole tag group into one digest written by the local model, keeps the five most relevant originals and archives the rest; it needs ten or more in a group and never touches rules or mistakes. `promote` turns a memory into a rule. `acknowledge_mistake` archives a learned mistake so it stops appearing before edits |
| `work` | `log_mistake`, `log_decision` | Record a mistake the auto-capture missed (description, file, how to avoid) or an architectural choice (decision, reason, alternatives) |
| `context` | `checkpoint_save`, `checkpoint_restore`, `checkpoint_list`, `verify_completion` (`handoff_create`, `handoff_get`, `handoff_list` are deprecated aliases) | Checkpoints and handoffs are one construct, a durable per-project ring of the last 20 deliberate saves. A save carries the task, current step, completed and pending steps, files, and optional handoff fields (summary, context needed, warnings). A restore takes `index` (0 is the latest) or `task_id` and prints the goal and a staleness line. `verify_completion` checks a done claim against evidence and verification steps |
| `session_mine` | `search`, `decisions`, `replay`, `predict`, `struggles`, `errors`, `correlations`, `timeline`, `summaries`, `overview`, `status`, `cross_project`, `reflect`, `commitments`, `run_report`, `run_status`, `rotate`, `reindex` | Everything derived from the transcripts. See [Session mining](#session-mining) |
| `scope` | `declare`, `check`, `expand`, `status`, `clear` | Declare the files and patterns a task may touch. Edits outside it are flagged before they happen |
| `deps_map` (read-only) | `file_path` or `symbol` | A file's imports and, with `include_reverse`, its importers. With `symbol`: where is X defined, its signature and its importers, from the code index, cheaper than a grep and a read |
| `impact_analyze` (read-only) | `file_path`, `proposed_changes` | Dependents, exported symbols at risk, suggested test targets and a risk level before a refactor |
| `scout_search` (read-only) | `query`, `directory` | Semantic search over the codebase. Uses the local model when Ollama is up |
| `file_summarize` (read-only) | `file_path` | Purpose, exports, dependencies and complexity from structural analysis |
| `audit_batch` (read-only) | `file_paths` or `code` | Audit files on disk for bugs, missing error handling, security issues and TODOs, or lint an inline snippet for long functions, vague names and deep nesting |
| `find_similar_issues` (read-only) | `issue_pattern` | Every occurrence of a regex bug pattern across the codebase, with context |
| `convention` | `add`, `get`, `check`, `remove` | Per-project coding conventions with categories and reasons, checked against code or a filename by pattern matching |
| `claude_engram_status` (read-only) | | Health: version, model, the scorer daemon's device, memory counts |
| `session_start`, `session_end`, `pre_edit_check` | | Rarely needed. The hooks run these on their own. Call them only for an explicit deep reload, a summary, or an impact check by hand |

Examples:

```python
memory(operation="remember", content="The scorer must run on one pinned thread", project_path="/path")
memory(operation="add_rule", content="Never push without asking", reason="Owner decides what leaves the machine", project_path="/path")
memory(operation="hybrid_search", query="auth token refresh", project_path="/path")
memory(operation="list_mistakes", project_path="/path")

work(operation="log_decision", decision="Keep the ring per project", reason="Workspaces must not clobber each other", alternatives=["one global ring"])

context(operation="checkpoint_save", task_description="OAuth2 migration", current_step="Step 3: token refresh",
        completed_steps=["Step 1: provider config", "Step 2: login flow"], pending_steps=["Step 3: token refresh", "Step 4: tests"],
        files_involved=["auth.py", "oauth.py"], handoff_summary="60% done, refresh next",
        handoff_warnings=["legacy auth.py is still used by mobile"], project_path="/path")
context(operation="checkpoint_restore", project_path="/path", index=1)
context(operation="checkpoint_list", project_path="/path")

session_mine(operation="search", query="why did we drop the cache", kind="decision", since="2026-04-01", project_path="/path")
session_mine(operation="commitments", project_path="/path")
deps_map(symbol="load_project_memory", project_path="/path")
```

## Memory

Six categories:

| Category | Purpose | Protected | Captured |
|---|---|---|---|
| `rule` | Project rules that always apply | Never archived or decayed | By hand with `memory(add_rule)` or `promote`; the default pack seeds its tiers once |
| `lesson` | Curated insights synced from lesson files | Never archived; the source file owns the lifecycle | Opt-in, the miner syncs `lessons_globs` |
| `mistake` | Errors to avoid repeating | Manual ones never archive. Stale machine-written one-offs (three weeks old, never recurred, away from current work) auto-archive. All restorable | Failed tools, transcript mining, `work(log_mistake)` |
| `decision` | Choices and their reasoning | No | Prompts, transcript mining, `work(log_decision)` |
| `discovery` | Facts about the codebase | No | By hand, `memory(remember)` |
| `context` | Session notes | No | By hand; `session_end` also files a one-line session summary |

Two tiers. The hot tier (`memory.json`) holds rules, mistakes and recent memories and is what the hooks load on every tool call. The cold tier (`archive.json`) holds old inactive memories, searchable with `archive_search` and restorable by id, and is never on the hot path. Memories archive after 14 days without access (`CLAUDE_ENGRAM_ARCHIVE_DAYS`). A relevance of 8 or more exempts a memory from age archiving, which sits above every default (a manual `remember` is 5, the miner mints decisions at 7). Nothing is deleted without review: `cleanup` archives before it deletes.

Before every edit the hot memories are scored against the file: 35% file path match, 20% tag overlap, 20% recency (30-day decay), 15% importance, 10% access frequency, plus a bonus of 0.3 for rules, 0.25 for lessons and 0.2 for mistakes. Path matching is path-aware, so a shared basename across diverging paths is not a match, and generic names (`__init__.py`, `index.js`, `README.md`, `main.py`) need a full-path signal to score. The top three are injected. The outcome feedback loop applies a bounded multiplier (0.8 to 1.2) to the kinds of injection that precede passing tests.

In a workspace with several projects, memories are scoped to the sub-project of the file being edited, detected by markers like `pyproject.toml`, `package.json`, `.git` or `CLAUDE.md`. Rules and mistakes at the workspace root are inherited by every project under it, and `memory(list_rules)` marks the inherited ones. A session started inside a git worktree, or under `node_modules`, a virtualenv or a directory you list in `non_project_dirs`, belongs to the repository above it: its rules, its checkpoint ring, its patterns. Mined mistakes and decisions are filed under the registered project whose files they name, so `list_mistakes`, `recall` and the banner are per project.

## Checkpoints and compaction

Hooks never see context usage, but the statusline does. Engram mirrors the statusline's token counts to a per-session file and computes the distance to the point where auto-compaction fires: `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, else `autoCompactWindow` in settings (the env var, then managed settings, then project and user settings, in Claude Code's own order), else the model default. Never the raw percentage.

| Distance to the compaction point | Engram injects |
|---|---|
| About 10% of the window out | A heads-up: finish the current step, start nothing long |
| 20K tokens above the auto-compaction trigger (10K on a 200K window) | `CHECKPOINT NOW`: write a deliberate `context(checkpoint_save)`, then continue |
| 60 turns with neither a checkpoint nor a completed step | A fallback reminder |

Auto-compaction does not fire at the configured number. Claude Code keeps room for the model's output first, so the trigger sits about 32K tokens below the setting (a 750K setting compacted at 717,578). Engram places the last band above that measured trigger, not a fraction below the setting. Each band fires once per compaction cycle. After a compaction the banner restates the rhythm and shows the checkpoint banked before it.

Milestones are Claude's to call. When it judges a phase, a step or part of a plan done, the rule in the skill says checkpoint before saying so. Engram reads the final message at Stop, and a completion claim ("Phase 1 built", "step 3 done, next is X") with no deliberate checkpoint that turn gets one reminder quoting the sentence, but only when that turn also changed something (an edit, a commit, a delegated agent), never for a list bullet, and at most once an hour. A status report to you is not a close. Questions, negations and future tense never fire. A turn that banks state with `memory(remember)` and no checkpoint gets a different reminder: a remember stores a fact, the restore reads checkpoints only, and both together are fine. After ExitPlanMode it asks for the approved plan to be banked with its steps pending. Nothing is written for the model, and commits are never a trigger.

Every deliberate checkpoint records the commit the repo stood at and the active `/goal`, if any. A restore, whether the banner or `context(checkpoint_restore)`, prints the goal and one staleness line: commits and files changed since the save, the checkpoint's own files among them, or that its commit is not in this history. A handoff carries the last session's framing, and that line is what to read before acting on it. A save with handoff content also writes a readable `HANDOFF.md` next to the store.

The nudges need a statusline that records the mirror. Either use engram's, which prints `Fable 5.1 | ctx 660K/1000K | compact at 750K (90K left) | $1.25 | 5h 93% | proj` (the usage window only on a Claude.ai plan):

```json
"statusLine": {"type": "command", "command": "<venv python> -m claude_engram.hooks.context_pressure statusline"}
```

or have your own script call `claude_engram.hooks.context_pressure.record_statusline(data)` with the JSON it received, or write the same record to `~/.claude_engram/sessions/<session_id>.ctx.json` yourself (eight flat fields, listed in the module docstring; no engram import needed). Without a statusline engram says so at session start and only the turn cadence runs. A window set only by the `--autocompact` launch flag is invisible to hooks, so engram falls back to the model default and names the source it used.

The setting is a token count capped at the model's window. `/autocompact 750k` is 75% of a 1M model and the whole window of a 200K one, which leaves no room for the checkpoint call. Engram tells you once, at the first reading, when the number does not fit the model and names one that does. For long unattended runs, set the point yourself: `CLAUDE_CODE_AUTO_COMPACT_WINDOW=750000` on a 1M model keeps turns cheaper and puts the checkpoint nudge a known distance below a number you chose.

On a Claude.ai plan the statusline also carries the 5-hour and 7-day usage windows, and engram mirrors them beside the token counts. At 90% of the 5-hour window (95% of the weekly) it says so once per window, with the reset time, and asks for a checkpoint and a park on a wakeup until the reset. A limit hit ends the run on an API error that no Stop hook sees and that Claude Code does not retry, which is why the warning comes first. The `StopFailure` hook records every API failure with its type and the reset time, and the run report shows it. API-key sessions get no windows and no nudge. A custom statusline mirrors the windows by copying `rate_limits.five_hour` and `seven_day` (`used_percentage`, `resets_at`) into the record as `five_hour_pct`, `five_hour_resets_at`, `seven_day_pct` and `seven_day_resets_at`.

## Unattended runs

Engram does not invent a loop. `/goal` is the loop, and engram brackets it.

```text
/goal <condition>                 # Claude Code's own loop; engram brackets it from the next stop
/goal clear                       # you end it; engram cannot
/engram run <goal>                # Claude hands you the /goal line to type, then waits
/engram status [<session>]        # strikes, halt, alerts, and the report once the run ended
/engram report [<session>]        # the run report, summarized
/engram release <session>         # lift a halt, on your word
python -m claude_engram.run --headless --goal "<goal>" --alert-command 'curl -s -d {message} https://ntfy.sh/<topic>'   # cron and overnight only
```

You type `/goal`, in the session you are in. Nothing else sets a goal: no flag, setting, hook output or tool call, and Claude cannot type a slash command. When a plan should run unattended, Claude hands you the exact `/goal` line and waits. From the next stop engram sees the goal in the transcript and brackets it for the goal's life:

- Rules with deny detectors refuse their commands instead of only showing the rule.
- Three no-effect strikes halt every tool (see below), and alerts go out.
- The goal is stamped into every checkpoint, and the compaction and budget nudges do their work.
- The turn cap (150 by default, `goal_turn_cap`) arms the same halt, since engram cannot end a goal loop, and the alert asks you to `/goal clear`.
- Engram never judges the goal. Claude Code's evaluator does, reading what Claude shows in the conversation, so write the goal as something Claude's own output can demonstrate.

The run ends when the evaluator says met (the goal clears itself), judges it impossible, or you clear it. Engram writes a manifest at the start (goal, the rules in scope with their detectors, the start commit), one alert at the end, and a run report with a "Goal run" section: the goal, turns against the cap, verdicts and how it ended. `session_mine(run_status)` shows the bracket's state at any time.

### Stall detection

`/goal` stops its own loop after several turns with no tool use. The overnight failure that matters is the other one: a run that uses a tool every turn and changes nothing. Seen live, a goal loop ran nine turns of `cat` on a file that was never going to change. Engram judges a turn by its effect:

| Turn | Counts as |
|---|---|
| A file changed (an edit, a mutating shell command, or the git working tree moved), a test status flipped, a commit landed, work was delegated to an agent | Good |
| Tools were used and none of that happened | No effect |
| No tools at all, a park on a wait primitive (Monitor, ScheduleWakeup, a cron, a background task), or a test run that was not a repeat of the last one | Neutral |

Turns count, not time, so a four-hour foreground command is one turn. Verification is neutral. The same test command with the same verdict again is the re-run-and-hope pattern and counts as no effect.

Three consecutive no-effect turns are one strike. Strike 1 names the pattern and asks for a wait primitive instead of polling. Strike 2 re-injects the latest checkpoint and the rules and asks for a bearings check (task, last real change, blocker, different action). Strike 3 is the cap, and under a goal it becomes the halt. Strikes decay rather than reset: five consecutive good turns remove one. Every increment and decrement is an event with its turn number in the run report. Tune with `CLAUDE_ENGRAM_STALL_TURNS`, `CLAUDE_ENGRAM_STALL_DECAY` and `CLAUDE_ENGRAM_STRIKE_CAP`.

### Halt and alerts

At the strike cap every tool call is denied with a reason the model sees, except PushNotification, ToolSearch, SendMessage and engram's checkpoint call, so the model can leave a record and a one-line notification, then stop. A subagent already running is never denied: it shares the session id, the halt is for the main loop, and it reports back with SendMessage. A deny ends the turn, and with no tool use the goal's own stall rule closes the loop. Engram never blocks a Stop of its own. A person lifts the halt with `/engram release <session>` or `python -m claude_engram.hooks.stall release <session>`, and strikes reset. `python -m claude_engram.hooks.stall status <session>` prints strikes, the halt and the alerts.

A halt, an API failure, a run waiting on a person (a permission prompt, needs input, idle), the launcher pausing for a usage limit, and the run ending each send one line under 200 characters through the command you configure: `alert_command` in `.engram/config.json`, `CLAUDE_ENGRAM_ALERT_COMMAND`, or `--alert-command`. `{message}` is replaced, or the message arrives on stdin. No service is built in. Every alert lands in the run report whether or not a command was configured. PushNotification is the model's tool, and on a headless run the desktop notification has nowhere to land, which is why the command exists.

### Cron and overnight

Outside any session, the launcher runs `claude -p` with the same supervision. It writes the manifest, sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 75% of the model's window (`--window-fraction`, `--context-window`), a hard `--max-turns` (150), the park instruction (`--no-park-hint` drops it) and `bypassPermissions` because nobody is there to answer a prompt (`--permission-mode`). After a usage-limit exit it sleeps until the window resets, plus `CLAUDE_ENGRAM_RESUME_SLACK` seconds, and resumes the same session, up to `--max-resumes` (3) times. `--model`, `--project`, `--prompt` or `--prompt-file` for the task text after the goal, `--session-id`, and `--dry-run` to print the plan. Cost is the same as any session: a Claude.ai plan pays with its usage windows, an API key per token; the `total_cost_usd` a headless run prints is Claude Code's own client-side estimate.

A goal with nothing to do burns turns: a not-met goal re-prompts at once, so it starves `/loop` and cron (seen live: nine verdicts in two minutes, a cron fire lost). A goal idles while it waits on a Monitor, a wakeup or a background task, and the loop fires then. Tell the model to park on one of those instead of polling. From Git Bash on Windows set `MSYS_NO_PATHCONV=1`, or the leading `/goal` is rewritten into a filesystem path and Claude gets a plain prompt.

## Rules with detectors

Rules are natural language and stay that way. A rule may carry a detector, hand-written and never inferred:

```text
memory(add_rule, content="Never push without asking", detector={"tools": ["Bash"], "command": "\\bgit\\s+push\\b", "note": "push"})
memory(set_detector, memory_id=<rule id>, detector={"paths": ["design/**", "*.pem"]})   # {} clears
```

A detector has `tools` (tool names; empty means any), `command` (a regex against a shell command), `paths` (globs against an edited path), `input` (a regex against the JSON of the tool input), `note` (for the report) and optionally `"unattended": "deny"`. With one, every matching call is recorded in the run report with the turn, an excerpt of the input and a verdict that is only what the hooks can see: `unattended` (bypass, auto or dontAsk mode, so no person approved the call), `prompted` (Claude Code's own permission prompt stood between the model and the call) or `plan`. A matching shell command also gets the rule injected before it runs. A rule without a detector is advisory, and the report says so per rule. Detector health is shown too, so a regex that stopped compiling is visible. No language model sits in this path.

`"unattended": "deny"` refuses the command during a goal run, with the rule as the reason, and the model is told to record what it needs approved, notify, and continue with allowed work. An attended session, even in bypass mode, is only shown the rule. The default pack ships deny detectors on destructive shell commands (recursive or forced deletes, hard resets, force-push, DROP and TRUNCATE, disk formats, kills), kill by image name, and anything that leaves the machine (push, pull request, publish, outbound POST). A project whose own rule already covers that ground adopts the pack detector if it has none. `"compliance": false` in `.engram/config.json` or `CLAUDE_ENGRAM_COMPLIANCE=off` turns the trail off.

## Project defaults

Engram ships an opinion about how a project is kept. Everything is on by default and `<project>/.engram/config.json` turns each piece off:

```json
{"rotation": "auto", "default_rules": false, "workflow_rules": true, "code_rules": true, "structure": true,
 "compliance": true, "alert_command": "", "goal_turn_cap": 150,
 "rotation_log_days": 30, "rotation_learn_days": 90, "rotation_learnings_days": 0, "rotation_learn_max_lines": 500}
```

Structure: a project (a git repo, a package manifest or a `CLAUDE.md`) gets missing pieces scaffolded: a headered `CLAUDE.md` with Purpose, Testing and Structure, `.learnings/ERRORS.md`, `.learnings/LEARNINGS.md` and `session-logs/`. A multi-person layout (`.learnings/<name>/`, `session-logs/<name>/`) is left as it is.

Rules: three tiers seeded once into the project's memory on its first session. Universal: no destructive commands without asking, search first, quality over speed, prerequisites first, be direct, try before asking, private stays private, push back, follow the plan in order, never kill by image name, session maintenance, checkpoint when you judge a step done. Workflow: plan before code; proposed, open and decided are three things; every milestone has a gate before and a verdict after; delegate by size with a hard agent budget; verify before claiming done; numbers get a source; anything that leaves the machine is the owner's decision; write the learning when it happens. Code: one function, one purpose; names and comments that explain why; nothing left lying around; verify by quoting what it printed; never swallow an error on the decision path; same inputs, same outputs; the real thing over a stand-in; no secrets anywhere; performance from the start; both Windows and Linux; the fast path on purpose; never do work twice; smart over busy. The workflow and code text also land in the scaffolded `CLAUDE.md`. Any rule the project or an ancestor already has in substance is skipped, so your own rules win. `memory(list_rules)` shows them.

Rotation: nothing is deleted, ever. Session logs older than 30 days move to `session-logs/archive/<month>/` with a monthly digest beside them. Dated `ERRORS.md` entries older than 90 days move to `.learnings/archive/ERRORS-<year>.md`. `LEARNINGS.md` holds patterns that do not age out, so it rotates only when over the cap. Either file over 500 lines sheds its oldest 30-day-plus entries until it fits. Undated and STANDING entries never move, and each trimmed file gets a one-line note under its title saying what moved and where. Per-person folders rotate inside themselves. By default SessionEnd only plans and SessionStart announces. `session_mine(rotate, dry_run=false)` applies, `"rotation": "auto"` applies at every session end, `"rotation": false` stops planning.

## Run report

Every substantial session leaves one auditable record in the repo: `<project>/.engram/runs/<date>-<session>.md` plus a `.json` twin, written at SessionEnd or on demand with `session_mine(run_report)` or `python -m claude_engram.run_report --session <id>`. Add `.engram/runs/` to the project's `.gitignore`, since the reports carry session ids, costs and local paths; `.engram/config.json` is the file worth tracking. Every line is hook-captured or read from the transcript, never self-reported by the model:

- the `/goal` condition, every evaluator verdict with its reason, and the outcome; model, permission mode, branch, start and end commit
- wall time, turns, prompts, context at end and cost
- every compaction with its trigger, before and after token sizes, and which checkpoint it restored
- files touched with per-file edit counts; test runs, first and last status
- errors grouped by signature, recurrences, and whether the miner already knew them
- checkpoints written this session, deliberate versus automatic
- stalls: turns with and without effect, every strike and decay with its turn number
- rule matches with their verdicts, and detector health
- alerts and API failures
- what was not measured, listed rather than omitted

## Session mining

The hooks capture what happens inside a session. The miner reads the transcripts for what they cannot see. After every session a background process indexes the session, extracts decisions, mistakes and approaches, and builds search embeddings. During a session a debounced live tick at turn end refreshes the same index, so `session_mine(search)` sees this session's earlier work. Recurring errors and struggles are attributed to sub-projects and filtered by what the last session touched, and errors quiet for 30 days drop out. The lessons bridge, opt-in through `lessons_globs`, syncs dated entries in curated markdown as protected `lesson` memories with code-index triggers, so a lesson naming a module surfaces when editing files that import it.

`session_mine` operations:

- `search(query, method=hybrid|semantic|keyword, kind=decision|next-step|error|narration, since, until)`: every past conversation, tool content included
- `decisions(query)`: when and why a decision was made, from the transcripts and from the repository's own history (`git log -S` on the query and its most specific tokens, with the commit messages)
- `replay(file_path)`: discussions about a file, followed by the commits that touched it; `predict(file_path)`: the context an edit will need
- `struggles`, `errors`, `correlations` (files always edited together), `timeline`, `summaries`, `overview`, `status` (index coverage), `cross_project`
- `reflect`: which injection kinds precede passing tests, plus insights from recurring mistakes synthesized by the local model
- `commitments`: what you said you would do this session and whether it is done, from the live transcript
- `run_report`, `run_status`, `rotate(dry_run)`, `reindex(mode=post_session|bootstrap|full)`

Claude Code files a transcript under the directory the session was started from. A session run from a workspace root indexes under the root, so the views for a sub-project (`overview`, `timeline`, `struggles`, `errors`, `search`, `reflect`) are the workspace's views, and the counts include every sibling project worked on from that root. Start the session inside a project when you want its history alone. Memory works the other way: each mined mistake and decision is filed under the registered project whose files it names.

If search quality degrades or after a big update:

```bash
python scripts/reindex.py "/path/to/your/workspace" --force            # rebuild search index
python scripts/reindex.py "/path/to/your/workspace" --force --extract  # also re-extract decisions/mistakes
```

Or through MCP: `session_mine(operation="reindex", mode="bootstrap")`. On a large history this can exceed Claude Code's two-minute MCP call limit and continue in the background; the rebuild still finishes.

## Configuration

All optional. The [library book](./library-book/) has the detail on each.

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_ENGRAM_DIR` | `~/.claude_engram` | Storage location, also the test-isolation seam |
| `CLAUDE_ENGRAM_MODEL` | `gemma3:12b` | Ollama model. Only `scout_search`, `memory(consolidate)` and `session_mine(reflect)` use it |
| `CLAUDE_ENGRAM_OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `CLAUDE_ENGRAM_TIMEOUT` | `300` | Timeout in seconds for local model calls |
| `CLAUDE_ENGRAM_KEEP_ALIVE` | `0` | How long Ollama keeps the model loaded after a call (`5m`) |
| `CLAUDE_ENGRAM_EMBED_MODEL` | `BAAI/bge-base-en-v1.5` | Embedding model (about 1.1GB scorer RAM). `all-MiniLM-L6-v2` is a 90MB setup at lower accuracy |
| `CLAUDE_ENGRAM_EMBED_DIM` | model native | Matryoshka truncation dim. Stores are signature-stamped and rebuild on a model change |
| `CLAUDE_ENGRAM_DEVICE` | smart | Unset: the daemon stays on cpu and bulk jobs use a transient GPU worker that exits after the job. `cuda` or `cpu` forces one device |
| `CLAUDE_ENGRAM_GPU_BULK_MIN` | `512` | Job size in texts that routes to the GPU worker |
| `CLAUDE_ENGRAM_GPU_BATCH` | `64` | Rows per forward pass on the GPU (about 26 MiB per row) |
| `CLAUDE_ENGRAM_CPU_BATCH` | `16` | Rows per forward pass in the resident daemon on the CPU. The daemon keeps the activation arena of its largest batch for life: 64 rows parked 1.2 GB more than 16 at the same speed |
| `CLAUDE_ENGRAM_SCORER_TIMEOUT` | `1800` | Scorer daemon idle timeout in seconds |
| `CLAUDE_ENGRAM_NO_DAEMON` | unset | Set to run every hook in-process and never start the daemon (tests, benches) |
| `CLAUDE_ENGRAM_LIVE_MINE` | `300` | Live mining tick interval in seconds. `0` disables |
| `CLAUDE_ENGRAM_ARCHIVE_DAYS` | `14` | Days until inactive memories archive |
| `CLAUDE_ENGRAM_SESSION_RETENTION_DAYS` | `0` (keep all) | Prune session-search shards older than N days |
| `CLAUDE_ENGRAM_LAST_FILE_PATH` | unset | Mirror the last-read file path to this file (statusline integration) |
| `CLAUDE_ENGRAM_HEADSUP_FRACTION` | `0.10` | Heads-up nudge this fraction of the window before the compaction point |
| `CLAUDE_ENGRAM_OUTPUT_RESERVE` | `32000` | Tokens Claude Code keeps below the setting before it compacts |
| `CLAUDE_ENGRAM_CHECKPOINT_MARGIN` | `20000` (`10000` on a 200K window) | `CHECKPOINT NOW` this many tokens above the trigger |
| `CLAUDE_ENGRAM_CHECKPOINT_CADENCE` | `60` | Turns without a deliberate checkpoint or a completed step before the fallback reminder |
| `CLAUDE_ENGRAM_BUDGET_FIVE_HOUR_PCT`, `CLAUDE_ENGRAM_BUDGET_SEVEN_DAY_PCT` | `90`, `95` | Usage-window warning thresholds |
| `CLAUDE_ENGRAM_STALL_TURNS`, `CLAUDE_ENGRAM_STALL_DECAY`, `CLAUDE_ENGRAM_STRIKE_CAP` | `3`, `5`, `3` | No-effect turns per strike, good turns per decay, strikes to the cap |
| `CLAUDE_ENGRAM_GOAL_TURN_CAP` | `150` | Turns under a `/goal` before the halt arms (also `goal_turn_cap` in the project config) |
| `CLAUDE_ENGRAM_AUTONOMY` | unset | `1` arms the halt and the alerts outside a `/goal` (the launcher sets it) |
| `CLAUDE_ENGRAM_ALERT_COMMAND` | unset | Shell command for alerts; `{message}` is replaced |
| `CLAUDE_ENGRAM_RESUME_SLACK` | `90` | Seconds the launcher waits past a usage-window reset before resuming |
| `CLAUDE_ENGRAM_COMPLIANCE`, `CLAUDE_ENGRAM_ROTATION`, `CLAUDE_ENGRAM_STRUCTURE`, `CLAUDE_ENGRAM_DEFAULT_RULES`, `CLAUDE_ENGRAM_WORKFLOW_RULES`, `CLAUDE_ENGRAM_CODE_RULES` | on | Environment overrides for the project config switches (`off` disables; `ROTATION` also takes `auto`) |
| `CLAUDE_ENGRAM_NON_PROJECT_DIRS` | unset | Comma-separated directory names that are never a project (adds to `non_project_dirs` in the config file) |
| `CLAUDE_ENGRAM_HOOK_DEBUG` | unset | `1` prints a stderr breadcrumb per hook |
| `CLAUDE_ENGRAM_GIT_TRACE` | unset | A file path; every git call the hooks make is logged there |

`~/.claude_engram/config.json` accepts `embed_model`, `embed_dim`, `lessons_globs` (a list of globs, for example `["docs/lessons/*.md"]`; no default path) and `non_project_dirs` (directory names that are never a project of their own, added to the built-in `node_modules`, `.venv`, `venv` and `__pycache__`; a workspace with a `.scratch/` convention lists it here). `<project>/.engram/config.json` holds the per-project switches listed under [Project defaults](#project-defaults).

## Storage

Everything lives under `~/.claude_engram/` (`CLAUDE_ENGRAM_DIR`): `manifest.json`, `projects/<hash>/` with `memory.json`, `archive.json`, `embeddings.npy`, `session_index.json`, `extractions/` and the checkpoint ring, `checkpoints/` for the per-task files, and `sessions/<session_id>.json` for each session's working state, so concurrent sessions never clobber each other. All writes are atomic (temp file, then replace). The scorer daemon serves the embedding model over localhost, stays on cpu with zero VRAM parked, runs every model call on one pinned thread, and exits after 30 minutes idle or when the package source changes. Ollama, when present, is used only by `scout_search`, `memory(consolidate)` and `session_mine(reflect)`.

## Compatibility

| Platform | What works | Auto-capture |
|---|---|---|
| Claude Code (CLI, desktop, VS Code, JetBrains) | Everything | Hooks and session mining |
| Cursor, Windsurf, Continue.dev, Zed, any MCP client | MCP tools | No hooks |
| Obsidian vaults | Everything, with a `CLAUDE.md` at the root | With Claude Code |

## Benchmarks

Retrieval (recall at k): LongMemEval 0.966 R@5 and 0.982 R@10 over 500 questions, ConvoMem 0.960 over 250 items, LoCoMo 0.649 R@10 over about 2k questions. About 43ms per query, 112ms cross-session over 7,310 chunks.

Product behavior, integration suites green: decision capture 97.8% precision, error auto-capture 100% recall, compaction survival 6/6, multi-project isolation 11/11, edit-loop detection 12/12, session mining 64/64, Obsidian vault compatibility 25/25.

Reproduce the retrieval numbers with `tests/bench_longmemeval.py`, `tests/bench_convomem.py` and `tests/bench_locomo.py`; the product suites are the other `tests/bench_*.py` scripts, listed in the library book's contributing chapter.

## Documentation

The [library book](./library-book/) holds the design, the internals, the full usage guide, the API reference, the gotchas and the changelog. `/engram` is the quick reference that `install.py` installs. The `CLAUDE.md` in this repo is the developer's map of the hooks and modules.

## License

MIT

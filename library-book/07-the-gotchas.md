# Chapter 7: The Gotchas

[← Back to Table of Contents](./README.md) · [Previous: Advanced Usage](./06-advanced-usage.md) · [Next: Contributing →](./08-contributing.md)

---

### Gotcha: Memories stored under workspace root, not sub-project

**Symptom:** You call `memory(remember, project_path="/home/user/projects")` then wonder why the memory doesn't show up when editing `~/projects/my-project/app.py`.

**Cause:** It does show up: sub-projects inherit workspace-level memories via parent-path fallback. But if you store everything at workspace level, there's no per-project scoping.

**Fix:** Let the hooks handle it. When hooks auto-capture mistakes or decisions, they resolve the sub-project automatically from the file being edited. For manual `memory(remember)` calls, pass the sub-project path.

**Lesson:** Use the most specific path that makes sense. Workspace-level for cross-project rules, sub-project-level for project-specific knowledge.

---

### Gotcha: Generic-basename memories fire on unrelated files

**Symptom:** A mistake logged for `service-a/auth/__init__.py` surfaces as a warning when editing `service-b/auth/__init__.py`, even though the two files are unrelated.

**Cause:** Pre-v0.5.0, `file_match` compared only basenames. `__init__.py` matched any `__init__.py` anywhere.

**Fix:** Resolved in v0.5.0. File matching is now path-aware: a shared basename across diverging paths is not treated as a match. Generic basenames (`__init__.py`, `index.js`, `__main__.py`, etc.) require a full-path signal; specific filenames still match by name.

If you upgraded and still see stale cross-version warnings, run `python -m claude_engram.migrations` to re-extract `related_files` to full paths for existing memories.

**Lesson:** If you store a mistake with a specific file context, the path matters. Logging a mistake with `file_path="service-a/auth/__init__.py"` and later editing `service-b/auth/__init__.py` will correctly not trigger it.

---

### Gotcha: Scorer server not starting

**Symptom:** Decision capture only works via regex. Semantic scoring returns 0.0.

**Cause:** `sentence-transformers` is not installed, or the server failed to start. The server auto-starts on SessionStart but is fire-and-forget, so if it fails, there's no error shown.

**Fix:**
```bash
pip install -e ".[semantic]"
# Verify manually:
python -m claude_engram.hooks.scorer_server  # Should say "Scorer server listening..."
```

**Lesson:** Semantic scoring is optional. The regex fallback captures most clear decisions. `claude_engram_status` lists the daemon (role, pid, memory); `~/.claude_engram/scorer.lock` is held while one is alive.

---

### Gotcha: Hook timeout silently swallows output

**Symptom:** Hooks produce no output, no error. Claude Engram seems dead.

**Cause:** Claude Code gives hooks 1-2 seconds. If the per-project `memory.json` is very large, or the scorer server is slow, the hook times out and Claude Code discards the output silently. Per-project storage (v3) reduces this risk since each project's file is much smaller than the old monolithic file.

**Fix:**
```python
memory(operation="archive_status", project_path="/path")  # Check hot tier size
memory(operation="cleanup", dry_run=False, project_path="/path")  # Reduce hot entries
```

**Lesson:** Keep the hot tier under ~50 entries. Archive aggressively. The archive is unlimited, and searches are fast because they only happen on explicit request.

---

### Gotcha: Path variant duplicates (pre-v3 only)

**Symptom:** You have memories under `D:/Code/project` AND `d:/code/project` AND `D:\Code\project`. Three separate buckets for the same project.

**Cause:** Pre-v3 versions stored all projects in one file without consistent path normalization.

**Fix:** This is resolved in v3 (per-project storage). The manifest uses normalized paths as keys, and migration merges duplicates automatically. If you still have the old `memory.json`, loading it triggers auto-migration.

**Lesson:** This was fixed in v0.2.0. Path normalization (lowercase drive, forward slashes) now happens on every write.

---

### Gotcha: `CLAUDE_ENGRAM_MODEL` env var not picked up

**Symptom:** You set `CLAUDE_ENGRAM_MODEL=gemma3:4b` but the status tool still shows `gemma3:12b`.

**Cause:** The MCP server runs as a separate process launched by Claude Code. Setting env vars in your terminal only affects that terminal, not the MCP server process. The `.mcp.json` `env` field exists but has a known issue on Windows where values arrive empty.

**Fix:** Set the env var system-wide, then restart Claude Code:
```bash
# Windows (PowerShell)
[System.Environment]::SetEnvironmentVariable("CLAUDE_ENGRAM_MODEL", "gemma3:4b", "User")

# Linux/Mac (add to ~/.bashrc or ~/.zshrc)
export CLAUDE_ENGRAM_MODEL="gemma3:4b"
```

**Lesson:** MCP server env vars must be set system-wide, not per-terminal. Always restart Claude Code after changing them.

---

### Gotcha: `scout_search` returns empty with small models

**Symptom:** `scout_search(query="how does auth work")` returns no results, but `scout_search(query="authenticate")` works.

**Cause:** Semantic search asks the LLM to identify relevant files from natural language queries. Smaller models (`gemma3:4b`, `gemma3:1b`) are weaker at this reasoning. Literal/keyword search always works regardless of model size.

**Fix:** Use specific terms instead of natural language, or use a larger model for better semantic search.

**Lesson:** `gemma3:4b` is fine for most features. If semantic search matters, use `gemma3:12b` or larger.

---

### Gotcha: Ollama not required for most features

**Symptom:** Ollama isn't running but Claude Engram seems to work fine.

**Cause:** Ollama is only needed by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently without it), plus `scout_search` when available. Everything else is LLM-free: all hook-based features (mistake tracking, decision capture, loop detection, scoring, archiving, code index, pre-edit import verification, blast-radius) plus `convention(check)`, `file_summarize`, `audit_batch`, and `find_similar_issues`.

**Fix:** Nothing to fix. Just know that `claude_engram_status` will report "failed" if Ollama is down, but that only affects the two optional insight paths and `scout_search`'s semantic mode.

**Lesson:** Claude Engram has two layers: the proactive/analysis system (no external deps, pure ast/regex) and an optional LLM flavor (Ollama, for `consolidate`/`reflect` synthesis and `scout_search`). They're independent.

---

### Gotcha: Delete the venv and nothing works

**Symptom:** MCP server won't start. Hooks error with `ModuleNotFoundError`.

**Cause:** The venv contains the installed `claude_engram` package. The launcher scripts and `.mcp.json` point to the venv's Python. Deleting it breaks everything.

**Fix:** Recreate the venv and reinstall:
```bash
cd claude-engram
python -m venv venv
source venv/bin/activate
pip install -e .
python install.py
```

**Lesson:** The venv is not disposable. It's the runtime environment.

---

### Gotcha: Pre-edit import verification is Python-only and advisory

**Symptom:** You edit a TypeScript or Go file and don't get any import warnings, even for broken imports.

**Cause:** The code index (`mining/code_index.py`) uses Python's `ast` module. It only indexes `.py` files. Non-Python files are not parsed, and `hooks/precheck.py` silently degrades to no output for them.

**Fix:** Nothing to fix; this is the intended scope. For non-Python projects, `impact_analyze` and `deps_map` still provide blast-radius and dependency info, just without the symbol-level import check.

**Lesson:** Pre-edit import verification is Python-only. It is also advisory: it warns but never blocks. A missing warning doesn't mean the import is valid.

---

### Gotcha: Code index is sub-project scoped, so a workspace root won't index sibling projects

**Symptom:** You run from a workspace root containing `projectA/` and `projectB/`. The code index built for the workspace doesn't know about symbols in `projectB/` when you're working in `projectA/`.

**Cause:** The index walk stops at project boundaries (dirs containing `pyproject.toml`, `package.json`, `.git`, `CLAUDE.md`, etc.). Each sub-project gets its own index. This is deliberate: a pooled cross-project symbol table would cause service-a/service-b-style cross-pollution.

**Fix:** Nothing to fix. When the hook fires for a file in `projectA/`, it resolves the index for `projectA/` only. Impact analysis across projects still works via `impact_analyze` with an explicit `project_root`.

**Lesson:** The code index mirrors the memory system's sub-project scoping: per-project, not workspace-wide.

---

### Gotcha: Two concurrent sessions can drop a few outcome log events

**Symptom:** `session_mine(reflect)` shows injection precision that seems slightly off, missing a few injections or test results.

**Cause:** The outcome log (`mining/outcomes.py`) is a single global file (the edit hook and bash hook see different cwds, so per-project attribution is ambiguous). Under two concurrent Claude Code sessions, the last writer wins on each atomic write, so a small number of outcome events from the other session can be overwritten. Note: loop-detection state is NOT affected: it moved to per-session files (`sessions/<sid>.json`) in v0.8.0, so edit counts and test results never cross-contaminate.

**Fix:** Nothing to fix. The outcome log is bounded (1000 events) and atomic per write, so it's correct for single sessions. For concurrent sessions, precision metrics are approximate, which is tolerable for a tuning signal.

**Lesson:** Don't run two sessions doing heavy editing simultaneously if you care about precise reflect metrics. One-session workflows are fully accurate.

---

### Gotcha: No checkpoint nudges, or nudges at the wrong moment

**Symptom:** Compaction fires without a heads-up or `CHECKPOINT NOW`, or the nudge lands hundreds of thousands of tokens early on a 1M model.

**Cause:** Hooks receive no context-usage numbers; the signal comes from the statusline. No `statusLine` in settings, or a custom statusline script that never records the mirror, means no reading. Engram says so at session start (no statusLine) or after five silent minutes (statusLine configured but not recording).

The "wrong moment" case is the raw-percent trap: the statusline's `used_percentage` is against the full window (1M), but a native-1M model compacts at about 967K by default, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `autoCompactWindow` move the point. Engram computes the distance to the real point. The `--autocompact` launch flag is not in a hook's environment: a background job (`claude --bg`) saves its flags, and engram reads the window from there (source `launch flag`); an interactive session's flag is invisible, so engram falls back to the model default and labels the source (`env`, `launch flag`, `settings`, `model-default`) in the nudge, so a wrong source is visible. Before 0.8.59 the four standing background sessions launched with `--autocompact 200k` computed their nudges against the model default, so compaction fired before either nudge and only the PreCompact floor checkpoint landed.

**Fix:** Point `statusLine` at `python -m claude_engram.hooks.context_pressure statusline`, or add `record_statusline(data)` to your own script (README: Context pressure). In an interactive session prefer the env var or the setting over the launch flag for the window. `python -m claude_engram.hooks.context_pressure assess <session_id>` prints exactly what engram sees.

### Gotcha: `/autocompact 750k` set on a 1M model, then a 200K session compacts with no headroom

**Symptom:** On the smaller model the `CHECKPOINT NOW` nudge arrives a few thousand tokens before compaction, or the PostCompact rhythm says `compaction at ~200K (settings; the configured 750K is capped at the 200K window …)`.

**Cause:** `autoCompactWindow` is a token count, not a fraction, and Claude Code caps it at the model's context window. 750K is 75% of a 1M model and the whole window of a 200K one. The setting lives in the user's settings file, so it follows you across models. Hooks cannot change a live session's point.

**Fix:** Engram says so once at the first context reading, with the number for that model (`/autocompact 150k` on 200K). For unattended launches set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 75% of the model's window in the launch environment instead; the env var beats the setting.

### Gotcha: `context(checkpoint_save)` through the MCP server runs for minutes

**Symptom:** Claude Code shows the call as still running (its MCP log: "Tool 'context' still running (210s elapsed)"), the model gets "Connection closed", and yet the checkpoint IS in the ring afterwards. Reconnecting the server (`/mcp`) clears it until the next save.

**Cause:** The save runs one git call (`repo_state.head`) for the commit stamp. Inside a stdio MCP server the git child inherited the server's stdin, the JSON-RPC pipe from Claude Code, and stalled for the whole git timeout; the same handler takes 40 ms in-process. Measured by driving a fresh server over stdio with the MCP client library: 4.0 s per save with a project path, 0.0 s without one.

**Fix (0.8.33):** every `subprocess` call in the package passes `stdin=subprocess.DEVNULL` (a smoke test guards the rule). To see git from inside a long-lived process, set `CLAUDE_ENGRAM_GIT_TRACE=<file>`: one line per call with cwd, exit code and seconds.

### Gotcha: the `CHECKPOINT NOW` call never came, and after the auto compaction the checkpoint was not shown

**Symptom:** The heads-up arrived, the model banked a checkpoint, and then the session compacted with no `CHECKPOINT NOW` in between. After the compaction the session-start banner showed rules and mistakes but not the checkpoint the model had just written; the model resumed from Claude Code's own summary. (Seen on the engram build session itself, 2026-09-10: heads-up at 651K, compaction at 717,578 against a 750K setting.)

**Cause:** Two. Auto-compaction fires below the configured number, because Claude Code keeps room for the model's output first (~32K), so a band placed "3% out" (30K on a 1M window) sat inside that reserve and could not fire; the 5% band on a 200K window (10K) is inside it too. And `PostCompact` printed plain stdout on the belief that the hook had no structured output; per the hooks reference plain stdout on exit 0 is shown to the person, never added to Claude's context, while `hookSpecificOutput.additionalContext` is. A manual `/compact` looked fine only because the terminal echoed the command's output into the user turn. The SessionStart(compact) banner, which does reach the model, skipped the restored checkpoint because "PostCompact handles it."

**Fix (0.8.29):** The last band is an absolute distance above the measured trigger (`OUTPUT_RESERVE` 32K, `CHECKPOINT_MARGIN` 20K; 10K on ≤ 200K windows), so on 750K it fires at ~698K, before the 717K compaction. SessionStart(compact) shows the banked checkpoint with its goal and the repo's movement since, and since 0.8.50 states the rhythm too: Claude Code's hook output schema has no PostCompact entry, so the `additionalContext` PostCompact emitted from 0.8.29 was rejected with a validation error at every compaction; PostCompact now does bookkeeping only. `bench_context_pressure` replays the session's numbers through the real hooks.

### Gotcha: a stall strike after a few research turns

**Symptom:** `<engram-stall>Strike 1 of 3: 3 turns with tool use and no effect` while you were legitimately reading code before deciding.

**Cause:** Strike 1 is exactly that cheap by design: three consecutive turns of reads and searches with nothing changed. In an interactive session that is usually research; in an unattended loop it is the first sign of circling, and the same three turns cost the same money either way.

**Fix:** Nothing, if it was research: say what you are looking for and carry on; the strike decays after five turns with real effect. If a run keeps hitting strike 2, the bearings check is the point: name the blocker and pick a different action, or park on a wait primitive instead of polling. Turns with no tools at all and turns parked on Monitor / ScheduleWakeup / a cron are neutral and never count.

### Gotcha: a rule added from the CLI is "not found" through the MCP tools, or vanishes later

**Symptom:** `python -m claude_engram …` (or a hook) writes a rule or memory; the running session's `memory(delete)` on that id says not found, or a later save from the session quietly drops what the CLI wrote.

**Cause (fixed in 0.8.22):** The MCP server is one long-lived `MemoryStore`. It loaded each project's `memory.json` once and kept serving that copy, and its save path fell back to "write every loaded project" for callers that never marked a project dirty, so a save for one project rewrote the others from a stale copy.

**Fix:** Upgrade. Each loaded file carries a disk stamp; reads reload a copy the disk moved past, the manifest is re-read when another writer extended it, a stale project this process never touched is not written, and a mutation on a stale base merges by entry id. If you are on an older version, use one writer per session.

### Gotcha: an unattended run says "engram halt" on every tool call

**Symptom:** In a run launched with autonomy mode on, every tool call comes back denied with `engram halt: 3 strikes …`, and the run ends a few turns later with the goal still set.

**Cause:** That is the design working. The run used tools for the whole strike ladder without changing a file, a test status or a commit. That is the overnight failure autonomy mode exists for, so engram starved the run: every tool denied except PushNotification, ToolSearch and the checkpoint call. With no tool use the goal's own stall rule closes the loop; the launcher's turn cap is the backstop.

**Fix:** Read the run report's Stalls section and the checkpoint the model left, decide what the run was missing, and either change the task or lift the halt with `python -m claude_engram.hooks.stall release <session_id>` (strikes reset) and resume the session. A halt that fires on a healthy run means the effect detector missed how the work lands (a script writing files under a name it does not recognise, say), and the fix is the detector, not the cap.

### Gotcha: an unattended run gets "refused by rule" on a push or a delete

**Symptom:** In a launcher run, `git push`, `rm -rf`, `taskkill /IM …` or `gh pr create` comes back `engram: refused by rule [..] …`, while the same command in your own session only shows the rule.

**Cause:** The detector on that rule carries `unattended: deny`. In your session Claude Code's permission prompt, or you at the terminal, is the ask; in a launcher run nobody can answer, so an ask-first rule cannot be asked and the call is refused instead of recorded. The pack's destructive, kill-by-name and leaves-the-machine detectors ship this way.

**Fix:** That is the intended stop. The model is told to bank what it needs approved in a checkpoint, notify, and continue with allowed work. If a rule should only record in unattended runs, set its detector's `unattended` to `record` with `memory(set_detector)`; if a run genuinely needs to push, give it a rule-free way (a script the owner reviewed) or do that step yourself afterwards.

### Gotcha: PushNotification "wasn't delivered" on a headless run

**Symptom:** The halted model calls PushNotification, the transcript says it was not delivered (Remote Control inactive), and nothing reached your phone.

**Cause:** PushNotification is the model's tool: a desktop notification, and a phone push only when Remote Control is connected. A `claude -p` process has no desktop session to notify, and hooks cannot call the tool at all (verified).

**Fix:** Configure `alert_command` (`.engram/config.json`, `CLAUDE_ENGRAM_ALERT_COMMAND`, or the launcher's `--alert-command`) with the thing that reaches you (an ntfy topic, a webhook, a mail command) and `{message}` where the text goes. Every alert is recorded in the run report either way, so a missing command shows as `sent: no (no alert_command configured)`.

### Gotcha: `claude -p "/goal …"` from Git Bash sets no goal

**Symptom:** A headless goal run answers like a normal prompt, the transcript has no `goal_status` entries, and no run report is written.

**Cause:** MSYS path conversion. Git Bash rewrites a leading `/goal` argument into `C:/Program Files/Git/goal …` before `claude` sees it. The same command from PowerShell, or from Bash with `MSYS_NO_PATHCONV=1`, sets the goal.

**Fix:** `MSYS_NO_PATHCONV=1 claude -p "/goal …"`. The report's `goal_outcome` will read `met`, `failed` or `unresolved` once the goal is real.

### Gotcha: `session_mine` for a sub-project shows the whole workspace

**Symptom:** `session_mine(overview, project_path="E:/workspace/claude-engram")` reports 248 sessions and lists files like `page.tsx` and `make_slice.py` that belong to other projects in the workspace.

**Cause:** Claude Code stores a transcript under the directory the session was STARTED from, not the directory the edits landed in: one folder per cwd under `~/.claude/projects/`. Sessions run from a workspace root therefore all index under the root, and every session-mining view for a sub-project under it (overview, timeline, patterns, search, reflect) is really the workspace's view. Nothing in engram can re-cut that: the transcripts carry no per-project split.

**Fix:** Read the mining views as workspace-wide when you work from a root, and start a session inside the sub-project when you want its history alone. What IS attributed per project is `memory`: since v0.8.36 (rule corrected in v0.8.37) every mined mistake and decision is filed under the sub-project the files it names belong to, and since v0.8.52/v0.8.54 an entry with no files, or with files that cast no vote (a relative traceback path, a file outside the root), follows the session's own edits, so `memory(list_mistakes)`, `memory(recall)` and the session banner are project-scoped even when the mining views are not.

**Lesson:** Mining is indexed by where the session started; memory is attributed by which files the entry names. Two different keys, and only the second one follows the work.

### Gotcha: `session_mine(decisions)` crashed on a sub-project with no embeddings index

**Symptom:** `session_mine(decisions, query="why is PACE 0.15")` on a sub-project raised `FileNotFoundError`, or `replay` came back with edit timestamps and no reasons.

**Cause (fixed in 0.8.42):** `search_sessions` already walked up to the workspace root's index when a sub-project had none of its own, but the context-expansion step that followed reopened the sub-project's OWN store and found nothing there.

**Fix:** `_resolve_project_with_inheritance` returns the project that actually holds the index and its store dir, and the expansion reads that index and that project's transcript folder. Both `decisions` and `replay` also read the repository itself now: `git_pickaxe` runs `git log -S` with the most specific needle first (an identifier near a number, then the number, the identifiers, the longest words), scoped to the files a query token names, and each hit carries the added lines around the needle from that commit's diff, since the reason for a constant is usually a comment above it, not the commit message. `replay` appends `git_file_history` (`git log --follow`). Neither needs the embeddings index at all, so a query that used to crash now answers from git alone if the transcript store is missing.

**Lesson:** The transcript is not the only record of why. When mining answers nothing, ask git the same question.

### Gotcha: many engram processes in Task Manager, the machine out of memory

**Symptom:** Task Manager shows a pile of `python.exe` running `claude_engram.hooks.scorer_server` and `claude_engram.mining.background`, several GB each; Windows logs low-memory events; the box needs a reboot (2026-09-25, on 0.8.54: three sessions plus a workflow of parallel agents).

**Cause:** Two locks that were not locks. The daemon's "one instance" check was a pid file plus a 0.5 s connect; a stalled daemon absorbs only 8 pending connections, so a burst of hooks made the 9th read it as dead, delete its files and spawn a second one. The first idled 30 minutes at ~3 GB, and its exit deleted the second's files, so the next hook spawned a third: every idle exit orphaned the live daemon. Hooks that found no port file loaded the model themselves, ~3 GB of commit each. The miner's lock was check-then-write: four miners started together all acquired it, each ~3.6 GB for seven minutes.

**Fix:** v0.8.55. Both are OS process locks the kernel releases at exit (`hooks/proc_lock.py`); a daemon's exit removes only its own files; no hook loads a model; a post-session run right after another runs as a live tick. `claude_engram_status` lists every engram process and warns at a second scorer or miner on the same store.

**Lesson:** A pid file answers "did a process write here", not "is one alive"; a connect answers "did it accept this instant", not "is it dead". Only a lock the kernel drops on exit answers the question the spawner is asking.

---

### Gotcha: after a rewind, the checkpoint describes work that is not on disk

**Symptom:** You pressed Esc twice (or `/rewind`) and went back a few turns. The file is back to the earlier version, the conversation has forgotten the later turns, but `checkpoint_restore` (or the banner after the next compaction) describes the later work as this session's latest checkpoint.

**Cause:** A rewind fires no hook and writes no record. Claude Code's transcript is append-only: the abandoned turns stay in the file and the next prompt forks off the record you rewound to. Engram's ring kept every checkpoint the abandoned turns saved, all under this session's id, and returned the newest.

**Fix:** v0.8.57 walks the transcript's live chain (`transcript_chain.py`) and skips a checkpoint saved off it, naming it as skipped; the miner mines the live branch only. Two things a rewind never undoes: a file written by a shell redirect (Claude Code restores only what Write and Edit touched) and anything engram stored in the meantime (decisions, mistakes) — the live-chain read stops the miner from adding more, and `memory(delete)` removes what it already stored.

### Gotcha: a decision in the store that nobody made

**Symptom:** "Relevant memories" before an edit shows a decision that reads like the first sentence of a report, a verdict ("the plan is approved") with no plan in it, a leaning ("probably the queue, up to you"), a question typed without its mark, or the same sentence three times with three prefixes.

**Cause:** Four capture leaks found by reading nine sessions after 0.8.55: a relayed teammate message mined as the user's words; three sentence shapes the gate had no corpus row for; the prompt hook and the miner each storing the same typed sentence under a different prefix, sometimes in an ancestor store.

**Fix:** v0.8.56 drops relayed messages before any pattern sees them, adds the three shapes to the neutral corpus and the gate, and compares the bare sentence across the destination store and its ancestors before storing. Migration `0.8.56:rejudge_mined_decisions` archives what the old gate let through; `memory(restore, memory_id)` brings any of it back.

## Common mistakes

| Mistake | What They Do | What They Should Do |
|---------|-------------|-------------------|
| Pass workspace root for everything | `project_path="/home/user/projects"` for all operations | Let hooks auto-resolve, or pass sub-project path |
| Manually call `pre_edit_check` | Invokes it before every edit | It's automatic via PreToolUse hook. Only call for impact analysis. |
| Never run cleanup | Hot tier grows to 100+ entries, hooks slow down | Run `cleanup` periodically, or it runs automatically on `session_start` |
| Forget to install hooks | Copies `.mcp.json` but not hooks | Run `python install.py`, which installs both |

## Things that look like bugs but aren't

| Behavior | Why It Looks Wrong | Why It's Intentional |
|----------|-------------------|---------------------|
| Same memory appears from workspace AND sub-project | Looks like a duplicate | Parent-path inheritance. Workspace rules should be visible everywhere. |
| Scorer server consumes ~1.1GB RAM | Seems excessive for a hook | It's a loaded ML model (default `bge-base-en-v1.5`; `all-MiniLM-L6-v2` via config drops it to ~90MB). Shared across all hook calls. Exits after 30 min idle. |
| `session_end` does nothing new | Expected a big summary | Stop + SessionEnd hooks handle everything. `session_end` is just a display tool. |
| Decisions captured from user prompts have `(from user)` prefix | Looks redundant | Distinguishes auto-captured decisions from manually logged ones. |

---

[Next: Contributing →](./08-contributing.md)

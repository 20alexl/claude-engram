# Chapter 7 — The Gotchas

[← Back to Table of Contents](./README.md) · [Previous: Advanced Usage](./06-advanced-usage.md) · [Next: Contributing →](./08-contributing.md)

---

### Gotcha: Memories stored under workspace root, not sub-project

**Symptom:** You call `memory(remember, project_path="/home/user/projects")` then wonder why the memory doesn't show up when editing `~/projects/my-project/app.py`.

**Cause:** It actually does show up — sub-projects inherit workspace-level memories via parent-path fallback. But if you store everything at workspace level, there's no per-project scoping.

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

**Cause:** `sentence-transformers` is not installed, or the server failed to start. The server auto-starts on SessionStart but is fire-and-forget — if it fails, there's no error shown.

**Fix:**
```bash
pip install -e ".[semantic]"
# Verify manually:
python -m claude_engram.hooks.scorer_server  # Should say "Scorer server listening..."
```

**Lesson:** Semantic scoring is optional. The regex fallback captures most clear decisions. Check `~/.claude_engram/scorer_port` to see if the server is running.

---

### Gotcha: Hook timeout silently swallows output

**Symptom:** Hooks produce no output, no error. Claude Engram seems dead.

**Cause:** Claude Code gives hooks 1-2 seconds. If the per-project `memory.json` is very large, or the scorer server is slow, the hook times out and Claude Code discards the output silently. Per-project storage (v3) reduces this risk since each project's file is much smaller than the old monolithic file.

**Fix:**
```python
memory(operation="archive_status", project_path="/path")  # Check hot tier size
memory(operation="cleanup", dry_run=False, project_path="/path")  # Reduce hot entries
```

**Lesson:** Keep the hot tier under ~50 entries. Archive aggressively. The archive is unlimited — searches are fast because they only happen on explicit request.

---

### Gotcha: Path variant duplicates (pre-v3 only)

**Symptom:** You have memories under `D:/Code/project` AND `d:/code/project` AND `D:\Code\project`. Three separate buckets for the same project.

**Cause:** Pre-v3 versions stored all projects in one file without consistent path normalization.

**Fix:** This is resolved in v3 (per-project storage). The manifest uses normalized paths as keys, and migration merges duplicates automatically. If you still have the old `memory.json`, loading it triggers auto-migration.

**Lesson:** This was fixed in v0.2.0. Path normalization (lowercase drive, forward slashes) now happens on every write.

---

### Gotcha: `CLAUDE_ENGRAM_MODEL` env var not picked up

**Symptom:** You set `CLAUDE_ENGRAM_MODEL=gemma3:4b` but the status tool still shows `gemma3:12b`.

**Cause:** The MCP server runs as a separate process launched by Claude Code. Setting env vars in your terminal only affects that terminal — not the MCP server process. The `.mcp.json` `env` field exists but has a known issue on Windows where values arrive empty.

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

**Cause:** Ollama is only needed by `memory(consolidate)` and `session_mine(reflect)` insight synthesis (both background, both degrade silently without it), plus `scout_search` when available. Everything else — all hook-based features (mistake tracking, decision capture, loop detection, scoring, archiving, code index, pre-edit import verification, blast-radius) plus `convention(check)`, `file_summarize`, `audit_batch`, and `find_similar_issues` — is LLM-free.

**Fix:** Nothing to fix. Just know that `claude_engram_status` will report "failed" if Ollama is down, but that only affects the two optional insight paths and `scout_search`'s semantic mode.

**Lesson:** Claude Engram has two layers: the proactive/analysis system (no external deps — pure ast/regex) and an optional LLM flavor (Ollama, for `consolidate`/`reflect` synthesis and `scout_search`). They're independent.

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

**Fix:** Nothing to fix — it's intentional scope. For non-Python projects, `impact_analyze` and `deps_map` still provide blast-radius and dependency info, just without the symbol-level import check.

**Lesson:** Pre-edit import verification is Python-only. It is also advisory: it warns but never blocks. A missing warning doesn't mean the import is valid.

---

### Gotcha: Code index is sub-project scoped — workspace root won't index sibling projects

**Symptom:** You run from a workspace root containing `projectA/` and `projectB/`. The code index built for the workspace doesn't know about symbols in `projectB/` when you're working in `projectA/`.

**Cause:** The index walk stops at project boundaries (dirs containing `pyproject.toml`, `package.json`, `.git`, `CLAUDE.md`, etc.). Each sub-project gets its own index. This is deliberate — a pooled cross-project symbol table would cause service-a/service-b-style cross-pollution.

**Fix:** Nothing to fix. When the hook fires for a file in `projectA/`, it resolves the index for `projectA/` only. Impact analysis across projects still works via `impact_analyze` with an explicit `project_root`.

**Lesson:** The code index mirrors the memory system's sub-project scoping: per-project, not workspace-wide.

---

### Gotcha: Two concurrent sessions can drop a few outcome log events

**Symptom:** `session_mine(reflect)` shows injection precision that seems slightly off, missing a few injections or test results.

**Cause:** The outcome log (`mining/outcomes.py`) is a single global file (the edit hook and bash hook see different cwds, so per-project attribution is ambiguous). Under two concurrent Claude Code sessions, the last writer wins on each atomic write, so a small number of outcome events from the other session can be overwritten. Note: loop-detection state is NOT affected — it moved to per-session files (`sessions/<sid>.json`) in v0.8.0, so edit counts and test results never cross-contaminate.

**Fix:** Nothing to fix. The outcome log is bounded (1000 events) and atomic per write, so it's correct for single sessions. For concurrent sessions, precision metrics are approximate — tolerable for a tuning signal.

**Lesson:** Don't run two sessions doing heavy editing simultaneously if you care about precise reflect metrics. One-session workflows are fully accurate.

---

### Gotcha: No checkpoint nudges, or nudges at the wrong moment

**Symptom:** Compaction fires without a heads-up or `CHECKPOINT NOW`, or the nudge lands hundreds of thousands of tokens early on a 1M model.

**Cause:** Hooks receive no context-usage numbers; the signal comes from the statusline. No `statusLine` in settings, or a custom statusline script that never records the mirror, means no reading. Engram says so at session start (no statusLine) or after five silent minutes (statusLine configured but not recording).

The "wrong moment" case is the raw-percent trap: the statusline's `used_percentage` is against the full window (1M), but a native-1M model compacts at about 967K by default, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `autoCompactWindow` move the point. Engram computes the distance to the real point. One thing it cannot see is a window set only by the `--autocompact` launch flag; it falls back to the model default and labels the source (`env`, `settings`, `model-default`) in the nudge, so a wrong source is visible.

**Fix:** Point `statusLine` at `python -m claude_engram.hooks.context_pressure statusline`, or add `record_statusline(data)` to your own script (README: Context pressure). Prefer the env var or the setting over the launch flag for the window. `python -m claude_engram.hooks.context_pressure assess <session_id>` prints exactly what engram sees.

### Gotcha: `/autocompact 750k` set on a 1M model, then a 200K session compacts with no headroom

**Symptom:** On the smaller model the `CHECKPOINT NOW` nudge arrives a few thousand tokens before compaction, or the PostCompact rhythm says `compaction at ~200K (settings; the configured 750K is capped at the 200K window …)`.

**Cause:** `autoCompactWindow` is a token count, not a fraction, and Claude Code caps it at the model's context window. 750K is 75% of a 1M model and the whole window of a 200K one. The setting lives in the user's settings file, so it follows you across models. Hooks cannot change a live session's point.

**Fix:** Engram says so once at the first context reading, with the number for that model (`/autocompact 150k` on 200K). For unattended launches set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to 75% of the model's window in the launch environment instead; the env var beats the setting.

### Gotcha: a stall strike after a few research turns

**Symptom:** `<engram-stall>Strike 1 of 3: 3 turns with tool use and no effect` while you were legitimately reading code before deciding.

**Cause:** Strike 1 is exactly that cheap by design: three consecutive turns of reads and searches with nothing changed. In an interactive session that is usually research; in an unattended loop it is the first sign of circling, and the same three turns cost the same money either way.

**Fix:** Nothing, if it was research: say what you are looking for and carry on; the strike decays after five turns with real effect. If a run keeps hitting strike 2, the bearings check is the point: name the blocker and pick a different action, or park on a wait primitive instead of polling. Turns with no tools at all and turns parked on Monitor / ScheduleWakeup / a cron are neutral and never count.

### Gotcha: a rule added from the CLI is "not found" through the MCP tools, or vanishes later

**Symptom:** `python -m claude_engram …` (or a hook) writes a rule or memory; the running session's `memory(delete)` on that id says not found, or a later save from the session quietly drops what the CLI wrote.

**Cause (fixed in 0.8.22):** The MCP server is one long-lived `MemoryStore`. It loaded each project's `memory.json` once and kept serving that copy, and its save path fell back to "write every loaded project" for callers that never marked a project dirty — so a save for one project rewrote the others from a stale copy.

**Fix:** Upgrade. Each loaded file carries a disk stamp; reads reload a copy the disk moved past, the manifest is re-read when another writer extended it, a stale project this process never touched is not written, and a mutation on a stale base merges by entry id. If you are on an older version, use one writer per session.

### Gotcha: an unattended run says "engram halt" on every tool call

**Symptom:** In a run launched with autonomy mode on, every tool call comes back denied with `engram halt: 3 strikes …`, and the run ends a few turns later with the goal still set.

**Cause:** That is the design working. The run used tools for the whole strike ladder without changing a file, a test status or a commit — the overnight failure autonomy mode exists for — so engram starved it: every tool denied except PushNotification, ToolSearch and the checkpoint call. With no tool use the goal's own stall rule closes the loop; the launcher's turn cap is the backstop.

**Fix:** Read the run report's Stalls section and the checkpoint the model left, decide what the run was missing, and either change the task or lift the halt with `python -m claude_engram.hooks.stall release <session_id>` (strikes reset) and resume the session. A halt that fires on a healthy run means the effect detector missed how the work lands — a script writing files under a name it does not recognise, say — and the fix is the detector, not the cap.

### Gotcha: an unattended run gets "refused by rule" on a push or a delete

**Symptom:** In a launcher run, `git push`, `rm -rf`, `taskkill /IM …` or `gh pr create` comes back `engram: refused by rule [..] …`, while the same command in your own session only shows the rule.

**Cause:** The detector on that rule carries `unattended: deny`. In your session Claude Code's permission prompt, or you at the terminal, is the ask; in a launcher run nobody can answer, so an ask-first rule cannot be asked and the call is refused instead of recorded. The pack's destructive, kill-by-name and leaves-the-machine detectors ship this way.

**Fix:** That is the intended stop. The model is told to bank what it needs approved in a checkpoint, notify, and continue with allowed work. If a rule should only record in unattended runs, set its detector's `unattended` to `record` with `memory(set_detector)`; if a run genuinely needs to push, give it a rule-free way (a script the owner reviewed) or do that step yourself afterwards.

### Gotcha: PushNotification "wasn't delivered" on a headless run

**Symptom:** The halted model calls PushNotification, the transcript says it was not delivered (Remote Control inactive), and nothing reached your phone.

**Cause:** PushNotification is the model's tool: a desktop notification, and a phone push only when Remote Control is connected. A `claude -p` process has no desktop session to notify, and hooks cannot call the tool at all (verified).

**Fix:** Configure `alert_command` (`.engram/config.json`, `CLAUDE_ENGRAM_ALERT_COMMAND`, or the launcher's `--alert-command`) with the thing that reaches you — an ntfy topic, a webhook, a mail command — and `{message}` where the text goes. Every alert is recorded in the run report either way, so a missing command shows as `sent: no (no alert_command configured)`.

### Gotcha: `claude -p "/goal …"` from Git Bash sets no goal

**Symptom:** A headless goal run answers like a normal prompt, the transcript has no `goal_status` entries, and no run report is written.

**Cause:** MSYS path conversion. Git Bash rewrites a leading `/goal` argument into `C:/Program Files/Git/goal …` before `claude` sees it. The same command from PowerShell, or from Bash with `MSYS_NO_PATHCONV=1`, sets the goal.

**Fix:** `MSYS_NO_PATHCONV=1 claude -p "/goal …"`. The report's `goal_outcome` will read `met`, `failed` or `unresolved` once the goal is real.

## Common Mistakes

| Mistake | What They Do | What They Should Do |
|---------|-------------|-------------------|
| Pass workspace root for everything | `project_path="/home/user/projects"` for all operations | Let hooks auto-resolve, or pass sub-project path |
| Manually call `pre_edit_check` | Invokes it before every edit | It's automatic via PreToolUse hook. Only call for impact analysis. |
| Never run cleanup | Hot tier grows to 100+ entries, hooks slow down | Run `cleanup` periodically, or it runs automatically on `session_start` |
| Forget to install hooks | Copies `.mcp.json` but not hooks | Run `python install.py` — it installs both |

## Things That Look Like Bugs But Aren't

| Behavior | Why It Looks Wrong | Why It's Intentional |
|----------|-------------------|---------------------|
| Same memory appears from workspace AND sub-project | Looks like a duplicate | Parent-path inheritance. Workspace rules should be visible everywhere. |
| Scorer server consumes ~1.1GB RAM | Seems excessive for a hook | It's a loaded ML model (default `bge-base-en-v1.5`; `all-MiniLM-L6-v2` via config drops it to ~90MB). Shared across all hook calls. Exits after 30 min idle. |
| `session_end` does nothing new | Expected a big summary | Stop + SessionEnd hooks handle everything. `session_end` is just a display tool. |
| Decisions captured from user prompts have `(from user)` prefix | Looks redundant | Distinguishes auto-captured decisions from manually logged ones. |

---

[Next: Contributing →](./08-contributing.md)

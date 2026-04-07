# Chapter 7 — The Gotchas

[← Back to Table of Contents](./README.md) · [Previous: Advanced Usage](./06-advanced-usage.md) · [Next: Contributing →](./08-contributing.md)

---

### Gotcha: Memories stored under workspace root, not sub-project

**Symptom:** You call `memory(remember, project_path="/home/user/projects")` then wonder why the memory doesn't show up when editing `~/projects/my-project/app.py`.

**Cause:** It actually does show up — sub-projects inherit workspace-level memories via parent-path fallback. But if you store everything at workspace level, there's no per-project scoping.

**Fix:** Let the hooks handle it. When hooks auto-capture mistakes or decisions, they resolve the sub-project automatically from the file being edited. For manual `memory(remember)` calls, pass the sub-project path.

**Lesson:** Use the most specific path that makes sense. Workspace-level for cross-project rules, sub-project-level for project-specific knowledge.

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

**Cause:** Ollama is only needed for `scout_search`, `scout_analyze`, `file_summarize`, LLM-based convention checking, and memory consolidation. All hook-based features (mistake tracking, decision capture, loop detection, scoring, archiving) work without Ollama.

**Fix:** Nothing to fix. Just know that `claude_engram_status` will report "failed" if Ollama is down, but that only affects the LLM-powered tools.

**Lesson:** Claude Engram has two layers: the hook system (no external deps) and the LLM tools (requires Ollama). They're independent.

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
| Scorer server consumes 90MB RAM | Seems excessive for a hook | It's a loaded ML model. Shared across all hook calls. Exits after 30 min idle. |
| `session_end` does nothing new | Expected a big summary | Stop + SessionEnd hooks handle everything. `session_end` is just a display tool. |
| Decisions captured from user prompts have `(from user)` prefix | Looks redundant | Distinguishes auto-captured decisions from manually logged ones. |

---

[Next: Contributing →](./08-contributing.md)
